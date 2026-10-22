"""Pecas comuns das funcoes Python da Vercel (api/*.py): login, permissao, pagina pronta e atualizacao dos paineis.

Substitui o que o servidor_portal.py fazia no computador da clinica:
- login e usuarios: o do Supabase Auth (a mesma sessao do site Next.js); permissoes em profiles.permissions.<id do painel>;
- Excel/SQLite: tabelas do Supabase (armazenamento.py);
- "pagina pronta": o HTML calculado fica em painel_pagina e so e refeito quando os dados (ou o dia) mudam.

Seguranca: o navegador nunca fala com as tabelas dos paineis. Aqui o login e conferido no Supabase e a permissao e lida em profiles
ANTES de qualquer dado ser lido com a service_role (que so existe no servidor).
"""
import base64
import gzip
import importlib
import json
import os
import re
import sys
import time
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path

os.environ.setdefault("PORTAL_ARMAZENAMENTO", "supabase")
os.environ["TZ"] = "BRT3"   # Brasilia (UTC-3, sem horario de verao desde 2019): "hoje" e "agora" dos paineis seguem o relogio da clinica, nao o UTC da Vercel
if hasattr(time, "tzset"):
    time.tzset()

RAIZ = Path(__file__).parent
for _p in (RAIZ, RAIZ / "Acompanhamento de META"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import armazenamento as arm  # noqa: E402

PADRAO_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PRAZO_TOTAL_S = 270          # a funcao da Vercel para em 300 s (maxDuration em vercel.json)
FIM_DAS_ATUALIZACOES_S = 190  # ate aqui baixa do Klingo; o resto do tempo e para calcular e guardar a pagina
SINCRONIA_S = 5 * 3600        # o painel copia do banco sozinho quando a ultima atualizacao tem mais de 5 h (alem do botao)
CACHE_LOGIN_S = 60
USUARIO_SYNC = "automático (a cada 5 h)"    # como a copia do banco e registrada em painel_atualizacao (e de onde sai o tempo previsto)
USUARIO_PAGINA = "automático (página)"      # so refez a pagina (dia novo, layout novo): status 'pagina', nao conta como atualizacao dos dados
PREVISTO_SYNC_PADRAO_S = 40                 # sem historico ainda: quanto se espera que a copia + a pagina levem
PREVISTO_PAGINA_PADRAO_S = 20
_LOGINS: dict[str, tuple[float, dict | None]] = {}
_CODIGOS: dict[str, object] = {}


class Negado(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status, self.mensagem = status, mensagem


# ---------------------------------------------------------------- modulos
def modulos() -> dict[str, dict]:
    """Paineis em Python do modulos.json, por id (as Metas tem tela propria no site e ficam de fora)."""
    cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
    return {m["id"]: m for m in cfg["modulos"] if m["tipo"] == "relatorios"}


def modo_financeiro(painel: str) -> str | None:
    """O que o painel tem de dinheiro (modulos.json, campo "financeiro"): "total" (so dinheiro: nem abre sem "Dados financeiros"), "parcial" (misto: abre sem os
    valores) ou None ("nenhum"). Painel SEM o campo conta como "total": esquecer de preencher bloqueia, nao libera."""
    m = modulos().get(painel)
    if m is None:
        return None
    modo = m.get("financeiro", "total")
    return None if modo == "nenhum" else modo


def codigo_do(painel: str):
    """Importa o gerar_*.py do painel (uma vez por instancia da funcao)."""
    if painel not in _CODIGOS:
        m = modulos()[painel]
        pasta = str(RAIZ / m["pasta"])
        if pasta not in sys.path:
            sys.path.insert(0, pasta)
        _CODIGOS[painel] = importlib.import_module(m["codigo"])
    return _CODIGOS[painel]


# ---------------------------------------------------------------- login e permissao
def _valor_do_cookie(c: SimpleCookie, base: str) -> str | None:
    """Valor de um cookie do Supabase (@supabase/ssr), que passa de 3180 caracteres em pedacos: base, base.0, base.1..."""
    if base in c:
        return urllib.parse.unquote(c[base].value)
    pedacos = sorted(((int(n.rsplit(".", 1)[1]), urllib.parse.unquote(m.value)) for n, m in c.items()
                      if n.startswith(base + ".") and n.rsplit(".", 1)[1].isdigit()))
    return "".join(v for _, v in pedacos) or None


def token_do_pedido(cabecalhos) -> str | None:
    """Token de acesso do usuario: cabecalho Authorization ou o cookie de sessao que o site Next.js ja guarda (sb-<projeto>-auth-token)."""
    auth = cabecalhos.get("Authorization", "")
    if auth.lower().startswith("bearer ") and auth[7:].strip():
        return auth[7:].strip()
    c = SimpleCookie()
    try:
        c.load(cabecalhos.get("Cookie", ""))
    except Exception:
        return None
    bases = {re.sub(r"\.\d+$", "", n) for n in c if re.fullmatch(r"sb-.+-auth-token(\.\d+)?", n)}
    for base in sorted(bases):
        bruto = _valor_do_cookie(c, base)
        if not bruto:
            continue
        try:
            if bruto.startswith("base64-"):
                bruto = base64.urlsafe_b64decode(bruto[7:] + "=" * (-len(bruto[7:]) % 4)).decode("utf-8")
            sessao = json.loads(bruto)
        except Exception:
            continue
        if isinstance(sessao, list) and sessao:   # formato antigo: [access_token, refresh_token, ...]
            sessao = {"access_token": sessao[0]}
        if isinstance(sessao, dict) and isinstance(sessao.get("access_token"), str):
            return sessao["access_token"]
    return None


def _sub_do_token(token: str) -> str | None:
    """O 'sub' (id do usuario) escrito no JWT, sem conferir assinatura (quem confere e o Supabase); None se nao for um JWT."""
    try:
        corpo = token.split(".")[1]
        sub = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4))).get("sub")
        return sub if isinstance(sub, str) and sub else None
    except Exception:
        return None


