"""Leitura dos dados do Klingo para os paineis (lado Python).

ATENCAO: o klingo_relatorios.py original (que baixava os relatorios e gravava no Excel) nao veio na copia recebida e, no site novo, a
sincronizacao com o Klingo roda no servidor Next.js (src/klingo/). Este modulo mantem so a parte que os gerar_*.py usam para LER os dados
(carregar, ler_definicao, planilha_de, meses_entre, mes_mais, COL_MES) e le do Supabase em vez do Excel. Ver docs/PREMISSAS.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import fonte
from painel_comum import MENU_DA_PASTA, mes_mais, meses_entre  # noqa: F401  (reexportados: os paineis usam k.mes_mais / k.meses_entre)

COL_MES = "Mês (filtro)"       # mes em que o dado foi pedido ao Klingo (AAAA-MM), igual a coluna do Excel do legado
COL_EM = "Atualizado em"       # quando a linha foi gravada pela ultima vez


def _menu(pasta) -> str:
    nome = Path(pasta).name
    if nome not in MENU_DA_PASTA:
        raise KeyError(f"Pasta de menu desconhecida: {nome!r}")
    return MENU_DA_PASTA[nome]


def ler_definicao(pasta) -> dict:
    """relatorios.json do menu (com BOM, se houver)."""
    return json.loads((Path(pasta) / "relatorios.json").read_text(encoding="utf-8-sig"))


class _Stat:
    def __init__(self, ts: float):
        self.st_mtime = ts
        self.st_mtime_ns = int(ts * 1e9)
        self.st_size = 0


class Arquivo:
    """Faz o papel do .xlsx do legado: 'quando os dados mudaram' (dados_versao), que os paineis usam como 'dados de ...' e como chave de cache."""

    def __init__(self, menu: str):
        self.menu = menu
        self.name = f"{menu}"

    def exists(self) -> bool:
        return fonte.versao_dados(self.menu) is not None

    def stat(self) -> _Stat:
        v = fonte.versao_dados(self.menu)
        if v is None:
            raise OSError("sem dados")
        return _Stat(v)

    def as_uri(self) -> str:
        return f"dados://{self.menu}"

    def __str__(self) -> str:
        return self.name


def planilha_de(pasta) -> Arquivo:
    return Arquivo(_menu(pasta))


def _converter(df: pd.DataFrame, defn_aba: dict) -> pd.DataFrame:
    for c in defn_aba.get("datas", {}):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in defn_aba.get("numeros", []):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def carregar(pasta) -> dict[str, pd.DataFrame]:
    """{nome da aba: DataFrame}, com as mesmas colunas que o Excel do legado tinha (titulos do Klingo + COL_MES)."""
    menu = _menu(pasta)
    defn = ler_definicao(pasta) if (Path(pasta) / "relatorios.json").exists() else {"relatorios": []}
    por_aba: dict[str, list[pd.DataFrame]] = {}
    for b in fonte.blocos(menu):
        df = pd.DataFrame(b["linhas"], columns=b["colunas"])
        df[COL_MES] = b["mes"]
        por_aba.setdefault(b["aba"], []).append(df)
    saida: dict[str, pd.DataFrame] = {}
    for r in defn.get("relatorios", []):
        partes = por_aba.get(r["aba"], [])
        df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=[*r.get("numeros", []), *r.get("datas", {}), COL_MES])
        df = _converter(df, r)
        if r.get("ordenar") and len(df) and all(c in df.columns for c in r["ordenar"]):
            df = df.sort_values(r["ordenar"], kind="stable", na_position="last").reset_index(drop=True)
        saida[r["aba"]] = df
    return saida


def atualizar(*_a, **_k):
    raise RuntimeError("A atualização com o Klingo roda no servidor do site (POST /api/atualizar), não neste módulo.")
