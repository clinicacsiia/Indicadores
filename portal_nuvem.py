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
from datetime import date, datetime
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
CACHE_LOGIN_S = 60
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


def autenticar(cabecalhos) -> dict:
    """{'id', 'email', 'admin', 'permissoes'} do usuario logado; levanta Negado(401) sem login valido."""
    token = token_do_pedido(cabecalhos)
    if not token:
        raise Negado(401, "Sessão não encontrada. Entre de novo no site.")
    agora = time.time()
    guardado = _LOGINS.get(token)
    if guardado and agora - guardado[0] < CACHE_LOGIN_S and guardado[1]:
        return guardado[1]
    u = arm.usuario_do_token(token)
    if not u:
        raise Negado(401, "Sua sessão expirou. Recarregue a página para entrar de novo.")
    p = arm.perfil(u["id"]) or {}
    info = {"id": u["id"], "email": u["email"], "admin": p.get("role") == "admin", "permissoes": p.get("permissions") or {}}
    if len(_LOGINS) > 200:
        _LOGINS.clear()
    _LOGINS[token] = (agora, info)
    return info


def conferir_acesso(cabecalhos, painel: str, so_admin: bool = False) -> dict:
    """Login valido + painel existente + permissao. Admin sempre; viewer so com permissions.<painel> = true (painel novo nasce bloqueado)."""
    if painel not in modulos():
        raise Negado(404, "Painel não encontrado.")
    u = autenticar(cabecalhos)
    if so_admin and not u["admin"]:
        raise Negado(403, "Somente administradores podem fazer isso.")
    if not u["admin"] and u["permissoes"].get(painel) is not True:
        raise Negado(403, "Você não tem permissão para ver este painel. Peça a um administrador em Configurações.")
    return u


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


def garantir_pagina(painel: str, periodo: tuple[str, str] | None = None, guardar: bool = True) -> str:
    """HTML do painel: o guardado se os dados e o dia ainda valem; senao calcula (e guarda para os proximos)."""
    chave = "padrao" if not periodo else f"{periodo[0]}..{periodo[1]}"
    hoje, versao = date.today(), arm.versao_com_dependencias(painel)
    pronta = arm.ler_pagina(painel, chave)
    # a pagina guardada so vale se os dados, o dia E o layout (CSS/JS/modelo, ver painel_comum.versao_layout) sao os de agora
    if pronta and pronta["dados_versao"] == versao and pronta["dia"] == hoje.isoformat() and _marca_layout() in pronta["html"]:
        return pronta["html"]
    html = montar_pagina(painel, periodo)
    if guardar:
        try:
            arm.gravar_pagina(painel, chave, html, versao, hoje)
            if not periodo:
                arm.limpar_paginas(painel, versao, hoje)
        except arm.ErroArmazenamento as e:   # sem guardar so fica mais lento; a pagina sai do mesmo jeito
            print(f">>> AVISO: não consegui guardar a página de {painel} ({e})", flush=True)
    return html


def com_marcas(html: str, painel: str, admin: bool) -> str:
    """Poe no HTML o que o painel_base.js precisa saber (painel, nuvem, se o usuario e admin). Feito a cada pedido: a pagina guardada e a mesma para todos."""
    # "embutido": a pagina aparece dentro de uma tela do site, que ja da o respiro e o fundo (ver .embutido em painel_base.css)
    marca = (f"<script>window.PAINEL_NUVEM=true;window.PAINEL_ID={json.dumps(painel)};window.PAINEL_ADMIN={'true' if admin else 'false'};"
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
            html = garantir_pagina(painel, periodo)
        except Exception as e:
            traceback.print_exc()
            detalhe = f"{type(e).__name__}: {e}" if u["admin"] else "Avise um administrador."
            return responder(h, 500, _pagina_de_aviso("Não consegui montar este painel", detalhe), "text/html; charset=utf-8")
        responder(h, 200, com_marcas(html, painel, u["admin"]), "text/html; charset=utf-8")
    tratar(h, fazer)


def rota_estado(h) -> None:
    def fazer():
        painel = _consulta(h).get("id", "")
        conferir_acesso(h.headers, painel)
        v = arm.versao_dados(painel)
        # a mesma conta do "versao" que o gerador poe na pagina (int do timestamp de datetime.fromtimestamp)
        responder(h, 200, {"versao": int(datetime.fromtimestamp(v).timestamp()) if v else int(datetime.now().timestamp()), "atualizando": False, "aviso": None})
    tratar(h, fazer)


def rota_atualizar(h) -> None:
    def fazer():
        if h.headers.get("X-Painel") != "1":   # barra paginas de outros sites chamando a API com o cookie do usuario
            raise Negado(403, "Pedido recusado.")
        painel = _consulta(h).get("id", "")
        u = conferir_acesso(h.headers, painel, so_admin=True)
        try:
            resposta = atualizar(painel, u["email"])
        except Exception as e:
            traceback.print_exc()
            return responder(h, 200, {"ok": False, "mensagem": f"Não consegui atualizar: {type(e).__name__}: {e}"})
        responder(h, 200, resposta)
    tratar(h, fazer)


def rota_pendencias(h) -> None:
    def fazer():
        q = _consulta(h)
        painel = q.get("id", "")
        u = conferir_acesso(h.headers, painel)
        if h.command == "GET":
            return responder(h, 200, {"ok": True, "resolvidas": arm.listar_pendencias(painel)})
        if h.headers.get("X-Painel") != "1":
            raise Negado(403, "Pedido recusado.")
        acao = q.get("acao", "")
        if acao not in ("resolver", "reabrir"):
            raise Negado(404, "Ação desconhecida.")
        try:
            tam = int(h.headers.get("Content-Length") or 0)
            dados = json.loads(h.rfile.read(min(tam, 65536)) or b"{}")
        except ValueError:
            raise Negado(400, "Pedido inválido.")
        chave = str(dados.get("chave", ""))[:200]
        if not chave:
            raise Negado(400, "Falta a chave do alerta.")
        if acao == "resolver":
            arm.marcar_pendencia(painel, chave, str(dados.get("titulo", ""))[:300], u["email"], int(dados.get("versao") or 0))
        else:
            arm.desmarcar_pendencia(painel, chave)
        responder(h, 200, {"ok": True, "resolvidas": arm.listar_pendencias(painel)})
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
            try:
                garantir_pagina(painel)
                resultado[painel] = "ok"
            except Exception as e:
                resultado[painel] = f"erro: {type(e).__name__}: {e}"
        responder(h, 200, {"ok": True, "paineis": resultado})
    tratar(h, fazer)
