"""Suprimentos: atualiza a planilha a partir do Klingo e gera 'Dashboard Suprimentos.html'.

Relatorios do Klingo (grupo "Suprimentos"):
  #13385  Suprimentos - Movimentações   cada entrada e saida de estoque (compra, consumo, transferencia, inventario, perda)
  #13387  Suprimentos - Solicitações    cada item pedido por um setor ao estoque, com o que foi atendido e se ainda esta pendente

Os dois sao baixados mes a mes desde fev/2026: o saldo do estoque depende de todo o historico e uma solicitacao
antiga ainda pode estar pendente. Alem do que o Klingo informa, o painel cruza com o Faturamento (#26) so para
comparar a atividade do dia (procedimentos lancados) com as baixas de consumo.

Uso:  python gerar_suprimentos.py             so regenera o dashboard com o que ja esta na planilha
      python gerar_suprimentos.py --forcar    consulta o Klingo agora (como o botao) e regenera
      python gerar_suprimentos.py --historico baixa de novo todos os meses desde o primeiro
"""
import html
import re
import sys
import webbrowser
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
import armazenamento  # noqa: E402  (na Vercel, custos informados vem do Supabase)
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import guia_pendencias as gp  # noqa: E402

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Suprimentos.html"
ABA_MOV, ABA_SOL = "Movimentações", "Solicitações"

# colunas do #13385
M_ES, M_DATA, M_TIPO, M_ITEM, M_UN, M_GRUPO, M_FORN = "Entrada/Saída", "Data da Movimentação", "Tipo", "Item", "Item - Unidade de Medida", "Grupo", "Fornecedor"
M_ENT, M_SAI, M_CONS = "Movimentação - Quantidade Entrada", "Movimentação - Quantidade Saída", "Movimentação - Quantidade Consolidada"
M_VT, M_VU = "Movimentação - Valor Total", "Movimentação - Valor Unitário"
M_LOCAL, M_CC, M_USU = "Local de Armazenagem", "Centro de Custo - Nome", "Usuário"
# colunas do #13387
S_USU, S_ID, S_DATA, S_ITEM = "Usuário Solicitante - Login", "Solicitação - Id", "Solicitação - Data", "Item - Nome"
S_GRUPO, S_UN, S_PEND, S_OBS = "Item - Grupo - Nome", "Item - Unidade de Medida", "Item - Pendente (S/N)", "Solicitação - Observação Item"
S_QS, S_QA, S_VA = "Solicitação - Quantidade Solicitada", "Solicitação - Quantidade Atendida", "Solicitação - Valor Atendido"
S_CC, S_LOCAL = "Centro de Custo - Nome", "Local de Armazenagem - Nome"

PENDENTE, ATENDIDA, ENCERRADA = "Pendente", "Atendida", "Encerrada sem entrega"
SEM_SETOR = "(sem centro de custo)"
CONSUMO, TRANSFERENCIA, INVENTARIO = "Consumo", "Transferência", "Inventário"
ENTRADAS_EXTERNAS = ("Compra", "Doação Recebida")

# limites dos alertas (aparecem em "Como ler este painel")
PENDENCIA_ATENCAO, PENDENCIA_CRITICA = 15, 30   # dias de um pedido pendente
SEM_BAIXA_ATENCAO, SEM_BAIXA_CRITICA = 7, 15     # dias sem nenhuma baixa de consumo
COBERTURA_MIN = 15                                # dias de estoque principal
JANELA_DEMANDA = 30                               # dias olhados para medir o ritmo de pedidos
SETOR_PARADO_PCT, SETOR_PARADO_MIN = 90, 50       # setor com >= 90% pendente e pelo menos 50 itens pedidos
CUSTO_CONCENTRADO_PCT = 50                        # um item com mais da metade do valor do estoque


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    return k.atualizar(PASTA, forcar=forcar, historico=historico)


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def n_br(v: float, casas: int = 0) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def dia_br(d) -> str:
    return d.strftime("%d/%m") if d is not None else ""


def ym_de(serie: pd.Series) -> pd.Series:
    return serie.dt.strftime("%Y-%m")


def tem(df: pd.DataFrame, *colunas: str) -> bool:
    return len(df) > 0 and all(c in df.columns for c in colunas)


def bonito(s) -> str:
    return " ".join(w.capitalize() for w in str(s).replace(".", " ").split())


# ---------------------------------------------------------------- preparo
def preparar_mov(mv: pd.DataFrame) -> pd.DataFrame:
    if not tem(mv, M_DATA, M_TIPO, M_ITEM, M_CONS):
        return mv.iloc[0:0]
    m = mv[mv[M_DATA].notna()].copy()
    m["_ym"] = ym_de(m[M_DATA])
    m["_dia"] = m[M_DATA].dt.date
    m["_un"] = m[M_UN].fillna("").astype(str).str.upper()          # o Klingo traz "ML" e "ml" para o mesmo tipo de unidade
    m["_princ"] = m[M_LOCAL].fillna("").astype(str).str.upper().str.contains("PRINCIPAL")
    m["_cc"] = m[M_CC].fillna(SEM_SETOR)
    for c in (M_ENT, M_SAI, M_CONS, M_VT, M_VU):
        m[c] = m[c].fillna(0.0).astype(float)
    return m


def preparar_sol(s: pd.DataFrame, hoje: date) -> pd.DataFrame:
    if not tem(s, S_DATA, S_ITEM, S_PEND, S_QS):
        return s.iloc[0:0]
    x = s[s[S_DATA].notna()].copy()
    x["_ym"] = ym_de(x[S_DATA])
    x["_dia"] = x[S_DATA].dt.date
    x["_un"] = x[S_UN].fillna("").astype(str).str.upper()
    x["_pend"] = x[S_PEND].astype(str).str.upper().eq("S")
    x["_qs"] = x[S_QS].fillna(0.0)
    x["_qa"] = x[S_QA].fillna(0.0)
    x["_status"] = np.where(x["_pend"], PENDENTE, np.where(x["_qa"] > 0, ATENDIDA, ENCERRADA))
    x["_pend_q"] = np.where(x["_pend"], (x["_qs"] - x["_qa"]).clip(lower=0), 0.0)
    x["_idade"] = (pd.Timestamp(hoje) - x[S_DATA].dt.normalize()).dt.days
    x["_cc"] = x[S_CC].fillna(SEM_SETOR)
    return x


def exames_por_dia() -> dict:
    """Procedimentos lancados por dia no Faturamento (#26), so para comparar a atividade; vazio se o painel ainda nao foi baixado."""
    try:
        p = k.carregar(PASTA.parent / "Faturamento")["Receita Produzida"]
        p = p[p["Data"].notna()]
        return {d: int(n) for d, n in p.groupby(p["Data"].dt.date).size().items()}
    except Exception:
        return {}


# ---------------------------------------------------------------- estoque
def saldos(m: pd.DataFrame) -> pd.DataFrame:
    """Saldo por item = soma das quantidades consolidadas (entrada menos saida), no estoque principal e nos estoques dos setores."""
    g = m.groupby([M_ITEM, "_princ"])[M_CONS].sum().unstack(fill_value=0.0)
    for c in (True, False):
        if c not in g.columns:
            g[c] = 0.0
    return g.rename(columns={True: "principal", False: "setores"})[["principal", "setores"]]


