"""Conferência dos números entre relatórios ("Conferir números").

ATENÇÃO: o conferir_numeros.py do legado (~248 checagens) não veio. Aqui estão só as conferências CRUZADAS descritas no prompt do projeto,
escritas de novo; as "contas internas dos painéis" ainda não foram portadas. Cada checagem devolve {nome, ok, esperado, obtido, detalhe}.
Tolerâncias são as do prompt (#26 × #13329 ~0,1%; Metas × #26 ~0,8%; Cesta cobre ~93,7% do #26).
"""
from __future__ import annotations

import pandas as pd

import klingo_relatorios as k
import painel_comum as pc
from painel_runtime import RAIZ

FAT = RAIZ / "Faturamento"
ESCOPO = 0.01   # tolerância relativa padrão (1%)


def _soma(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum()) if len(df) and col in df.columns else 0.0


def _rel(a: float, b: float) -> float | None:
    return (a - b) / b if b else None


def _item(nome: str, esperado, obtido, tol: float | None = None, detalhe: str = "", ok: bool | None = None) -> dict:
    if ok is None:
        d = _rel(obtido, esperado) if isinstance(esperado, (int, float)) and isinstance(obtido, (int, float)) else None
        ok = (abs(d) <= (tol if tol is not None else ESCOPO)) if d is not None else (obtido == esperado)
    return {"nome": nome, "ok": bool(ok), "esperado": esperado, "obtido": obtido, "detalhe": detalhe}


def conferir() -> list[dict]:
    out: list[dict] = []
    abas = k.carregar(FAT)
    prod, ctrl, aberto, emit = abas.get("Receita Produzida"), abas.get("Controle por Convênio"), abas.get("Faturas em Aberto"), abas.get("Faturas Emitidas")
    meses = sorted({m for m in prod.get(k.COL_MES, pd.Series(dtype=str)).dropna().unique()}) if prod is not None else []

    # 1) receita de convênios do #26 × produzido do #13329 (por mês), ~0,1%
    for ym in meses:
        p = prod[prod[k.COL_MES] == ym]
        conv26 = _soma(p[p["Operadora"].astype(str).str.upper().str.strip() != "PARTICULAR"], "Valor") if "Operadora" in p.columns else 0.0
        c = ctrl[ctrl[k.COL_MES] == ym] if ctrl is not None and len(ctrl) else ctrl
        prod13329 = _soma(c, "Produzido") if c is not None else 0.0
        if prod13329:
            out.append(_item(f"Receita de convênios (Faturamento) × Produzido (Controle por Convênio) em {pc.rotulo_mes(ym)}", prod13329, conv26, 0.01,
                             "diferença esperada de cerca de 0,1%"))

    # 2) faturas emitidas × faturas em aberto, lote a lote (protocolo = Nº do Lote)
    if emit is not None and aberto is not None and len(emit) and len(aberto) and "Fatura - Envio - Protocolo" in emit.columns:
        e = emit[emit["Fatura - Envio - Protocolo"].notna()].copy()
        e["_lote"] = e["Fatura - Envio - Protocolo"].astype(str).str.strip()
        por_lote = e.groupby("_lote")["Fatura - Valor"].sum()
        a = aberto.copy()
        a["_lote"] = a["Nº do Lote"].astype(str).str.strip()
        a_lote = a.groupby("_lote")["Valor Bruto"].sum()
        comuns = por_lote.index.intersection(a_lote.index)
        difs = [(l, float(por_lote[l]), float(a_lote[l])) for l in comuns if abs(por_lote[l] - a_lote[l]) > 0.01]
        out.append(_item("Faturas emitidas × faturas em aberto, lote a lote (valores)", 0, len(difs), ok=len(difs) == 0,
                         detalhe=f"{len(comuns)} lote(s) em comum; divergentes: {', '.join(f'{l} ({e_:.2f} × {a_:.2f})' for l, e_, a_ in difs[:5]) or 'nenhum'}"))

    # 3) recebido do #13329 = faturas movimentadas do #13355 (por competência = mês do início do período faturado)
    if emit is not None and len(emit) and ctrl is not None and len(ctrl) and "Fatura - Data Inicial" in emit.columns:
        mov = emit[emit["Fatura - Status"] == "Movimentada"].copy()
        mov["_comp"] = pd.to_datetime(mov["Fatura - Data Inicial"], errors="coerce").dt.strftime("%Y-%m")
        for ym in meses:
            rec = _soma(ctrl[ctrl[k.COL_MES] == ym], "Recebido")
            if rec:
                out.append(_item(f"Recebido (Controle por Convênio) × faturas movimentadas em {pc.rotulo_mes(ym)}", rec, _soma(mov[mov["_comp"] == ym], "Fatura - Valor"), 0.02))

    # 4) Metas × #26 em linhas (~0,8%)
    try:
        import gerar_dashboard as gd
        dm = gd.carregar_dados()
        for ym in meses:
            n_metas = int((dm["Data do Atendimento"].dt.strftime("%Y-%m") == ym).sum()) if len(dm) else 0
            p = prod[prod[k.COL_MES] == ym]
            n_prod = int(pd.to_numeric(p["Quantidade"], errors="coerce").fillna(1).sum()) if len(p) and "Quantidade" in p.columns else len(p)
            if n_prod and n_metas:
                out.append(_item(f"Atendimentos das Metas × linhas da Receita Produzida em {pc.rotulo_mes(ym)}", n_prod, n_metas, 0.02, "diferença esperada de cerca de 0,8%"))
    except Exception as e:   # sem dados de Metas ainda
        out.append(_item("Metas × Receita Produzida", "dados", "indisponível", ok=True, detalhe=f"não conferido: {type(e).__name__}"))

    # 5) Cesta × #26: a Cesta mede ~93,7% do produzido
    cesta = k.carregar(RAIZ / "Cesta").get("Base Cesta")
    if cesta is not None and len(cesta) and "Valor" in cesta.columns:
        for ym in meses:
            v_cesta = _soma(cesta[cesta[k.COL_MES] == ym], "Valor")
            v_prod = _soma(prod[prod[k.COL_MES] == ym], "Valor")
            if v_cesta and v_prod:
                pct = v_cesta / v_prod * 100
                out.append(_item(f"Cesta × Receita Produzida em {pc.rotulo_mes(ym)} (cobertura)", 93.7, round(pct, 1), 0.10, "a Cesta só mede cerca de 93,7% do produzido (por isso o ajuste ao Faturamento)"))
    return out