def autenticar(cabecalhos) -> dict:
    """{'id', 'email', 'admin', 'permissoes', 'financeiro'} do usuario logado; levanta Negado(401) sem login valido."""
    token = token_do_pedido(cabecalhos)
    if not token:
        raise Negado(401, "Sessão não encontrada. Entre de novo no site.")
    agora = time.time()
    guardado = _LOGINS.get(token)
    if guardado and agora - guardado[0] < CACHE_LOGIN_S and guardado[1]:
        return guardado[1]
    # o token e um JWT: o id do dono ja vem escrito nele, entao o perfil e buscado junto com a conferencia do login (uma ida ao Supabase a menos).
    # So vale se o Supabase confirmar que o token e valido E e daquele mesmo id; senao nada do que veio do token e usado.
    sub = _sub_do_token(token)
    if sub:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_login, f_perfil = ex.submit(arm.usuario_do_token, token), ex.submit(arm.perfil, sub)
            u = f_login.result()
            p = (f_perfil.result() if u and u["id"] == sub else None)
        if u and p is None:
            p = arm.perfil(u["id"])
    else:
        u = arm.usuario_do_token(token)
        p = arm.perfil(u["id"]) if u else None
    if not u:
        raise Negado(401, "Sua sessão expirou. Recarregue a página para entrar de novo.")
    p = p or {}
    permissoes = p.get("permissions") or {}
    admin = p.get("role") == "admin"
    # "Dados financeiros" (Configuracoes): receita, despesa e valores em R$. A chave nao pode ser "financeiro" (e o id de um painel)
    info = {"id": u["id"], "email": u["email"], "admin": admin, "permissoes": permissoes,
            "financeiro": admin or permissoes.get("dados_financeiros") is True}
    if len(_LOGINS) > 200:
        _LOGINS.clear()
    _LOGINS[token] = (agora, info)
    return info


def conferir_acesso(cabecalhos, painel: str, so_admin: bool = False) -> dict:
    """Login valido + painel existente + permissao. Admin sempre; viewer so com permissions.<painel> = true (painel novo nasce bloqueado).
    Painel so de dinheiro (modulos.json: "financeiro": "total") exige tambem "Dados financeiros"; o misto abre, sem os valores (ver sigilo.py)."""
    if painel not in modulos():
        raise Negado(404, "Painel não encontrado.")
    u = autenticar(cabecalhos)
    if so_admin and not u["admin"]:
        raise Negado(403, "Somente administradores podem fazer isso.")
    if not u["admin"] and u["permissoes"].get(painel) is not True:
        raise Negado(403, "Você não tem permissão para ver este painel. Peça a um administrador em Configurações.")
    if modo_financeiro(painel) == "total" and not u["financeiro"]:
        raise Negado(403, "Este painel mostra dados financeiros. Peça a um administrador para liberar “Dados financeiros” em Configurações.")
    return u