def montar_estoque(m: pd.DataFrame, s: pd.DataFrame, hoje: date) -> dict:
    sal = saldos(m) if len(m) else pd.DataFrame(columns=["principal", "setores"])
    atributos: dict[str, dict] = {}
    if len(m):
        for item, un, grupo in zip(m[M_ITEM], m["_un"], m[M_GRUPO]):
            atributos.setdefault(item, {"un": un, "grupo": grupo})
    if len(s):
        for item, un, grupo in zip(s[S_ITEM], s["_un"], s[S_GRUPO]):
            atributos.setdefault(item, {"un": un, "grupo": grupo})
    demanda = (s[s["_dia"] >= hoje - timedelta(days=JANELA_DEMANDA)].groupby(S_ITEM)["_qs"].sum() / JANELA_DEMANDA) if len(s) else pd.Series(dtype=float)
    pendente = s.groupby(S_ITEM)["_pend_q"].sum() if len(s) else pd.Series(dtype=float)
    com_mov = set(m[M_ITEM]) if len(m) else set()

    linhas = []
    for item, a in atributos.items():
        principal = float(sal.loc[item, "principal"]) if item in sal.index else 0.0
        setores = float(sal.loc[item, "setores"]) if item in sal.index else 0.0
        d, p = float(demanda.get(item, 0.0)), float(pendente.get(item, 0.0))
        total = principal + setores
        cob = principal / d if d > 0 else None
        if item not in com_mov:
            sit = "sem_lancamento"
        elif total <= 0 and (d > 0 or p > 0):
            sit = "zerado"
        elif p > total and p > 0:
            sit = "falta"
        elif cob is not None and cob < COBERTURA_MIN:
            sit = "baixo"
        else:
            sit = "ok"
        linhas.append({"item": item, "un": a["un"], "grupo": a["grupo"], "principal": principal, "setores": setores, "pendente": p,
                       "demanda": d, "cobertura": cob, "situacao": sit})
    ordem = {"zerado": 0, "falta": 1, "sem_lancamento": 2, "baixo": 3, "ok": 4}
    linhas.sort(key=lambda x: (ordem[x["situacao"]], -x["demanda"], x["item"]))

    # por local: quantos itens tem saldo e quantos ficaram zerados
    por_local = []
    if len(m):
        sl = m.groupby([M_LOCAL, M_ITEM])[M_CONS].sum()
        for local, g in sl.groupby(level=0):
            por_local.append({"nome": local, "com_saldo": int((g > 0).sum()), "zerados": int((g == 0).sum()), "movimentos": int((m[M_LOCAL] == local).sum())})
        por_local.sort(key=lambda x: -x["com_saldo"])
    atencao = [x for x in linhas if x["situacao"] != "ok"]
    return {"itens": linhas, "n_itens": len(linhas), "n_atencao": len(atencao), "por_local": por_local,
            "contagem": {sit: sum(1 for x in linhas if x["situacao"] == sit) for sit in ordem},
            "janela": JANELA_DEMANDA, "cobertura_min": COBERTURA_MIN}


def montar_valor(m: pd.DataFrame) -> dict:
    """Valor em estoque segundo o Klingo: entradas menos saidas (as transferencias se anulam)."""
    if not len(m):
        return {"total": 0.0, "itens": 0, "itens_com_custo": 0, "linhas": 0, "linhas_com_valor": 0, "top": None}
    v = m.assign(_v=m[M_VT] * np.where(m[M_ES] == "E", 1.0, -1.0))
    por_item = v.groupby(M_ITEM)["_v"].sum()
    total = float(por_item.sum())
    top = None
    if len(por_item) and total > 0:
        item = por_item.abs().idxmax()
        g = v[v[M_ITEM] == item]
        maior = g.loc[g[M_VT].idxmax()]
        top = {"item": item, "valor": float(por_item[item]), "pct": float(por_item[item] / total * 100), "un": maior["_un"],
               "qtd": float(maior[M_ENT] or maior[M_SAI]), "custo_unit": float(maior[M_VU]), "tipo": maior[M_TIPO], "data": maior[M_DATA]}
    return {"total": total, "itens": int(m[M_ITEM].nunique()), "itens_com_custo": int(m.loc[m[M_VU] > 0, M_ITEM].nunique()),
            "linhas": int(len(m)), "linhas_com_valor": int((m[M_VT] > 0).sum()), "top": top}


# ---------------------------------------------------------------- pendencias (posicao de hoje)
def montar_pendentes(s: pd.DataFrame, hoje: date) -> dict:
    if not len(s):
        return {"linhas": 0, "solicitacoes": 0, "total_linhas": 0, "solicitacoes_total": 0, "faixas": [], "setores": [], "lista": []}
    pen = s[s["_pend"]]
    por_id = s.groupby(S_ID)["_pend"].agg(["sum", "size"])
    limites = [(3, "Até 3 dias"), (7, "De 4 a 7 dias"), (15, "De 8 a 15 dias"), (30, "De 16 a 30 dias"), (10 ** 6, "Mais de 30 dias")]
    faixas, anterior = [], -1
    for teto, rotulo in limites:
        sel = pen[(pen["_idade"] > anterior) & (pen["_idade"] <= teto)]
        faixas.append({"rotulo": rotulo, "qtd": int(len(sel)), "solicitacoes": int(sel[S_ID].nunique())})
        anterior = teto
    setores = []
    for nome, g in s.groupby("_cc"):
        setores.append({"nome": nome, "linhas": int(len(g)), "atendidas": int((g["_status"] == ATENDIDA).sum()), "pendentes": int(g["_pend"].sum()),
                        "encerradas": int((g["_status"] == ENCERRADA).sum()), "pct_pend": float(g["_pend"].mean() * 100)})
    setores.sort(key=lambda x: -x["pendentes"])
    mais_antigas = pen.sort_values([S_DATA, S_ID]).head(15)
    lista = [{"id": int(r[S_ID]), "data": r[S_DATA], "item": r[S_ITEM], "qtd": float(r["_qs"]), "un": r["_un"], "setor": r["_cc"],
              "solicitante": r[S_USU], "dias": int(r["_idade"])} for _, r in mais_antigas.iterrows()]
    itens = gp.tabela(["Solicitação", "Data", "Item", "Pedido", "Setor", "Solicitante", "Dias esperando"],
                      [[int(r[S_ID]), gp.dbr(r[S_DATA]), bonito(r[S_ITEM]), f"{n_br(r['_qs'], 1) if r['_qs'] % 1 else n_br(r['_qs'])} {str(r['_un']).lower()}", r["_cc"], r[S_USU], int(r["_idade"])]
                       for _, r in pen.sort_values([S_DATA, S_ID]).head(gp.MAX_ITENS).iterrows()], total=len(pen), numericas=(0, 6))
    return {"linhas": int(len(pen)), "solicitacoes": int(pen[S_ID].nunique()), "total_linhas": int(len(s)), "solicitacoes_total": int(s[S_ID].nunique()), "itens": itens,
            "sem_nenhum_atendido": int((por_id["sum"] == por_id["size"]).sum()),
            "mais_15": int((pen["_idade"] > PENDENCIA_ATENCAO).sum()), "mais_30": int((pen["_idade"] > PENDENCIA_CRITICA).sum()),
            "mais_antiga_dias": int(pen["_idade"].max()) if len(pen) else 0,
            "mais_antiga_id": int(mais_antigas.iloc[0][S_ID]) if len(mais_antigas) else None,
            "mais_antiga_data": mais_antigas.iloc[0][S_DATA] if len(mais_antigas) else None,
            "faixas": faixas, "setores": setores[:12], "lista": lista}


# ---------------------------------------------------------------- um mes
def itens_solicitacoes(df: pd.DataFrame, atendido: bool = False) -> dict:
    """Tabela 'quais sao' dos itens pedidos de um alerta (mais antigos primeiro). atendido=True mostra tambem a quantidade atendida."""
    qtd = lambda v: n_br(v, 1) if v % 1 else n_br(v)
    colunas = ["Solicitação", "Data", "Item", "Pedido"] + (["Atendido"] if atendido else []) + ["Setor", "Solicitante"]
    linhas = [[int(r[S_ID]), gp.dbr(r[S_DATA]), bonito(r[S_ITEM]), f"{qtd(r['_qs'])} {str(r['_un']).lower()}"] + ([qtd(r["_qa"])] if atendido else []) + [r["_cc"], r[S_USU]]
              for _, r in df.sort_values([S_DATA, S_ID]).head(gp.MAX_ITENS).iterrows()]
    return gp.tabela(colunas, linhas, total=len(df), numericas=(0,))


