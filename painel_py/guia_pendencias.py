"""Guia dos alertas: tabelas de evidencia, formatacao e "Como achar o problema" de cada alerta de problema.

ATENCAO: o guia_pendencias.py original nao veio na copia recebida. As funcoes de formatacao (tabela, reais, dbr) e anotar() foram
RECONSTRUIDAS a partir do uso nos gerar_*.py; os textos de cada alerta ficam em guia_regras.py (ver docs/PREMISSAS.md).
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from datetime import date, datetime

import pandas as pd

import guia_regras

MAX_ITENS = 25   # linhas mostradas em cada tabela de evidencia (o total real vai junto)
log = logging.getLogger("guia_pendencias")
URL_RELATORIO = "https://clinicacsi.klingo.app/#/relatorio/{id}"


def _vazio(v) -> bool:
    return v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v))


def reais(v) -> str:
    """R$ 1.234,56 (traco se vazio)."""
    if _vazio(v):
        return "—"
    s = f"{abs(float(v)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if float(v) < 0 else ''}R$ {s}"


def dbr(v) -> str:
    """dd/mm/aaaa (traco se vazio)."""
    if _vazio(v):
        return "—"
    if isinstance(v, str):
        try:
            v = pd.Timestamp(v)
        except (ValueError, TypeError):
            return v
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return f"{v:%d/%m/%Y}"
    return str(v)


def _celula(v):
    if _vazio(v):
        return "—"
    if hasattr(v, "item") and not isinstance(v, (int, float, str)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    return v


def tabela(cabecalho: list[str], linhas: list[list], total: int | None = None, numericas: tuple = ()) -> dict:
    """Tabela de evidencia de um alerta: no maximo MAX_ITENS linhas, com o total real para o painel dizer "mostrando 25 de 130"."""
    total = len(linhas) if total is None else int(total)
    return {"cab": list(cabecalho), "linhas": [[_celula(c) for c in l] for l in linhas[:MAX_ITENS]],
            "total": total, "numericas": list(numericas)}


def slug(titulo: str) -> str:
    t = unicodedata.normalize("NFKD", str(titulo)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:80]


def anotar(painel: str, alertas: list[dict], escopo: str = "geral") -> list[dict]:
    """Marca cada alerta de problema (critico/atencao) com a chave estavel (escopo|id) e o guia. Os informativos ficam sem botoes."""
    for a in alertas:
        if a.get("nivel") not in ("critico", "atencao"):
            continue
        a["painel"] = painel
        a["chave"] = f"{escopo}|{slug(a.get('titulo', ''))}"
        regra = guia_regras.regra(painel, a.get("titulo", ""))
        if regra is None or regra.get("generica"):   # alerta de problema sem regra própria: segue com guia genérico e avisa no log
            log.warning("Alerta de problema sem regra de guia: %s / %s", painel, a.get("titulo"))
        if regra is None:
            a["guia"] = None
            continue
        a["guia"] = {"relatorio": regra["relatorio"], "url": URL_RELATORIO.format(id=regra["id"]) if regra.get("id") else None,
                     "passos": regra["passos"], "resolvido_quando": regra["resolvido"]}
    return alertas
