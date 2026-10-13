"""Cache das paginas dos paineis no Supabase (tabela painel_cache): vale enquanto os dados (dados_versao) e o dia nao mudam.

A chave de versao junta o contador do proprio menu e o dos menus de que ele depende (Financeiro le o Faturamento, etc.): assim, quando
qualquer fonte muda, a pagina e recalculada. Primeira geracao de todos os paineis levava 30-60 s de CPU no legado: por isso o pre-aquecimento
apos cada atualizacao e o cache por (menu, periodo, versao).
"""
from __future__ import annotations

import base64
import gzip
from datetime import date

import fonte

DEPENDE_DE = {
    "metas": [], "faturamento": [], "financeiro": ["faturamento"], "despesas": [],
    "indicadores": ["faturamento", "financeiro"], "cesta": ["faturamento"], "suprimentos": ["atendimento"], "atendimento": ["metas"],
}


def chave_versao(menu: str) -> str:
    partes = [f"{m}:{fonte.contador_versao(m)}" for m in [menu, *DEPENDE_DE.get(menu, [])]]
    return "|".join(partes) + f"|{date.today().isoformat()}"


def ler(menu: str, periodo: str, versao: str) -> str | None:
    if fonte._dir():
        return None
    linhas = fonte.rest("painel_cache", {"select": "chave_versao,conteudo", "menu": f"eq.{menu}", "periodo": f"eq.{periodo}"})
    if linhas and linhas[0]["chave_versao"] == versao:
        return gzip.decompress(base64.b64decode(linhas[0]["conteudo"])).decode("utf-8")
    return None


def gravar(menu: str, periodo: str, versao: str, html: str) -> None:
    if fonte._dir():
        return
    corpo = {"menu": menu, "periodo": periodo, "chave_versao": versao, "conteudo": base64.b64encode(gzip.compress(html.encode("utf-8"))).decode()}
    fonte.rest("painel_cache", {"on_conflict": "menu,periodo"}, "POST", corpo, {"Prefer": "resolution=merge-duplicates,return=minimal"})


def limpar_antigos(menu: str, manter: int = 24) -> None:
    """Periodos escolhidos uma vez nao acumulam para sempre: guarda os ultimos 'manter' de cada menu."""
    if fonte._dir():
        return
    linhas = fonte.rest("painel_cache", {"select": "periodo,gerado_em", "menu": f"eq.{menu}", "order": "gerado_em.desc", "offset": str(manter), "limit": "200"}) or []
    for l in linhas:
        fonte.rest("painel_cache", {"menu": f"eq.{menu}", "periodo": f"eq.{l['periodo']}"}, "DELETE")