def montar_sol_mes(sm: pd.DataFrame) -> dict:
    if not len(sm):
        return {"solicitacoes": 0, "linhas": 0, "solicitantes": 0, "atendidas": 0, "pendentes": 0, "encerradas": 0, "parciais": 0,
                "setores": [], "solicitantes_lista": [], "itens": [], "grupos": []}
    atend = sm[sm["_status"] == ATENDIDA]
    setores = [{"nome": nome, "solicitacoes": int(g[S_ID].nunique()), "linhas": int(len(g)), "atendidas": int((g["_status"] == ATENDIDA).sum()),
                "pendentes": int(g["_pend"].sum()), "encerradas": int((g["_status"] == ENCERRADA).sum())} for nome, g in sm.groupby("_cc")]
    setores.sort(key=lambda x: -x["linhas"])
    pessoas = [{"nome": nome, "solicitacoes": int(g[S_ID].nunique()), "linhas": int(len(g)), "atendidas": int((g["_status"] == ATENDIDA).sum()),
                "pendentes": int(g["_pend"].sum())} for nome, g in sm.groupby(S_USU)]
    pessoas.sort(key=lambda x: -x["linhas"])
    itens = [{"nome": item, "un": un, "pedidos": int(len(g)), "qtd": float(g["_qs"].sum()), "atendida": float(g["_qa"].sum()),
              "pendente": float(g["_pend_q"].sum())} for (item, un), g in sm.groupby([S_ITEM, "_un"])]
    itens.sort(key=lambda x: (-x["pedidos"], x["nome"]))
    grupos = [{"nome": nome, "linhas": int(len(g))} for nome, g in sm.groupby(sm[S_GRUPO].fillna("(sem grupo)"))]
    grupos.sort(key=lambda x: -x["linhas"])
    return {"solicitacoes": int(sm[S_ID].nunique()), "linhas": int(len(sm)), "solicitantes": int(sm[S_USU].nunique()),
            "atendidas": int(len(atend)), "pendentes": int(sm["_pend"].sum()), "encerradas": int((sm["_status"] == ENCERRADA).sum()),
            "parciais": int((atend["_qa"] < atend["_qs"]).sum()),
            "setores": setores, "solicitantes_lista": pessoas, "itens": itens, "grupos": grupos}


def montar_mov_mes(mm: pd.DataFrame) -> dict:
    if not len(mm):
        return {"linhas": 0, "consumo_linhas": 0, "consumo_itens": 0, "transferencias": 0, "tipos": [], "consumo_top": [], "consumo_setores": [],
                "consumo_grupos": [], "compras": [], "inventarios": []}
    cons = mm[mm[M_TIPO] == CONSUMO]
    tipos = []
    for (tipo, es), g in mm.groupby([M_TIPO, M_ES]):
        tipos.append({"nome": f"{tipo} ({'entrada' if es == 'E' else 'saída'})", "linhas": int(len(g)), "entrada": float(g[M_ENT].sum()),
                      "saida": float(g[M_SAI].sum()), "valor": float(g[M_VT].sum())})
    tipos.sort(key=lambda x: -x["linhas"])
    top = [{"nome": item, "un": un, "baixas": int(len(g)), "qtd": float(g[M_SAI].sum())} for (item, un), g in cons.groupby([M_ITEM, "_un"])]
    top.sort(key=lambda x: (-x["baixas"], x["nome"]))
    setores = [{"nome": nome, "baixas": int(len(g)), "itens": int(g[M_ITEM].nunique())} for nome, g in cons.groupby("_cc")]
    setores.sort(key=lambda x: -x["baixas"])
    grupos = [{"nome": nome, "baixas": int(len(g))} for nome, g in cons.groupby(cons[M_GRUPO].fillna("(sem grupo)"))]
    grupos.sort(key=lambda x: -x["baixas"])
    ext = mm[mm[M_TIPO].isin(ENTRADAS_EXTERNAS)].sort_values(M_DATA, ascending=False)
    compras = [{"data": r[M_DATA], "tipo": r[M_TIPO], "item": r[M_ITEM], "un": r["_un"], "fornecedor": None if pd.isna(r[M_FORN]) else r[M_FORN],
                "qtd": float(r[M_ENT]), "valor": float(r[M_VT]), "local": r[M_LOCAL]} for _, r in ext.head(20).iterrows()]
    inv = mm[mm[M_TIPO] == INVENTARIO]
    inventarios = []
    for (dia, local), g in inv.groupby(["_dia", M_LOCAL]):
        inventarios.append({"dia": dia, "local": local, "contados": int((g[M_ES] == "E").sum()), "zerados": int((g[M_ES] == "S").sum()),
                            "itens": int(g[M_ITEM].nunique())})
    inventarios.sort(key=lambda x: (x["dia"], x["local"]), reverse=True)
    return {"linhas": int(len(mm)), "consumo_linhas": int(len(cons)), "consumo_itens": int(cons[M_ITEM].nunique()),
            "transferencias": int(((mm[M_TIPO] == TRANSFERENCIA) & (mm[M_ES] == "E")).sum()),
            "tipos": tipos, "consumo_top": top[:12], "consumo_setores": setores[:10], "consumo_grupos": grupos, "compras": compras,
            "inventarios": inventarios[:12]}


def dias_do_mes(ym: str, hoje: date, m: pd.DataFrame, s: pd.DataFrame, exames: dict) -> list[dict]:
    ano, mes = int(ym[:4]), int(ym[5:])
    ultimo = min(date(ano, mes, monthrange(ano, mes)[1]), hoje)
    sol = s[s["_ym"] == ym].groupby("_dia")[S_ID].nunique() if len(s) else pd.Series(dtype=int)
    mm = m[m["_ym"] == ym] if len(m) else m
    cons = mm[mm[M_TIPO] == CONSUMO].groupby("_dia").size() if len(mm) else pd.Series(dtype=int)
    transf = mm[(mm[M_TIPO] == TRANSFERENCIA) & (mm[M_ES] == "E")].groupby("_dia").size() if len(mm) else pd.Series(dtype=int)
    dias = []
    for n in range(1, ultimo.day + 1):
        d = date(ano, mes, n)
        dias.append({"d": d.isoformat(), "sol": int(sol.get(d, 0)), "cons": int(cons.get(d, 0)), "transf": int(transf.get(d, 0)),
                     "exames": exames.get(d) if exames else None})
    return dias