def pode_ver_painel(u: dict, painel: str) -> bool:
    """A mesma regra de conferir_acesso, sem levantar erro (e a mesma de podeVerPainel em lib/paineis.ts: tests/test_paineis_ts.py confere as duas)."""
    if u["admin"]:
        return True
    if u["permissoes"].get(painel) is not True:
        return False
    return not (modo_financeiro(painel) == "total" and not u["financeiro"])


# ---------------------------------------------------------------- pagina pronta
def periodo_da_url(de: str, ate: str) -> tuple[str, str] | None:
    """('2026-09', '2026-10') se a URL pede varios meses, ou ('2026-09-10', '2026-10-25') se pede dias exatos; um mes inteiro so e a pagina
    de sempre (o proprio painel escolhe)."""
    import painel_comum as pc
    return pc.periodo_da_consulta(de, ate)


def _marca_layout() -> str:
    import painel_comum as pc
    return pc.marca_layout()


def montar_pagina(painel: str, periodo: tuple[str, str] | None) -> str:
    codigo = codigo_do(painel)
    return codigo.gerar(*(periodo or (None, None)), devolver_html=True)


def registrar_avisos(painel: str, versao: int) -> None:
    """Leva para a aba Avisos os alertas da pagina que acabou de ser montada (ver avisos.py). Falhar aqui nunca impede de abrir o painel."""
    import avisos
    import painel_comum as pc
    try:
        payload = pc.payload_montado()
        if payload:
            avisos.sincronizar(painel, payload, versao)
    except Exception as e:
        print(f">>> AVISO: não consegui atualizar os avisos de {painel}: {type(e).__name__}: {e}", flush=True)


def _chave_da_pagina(periodo: tuple[str, str] | None) -> str:
    return "padrao" if not periodo else f"{periodo[0]}..{periodo[1]}"


def _pagina_vale(pronta: dict | None, versao: int, hoje: date) -> bool:
    """A pagina guardada so vale se os dados, o dia E o layout (CSS/JS/modelo, ver painel_comum.versao_layout) sao os de agora."""
    return bool(pronta and pronta["dados_versao"] == versao and pronta["dia"] == hoje.isoformat() and _marca_layout() in pronta["html"])


def garantir_pagina(painel: str, periodo: tuple[str, str] | None = None, guardar: bool = True) -> str:
    """HTML do painel: o guardado se os dados e o dia ainda valem; senao calcula (e guarda para os proximos)."""
    chave = _chave_da_pagina(periodo)
    hoje, versao = date.today(), arm.versao_com_dependencias(painel)
    pronta = arm.ler_pagina(painel, chave)
    if _pagina_vale(pronta, versao, hoje):
        return pronta["html"]
    return _calcular_e_guardar(painel, periodo, chave, hoje, versao, guardar)


def _calcular_e_guardar(painel: str, periodo: tuple[str, str] | None, chave: str, hoje: date, versao: int, guardar: bool = True) -> str:
    html = montar_pagina(painel, periodo)
    if not periodo:   # os avisos descrevem a posicao de hoje; um recorte de periodo mostra so uma parte dos dados
        registrar_avisos(painel, versao)
    if guardar:
        try:
            arm.gravar_pagina(painel, chave, html, versao, hoje)
            if not periodo:
                arm.limpar_paginas(painel, versao, hoje)
        except arm.ErroArmazenamento as e:   # sem guardar so fica mais lento; a pagina sai do mesmo jeito
            print(f">>> AVISO: não consegui guardar a página de {painel} ({e})", flush=True)
    return html


