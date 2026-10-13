"""Ponto de entrada do calculo dos paineis: menu + periodo -> pagina HTML (a mesma que o legado gerava).

Faz o papel que o servidor_portal.py tinha para os gerar_*.py: poe as pastas dos menus no caminho de importacao, acerta o fuso de Salvador
e chama gerar(de, ate, devolver_html=True) do menu pedido.
"""
from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).parent
os.environ.setdefault("TZ", "America/Bahia")   # "hoje" e "ultimo dia completo" sao de Salvador, nao da Vercel (UTC)
if hasattr(time, "tzset"):
    time.tzset()

PASTAS = ["Acompanhamento de META", "Faturamento", "Financeiro", "Despesas", "Indicadores", "Cesta", "Suprimentos", "Atendimento"]
for p in [RAIZ, *(RAIZ / n for n in PASTAS)]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MODULO_DO_MENU = {
    "metas": "gerar_dashboard", "faturamento": "gerar_faturamento", "financeiro": "gerar_financeiro", "despesas": "gerar_despesas",
    "indicadores": "gerar_indicadores", "cesta": "gerar_cesta", "suprimentos": "gerar_suprimentos", "atendimento": "gerar_atendimento",
}
MENUS = list(MODULO_DO_MENU)


def gerar_html(menu: str, de: str | None = None, ate: str | None = None) -> str:
    if menu not in MODULO_DO_MENU:
        raise KeyError(f"Menu desconhecido: {menu!r}")
    mod = importlib.import_module(MODULO_DO_MENU[menu])
    return mod.gerar(de or None, ate or None, devolver_html=True)