def montar_mes(ym: str, hoje: date, m: pd.DataFrame, s: pd.DataFrame, exames: dict, per: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses: as linhas de todos os meses juntas; o dia a dia (que so existe dentro de um mes) nao e montado."""
    yms = per.yms if per else [ym]
    rot = per.rotulo if per else pc.rotulo_mes(ym)
    exato = bool(per and per.exato)   # recorte de dias: a data de cada linha decide, nao o mes dela
    sm = (s[per.dentro(s[S_DATA])] if exato else s[s["_ym"].isin(yms)]) if len(s) else s
    mm = (m[per.dentro(m[M_DATA])] if exato else m[m["_ym"].isin(yms)]) if len(m) else m
    sol, mov = montar_sol_mes(sm), montar_mov_mes(mm)
    alertas = []
    if sol["linhas"]:
        if sol["encerradas"] >= 10 and sol["encerradas"] / sol["linhas"] >= 0.05:
            alertas.append({"nivel": "info", "titulo": "Pedidos encerrados sem entrega",
                            "itens": itens_solicitacoes(sm[sm["_status"] == ENCERRADA]),
                            "texto": f"<b>{n_br(sol['encerradas'])}</b> de {n_br(sol['linhas'])} itens pedidos em {rot} (<b>{sol['encerradas'] / sol['linhas'] * 100:.0f}%</b>) "
                                     "foram encerrados sem nenhuma quantidade entregue: o pedido saiu da fila, mas nada foi atendido. Vale saber se foi cancelamento ou falta de estoque."})
        if sol["parciais"] >= 10:
            alertas.append({"nivel": "info", "titulo": "Pedidos atendidos pela metade",
                            "itens": itens_solicitacoes(sm[(sm["_status"] == ATENDIDA) & (sm["_qa"] < sm["_qs"])], atendido=True),
                            "texto": f"<b>{n_br(sol['parciais'])}</b> itens receberam menos do que o setor pediu em {rot}."})
        sem_setor = int((sm["_cc"] == SEM_SETOR).sum())
        if sem_setor / sol["linhas"] >= 0.05:
            ids = int(sm.loc[sm["_cc"] == SEM_SETOR, S_ID].nunique())
            alertas.append({"nivel": "info", "titulo": "Pedidos sem centro de custo", "itens": itens_solicitacoes(sm[sm["_cc"] == SEM_SETOR]),
                            "texto": f"<b>{n_br(ids)}</b> solicitações ({n_br(sem_setor)} itens, <b>{sem_setor / sol['linhas'] * 100:.0f}%</b>) de {rot} não dizem para qual setor o material vai; "
                                     "sem isso o consumo não pode ser dividido por setor."})
    gp.anotar("suprimentos", alertas, per.chave if per else ym)
    return {"rotulo": rot, "sol": sol, "mov": mov, "dias": [] if per else dias_do_mes(ym, hoje, m, s, exames), "alertas": alertas}


# ---------------------------------------------------------------- evolucao, conferencia e qualidade
def montar_evolucao(m: pd.DataFrame, s: pd.DataFrame) -> list[dict]:
    meses = sorted((set(s["_ym"]) if len(s) else set()) | (set(m["_ym"]) if len(m) else set()))
    out = []
    for ym in meses:
        sm = s[s["_ym"] == ym] if len(s) else s
        mm = m[m["_ym"] == ym] if len(m) else m
        out.append({"ym": ym, "rotulo": pc.rotulo_mes(ym), "solicitacoes": int(sm[S_ID].nunique()) if len(sm) else 0, "linhas": int(len(sm)),
                    "atendidas": int((sm["_status"] == ATENDIDA).sum()) if len(sm) else 0, "pendentes": int(sm["_pend"].sum()) if len(sm) else 0,
                    "encerradas": int((sm["_status"] == ENCERRADA).sum()) if len(sm) else 0,
                    "consumo": int((mm[M_TIPO] == CONSUMO).sum()) if len(mm) else 0,
                    "transferencias": int(((mm[M_TIPO] == TRANSFERENCIA) & (mm[M_ES] == "E")).sum()) if len(mm) else 0,
                    "compras": int(mm[M_TIPO].isin(ENTRADAS_EXTERNAS).sum()) if len(mm) else 0,
                    "inventario": int((mm[M_TIPO] == INVENTARIO).sum()) if len(mm) else 0})
    return out


def conferir(m: pd.DataFrame, s: pd.DataFrame, valor: dict, consumo: dict, primeiro_mes: str) -> list[dict]:
    """Verificacoes de consistencia e de qualidade do que o Klingo devolve. nivel: ok | atencao | info."""
    itens = []

    def add(nivel, titulo, texto, tabela=None):
        itens.append({"nivel": nivel, "titulo": titulo, "texto": texto, **({"itens": tabela} if tabela else {})})

    if len(m):
        t = m[m[M_TIPO] == TRANSFERENCIA]
        ent, sai = float(t[M_ENT].sum()), float(t[M_SAI].sum())
        par = t.groupby([M_DATA, M_ITEM])[M_CONS].sum()
        soltos = int((par.abs() > 1e-9).sum())
        add("ok" if abs(ent - sai) < 1e-6 and soltos == 0 else "atencao", "Transferências entre estoques fecham",
            f"Entrou <b>{n_br(ent)}</b> e saiu <b>{n_br(sai)}</b> nas transferências; {('todas as ' + n_br(len(par)) + ' transferências têm a saída e a entrada iguais.') if soltos == 0 else f'<b>{soltos}</b> transferência(s) com saída diferente da entrada.'}")
        erradas = int(((m[M_ENT] - m[M_SAI] - m[M_CONS]).abs() > 1e-6).sum())
        add("ok" if erradas == 0 else "atencao", "Quantidade consolidada = entrada − saída",
            f"Conferido nas {n_br(len(m))} movimentações: {'nenhuma diferença.' if erradas == 0 else f'<b>{erradas}</b> linha(s) não fecham.'}")
        sl = m.groupby([M_LOCAL, M_ITEM])[M_CONS].sum()
        neg = sl[sl < 0]
        add("ok" if not len(neg) else "atencao", "Nenhum saldo negativo por local",
            "Nenhum item ficou com saldo abaixo de zero em nenhum estoque." if not len(neg) else
            f"<b>{len(neg)}</b> item(ns) com saldo negativo (saiu mais do que entrou), ex.: {html.escape(str(neg.sort_values().index[0][1]))} em {html.escape(str(neg.sort_values().index[0][0]))}.",
            gp.tabela(["Local", "Item", "Saldo"], [[bonito(loc), bonito(item), n_br(v, 1)] for (loc, item), v in neg.sort_values().items()], total=len(neg), numericas=(2,)) if len(neg) else None)
        com_custo = valor["linhas_com_valor"]
        add("atencao" if com_custo / max(valor["linhas"], 1) < 0.5 else "ok", "Custo registrado nas movimentações",
            f"Só <b>{n_br(com_custo)}</b> de {n_br(valor['linhas'])} movimentações ({n_br(com_custo / max(valor['linhas'], 1) * 100, 1)}%) têm valor; "
            f"o custo está cadastrado em <b>{valor['itens_com_custo']}</b> de {valor['itens']} itens. O custo do consumo não pode ser calculado enquanto o valor unitário não for cadastrado.")
        usuarios = m[M_USU].value_counts()
        if len(usuarios) and usuarios.iloc[0] / len(m) >= 0.8 and len(m) >= 50:
            add("info", "Quase tudo foi lançado por um só usuário",
                f"O usuário <b>{html.escape(str(usuarios.index[0]))}</b> lançou {n_br(usuarios.iloc[0] / len(m) * 100, 1)}% das movimentações ({n_br(usuarios.iloc[0])} de {n_br(len(m))}). Se essa pessoa se ausentar, o estoque deixa de ser atualizado.")
        if consumo.get("dia_pico") and consumo["pico_pct"] >= 40:
            add("info", "Baixas de consumo lançadas em bloco",
                f"Em <b>{dia_br(consumo['dia_pico'])}</b> foram lançadas <b>{n_br(consumo['pico_linhas'])}</b> baixas de uma vez ({consumo['pico_pct']:.0f}% de todas as baixas): provavelmente lançamento retroativo, não o consumo daquele dia.")
        antes = int((m["_ym"] < primeiro_mes).sum())
        antes_s = int((s["_ym"] < primeiro_mes).sum()) if len(s) else 0
        if antes + antes_s:
            add("info", "Registros anteriores ao uso do sistema",
                f"Há <b>{n_br(antes)}</b> movimentações e <b>{n_br(antes_s)}</b> itens de solicitação de antes de {pc.rotulo_mes(primeiro_mes)} (testes ou implantação). Entram no saldo e nas pendências, mas não nos meses do painel.")
    if len(s):
        pend = int(s["_pend"].sum())
        soma = int((s["_status"] == ATENDIDA).sum()) + int((s["_status"] == ENCERRADA).sum()) + pend
        add("ok" if soma == len(s) else "atencao", "Situação dos pedidos fecha com o total",
            f"{n_br(len(s))} itens pedidos = {n_br(int((s['_status'] == ATENDIDA).sum()))} atendidos + {n_br(pend)} pendentes + {n_br(int((s['_status'] == ENCERRADA).sum()))} encerrados sem entrega.")
        valor_at = float(s[S_VA].fillna(0).sum())
        add("info", "Valor atendido nas solicitações", f"O relatório de solicitações soma <b>{brl(valor_at)}</b> em valor atendido; sem custo cadastrado nos itens, ele não mostra o custo real do que saiu do estoque.")
    return itens


# ---------------------------------------------------------------- alertas gerais
def alertas_gerais(hoje: date, m: pd.DataFrame, s: pd.DataFrame, pend: dict, est: dict, valor: dict, consumo: dict, exames: dict, itens: dict | None = None) -> list[dict]:
    a = []
    sem_baixa = [x for x in (itens or {}).get("lista", []) if "sem_baixa" in x["flags"]]
    if sem_baixa:
        sem_baixa.sort(key=lambda x: -x["entregue"])
        nomes = ", ".join(f"{html.escape(bonito(x['item']))} ({n_br(x['entregue'])} {html.escape(x['un'].lower())})" for x in sem_baixa[:6])
        a.append({"nivel": "atencao", "titulo": "Material entregue aos setores que nunca foi baixado",
                  "itens": gp.tabela(["Item", "Entregue aos setores", "Unidade", "Pedidos"], [[bonito(x["item"]), n_br(x["entregue"]), str(x["un"]).lower(), x["pedidos"]] for x in sem_baixa],
                                     total=len(sem_baixa), numericas=(1, 3)),
                  "texto": f"<b>{n_br(len(sem_baixa))}</b> itens foram entregues aos setores (a quantidade atendida nas solicitações passa de {SEM_BAIXA_ENTREGUE_MIN}) e não têm nenhuma baixa de consumo: {nomes}. "
                           "Enquanto o consumo não é baixado, não há como saber quanto cada item custa por procedimento."})
    if pend["linhas"]:
        n30, n15 = pend["mais_30"], pend["mais_15"]
        nivel = "critico" if n30 else "atencao" if n15 else "info"
        a.append({"nivel": nivel, "titulo": "Pedidos de material parados sem atendimento", "itens": pend["itens"],
                  "texto": f"<b>{n_br(pend['linhas'])}</b> de {n_br(pend['total_linhas'])} itens pedidos ({pend['linhas'] / pend['total_linhas'] * 100:.0f}%) ainda constam como pendentes, em <b>{n_br(pend['solicitacoes'])}</b> solicitações. "
                           f"<b>{n_br(n15)}</b> esperam há mais de {PENDENCIA_ATENCAO} dias e <b>{n_br(n30)}</b> há mais de {PENDENCIA_CRITICA}; o mais antigo é da solicitação <b>#{pend['mais_antiga_id']}</b> ({dia_br(pend['mais_antiga_data'])}, {pend['mais_antiga_dias']} dias). "
                           f"Em <b>{n_br(pend['sem_nenhum_atendido'])}</b> das {n_br(pend['solicitacoes_total'])} solicitações nenhum item foi atendido. "
                           "Se o material foi entregue sem registrar o atendimento, a fila está inflada; se não foi, os setores estão esperando."})
        parados = [x for x in pend["setores"] if x["linhas"] >= SETOR_PARADO_MIN and x["pct_pend"] >= SETOR_PARADO_PCT]
        if parados:
            nomes = "; ".join(f"{html.escape(bonito(x['nome']))} ({x['pct_pend']:.0f}% de {n_br(x['linhas'])})" for x in sorted(parados, key=lambda x: -x["pendentes"])[:5])
            a.append({"nivel": "atencao", "titulo": "Setores em que quase nada é atendido",
                      "itens": gp.tabela(["Setor", "Itens pedidos", "Pendentes", "% pendente"],
                                         [[bonito(x["nome"]), n_br(x["linhas"]), n_br(x["pendentes"]), f"{x['pct_pend']:.0f}%"] for x in sorted(parados, key=lambda x: -x["pendentes"])],
                                         numericas=(1, 2, 3)),
                      "texto": f"Setores com {SETOR_PARADO_PCT}% ou mais dos itens pedidos ainda pendentes: {nomes}."})
    if consumo.get("ultima") is not None:
        dias = (hoje - consumo["ultima"]).days
        if dias >= SEM_BAIXA_ATENCAO:
            desde = int(s.loc[s["_dia"] > consumo["ultima"], S_ID].nunique()) if len(s) else 0
            ex = sum(n for d, n in exames.items() if d > consumo["ultima"]) if exames else None
            a.append({"nivel": "critico" if dias >= SEM_BAIXA_CRITICA else "atencao", "titulo": "Sem baixa de consumo há dias",
                      "texto": f"A última baixa de consumo foi em <b>{dia_br(consumo['ultima'])}</b> ({dias} dias atrás). Desde então houve <b>{n_br(desde)}</b> solicitações de material"
                               f"{(' e o Faturamento lançou <b>' + n_br(ex) + '</b> procedimentos') if ex else ''}. Sem a baixa, o saldo do estoque mostra mais material do que existe de verdade."})
    elif len(m) and len(s):
        a.append({"nivel": "atencao", "titulo": "Nenhuma baixa de consumo registrada",
                  "texto": "Há solicitações e movimentações, mas nenhuma saída do tipo Consumo: o saldo não desce com o uso."})
    if consumo.get("zero_linhas", 0) >= 10 and consumo["linhas"]:
        nomes = ", ".join(f"{html.escape(bonito(n))} ({n_br(q)})" for n, q in consumo["zero_itens"])
        a.append({"nivel": "atencao", "titulo": "Baixas de consumo que não baixam nada",
                  "itens": gp.tabela(["Item", "Baixas com quantidade zero"], [[bonito(n), q] for n, q in consumo["zero_itens"]], numericas=(1,)),
                  "texto": f"<b>{n_br(consumo['zero_linhas'])}</b> de {n_br(consumo['linhas'])} baixas de consumo (<b>{consumo['zero_linhas'] / consumo['linhas'] * 100:.0f}%</b>) foram lançadas com quantidade zero: "
                           f"o registro existe, mas o saldo não diminui. Itens mais afetados (baixas): {nomes}. Para eles o estoque no Klingo só vai crescer."})
    sem = [x for x in est["itens"] if x["situacao"] == "sem_lancamento"]
    if sem:
        pedidos = sorted(sem, key=lambda x: -x["demanda"])
        nomes = ", ".join(html.escape(bonito(x["item"])) for x in pedidos[:8])
        a.append({"nivel": "atencao", "titulo": "Itens pedidos que nunca tiveram estoque lançado",
                  "itens": gp.tabela(["Item", "Pedidos nos últimos 30 dias (por dia)", "Unidade"], [[bonito(x["item"]), n_br(x["demanda"], 1), str(x["un"]).lower()] for x in pedidos],
                                     total=len(sem), numericas=(1,)),
                  "texto": f"<b>{len(sem)}</b> itens são pedidos pelos setores, mas não têm nenhuma entrada, inventário ou saída no sistema: {nomes}. "
                           "Entre eles há medicamentos de sedação (fentanil, midazolam, propofol, flumazenil), que normalmente exigem controle rigoroso de estoque."})
    zerados = [x for x in est["itens"] if x["situacao"] == "zerado"]
    if zerados:
        nomes = ", ".join(html.escape(bonito(x["item"])) + (f" (pedido em aberto: {n_br(x['pendente'])} {html.escape(x['un'].lower())})" if x["pendente"] else "") for x in zerados[:6])
        a.append({"nivel": "atencao", "titulo": "Itens pedidos com estoque zerado",
                  "itens": gp.tabela(["Item", "Pedido em aberto", "Unidade"], [[bonito(x["item"]), n_br(x["pendente"]), str(x["un"]).lower()] for x in zerados], total=len(zerados), numericas=(1,)),
                  "texto": f"<b>{len(zerados)}</b> itens que os setores pedem estão com saldo zero em todos os estoques: {nomes}."})
    falta = [x for x in est["itens"] if x["situacao"] == "falta"]
    if falta:
        nomes = ", ".join(f"{html.escape(bonito(x['item']))} (pedido {n_br(x['pendente'])} {html.escape(x['un'].lower())}, em estoque {n_br(x['principal'] + x['setores'])})" for x in falta[:5])
        a.append({"nivel": "atencao", "titulo": "Pedidos em aberto maiores que o estoque",
                  "itens": gp.tabela(["Item", "Pedido em aberto", "Em estoque (principal + setores)", "Unidade"],
                                     [[bonito(x["item"]), n_br(x["pendente"]), n_br(x["principal"] + x["setores"]), str(x["un"]).lower()] for x in falta], total=len(falta), numericas=(1, 2)),
                  "texto": f"<b>{len(falta)}</b> itens têm mais pedido em aberto do que material em estoque (principal e setores somados): {nomes}."})
    baixo = [x for x in est["itens"] if x["situacao"] == "baixo"]
    if baixo:
        nomes = ", ".join(f"{html.escape(bonito(x['item']))} ({n_br(x['cobertura'], 1)} dias)" for x in sorted(baixo, key=lambda x: x["cobertura"])[:6])
        a.append({"nivel": "info", "titulo": "Estoque principal para poucos dias",
                  "itens": gp.tabela(["Item", "Dias de estoque principal", "Estoque principal", "Unidade"],
                                     [[bonito(x["item"]), n_br(x["cobertura"], 1), n_br(x["principal"], 1), str(x["un"]).lower()] for x in sorted(baixo, key=lambda x: x["cobertura"])],
                                     total=len(baixo), numericas=(1, 2)),
                  "texto": f"<b>{len(baixo)}</b> itens têm no estoque principal menos de {COBERTURA_MIN} dias do ritmo de pedidos dos últimos {JANELA_DEMANDA} dias: {nomes}."})
    top = valor.get("top")
    if top and top["pct"] >= CUSTO_CONCENTRADO_PCT:
        a.append({"nivel": "atencao", "titulo": "Valor do estoque concentrado em um item",
                  "itens": gp.tabela(["Item", "Quantidade", "Custo unitário", "Valor em estoque"],
                                     [[bonito(top["item"]), f"{n_br(top['qtd'])} {str(top['un']).lower()}", brl(top["custo_unit"]), brl(top["valor"])]], numericas=(2, 3)),
                  "texto": f"O Klingo registra <b>{brl(valor['total'])}</b> em estoque, mas <b>{n_br(top['pct'], 1)}%</b> ({brl(top['valor'])}) é de <b>{html.escape(bonito(top['item']))}</b>: "
                           f"{n_br(top['qtd'])} {html.escape(top['un'].lower())} a {brl(top['custo_unit'])} cada ({html.escape(str(top['tipo']).lower())}). "
                           "Confira se o custo cadastrado é por frasco ou caixa enquanto a quantidade está em mL: se for, o valor está muito acima do real."})
    ordem = {"critico": 0, "atencao": 1, "ok": 2, "info": 3}
    a.sort(key=lambda x: ordem[x["nivel"]])
    return gp.anotar("suprimentos", a)


# ---------------------------------------------------------------- item a item (visao macro e micro)
EMBALAGEM = re.compile(r"C/\s*(\d+)", re.I)
UN_EMBALAGEM = {"CX": "caixa", "PCT": "pacote"}
BAIXA_ZERO_MIN, BAIXA_ZERO_PCT = 3, 50        # item com pelo menos 3 baixas e metade delas sem quantidade
SEM_BAIXA_ENTREGUE_MIN = 10                    # entregue aos setores (na unidade do item) sem nenhuma baixa de consumo
CUSTOS_ARQ = PASTA / "Custos dos Itens.xlsx"
COLUNAS_CUSTO = ["Item", "Grupo", "Unidade no Klingo", "Embalagem", "Unidades por embalagem", "Custo no Klingo (R$ por unidade do estoque)",
                 "Custo informado (R$ por unidade do estoque)", "Observação"]
SETOR_ATENDIMENTO = {"RM/TC": ("SALAS RM/TC", "HIGIENIZAÇÃO RM/TC")}   # centros de custo que correspondem ao setor do relatorio de Atendimento


def embalagem(item: str, un: str) -> tuple[int, str, bool]:
    """(unidades por unidade-do-estoque, texto, controlado_em_embalagem). 'CX'/'PCT C/N' = N unidades por caixa; em 'UND' o Klingo ja conta unidades."""
    mt = EMBALAGEM.search(item)
    n = int(mt.group(1)) if mt else 1
    if un in UN_EMBALAGEM and n > 1:
        return n, f"{UN_EMBALAGEM[un]} com {n_br(n)} unidades", True
    if mt and n > 1:
        return 1, f"vem em embalagem com {n_br(n)}; o Klingo controla por unidade", False
    return 1, "", False


def ler_custos_informados() -> dict[str, float]:
    """Custos que o usuario digitou em 'Custos dos Itens.xlsx' (coluna 'Custo informado'). Vazio ou arquivo ausente = nenhum.
    Na Vercel vem da tabela painel_custo_item do Supabase."""
    if armazenamento.ativo():
        return armazenamento.custos_informados()
    if not CUSTOS_ARQ.exists():
        return {}
    try:
        d = pd.read_excel(CUSTOS_ARQ, sheet_name="Custos")
        out = {}
        for item, v in zip(d["Item"], d[COLUNAS_CUSTO[6]]):
            v = pd.to_numeric(str(v).replace("R$", "").replace(".", "").replace(",", ".") if isinstance(v, str) else v, errors="coerce")
            if pd.notna(v) and v > 0:
                out[str(item)] = float(v)
        return out
    except Exception as e:
        print(f">>> AVISO: nao consegui ler {CUSTOS_ARQ.name}: {e}", file=sys.stderr, flush=True)
        return {}


def gravar_modelo_custos(itens: list[dict]) -> None:
    """Cria/atualiza a planilha de custos com todos os itens, mantendo o que o usuario ja digitou. Nao grava se nada mudou."""
    if armazenamento.ativo():   # na Vercel nao ha planilha para preencher: os custos ficam na tabela painel_custo_item
        return
    try:
        antigos = {}
        if CUSTOS_ARQ.exists():
            d = pd.read_excel(CUSTOS_ARQ, sheet_name="Custos")
            antigos = {str(r["Item"]): (r[COLUNAS_CUSTO[6]], r["Observação"]) for _, r in d.iterrows()}
            if set(antigos) >= {x["item"] for x in itens}:
                return
        wb = Workbook()
        ws = wb.active
        ws.title = "Custos"
        ws.append(COLUNAS_CUSTO)
        for x in sorted(itens, key=lambda x: (str(x["grupo"]), x["item"])):
            inf, obs = antigos.get(x["item"], (None, None))
            ws.append([x["item"], x["grupo"], x["un"], x["embalagem_txt"] or None, x["fator"] if x["fator"] > 1 else None, x["custo_klingo"],
                       None if pd.isna(inf) else inf, None if pd.isna(obs) else obs])
        for col, larg in zip("ABCDEFGH", (46, 30, 12, 30, 12, 20, 20, 40)):
            ws.column_dimensions[col].width = larg
        for c in ws[1]:
            c.font = Font(bold=True)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "B2"
        ws2 = wb.create_sheet("Como preencher")
        for linha in ("Preencha só a coluna G (Custo informado), em R$, e não apague nada mais.",
                      "O valor é o preço de UMA unidade do estoque do item, na unidade da coluna C: se a unidade é CX, o preço da caixa; se é UND, o preço de cada unidade; se é ML, o preço de cada mL.",
                      "Exemplo: GRAMPO 26/6 (CX. C/ 5000), unidade CX, caixa a R$ 18,00: escreva 18. O painel divide por 5.000 e mostra quanto custa cada grampo.",
                      "A coluna F mostra o custo que já existe no Klingo (só em itens comprados com valor). Se a G estiver preenchida, ela vale no lugar da F.",
                      "Depois de salvar, clique em Atualizar agora no painel de Suprimentos."):
            ws2.append([linha])
        ws2.column_dimensions["A"].width = 140
        tmp = CUSTOS_ARQ.with_suffix(".tmp.xlsx")
        wb.save(tmp)
        tmp.replace(CUSTOS_ARQ)
    except Exception as e:   # arquivo aberto no Excel ou sem permissao: o painel segue sem ele
        print(f">>> AVISO: nao consegui gravar {CUSTOS_ARQ.name}: {e}", file=sys.stderr, flush=True)


def montar_itens(m: pd.DataFrame, s: pd.DataFrame, hoje: date, informados: dict[str, float]) -> dict:
    """Uma linha por item: estoque, custo, consumo registrado, o que os setores pediram e receberam, e o que impede de enxergar o custo."""
    vazio = {"lista": [], "resumo": {}, "compras": [], "achados": [], "informados": len(informados), "arquivo_custos": CUSTOS_ARQ.name, "custos_nuvem": armazenamento.ativo()}
    if not len(m) and not len(s):
        return vazio
    pm = {i: g for i, g in m.groupby(M_ITEM)} if len(m) else {}
    ps = {i: g for i, g in s.groupby(S_ITEM)} if len(s) else {}
    atributos: dict[str, dict] = {}
    for df, ic, uc, gc in ((m, M_ITEM, "_un", M_GRUPO), (s, S_ITEM, "_un", S_GRUPO)):
        if len(df):
            for item, un, grupo in zip(df[ic], df[uc], df[gc]):
                atributos.setdefault(item, {"un": un, "grupo": "" if pd.isna(grupo) else grupo})
    lista = []
    for item, a in atributos.items():
        g, sg = pm.get(item), ps.get(item)
        un = a["un"]
        fator, emb_txt, em_emb = embalagem(item, un)
        x = {"item": item, "un": un, "grupo": a["grupo"], "fator": fator, "embalagem_txt": emb_txt, "em_embalagem": em_emb,
             "saldo": 0.0, "principal": 0.0, "setores": 0.0, "custo_klingo": None, "custo_origem": None, "compra_qtd": 0.0, "compra_valor": 0.0,
             "consumo": 0.0, "baixas": 0, "baixas_zero": 0, "primeira_baixa": None, "ultima_baixa": None,
             "pedido": 0.0, "entregue": 0.0, "pendente": 0.0, "pedidos": 0, "por_setor": [], "por_mes": [], "tipos": [], "compras": []}
        if g is not None:
            x["saldo"], x["principal"] = float(g[M_CONS].sum()), float(g.loc[g["_princ"], M_CONS].sum())
            x["setores"] = x["saldo"] - x["principal"]
            comp = g[g[M_TIPO] == "Compra"]
            x["compra_qtd"], x["compra_valor"] = float(comp[M_ENT].sum()), float(comp[M_VT].sum())
            custo = g[g[M_VU] > 0].sort_values(M_DATA)
            if len(custo):
                x["custo_klingo"] = float(custo.iloc[-1][M_VU])
                x["custo_origem"] = "compra" if len(comp[comp[M_VU] > 0]) else "registro do Klingo"
            cg = g[g[M_TIPO] == CONSUMO]
            if len(cg):
                x["consumo"], x["baixas"], x["baixas_zero"] = float(cg[M_SAI].sum()), int(len(cg)), int((cg[M_SAI] == 0).sum())
                x["primeira_baixa"], x["ultima_baixa"] = cg[M_DATA].min(), cg[M_DATA].max()
                x["por_setor"] = sorted(({"nome": n, "qtd": float(h[M_SAI].sum()), "baixas": int(len(h))} for n, h in cg.groupby("_cc")), key=lambda r: -r["qtd"])
                x["por_mes"] = [{"ym": ym, "qtd": float(h[M_SAI].sum()), "baixas": int(len(h))} for ym, h in cg.groupby("_ym")]
            x["tipos"] = sorted(({"nome": f"{t} ({'entrada' if es == 'E' else 'saída'})", "qtd": float(h[M_ENT].sum() + h[M_SAI].sum()), "linhas": int(len(h))}
                                 for (t, es), h in g.groupby([M_TIPO, M_ES]) if t != TRANSFERENCIA), key=lambda r: -r["linhas"])
            x["compras"] = [{"data": r[M_DATA], "tipo": r[M_TIPO], "fornecedor": None if pd.isna(r[M_FORN]) else r[M_FORN], "qtd": float(r[M_ENT]),
                             "valor": float(r[M_VT]), "custo_unit": float(r[M_VU]), "local": r[M_LOCAL]}
                            for _, r in g[g[M_TIPO].isin(ENTRADAS_EXTERNAS)].sort_values(M_DATA, ascending=False).iterrows()]
        if sg is not None:
            x["pedido"], x["entregue"], x["pendente"], x["pedidos"] = float(sg["_qs"].sum()), float(sg["_qa"].sum()), float(sg["_pend_q"].sum()), int(len(sg))
        inf = informados.get(item)
        x["custo_informado"] = inf
        x["custo"] = inf if inf is not None else x["custo_klingo"]
        x["custo_fonte"] = "informado por você" if inf is not None else x["custo_origem"]
        x["custo_min"] = x["custo"] / fator if x["custo"] is not None else None
        x["valor_estoque"] = x["saldo"] * x["custo"] if x["custo"] is not None else None
        x["valor_consumo"] = x["consumo"] * x["custo"] if x["custo"] is not None else None
        x["baixado_pct"] = (x["consumo"] / x["entregue"] * 100) if x["entregue"] > 0 else None
        flags = []
        if g is None:
            flags.append("sem_lancamento")
        else:
            if x["baixas"] >= BAIXA_ZERO_MIN and x["baixas_zero"] / x["baixas"] * 100 >= BAIXA_ZERO_PCT:
                flags.append("baixa_zero")
            if x["baixas"] == 0 and x["entregue"] >= SEM_BAIXA_ENTREGUE_MIN:
                flags.append("sem_baixa")
        if em_emb:
            flags.append("embalagem")
        if x["custo"] is None:
            flags.append("sem_custo")
        x["flags"] = flags
        lista.append(x)
    total_estoque = sum(x["valor_estoque"] or 0 for x in lista)
    for x in lista:   # um item com mais da metade do valor do estoque: o custo pode estar na unidade errada (frasco x mL) e nao entra nos totais "confiaveis"
        x["custo_confira"] = bool(total_estoque > 0 and (x["valor_estoque"] or 0) / total_estoque * 100 >= CUSTO_CONCENTRADO_PCT and x["custo_informado"] is None)
        if x["custo_confira"]:
            x["flags"].insert(0, "custo_confira")
    lista.sort(key=lambda x: (-(x["valor_consumo"] or 0), -x["consumo"], -x["pedido"], x["item"]))

    com_custo = [x for x in lista if x["custo"] is not None]
    cons_tot = sum(x["baixas"] for x in lista)
    zero_tot = sum(x["baixas_zero"] for x in lista)
    resumo = {"itens": len(lista), "com_custo": len(com_custo), "com_custo_compra": sum(1 for x in lista if x["custo_origem"] == "compra"),
              "valor_estoque": total_estoque, "valor_consumo": sum(x["valor_consumo"] or 0 for x in lista),
              "valor_estoque_ok": sum((x["valor_estoque"] or 0) for x in lista if not x["custo_confira"]),
              "valor_consumo_ok": sum((x["valor_consumo"] or 0) for x in lista if not x["custo_confira"]),
              "custo_confira": [x["item"] for x in lista if x["custo_confira"]],
              "com_consumo": sum(1 for x in lista if x["baixas"]), "baixa_zero": sum(1 for x in lista if "baixa_zero" in x["flags"]),
              "sem_baixa": sum(1 for x in lista if "sem_baixa" in x["flags"]), "em_embalagem": sum(1 for x in lista if x["em_embalagem"]),
              "baixas": cons_tot, "baixas_zero_total": zero_tot, "informados": len(informados)}

    compras = []
    if len(m):
        for _, r in m[m[M_TIPO].isin(ENTRADAS_EXTERNAS)].sort_values(M_DATA, ascending=False).iterrows():
            it = next((x for x in lista if x["item"] == r[M_ITEM]), None)
            compras.append({"data": r[M_DATA], "tipo": r[M_TIPO], "item": r[M_ITEM], "un": r["_un"], "fornecedor": None if pd.isna(r[M_FORN]) else r[M_FORN],
                            "qtd": float(r[M_ENT]), "valor": float(r[M_VT]), "custo_unit": float(r[M_VU]), "saldo": it["saldo"] if it else 0.0,
                            "consumo": it["consumo"] if it else 0.0, "baixas": it["baixas"] if it else 0, "baixas_zero": it["baixas_zero"] if it else 0})

    achados = []
    if len(m):
        ent = m[(m[M_ES] == "E") & (m[M_TIPO] != TRANSFERENCIA)]
        por_tipo = ent.groupby(M_TIPO).size()
        n_inv, n_comp = int(por_tipo.get(INVENTARIO, 0)), int(por_tipo.get("Compra", 0))
        if n_comp + n_inv:
            achados.append({"titulo": "O estoque nasceu de contagem, não de compra",
                            "texto": f"{n_br(n_inv)} de {n_br(len(ent))} entradas são inventário (contagem, sem custo) e só {n_br(n_comp)} são compra. "
                                     f"Por isso só {n_br(resumo['com_custo_compra'])} de {n_br(len(lista))} itens têm custo. Lance cada compra com o valor."})
        if resumo["em_embalagem"]:
            nomes = ", ".join(html.escape(bonito(x["item"])) for x in lista if x["em_embalagem"] and ("GRAMP" in x["item"].upper() or "CLIPES" in x["item"].upper()))
            achados.append({"titulo": "Grampo e clipe são contados por caixa",
                            "texto": f"{n_br(resumo['em_embalagem'])} itens são controlados em caixa ou pacote ({nomes}). O Klingo só baixa a caixa inteira, então o gasto de cada unidade fica invisível. "
                                     "Digite o preço da caixa e o painel mostra quanto custa cada unidade."})
    if len(s) and s[S_VA].fillna(0).sum() > 0:
        topo = s.loc[s[S_VA].fillna(0).idxmax()]
        pct_va = float(topo[S_VA] / s[S_VA].fillna(0).sum() * 100)
        if pct_va >= 50:
            achados.append({"titulo": "Uma única solicitação concentra o valor atendido",
                            "texto": f"A solicitação <b>#{int(topo[S_ID])}</b> ({dia_br(topo[S_DATA])}, {html.escape(bonito(topo[S_ITEM]))}, {n_br(float(topo[S_QA]))} {html.escape(str(topo['_un']).lower())} para {html.escape(bonito(topo['_cc']))}) "
                                     f"vale <b>{brl(float(topo[S_VA]))}</b>, {pct_va:.0f}% de todo o valor atendido ({brl(float(s[S_VA].fillna(0).sum()))}). Se o custo cadastrado for por frasco e não por mL, o valor está inflado."})
    sem_baixa = [x for x in lista if "sem_baixa" in x["flags"]]
    if sem_baixa:
        top = sorted(sem_baixa, key=lambda x: -x["entregue"])[:5]
        achados.append({"titulo": "Material entregue aos setores sem nenhuma baixa",
                        "texto": f"<b>{n_br(len(sem_baixa))}</b> itens saíram do estoque para os setores e nunca foram baixados como consumo, ex.: "
                                 + ", ".join(f"{html.escape(bonito(x['item']))} ({n_br(x['entregue'])} {html.escape(x['un'].lower())})" for x in top) + ". É consumo que nenhum custo alcança."})
    return {"lista": lista, "resumo": resumo, "compras": compras, "achados": achados, "informados": len(informados), "arquivo_custos": CUSTOS_ARQ.name, "custos_nuvem": armazenamento.ativo()}


def montar_exame(m: pd.DataFrame, itens: dict, primeiro_mes: str) -> dict | None:
    """Material gasto por atendimento em um setor (hoje so RM/TC, o unico que o relatorio de Atendimento separa). Ordem de grandeza: as baixas nao sao diarias."""
    try:
        at = k.carregar(PASTA.parent / "Atendimento")["Atendimentos"]
    except Exception:
        return None
    if not len(m) or not len(at) or "Setor (CSI/RM/RX/TC)" not in at.columns:
        return None
    alvo = SETOR_ATENDIMENTO["RM/TC"]
    cons = m[(m[M_TIPO] == CONSUMO) & (m["_cc"].isin(alvo)) & (m["_ym"] >= primeiro_mes)]
    if not len(cons):
        return None
    d0, d1 = cons["_dia"].min(), cons["_dia"].max()
    a = at[at["Setor (CSI/RM/RX/TC)"].astype(str).str.contains("RM/TC", na=False) & at["Data do Atendimento"].notna()].copy()
    a = a[(a["Data do Atendimento"].dt.date >= d0) & (a["Data do Atendimento"].dt.date <= d1)]
    n = float(pd.to_numeric(a["Atendimentos (Qtde)"], errors="coerce").fillna(1).sum()) if len(a) else 0.0
    if n <= 0:
        return None
    receita = float(pd.to_numeric(a["Valor do Atendimento"], errors="coerce").fillna(0).sum())
    por = {x["item"]: x for x in itens["lista"]}
    linhas = []
    for item, g in cons.groupby(M_ITEM):
        q = float(g[M_SAI].sum())
        if q <= 0:
            continue
        x = por.get(item, {})
        c = x.get("custo")
        linhas.append({"item": item, "un": x.get("un", ""), "qtd": q, "por_exame": q / n, "custo": c, "valor": q * c if c is not None else None, "baixas": int(len(g)),
                       "confira": bool(x.get("custo_confira"))})
    linhas.sort(key=lambda r: (-(r["valor"] or 0), -r["qtd"]))
    conhecido = sum(r["valor"] or 0 for r in linhas if not r["confira"])
    a_confirmar = sum(r["valor"] or 0 for r in linhas if r["confira"])
    return {"setor": "RM/TC", "de": d0, "ate": d1, "atendimentos": n, "receita": receita, "ticket": receita / n, "linhas": linhas[:20],
            "itens_total": len(linhas), "itens_com_custo": sum(1 for r in linhas if r["valor"] is not None and not r["confira"]), "custo_conhecido": conhecido,
            "custo_por_exame": conhecido / n, "a_confirmar": a_confirmar}


# ---------------------------------------------------------------- pagina
def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    defn = k.ler_definicao(PASTA)
    abas = k.carregar(PASTA)
    hoje = date.today()
    ym_hoje = hoje.strftime("%Y-%m")
    primeiro = defn["primeiro_mes"]
    m, s = preparar_mov(abas[ABA_MOV]), preparar_sol(abas[ABA_SOL], hoje)
    exames = exames_por_dia()

    meses, atencao, extras = {}, [], {}
    per, info = None, None
    if len(m) or len(s):
        for ym in k.meses_entre(primeiro, ym_hoje):
            meses[ym] = montar_mes(ym, hoje, m, s, exames)
        per, info = pc.periodo_pedido(de, ate, meses)
        if per and not per.unico:
            pc.acrescentar_periodo(meses, per, lambda p: montar_mes(p.fim, hoje, m, s, exames, per=p))
        est, valor, pend = montar_estoque(m, s, hoje), montar_valor(m), montar_pendentes(s, hoje)
        cons = m[m[M_TIPO] == CONSUMO] if len(m) else m
        consumo = {"ultima": None, "linhas": int(len(cons)), "dias_com_baixa": 0, "dia_pico": None, "pico_linhas": 0, "pico_pct": 0.0,
                   "zero_linhas": 0, "zero_itens": []}
        if len(cons):
            por_dia = cons.groupby("_dia").size()
            zero = cons[cons[M_SAI] == 0]
            consumo.update(ultima=cons[M_DATA].max().date(), dias_com_baixa=int(len(por_dia)), dia_pico=por_dia.idxmax(),
                           pico_linhas=int(por_dia.max()), pico_pct=float(por_dia.max() / len(cons) * 100),
                           zero_linhas=int(len(zero)), zero_itens=[(n, int(q)) for n, q in zero.groupby(M_ITEM).size().sort_values(ascending=False).head(6).items()])
        itens = montar_itens(m, s, hoje, ler_custos_informados())
        gravar_modelo_custos(itens["lista"])
        atencao = alertas_gerais(hoje, m, s, pend, est, valor, consumo, exames, itens)
        extras = {"pendentes": pend, "estoque": est, "valor": valor, "consumo": consumo, "evolucao": montar_evolucao(m, s),
                  "conferencia": gp.anotar("suprimentos", conferir(m, s, valor, consumo, primeiro)), "tem_exames": bool(exames),
                  "itens": itens, "exame": montar_exame(m, itens, primeiro)}

    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else datetime.now()
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()), "hoje": hoje.isoformat(),
        "mes_padrao": per.chave if per else (ym_hoje if ym_hoje in meses else (max(meses) if meses else None)), "periodo": info,
        "meses": meses, "atencao": atencao, "limites": {"pend_atencao": PENDENCIA_ATENCAO, "pend_critica": PENDENCIA_CRITICA, "cobertura": COBERTURA_MIN,
                                                        "janela": JANELA_DEMANDA, "sem_baixa": SEM_BAIXA_ATENCAO}, **extras,
    }
    pagina = pc.montar_html(MODELO, payload)
    if devolver_html:
        return pagina
    SAIDA.write_text(pagina, encoding="utf-8")
    return SAIDA


def main():
    args = set(sys.argv[1:])
    if args & {"--forcar", "--historico"}:
        print(">>>", atualizar(forcar=True, historico="--historico" in args)["mensagem"])
    saida = gerar()
    print(">>> Dashboard gerado:", saida)
    if "--sem-abrir" not in args:
        webbrowser.open(saida.as_uri())


if __name__ == "__main__":
    main()