def pagina_para_abrir(painel: str, periodo: tuple[str, str] | None) -> tuple[str, bool, int]:
    """(HTML, vencido, previsto_s) para abrir o painel SEM esperar a atualizacao.

    Se ha uma pagina guardada ela sai na hora, mesmo velha (dados novos, dia novo ou layout novo): `vencido` avisa a tela do site, que pede a
    renovacao em segundo plano (POST /api/renovar) e mostra o andamento. So espera a conta quem nao tem pagina guardada, ou pediu um periodo
    cuja pagina esta velha. `vencido` tambem vale quando a ultima copia do banco tem mais de 5 h. `previsto_s` = quanto a renovacao costuma levar."""
    chave, hoje = _chave_da_pagina(periodo), date.today()
    with ThreadPoolExecutor(max_workers=3) as ex:   # as tres consultas sao independentes: uma ida so ao Supabase em vez de tres em fila
        f_pronta = ex.submit(arm.ler_pagina, painel, chave)
        f_versao = ex.submit(arm.versao_com_dependencias, painel)
        f_sincronia = ex.submit(sincronia_vencida, painel)
    pronta, versao, sincronia = f_pronta.result(), f_versao.result(), f_sincronia.result()
    if _pagina_vale(pronta, versao, hoje):
        html, vencido = pronta["html"], sincronia
    elif pronta and not periodo:
        html, vencido = pronta["html"], True
    else:
        html, vencido = _calcular_e_guardar(painel, periodo, chave, hoje, versao), sincronia
    previsto = previsto_da_renovacao(painel, sincronia) if vencido else 0
    return html, vencido, previsto


def visao_restrita(u: dict, painel: str) -> str | None:
    """A visao a que este usuario esta restrito no painel (Configuracoes > "Atendimento: o que a pessoa vê"), ou None. Administrador nunca e restrito."""
    import restricao
    return None if u["admin"] else restricao.visao_do_perfil(u["permissoes"], painel)


def com_marcas(html: str, painel: str, admin: bool, vencido: bool = False, previsto_s: int = 0, sem_financeiro: bool = False, visao: str | None = None) -> str:
    """Poe no HTML o que o painel_base.js precisa saber (painel, nuvem, se o usuario e admin). Feito a cada pedido: a pagina guardada e a mesma para todos.
    `sem_financeiro` = o usuario nao tem "Dados financeiros": num painel misto os valores em R$ saem da pagina (sigilo.py).
    `visao` = o usuario so pode ver essa parte do painel (restricao.py): o resto da clinica sai da pagina.
    `vencido`/`previsto_s` sao para a tela do site (PainelFrame), que le o iframe e pede a renovacao."""
    # "embutido": a pagina aparece dentro de uma tela do site, que ja da o respiro e o fundo (ver .embutido em painel_base.css)
    if visao:
        import restricao
        try:
            html = restricao.limpar_html(html, painel, visao)   # os dados das outras visoes (e o total da clinica) saem do JSON da pagina
        except restricao.VisaoInexistente:
            raise Negado(403, "Seu acesso a este painel está limitado a uma parte que não existe mais. Peça a um administrador para ajustar em Configurações.")
    if sem_financeiro and modo_financeiro(painel) == "parcial":
        import sigilo
        html = sigilo.limpar_html(html, painel)   # os valores saem do JSON da pagina; o modelo so precisa saber que nao ha o que mostrar
    else:
        sem_financeiro = False
    marca = (f"<script>window.PAINEL_NUVEM=true;window.PAINEL_SEM_FIN={'true' if sem_financeiro else 'false'};window.PAINEL_ID={json.dumps(painel)};window.PAINEL_ADMIN={'true' if admin else 'false'};"
             f"window.PAINEL_VENCIDO={'true' if vencido else 'false'};window.PAINEL_PREVISTO_S={int(previsto_s)};"
             "document.documentElement.classList.add('embutido');</script>")
    return html.replace("<head>", "<head>" + marca, 1) if "<head>" in html else marca + html


# ---------------------------------------------------------------- atualizacao
def atualizar(painel: str, usuario: str) -> dict:
    """Consulta o Klingo (dados do painel e, no Atendimento, as Metas), grava no Supabase e deixa a pagina pronta. Devolve a resposta do botao."""
    import klingo_relatorios as k
    inicio = time.time()
    k.PRAZO_FINAL = inicio + FIM_DAS_ATUALIZACOES_S
    try:
        codigo = codigo_do(painel)
        partes = [codigo.atualizar(forcar=True)]
        if painel in ("atendimento",):   # as Metas nao tem menu proprio aqui: o Atendimento depende da base #13339
            import extrair_laudo as ex
            partes.append(ex.atualizar(forcar=True))
        mensagem = " ".join(p["mensagem"] for p in partes)
        avisos = [a for p in partes for a in p.get("avisos", [])]
        atualizou = any(p.get("atualizou") for p in partes)
        arm._CACHE_VERSAO.clear()
        if atualizou:
            _preparar_paginas(painel, inicio)
        arm.registrar_atualizacao(painel, "ok" if not avisos else "aviso", mensagem, time.time() - inicio, usuario)
        return {"ok": True, "atualizou": atualizou, "mensagem": mensagem, "avisos": avisos}
    except Exception as e:
        arm.registrar_atualizacao(painel, "erro", f"{type(e).__name__}: {e}", time.time() - inicio, usuario)
        raise
    finally:
        k.PRAZO_FINAL = None


