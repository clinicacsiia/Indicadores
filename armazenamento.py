"""Armazenamento dos paineis no Supabase, no lugar do Excel e do SQLite do programa local.

Os geradores (gerar_*.py) e o klingo_relatorios.py continuam os mesmos: quando `ativo()` e verdadeiro, as
poucas funcoes que liam e gravavam o Excel (ler_abas, gravar, planilha_de...) chamam este modulo.

- Liga sozinho na Vercel (variavel VERCEL) ou com PORTAL_ARMAZENAMENTO=supabase. No computador da clinica
  (programa local) nada muda: continua Excel + SQLite.
- Fala com o Supabase pela API REST (so biblioteca padrao, nada a instalar) usando a service_role, que fica
  APENAS no servidor (SUPABASE_SERVICE_ROLE_KEY, variavel da Vercel). As tabelas tem RLS sem policy: o navegador nunca
  chega nelas. Quem pode ver cada painel e conferido em api/_comum.py antes de qualquer leitura.
- Os dados de cada aba ficam por mes, em lotes (ver supabase/migrations/20261013130000_paineis_python.sql). O mes e
  SUBSTITUIDO inteiro por `gravar_mes` (troca atomica), como o Excel fazia.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).parent
TAMANHO_LOTE = 1500          # linhas por lote gravado (mantem cada pedido na casa de 1 a 3 MB)
LOTES_POR_PAGINA = 40        # lotes lidos por pedido
TIMEOUT = 90                 # segundos por pedido ao Supabase
TENTATIVAS = 3
CACHE_VERSAO_S = 15          # quanto tempo a "data do arquivo" fica guardada na memoria (uma pagina consulta isso varias vezes)

# O que cada painel le de OUTROS paineis (para saber quando a pagina pronta ficou velha e quais dados atualizar junto).
# "metas" = dados da base #13339 (antiga planilha "Acompanhamento de META.xlsx"), usados pelo Atendimento.
DEPENDENCIAS = {
    "financeiro": ["faturamento"],
    "indicadores": ["faturamento", "financeiro"],
    "cesta": ["faturamento"],
    "suprimentos": ["faturamento", "atendimento"],
    "atendimento": ["metas"],
}
PAINEL_METAS, ABA_METAS = "metas", "Dados"


class ErroArmazenamento(RuntimeError):
    """O Supabase nao respondeu como esperado (configuracao, rede ou permissao)."""


def ativo() -> bool:
    return bool(os.environ.get("VERCEL")) or os.environ.get("PORTAL_ARMAZENAMENTO", "").lower() == "supabase"


# ---------------------------------------------------------------- acesso ao Supabase (REST)
def _url_base() -> str:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").strip().rstrip("/")
    if not url:
        raise ErroArmazenamento("Falta a variável SUPABASE_URL (a integração Supabase da Vercel já a cria).")
    return url


def _chave_servico() -> str:
    chave = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not chave:
        raise ErroArmazenamento("Falta a variável SUPABASE_SERVICE_ROLE_KEY nesta Vercel (Settings > Environment Variables; "
                                "a integração Supabase cria só em Production: marque Preview se for testar num preview).")
    return chave


def _pedir(metodo: str, caminho: str, params: dict | None = None, corpo=None, cabecalhos: dict | None = None, chave: str | None = None):
    """Pedido a API REST. Devolve (status, cabecalhos, corpo_ja_lido_como_json_ou_None). Tenta de novo em 5xx e falha de rede."""
    url = _url_base() + caminho
    if params:
        url += "?" + urllib.parse.urlencode(params, safe=",.*()")
    chave = chave or _chave_servico()
    cab = {"apikey": chave, "Authorization": f"Bearer {chave}", "Accept": "application/json"}
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo, ensure_ascii=False, allow_nan=False, default=_json_padrao).encode("utf-8")
        cab["Content-Type"] = "application/json"
    cab.update(cabecalhos or {})
    ultimo = None
    for tentativa in range(1, TENTATIVAS + 1):
        req = urllib.request.Request(url, data=dados, headers=cab, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                bruto = r.read()
                return r.status, dict(r.headers), (json.loads(bruto) if bruto.strip() else None)
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")[:600]
            if e.code == 416:   # PostgREST: a pagina pedida (Range) comeca depois do ultimo registro
                return 416, {}, []
            if e.code >= 500 and tentativa < TENTATIVAS:
                ultimo = f"HTTP {e.code}"
                time.sleep(tentativa)
                continue
            raise ErroArmazenamento(f"Supabase recusou {metodo} {caminho}: HTTP {e.code} {texto}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            ultimo = f"{type(e).__name__}: {e}"
            if tentativa < TENTATIVAS:
                time.sleep(tentativa)
                continue
    raise ErroArmazenamento(f"Não consegui falar com o Supabase ({metodo} {caminho}): {ultimo}")


def _json_padrao(o):
    if isinstance(o, datetime):
        return o.isoformat(timespec="seconds")
    if isinstance(o, date):
        return o.isoformat()
    if hasattr(o, "item"):   # numpy
        return o.item()
    raise TypeError(f"{type(o).__name__} nao vai para JSON")


def _dt(valor) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------- paineis e pastas
def painel_de_pasta(pasta) -> str:
    """Id do painel (modulos.json) de uma pasta: 'Faturamento' -> 'faturamento'; 'Acompanhamento de META' -> 'metas'."""
    nome = Path(pasta).name
    for m in json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))["modulos"]:
        if m["pasta"] == nome:
            return m["id"]
    return nome.lower()


def dependencias_de(painel: str) -> list[str]:
    return DEPENDENCIAS.get(painel, [])


def _paginado(caminho: str, params: dict, por_pagina: int) -> list[dict]:
    """Todas as linhas de uma consulta, `por_pagina` de cada vez (o Supabase corta cada resposta em 1000 linhas)."""
    todas, inicio = [], 0
    while True:
        _, _, parte = _pedir("GET", caminho, params, cabecalhos={"Range-Unit": "items", "Range": f"{inicio}-{inicio + por_pagina - 1}"})
        parte = parte or []
        todas.extend(parte)
        if len(parte) < por_pagina:
            return todas
        inicio += por_pagina


# ---------------------------------------------------------------- dados dos relatorios
def ler_aba(painel: str, aba: str) -> list[dict]:
    """Todas as linhas guardadas de uma aba (todos os meses), na ordem do mes. A coluna 'Mês (filtro)' ja vem dentro de cada linha."""
    lotes = _paginado("/rest/v1/painel_dados_ativos",
                      {"painel": f"eq.{painel}", "aba": f"eq.{aba}", "select": "mes,lote,linhas", "order": "mes.asc,lote.asc"}, LOTES_POR_PAGINA)
    return [linha for lote in lotes for linha in lote["linhas"]]


def meses_gravados(painel: str) -> dict[tuple[str, str], datetime | None]:
    """{(aba, mes): quando foi atualizado} de um painel."""
    res = _paginado("/rest/v1/painel_mes", {"painel": f"eq.{painel}", "select": "aba,mes,atualizado_em", "order": "aba.asc,mes.asc"}, 500)
    return {(r["aba"], r["mes"]): _dt(r["atualizado_em"]) for r in res}


def gravar_mes(painel: str, aba: str, mes: str, linhas: list[dict], exclusivo: bool = False) -> int:
    """Substitui TODAS as linhas do mes dessa aba pelas `linhas` (troca atomica no banco). Devolve quantas linhas ficaram."""
    versao = uuid.uuid4().hex
    for n, ini in enumerate(range(0, len(linhas), TAMANHO_LOTE)):
        parte = linhas[ini:ini + TAMANHO_LOTE]
        _pedir("POST", "/rest/v1/painel_dados", corpo=[{"painel": painel, "aba": aba, "mes": mes, "versao": versao, "lote": n,
                                                       "linhas": parte, "n_linhas": len(parte)}],
               cabecalhos={"Prefer": "return=minimal"})
    _pedir("POST", "/rest/v1/rpc/painel_publicar_mes",
           corpo={"p_painel": painel, "p_aba": aba, "p_mes": mes, "p_versao": versao, "p_n_linhas": len(linhas), "p_exclusivo": exclusivo})
    _CACHE_VERSAO.clear()
    return len(linhas)


_CACHE_VERSAO: dict[str, tuple[float, float | None]] = {}


def versao_dados(painel: str) -> float | None:
    """Quando os dados do painel foram atualizados pela ultima vez (epoch, como o st_mtime do Excel). None = nunca."""
    agora = time.time()
    guardado = _CACHE_VERSAO.get(painel)
    if guardado and agora - guardado[0] < CACHE_VERSAO_S:
        return guardado[1]
    _, _, res = _pedir("GET", "/rest/v1/painel_mes", {"painel": f"eq.{painel}", "select": "atualizado_em", "order": "atualizado_em.desc", "limit": "1"})
    quando = _dt(res[0]["atualizado_em"]) if res else None
    v = quando.timestamp() if quando else None
    _CACHE_VERSAO[painel] = (agora, v)
    return v


def versao_com_dependencias(painel: str) -> int:
    """Versao que invalida a pagina pronta: a mais nova entre os dados do painel e dos paineis que ele le."""
    vs = [versao_dados(p) for p in [painel, *dependencias_de(painel)]]
    return int(max([v for v in vs if v] or [0]))


class PlanilhaVirtual:
    """Faz o papel do arquivo .xlsx para o codigo dos paineis (que so pergunta se existe e quando mudou)."""

    def __init__(self, painel: str):
        self.painel = painel
        self.name = f"{painel} (Supabase)"

    def exists(self) -> bool:
        return versao_dados(self.painel) is not None

    def stat(self):
        v = versao_dados(self.painel)
        if v is None:
            raise FileNotFoundError(self.name)
        return SimpleNamespace(st_mtime=v, st_mtime_ns=int(v * 1e9), st_size=0)

    def __str__(self):
        return self.name


# ---------------------------------------------------------------- dados da base de Metas (so para o Atendimento)
def ler_metas_dados():
    """DataFrame 'Dados' do painel de Metas (antiga aba 'Dados' do Excel); vazio se ainda nao foi baixado."""
    import pandas as pd
    linhas = ler_aba(PAINEL_METAS, ABA_METAS)
    return pd.DataFrame(linhas) if linhas else None


# ---------------------------------------------------------------- paginas prontas
def ler_pagina(painel: str, chave: str) -> dict | None:
    _, _, res = _pedir("GET", "/rest/v1/painel_pagina", {"painel": f"eq.{painel}", "chave": f"eq.{chave}", "select": "html,dados_versao,dia,gerado_em"})
    return res[0] if res else None


def gravar_pagina(painel: str, chave: str, html: str, dados_versao: int, dia: date) -> None:
    _pedir("POST", "/rest/v1/painel_pagina", params={"on_conflict": "painel,chave"},
           corpo=[{"painel": painel, "chave": chave, "html": html, "dados_versao": int(dados_versao), "dia": dia.isoformat(),
                   "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}],
           cabecalhos={"Prefer": "resolution=merge-duplicates,return=minimal"})


def limpar_paginas(painel: str, manter_versao: int, manter_dia: date) -> None:
    """Apaga as paginas de periodo (varios meses) calculadas com dados ou dia antigos."""
    _pedir("DELETE", "/rest/v1/painel_pagina",
           {"painel": f"eq.{painel}", "chave": "neq.padrao", "or": f"(dados_versao.neq.{int(manter_versao)},dia.neq.{manter_dia.isoformat()})"},
           cabecalhos={"Prefer": "return=minimal"})


# ---------------------------------------------------------------- avisos (aba Avisos)
def sincronizar_avisos(painel: str, escopos: list[str], versao: int, alertas: list[dict]) -> dict:
    """Compara os alertas que o painel mostra agora com os avisos registrados (novo, resolvido, voltou...). Quem decide e o banco: aviso_sincronizar."""
    _, _, res = _pedir("POST", "/rest/v1/rpc/aviso_sincronizar",
                       corpo={"p_painel": painel, "p_escopos": escopos, "p_versao": int(versao), "p_alertas": alertas})
    return res or {}


def listar_avisos(painel: str) -> list[dict]:
    """Avisos do painel que ja tiveram desfecho ou historico (justificados, resolvidos ou que voltaram): e o que a pagina do painel mostra junto dos alertas."""
    campos = "id,chave,titulo,status,recorrencias,reaberturas,justificativa,justificado_por,justificado_em,resolvido_em"
    _, _, res = _pedir("GET", "/rest/v1/aviso", {"painel": f"eq.{painel}", "select": campos, "order": "id.asc"})
    return [r for r in (res or []) if r["status"] != "aberto" or r["recorrencias"] or r["reaberturas"]]


# ---------------------------------------------------------------- historico de atualizacoes e custos
def registrar_atualizacao(painel: str, status: str, mensagem: str, duracao_segundos: float = 0.0, usuario: str = "") -> None:
    try:
        _pedir("POST", "/rest/v1/painel_atualizacao", corpo=[{"painel": painel, "usuario": usuario, "status": status, "mensagem": mensagem[:2000],
                                                             "duracao_segundos": round(duracao_segundos, 1)}],
               cabecalhos={"Prefer": "return=minimal"})
    except ErroArmazenamento as e:   # o historico nunca derruba uma atualizacao que deu certo
        print(f">>> AVISO: não consegui registrar a atualização no histórico ({e})", flush=True)


def ultima_atualizacao(painel: str) -> datetime | None:
    """Quando o painel foi atualizado pela ultima vez (botao ou automatica), mesmo que nao tenha mudado nada; None = nunca.
    Refazer so a pagina (status 'pagina') nao conta: ela nao traz dados novos."""
    _, _, res = _pedir("GET", "/rest/v1/painel_atualizacao", {"painel": f"eq.{painel}", "status": "neq.pagina", "select": "criado_em",
                                                              "order": "criado_em.desc", "limit": "1"})
    return _dt(res[0]["criado_em"]) if res else None


# ---------------------------------------------------------------- renovacao em andamento (trava + andamento)
TRAVA_VENCE_S = 6 * 60   # a funcao da Vercel para em 300 s: trava mais velha que isso e de uma execucao que morreu


def travar_painel(painel: str, usuario: str, previsto_s: int) -> bool | None:
    """Tenta ser a unica renovacao deste painel. True = conseguiu (chame liberar_painel no fim); False = ja ha outra rodando;
    None = a tabela painel_renovacao nao existe/nao respondeu (segue sem trava, como antes da trava existir)."""
    try:
        limite = (datetime.now(timezone.utc) - timedelta(seconds=TRAVA_VENCE_S)).isoformat(timespec="seconds")
        _pedir("DELETE", "/rest/v1/painel_renovacao", {"painel": f"eq.{painel}", "iniciado_em": f"lt.{limite}"}, cabecalhos={"Prefer": "return=minimal"})
        _, _, res = _pedir("POST", "/rest/v1/painel_renovacao", params={"on_conflict": "painel"},
                           corpo=[{"painel": painel, "usuario": usuario, "previsto_s": int(previsto_s),
                                   "iniciado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}],
                           cabecalhos={"Prefer": "resolution=ignore-duplicates,return=representation"})
        return bool(res)
    except ErroArmazenamento as e:
        print(f">>> AVISO: sem trava de renovação em {painel} ({e})", flush=True)
        return None


def liberar_painel(painel: str) -> None:
    try:
        _pedir("DELETE", "/rest/v1/painel_renovacao", {"painel": f"eq.{painel}"}, cabecalhos={"Prefer": "return=minimal"})
    except ErroArmazenamento as e:   # a trava vence sozinha
        print(f">>> AVISO: não consegui liberar a trava de {painel} ({e})", flush=True)


def andamento(painel: str) -> dict | None:
    """{'decorrido_s', 'previsto_s', 'usuario'} da renovacao em andamento; None se nao ha (ou a trava ja venceu)."""
    try:
        _, _, res = _pedir("GET", "/rest/v1/painel_renovacao", {"painel": f"eq.{painel}", "select": "iniciado_em,previsto_s,usuario"})
    except ErroArmazenamento:
        return None
    if not res:
        return None
    inicio = _dt(res[0]["iniciado_em"])
    decorrido = (datetime.now(timezone.utc) - inicio).total_seconds() if inicio else 0.0
    if decorrido > TRAVA_VENCE_S:
        return None
    return {"decorrido_s": round(max(decorrido, 0.0), 1), "previsto_s": int(res[0].get("previsto_s") or 30), "usuario": res[0].get("usuario") or ""}


def previsto_s(painel: str, usuario: str, padrao: int) -> int:
    """Quanto costuma levar (mediana das ultimas 5 execucoes bem-sucedidas do mesmo tipo, `usuario`); `padrao` se nao ha historico."""
    try:
        _, _, res = _pedir("GET", "/rest/v1/painel_atualizacao", {"painel": f"eq.{painel}", "usuario": f"eq.{usuario}", "status": "neq.erro",
                                                                  "select": "duracao_segundos", "order": "criado_em.desc", "limit": "5"})
    except ErroArmazenamento:
        return padrao
    duracoes = sorted(float(r["duracao_segundos"]) for r in (res or []) if r.get("duracao_segundos"))
    return max(int(round(duracoes[len(duracoes) // 2])), 5) if duracoes else padrao


def custos_informados() -> dict[str, float]:
    """Custos digitados a mao (tabela painel_custo_item), no lugar da planilha 'Custos dos Itens.xlsx'."""
    try:
        res = _paginado("/rest/v1/painel_custo_item", {"select": "item,custo", "custo": "gt.0", "order": "item.asc"}, 500)
    except ErroArmazenamento as e:
        print(f">>> AVISO: não consegui ler os custos informados ({e})", flush=True)
        return {}
    return {r["item"]: float(r["custo"]) for r in res}


# ---------------------------------------------------------------- usuarios (login do Supabase)
def usuario_do_token(token: str) -> dict | None:
    """{'id', 'email'} do dono do token de acesso (o Supabase confere assinatura e validade); None se invalido ou vencido."""
    anon = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or ""
    req = urllib.request.Request(_url_base() + "/auth/v1/user", headers={"apikey": anon.strip(), "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            u = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return None
        raise ErroArmazenamento(f"Falha ao conferir o login: HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroArmazenamento(f"Falha ao conferir o login: {e}") from None
    return {"id": u.get("id"), "email": u.get("email") or ""} if u.get("id") else None


def perfil(user_id: str) -> dict | None:
    """{'role', 'permissions'} do usuario (tabela profiles)."""
    _, _, res = _pedir("GET", "/rest/v1/profiles", {"id": f"eq.{user_id}", "select": "role,permissions"})
    return res[0] if res else None