def sincronia_vencida(painel: str) -> bool:
    """Verdadeiro se a copia do banco para o painel esta valendo ha mais de 5 h (botao ou automatica; None = nunca). Sempre falso fora do modo
    banco (PAINEL_FONTE=klingo) e se a consulta falhar: abrir o painel nunca depende disso."""
    import fonte_banco as fb
    if not fb.ativa():
        return False
    try:
        ultima = arm.ultima_atualizacao(painel)
    except arm.ErroArmazenamento as e:
        print(f">>> AVISO: não consegui ver a última atualização de {painel}: {e}", flush=True)
        return False
    return not ultima or (datetime.now(timezone.utc) - ultima).total_seconds() >= SINCRONIA_S


def previsto_da_renovacao(painel: str, com_copia: bool) -> int:
    """Quantos segundos a renovacao costuma levar (mediana das ultimas do mesmo tipo): copiar do banco + refazer a pagina, ou so refazer a pagina."""
    if com_copia:
        return arm.previsto_s(painel, USUARIO_SYNC, PREVISTO_SYNC_PADRAO_S)
    return arm.previsto_s(painel, USUARIO_PAGINA, PREVISTO_PAGINA_PADRAO_S)


class Ocupado(Exception):
    """Ja existe uma renovacao deste painel rodando; `andamento` diz ha quanto tempo e quanto costuma levar."""

    def __init__(self, andamento: dict | None):
        super().__init__("renovação em andamento")
        self.andamento = andamento


@contextmanager
def trava_do_painel(painel: str, usuario: str, previsto_s: int):
    """Uma renovacao por painel de cada vez. Duas gravando o mesmo painel se atropelavam (a troca de uma apagava os lotes da outra e dava
    'Nenhum lote gravado'). Levanta Ocupado se outra ja roda; sem a tabela da trava segue sem trava."""
    achou = arm.travar_painel(painel, usuario, previsto_s)
    if achou is False:
        raise Ocupado(arm.andamento(painel))
    try:
        yield
    finally:
        if achou:
            arm.liberar_painel(painel)


def renovar(painel: str, usuario: str) -> dict:
    """Renovacao em segundo plano de um painel (chamada pela tela do site e pelo cron): copia do banco se a copia venceu, refaz a pagina e
    deixa tudo pronto para a proxima abertura. Devolve {'ok', 'ocupado', 'atualizou', 'falhou', 'andamento'}; nunca levanta."""
    com_copia = sincronia_vencida(painel)
    previsto = previsto_da_renovacao(painel, com_copia)
    inicio, falhou, atualizou = time.time(), False, False
    try:
        with trava_do_painel(painel, usuario, previsto):
            if com_copia:
                try:
                    atualizou = bool(atualizar(painel, USUARIO_SYNC).get("atualizou"))   # registra o resultado (ou o erro) no historico
                except Exception as e:
                    falhou = True   # o painel continua com os dados da ultima atualizacao; a pagina de hoje sai do mesmo jeito
                    print(f">>> AVISO: não consegui sincronizar {painel} com o banco: {type(e).__name__}: {e}", flush=True)
            garantir_pagina(painel)
            if not com_copia:
                arm.registrar_atualizacao(painel, "pagina", "Página refeita.", time.time() - inicio, USUARIO_PAGINA)
    except Ocupado as o:
        return {"ok": True, "ocupado": True, "atualizou": False, "falhou": False, "andamento": o.andamento}
    except Exception as e:
        traceback.print_exc()
        print(f">>> AVISO: não consegui renovar {painel}: {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "ocupado": False, "atualizou": False, "falhou": True}
    return {"ok": True, "ocupado": False, "atualizou": atualizou, "falhou": falhou}


def _preparar_paginas(painel: str, inicio: float) -> None:
    """Refaz a pagina do painel e, enquanto sobrar tempo, as dos paineis que leem os dados dele (para ninguem esperar a conta no primeiro acesso)."""
    dependentes = [p for p, deps in arm.DEPENDENCIAS.items() if painel in deps and p in modulos()]
    for p in [painel, *dependentes]:
        if p != painel and time.time() - inicio > PRAZO_TOTAL_S - 90:
            break
        try:
            garantir_pagina(p)
        except Exception as e:   # o painel dependente que falhar mostra o erro quando alguem abri-lo; a atualizacao em si deu certo
            print(f">>> AVISO: não consegui preparar a página de {p}: {type(e).__name__}: {e}", flush=True)


# ---------------------------------------------------------------- HTTP
def _consulta(h) -> dict[str, str]:
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query)
    return {k: v[0] for k, v in q.items()}


def responder(h, status: int, corpo, tipo: str = "application/json; charset=utf-8") -> None:
    if not isinstance(corpo, (bytes, str)):
        corpo = json.dumps(corpo, ensure_ascii=False)
    dados = corpo.encode("utf-8") if isinstance(corpo, str) else corpo
    cab = {"Content-Type": tipo, "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if tipo.startswith("text/html"):   # o painel so pode aparecer dentro do proprio site (iframe da pagina /painel/<id>)
        cab["X-Frame-Options"] = "SAMEORIGIN"
        cab["Content-Security-Policy"] = "frame-ancestors 'self'"
    if len(dados) > 4096 and "gzip" in h.headers.get("Accept-Encoding", ""):
        dados, cab["Content-Encoding"] = gzip.compress(dados, 5), "gzip"   # a Vercel limita a resposta da funcao a 4,5 MB
    h.send_response(status)
    for k, v in cab.items():
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(dados)))
    h.end_headers()
    h.wfile.write(dados)


def _pagina_de_aviso(titulo: str, texto: str, recarregar: bool = False) -> str:
    script = ("<script>try{if(!sessionStorage.getItem('rl')){sessionStorage.setItem('rl','1');parent.location.reload();}}catch(e){}</script>"
              if recarregar else "")
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{titulo}</title>"
            "<body style='font:16px system-ui,sans-serif;margin:0;padding:48px 24px;color:#222;background:#fafaf8'>"
            f"<h1 style='font-size:20px;margin:0 0 8px'>{titulo}</h1><p style='max-width:560px;color:#52514e'>{texto}</p>{script}")


def tratar(h, funcao) -> None:
    """Roda `funcao` e transforma Negado e erros em resposta, sem vazar detalhes tecnicos para quem nao e admin."""
    try:
        funcao()
    except Negado as e:
        if h.command == "GET" and "text/html" in h.headers.get("Accept", ""):
            return responder(h, e.status, _pagina_de_aviso("Acesso negado" if e.status == 403 else "Atenção", e.mensagem, recarregar=e.status == 401),
                             "text/html; charset=utf-8")
        responder(h, e.status, {"ok": False, "mensagem": e.mensagem})
    except Exception as e:
        traceback.print_exc()
        # detalhes tecnicos so ficam no log da Vercel; a excecao e a falta de configuracao (so nomes de variaveis), que o administrador precisa ver
        config = isinstance(e, arm.ErroArmazenamento) and "Falta a variavel" in str(e)
        responder(h, 500, {"ok": False, "mensagem": str(e) if config else "Erro no servidor. Avise um administrador."})


# -- as rotas (cada arquivo de api/ chama uma)
def rota_pagina(h) -> None:
    def fazer():
        q = _consulta(h)
        painel = q.get("id", "")
        u = conferir_acesso(h.headers, painel)
        periodo = periodo_da_url(q.get("de", ""), q.get("ate", ""))
        try:
            html, vencido, previsto = pagina_para_abrir(painel, periodo)   # nunca espera a atualizacao: ver pagina_para_abrir
        except Exception as e:
            traceback.print_exc()
            detalhe = f"{type(e).__name__}: {e}" if u["admin"] else "Avise um administrador."
            return responder(h, 500, _pagina_de_aviso("Não consegui montar este painel", detalhe), "text/html; charset=utf-8")
        responder(h, 200, com_marcas(html, painel, u["admin"], vencido, previsto, sem_financeiro=not u["financeiro"],
                                      visao=visao_restrita(u, painel)), "text/html; charset=utf-8")
    tratar(h, fazer)


def rota_estado(h) -> None:
    def fazer():
        painel = _consulta(h).get("id", "")
        conferir_acesso(h.headers, painel)
        v = arm.versao_dados(painel)
        andamento = arm.andamento(painel)   # renovacao em curso (a da tela do site, a do botao ou a do cron): a pagina mostra o aviso e espera
        # a mesma conta do "versao" que o gerador poe na pagina (int do timestamp de datetime.fromtimestamp)
        responder(h, 200, {"versao": int(datetime.fromtimestamp(v).timestamp()) if v else int(datetime.now().timestamp()), "atualizando": bool(andamento),
                           "andamento": andamento, "aviso": None})
    tratar(h, fazer)


def rota_atualizar(h) -> None:
    def fazer():
        if h.headers.get("X-Painel") != "1":   # barra paginas de outros sites chamando a API com o cookie do usuario
            raise Negado(403, "Pedido recusado.")
        painel = _consulta(h).get("id", "")
        u = conferir_acesso(h.headers, painel, so_admin=True)
        try:
            with trava_do_painel(painel, u["email"], arm.previsto_s(painel, USUARIO_SYNC, PREVISTO_SYNC_PADRAO_S)):
                resposta = atualizar(painel, u["email"])
        except Ocupado as o:
            a = o.andamento or {}
            return responder(h, 200, {"ok": True, "atualizou": False, "avisos": [],
                                      "mensagem": "Este painel já está sendo atualizado" + (f" (começou há {int(a['decorrido_s'])} s)" if a else "") +
                                                  ". Quando terminar, a página recarrega sozinha."})
        except Exception as e:
            traceback.print_exc()
            return responder(h, 200, {"ok": False, "mensagem": f"Não consegui atualizar: {type(e).__name__}: {e}"})
        responder(h, 200, resposta)
    tratar(h, fazer)


def rota_renovar(h) -> None:
    """POST /api/renovar?id=<painel>: a tela do site pede isso quando o painel abriu com dados vencidos. Qualquer pessoa com acesso ao painel pode
    pedir (so copia do banco e refaz a pagina; nao consulta o Klingo). Se outra renovacao ja roda, devolve o andamento dela."""
    def fazer():
        if h.headers.get("X-Painel") != "1":   # barra paginas de outros sites chamando a API com o cookie do usuario
            raise Negado(403, "Pedido recusado.")
        painel = _consulta(h).get("id", "")
        u = conferir_acesso(h.headers, painel)
        responder(h, 200, renovar(painel, u["email"]))
    tratar(h, fazer)


def rota_pendencias(h) -> None:
    """GET /api/pendencias?id=<painel>: o que a aba Avisos sabe dos alertas deste painel (fechados com justificativa, resolvidos, que voltaram).
    A pagina do painel mostra isso junto de cada alerta. Fechar um aviso e feito na aba Avisos (exige justificativa), nao aqui."""
    def fazer():
        painel = _consulta(h).get("id", "")
        u = conferir_acesso(h.headers, painel)
        if h.command != "GET":
            raise Negado(405, "Para fechar um alerta use a aba Avisos: lá é preciso justificar.")
        if visao_restrita(u, painel):   # os avisos descrevem a clinica toda: quem esta limitado a uma parte do painel nao os recebe
            return responder(h, 200, {"ok": True, "avisos": []})
        responder(h, 200, {"ok": True, "avisos": arm.listar_avisos(painel, com_sensiveis=u["financeiro"])})
    tratar(h, fazer)


def rota_preaquecer(h) -> None:
    """Chamada pelo Vercel Cron todo dia cedo (vercel.json): refaz a pagina de cada painel para o primeiro acesso do dia nao esperar a conta."""
    def fazer():
        segredo = os.environ.get("CRON_SECRET", "")
        if not segredo or h.headers.get("Authorization") != f"Bearer {segredo}":
            raise Negado(403, "Não autorizado.")
        resultado, inicio = {}, time.time()
        for painel in modulos():
            if time.time() - inicio > PRAZO_TOTAL_S - 60:
                resultado[painel] = "adiado"
                continue
            r = renovar(painel, "cron")   # copia do banco se venceu + refaz a pagina; se uma pessoa ja esta renovando este painel, deixa para ela
            resultado[painel] = "ocupado" if r["ocupado"] else ("ok" if r["ok"] and not r["falhou"] else "erro")
        responder(h, 200, {"ok": True, "paineis": resultado})
    tratar(h, fazer)
