"""Faturamento: atualiza a planilha a partir do Klingo e gera 'Dashboard Faturamento.html'.

Uso:  python gerar_faturamento.py             so regenera o dashboard com o que ja esta na planilha
      python gerar_faturamento.py --forcar    consulta o Klingo agora (como o botao) e regenera
      python gerar_faturamento.py --historico baixa de novo todos os meses desde o primeiro
"""
import html
import json
import sys
import webbrowser
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import gerar_dashboard as gd  # noqa: E402  (dias uteis das Metas)
import guia_pendencias as gp  # noqa: E402

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Faturamento.html"
ABA_PROD, ABA_CTRL, ABA_ABERTO, ABA_FAT = "Receita Produzida", "Controle por Convênio", "Faturas em Aberto", "Faturas Emitidas"
PARTICULAR = "PARTICULAR"
LIMITE_RECEBIDO_BAIXO = 0.10   # recebido de convenio abaixo de 10% do produzido num mes fechado
LIMITE_VARIACAO = 10.0         # variacao (%) contra o mesmo ponto do mes anterior que merece aviso
MIN_DIAS_PROJECAO = 3          # dias uteis completos para projetar o fechamento do mes

# faturas emitidas (#13355): status do Klingo
A_ENVIAR, ENVIADA, MOVIMENTADA, CANCELADA = "A Enviar", "Enviada", "Movimentada", "Cancelada"
ENVIADAS = (ENVIADA, MOVIMENTADA)
ESPERA_ATENCAO = 7             # dias esperando envio: o normal e sair no mesmo dia (3/4 das enviadas saem no dia da emissao)
ESPERA_CRITICA = 30
LIMITE_FALTA_FATURAR = 0.10    # produzido ainda sem fatura acima de 10% num mes fechado
LIMITE_CANCELAMENTO = 0.20     # mais de 20% das faturas emitidas canceladas
MIN_FATURAS_CANCEL = 5         # so compara a taxa de cancelamento de convenios com ao menos 5 faturas
FAIXAS_ESPERA = [(1, "Hoje ou ontem", "var(--s1)"), (7, "2 a 7 dias", "var(--warn)"),
                 (15, "8 a 15 dias", "var(--serious)"), (10 ** 6, "Mais de 15 dias", "var(--crit)")]


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    return k.atualizar(PASTA, forcar=forcar, historico=historico)


def norm(s) -> str:
    return gd.norm(s)


# ---------------------------------------------------------------- calculos por mes
def faixa_de_atraso(dias: int) -> tuple[int, str]:
    """(ordem, rotulo) conforme a fatura esta vencida (dias > 0) ou a vencer (dias <= 0)."""
    if dias > 30:
        return 0, "Vencida há mais de 30 dias"
    if dias > 7:
        return 1, "Vencida há 8 a 30 dias"
    if dias > 0:
        return 2, "Vencida há 1 a 7 dias"
    if dias == 0:
        return 3, "Vence hoje"
    if dias >= -7:
        return 4, "Vence em 1 a 7 dias"
    if dias >= -30:
        return 5, "Vence em 8 a 30 dias"
    return 6, "Vence em mais de 30 dias"


COR_FAIXA = ["var(--crit)", "var(--crit)", "var(--serious)", "var(--warn)", "var(--s1)", "var(--s1)", "var(--s1)"]


def montar_aberto(ab: pd.DataFrame, hoje: date) -> dict:
    a = ab.copy()
    a["_dias"] = a["Vencimento"].map(lambda d: (hoje - d.date()).days if pd.notna(d) else None)
    valor = a["Valor Bruto"].fillna(0)
    vencidas = a[a["_dias"].fillna(-999) > 0]
    faixas = {}
    for dias, v in zip(a["_dias"], valor):
        if dias is None or pd.isna(dias):
            continue
        ordem, rot = faixa_de_atraso(int(dias))
        f = faixas.setdefault(ordem, {"ordem": ordem, "rotulo": rot, "valor": 0.0, "qtd": 0, "cor": COR_FAIXA[ordem]})
        f["valor"] += float(v)
        f["qtd"] += 1
    por_conv = []
    for nome, g in a.groupby("Convênio", dropna=False):
        gv = g[g["_dias"].fillna(-999) > 0]
        por_conv.append({"nome": str(nome), "valor": float(g["Valor Bruto"].fillna(0).sum()), "qtd": int(len(g)),
                         "vencido_valor": float(gv["Valor Bruto"].fillna(0).sum()), "vencido_qtd": int(len(gv)),
                         "maior_atraso": int(gv["_dias"].max()) if len(gv) else 0})
    por_conv.sort(key=lambda x: (-x["vencido_valor"], -x["valor"]))
    lista = vencidas.sort_values(["_dias", "Valor Bruto"], ascending=[False, False]).head(15)
    return {
        "total": float(valor.sum()), "qtd": int(len(a)),
        "sem_valor": int((a["Valor Bruto"].fillna(0) <= 0).sum()),
        "sem_valor_itens": gp.tabela(["Nº do Lote", "Convênio", "Fatura em", "Vencimento"],
                                     [[r["Nº do Lote"], r["Convênio"], gp.dbr(r["Data da Fatura"]), gp.dbr(r["Vencimento"])]
                                      for _, r in a[a["Valor Bruto"].fillna(0) <= 0].iterrows()], total=int((a["Valor Bruto"].fillna(0) <= 0).sum())),
        "vencidas_itens": gp.tabela(["Nº do Lote", "Convênio", "Vencimento", "Dias de atraso", "Valor"],
                                    [[r["Nº do Lote"], r["Convênio"], gp.dbr(r["Vencimento"]), int(r["_dias"]), gp.reais(r["Valor Bruto"])]
                                     for _, r in vencidas.sort_values(["_dias", "Valor Bruto"], ascending=[False, False]).iterrows()],
                                    total=len(vencidas), numericas=(3, 4)),
        "vencido_valor": float(vencidas["Valor Bruto"].fillna(0).sum()), "vencido_qtd": int(len(vencidas)),
        "maior_atraso": int(vencidas["_dias"].max()) if len(vencidas) else 0,
        "faixas": [faixas[o] for o in sorted(faixas)],
        "por_convenio": por_conv,
        "lista_vencidas": [{"convenio": str(r["Convênio"]), "lote": r["Nº do Lote"], "fatura_em": r["Data da Fatura"],
                            "vencimento": r["Vencimento"], "dias": int(r["_dias"]), "valor": r["Valor Bruto"]}
                           for _, r in lista.iterrows()],
    }


# ---------------------------------------------------------------- faturas emitidas (#13355)
def nz(v) -> float:
    return 0.0 if pd.isna(v) else float(v)


def preparar_faturas(fat: pd.DataFrame) -> pd.DataFrame:
    if not len(fat):
        return fat
    f = fat.copy()
    f["_op"] = f["Operadora - Nome"].fillna("(sem operadora)").astype(str)
    f["_st"] = f["Fatura - Status"]
    f["_valor"] = f["Fatura - Valor"]
    f["_comp"] = f["Fatura - Data Inicial"].dt.strftime("%Y-%m")  # competencia = mes em que comeca o periodo faturado
    return f


def montar_faturas(f: pd.DataFrame, hoje: date) -> dict:
    """Posicao de hoje das faturas emitidas: o que espera envio, prazos de pagamento, cancelamentos e falhas de cadastro."""
    if not len(f):
        return {"tem": False}
    hoje_ts = pd.Timestamp(hoje)
    ativas = f[f["_st"] != CANCELADA]
    enviadas = f[f["_st"].isin(ENVIADAS)]
    canceladas = f[f["_st"] == CANCELADA]

    # prazos: so as faturas enviadas tem data de envio e de vencimento
    e = enviadas.dropna(subset=["Fatura - Data de Envio", "Fatura - Data de Vencimento"]).copy()
    e["_prazo"] = (e["Fatura - Data de Vencimento"] - e["Fatura - Data de Envio"]).dt.days
    e["_dias_envio"] = (e["Fatura - Data de Envio"] - e["Fatura - Data de Emissão"]).dt.days
    ev = e[e["_valor"].fillna(0) > 0]
    prazo_pond = float((ev["_prazo"] * ev["_valor"]).sum() / ev["_valor"].sum()) if len(ev) else None
    fim_emissao = (ativas["Fatura - Data de Emissão"] - ativas["Fatura - Data Fim"]).dt.days.dropna()
    por_prazo = [{"nome": op, "qtd": int(len(g)), "valor": float(g["_valor"].fillna(0).sum()), "mediana": float(g["_prazo"].median()),
                  "minimo": int(g["_prazo"].min()), "maximo": int(g["_prazo"].max())} for op, g in e.groupby("_op")]
    por_prazo.sort(key=lambda x: (-x["mediana"], -x["valor"]))
    prazo_de = {x["nome"]: x["mediana"] for x in por_prazo}
    prazos = {
        "fim_emissao": float(fim_emissao.median()) if len(fim_emissao) else None,
        "emissao_envio": float(e["_dias_envio"].median()) if len(e) else None,
        "no_mesmo_dia": float((e["_dias_envio"] <= 0).mean() * 100) if len(e) else None,
        "pagamento": float(e["_prazo"].median()) if len(e) else None, "pagamento_pond": prazo_pond,
        "qtd": int(len(e)), "por_operadora": por_prazo,
    }

    # a enviar: emitidas e ainda nao enviadas (as sem valor ficam de fora dos totais e sao contadas a parte)
    ae = f[f["_st"] == A_ENVIAR].copy()
    ae["_dias"] = (hoje_ts - ae["Fatura - Data de Emissão"].dt.normalize()).dt.days
    sem_valor_ae = int((ae["_valor"].fillna(0) <= 0).sum())
    ae = ae[ae["_valor"].fillna(0) > 0]
    faixas, anterior = [], -1
    for limite, rotulo, cor in FAIXAS_ESPERA:
        g = ae[(ae["_dias"] > anterior) & (ae["_dias"] <= limite)]
        faixas.append({"rotulo": rotulo, "valor": float(g["_valor"].sum()), "qtd": int(len(g)), "cor": cor})
        anterior = limite
    ja_enviou = enviadas.groupby("_op").size().to_dict()
    por_op = [{"nome": op, "qtd": int(len(g)), "valor": float(g["_valor"].sum()), "espera_max": int(g["_dias"].max()),
               "enviadas_antes": int(ja_enviou.get(op, 0)), "prazo": prazo_de.get(op)} for op, g in ae.groupby("_op")]
    por_op.sort(key=lambda x: -x["valor"])
    nunca = [x for x in por_op if not x["enviadas_antes"]]

    def acima(dias):
        g = ae[ae["_dias"] > dias]
        return {"qtd": int(len(g)), "valor": float(g["_valor"].sum())}

    espera = ae[ae["_dias"] > ESPERA_ATENCAO].sort_values(["_dias", "_valor"], ascending=[False, False])
    itens_espera = gp.tabela(["Fatura (Id)", "Convênio", "Emitida em", "Dias esperando", "Valor", "Responsável"],
                             [[int(r["Fatura - Id"]), r["_op"], gp.dbr(r["Fatura - Data de Emissão"]), int(r["_dias"]), gp.reais(r["_valor"]), r["Fatura - Usuário Responsável"]]
                              for _, r in espera.iterrows()], total=len(espera), numericas=(0, 3, 4))
    itens_nunca = gp.tabela(["Convênio", "Faturas esperando envio", "Valor", "Espera máxima (dias)"],
                            [[x["nome"], x["qtd"], gp.reais(x["valor"]), x["espera_max"]] for x in nunca], numericas=(1, 2, 3))
    lista = ae.sort_values(["_dias", "_valor"], ascending=[False, False]).head(15)
    a_enviar = {
        "valor": float(ae["_valor"].sum()), "qtd": int(len(ae)), "sem_valor": sem_valor_ae,
        "maior_espera": int(ae["_dias"].max()) if len(ae) else 0,
        "limite_atencao": ESPERA_ATENCAO, "limite_critica": ESPERA_CRITICA,
        "acima_atencao": acima(ESPERA_ATENCAO), "acima_critica": acima(ESPERA_CRITICA),
        "faixas": faixas, "por_operadora": por_op,
        "nunca_enviou": {"qtd": sum(x["qtd"] for x in nunca), "valor": sum(x["valor"] for x in nunca), "nomes": [x["nome"] for x in nunca], "itens": itens_nunca},
        "itens_espera": itens_espera,
        "lista": [{"id": int(r["Fatura - Id"]), "operadora": r["_op"], "emitida": r["Fatura - Data de Emissão"], "dias": int(r["_dias"]),
                   "valor": float(r["_valor"]), "usuario": r["Fatura - Usuário Responsável"]} for _, r in lista.iterrows()],
    }

    # cancelamentos: o relatorio nao traz o valor das canceladas, so a quantidade
    def taxa(g_total, g_canc):
        return float(g_canc / g_total * 100) if g_total else None

    por_conv = []
    for op, g in f.groupby("_op"):
        c = int((g["_st"] == CANCELADA).sum())
        if len(g) >= MIN_FATURAS_CANCEL and c:
            por_conv.append({"nome": op, "total": int(len(g)), "canceladas": c, "pct": taxa(len(g), c)})
    por_conv.sort(key=lambda x: (-x["pct"], -x["canceladas"]))
    por_usuario = []
    for u, g in f.groupby(f["Fatura - Usuário Responsável"].fillna("(sem usuário)")):
        c = int((g["_st"] == CANCELADA).sum())
        por_usuario.append({"nome": u, "emitidas": int(len(g)), "canceladas": c, "pct": taxa(len(g), c),
                            "valor": float(g.loc[g["_st"] != CANCELADA, "_valor"].fillna(0).sum())})
    por_usuario.sort(key=lambda x: -x["emitidas"])
    por_mes = []
    for ym, g in f.groupby(f["Fatura - Data de Emissão"].dt.strftime("%Y-%m")):
        c = int((g["_st"] == CANCELADA).sum())
        por_mes.append({"mes": ym, "rotulo": pc.rotulo_mes(ym), "total": int(len(g)), "canceladas": c, "pct": taxa(len(g), c)})
    itens_cancel = gp.tabela(["Convênio", "Faturas emitidas", "Canceladas", "% canceladas"],
                             [[x["nome"], x["total"], x["canceladas"], f"{x['pct']:.0f}%"] for x in por_conv], numericas=(1, 2, 3))
    cancelamento = {"total": int(len(f)), "canceladas": int(len(canceladas)), "pct": taxa(len(f), len(canceladas)), "itens": itens_cancel,
                    "minimo_convenio": MIN_FATURAS_CANCEL, "por_convenio": por_conv, "por_usuario": por_usuario, "por_mes": por_mes}

    # falhas de cadastro
    sem_protocolo = enviadas[enviadas["Fatura - Envio - Protocolo"].isna()]
    sem_valor = ativas[ativas["_valor"].fillna(0) <= 0]
    retencoes = ativas["Fatura - Valor Retenções"].fillna(0)
    return {
        "tem": True, "total": int(len(f)), "ativas": int(len(ativas)),
        "status": {s: {"qtd": int((f["_st"] == s).sum()), "valor": float(f.loc[f["_st"] == s, "_valor"].fillna(0).sum())}
                   for s in (A_ENVIAR, ENVIADA, MOVIMENTADA, CANCELADA)},
        "a_enviar": a_enviar, "prazos": prazos, "cancelamento": cancelamento,
        "sem_protocolo": {"qtd": int(len(sem_protocolo)), "valor": float(sem_protocolo["_valor"].fillna(0).sum()),
                          "itens": gp.tabela(["Fatura (Id)", "Convênio", "Status", "Enviada em", "Valor"],
                                             [[int(r["Fatura - Id"]), r["_op"], r["_st"], gp.dbr(r["Fatura - Data de Envio"]), gp.reais(r["_valor"])]
                                              for _, r in sem_protocolo.sort_values("Fatura - Data de Envio").iterrows()], total=len(sem_protocolo), numericas=(0, 4)),
                          "nomes": sorted(sem_protocolo["_op"].unique().tolist())},
        "sem_valor": {"qtd": int(len(sem_valor)), "a_enviar": int((sem_valor["_st"] == A_ENVIAR).sum()),
                      "itens": gp.tabela(["Fatura (Id)", "Convênio", "Status", "Emitida em"],
                                         [[int(r["Fatura - Id"]), r["_op"], r["_st"], gp.dbr(r["Fatura - Data de Emissão"])]
                                          for _, r in sem_valor.sort_values("Fatura - Data de Emissão").iterrows()], total=len(sem_valor), numericas=(0,))},
        "retencoes": {"qtd": int((retencoes > 0).sum()), "valor": float(retencoes.sum())},
        "primeira_emissao": f["Fatura - Data de Emissão"].min(), "ultima_emissao": f["Fatura - Data de Emissão"].max(),
    }


def montar_funil(ym: str, f: pd.DataFrame, c: pd.DataFrame) -> dict:
    """Do produzido (#13329) ao faturado, enviado e recebido, por convenio, para a competencia ym (mes em que comeca o periodo da fatura)."""
    linhas: dict[str, dict] = {}

    def linha(chave, nome):
        return linhas.setdefault(chave, {"nome": nome, "produzido": 0.0, "guias": 0, "recebido": 0.0, "faturado": 0.0,
                                         "a_enviar": 0.0, "enviado": 0.0, "faturas": 0, "canceladas": 0})

    for _, r in c.iterrows():
        x = linha(norm(r["Convênio"]), r["Convênio"])
        x["produzido"], x["guias"], x["recebido"] = nz(r["Produzido"]), int(nz(r["Qtd. Guias"])), nz(r["Recebido"])
    if len(f):
        a = f[f["_comp"] == ym]
        for op, g in a[a["_st"] != CANCELADA].groupby("_op"):
            x = linha(norm(op), op)
            x["faturado"] = float(g["_valor"].fillna(0).sum())
            x["a_enviar"] = float(g.loc[g["_st"] == A_ENVIAR, "_valor"].fillna(0).sum())
            x["enviado"] = float(g.loc[g["_st"].isin(ENVIADAS), "_valor"].fillna(0).sum())
            x["faturas"] = int(len(g))
        for op, g in a[a["_st"] == CANCELADA].groupby("_op"):
            linha(norm(op), op)["canceladas"] = int(len(g))
    por_conv = []
    for x in linhas.values():
        x["falta"] = max(x["produzido"] - x["faturado"], 0.0)
        x["pct_faturado"] = x["faturado"] / x["produzido"] * 100 if x["produzido"] else None
        por_conv.append(x)
    por_conv.sort(key=lambda x: (-x["falta"], -x["produzido"]))
    produzido = sum(x["produzido"] for x in por_conv)
    faturado = sum(x["faturado"] for x in por_conv)
    falta = sum(x["falta"] for x in por_conv)
    sem_fatura = [{"nome": x["nome"], "produzido": x["produzido"], "guias": x["guias"]}
                  for x in por_conv if x["produzido"] > 0 and x["faturas"] == 0 and x["canceladas"] == 0]
    return {
        "tem": bool(produzido or faturado), "produzido": produzido, "faturado": faturado,
        "a_enviar": sum(x["a_enviar"] for x in por_conv), "enviado": sum(x["enviado"] for x in por_conv),
        "recebido": sum(x["recebido"] for x in por_conv), "falta": falta,
        "pct_faturado": faturado / produzido * 100 if produzido else None,
        "pct_falta": falta / produzido * 100 if produzido else None,
        "por_convenio": por_conv, "sem_fatura": sem_fatura,
    }


def conferir_abertas(f: pd.DataFrame, ab: pd.DataFrame) -> dict:
    """As faturas Enviadas do #13355 devem ser as 'Faturas em aberto' do #13328: compara lote a lote (protocolo = Nº do Lote)."""
    if not len(f) or not len(ab):
        return {"tem": False}
    txt = lambda s: s.dropna().map(lambda v: str(v).strip().removesuffix(".0"))
    env = f[f["_st"].isin(ENVIADAS) & f["Fatura - Envio - Protocolo"].notna()].copy()
    env["_lote"] = txt(env["Fatura - Envio - Protocolo"])
    a = ab[ab["Nº do Lote"].notna()].copy()
    a["_lote"] = txt(a["Nº do Lote"])
    v355 = env.groupby("_lote")["_valor"].sum()
    v328 = a.groupby("_lote")["Valor Bruto"].sum()
    juntos = pd.concat([v355.rename("v355"), v328.rename("v328")], axis=1)
    so_328 = juntos[juntos["v355"].isna()]
    so_355 = juntos[juntos["v328"].isna()]
    ambos = juntos.dropna()
    dif = ambos[(ambos["v355"] - ambos["v328"]).abs() > 0.01]
    mov = env[(env["_st"] == MOVIMENTADA) & env["_lote"].isin(set(a["_lote"]))]
    return {
        "tem": True, "lotes_13328": int(len(v328)), "lotes_batem": int(len(ambos) - len(dif)),
        "so_no_13328": int(len(so_328)), "so_no_13355": int(len(so_355)), "valor_diferente": int(len(dif)),
        "movimentada_em_aberto": {"qtd": int(len(mov)), "valor": float(mov["_valor"].fillna(0).sum())},
    }


def alertas_faturas(fg: dict, funil: dict, ref_rotulo: str) -> list[dict]:
    """Alertas ligados ao #13355. 'fg' = posicao de hoje; 'funil' = do mes de referencia (o proprio mes se ja fechou, senao o anterior,
    que ja esta fechado: em mes aberto e normal faltar faturar)."""
    out = []
    if fg.get("tem"):
        ae = fg["a_enviar"]
        crit, aten = ae["acima_critica"], ae["acima_atencao"]
        if crit["qtd"]:
            out.append({"nivel": "critico", "titulo": f"Faturas paradas há mais de {ESPERA_CRITICA} dias sem envio",
                        "itens": ae["itens_espera"],
                        "texto": f"<b>{crit['qtd']}</b> fatura(s) somando <b>{pc_brl(crit['valor'])}</b> foram emitidas há mais de {ESPERA_CRITICA} dias e ainda estão “A enviar”. "
                                 f"Enquanto não forem enviadas, o convênio não começa a contar o prazo de pagamento."})
        elif aten["qtd"]:
            out.append({"nivel": "atencao", "titulo": f"Faturas esperando envio há mais de {ESPERA_ATENCAO} dias",
                        "itens": ae["itens_espera"],
                        "texto": f"<b>{aten['qtd']}</b> fatura(s) somando <b>{pc_brl(aten['valor'])}</b> estão “A enviar” há mais de {ESPERA_ATENCAO} dias "
                                 f"(a mais antiga há <b>{ae['maior_espera']}</b> dias). O normal é sair no mesmo dia da emissão."})
        n = ae["nunca_enviou"]
        if n["qtd"]:
            nomes = ", ".join(html.escape(x) for x in n["nomes"])
            out.append({"nivel": "atencao", "titulo": "Convênios com faturas emitidas e nenhuma enviada", "itens": n["itens"],
                        "texto": f"<b>{nomes}</b>: <b>{n['qtd']}</b> fatura(s), <b>{pc_brl(n['valor'])}</b> ({n['valor'] / ae['valor'] * 100:.0f}% do que espera envio), sem nenhuma enviada até hoje. "
                                 f"Se o envio é feito pelo portal do convênio, marque as faturas como enviadas no Klingo; senão, esse valor não aparece em “Faturas em aberto”."})
        cancel = fg["cancelamento"]
        if cancel["pct"] is not None and cancel["pct"] / 100 >= LIMITE_CANCELAMENTO:
            piores = ", ".join(f"{html.escape(x['nome'])} ({x['pct']:.0f}%)" for x in cancel["por_convenio"][:3])
            out.append({"nivel": "atencao", "titulo": "Muitas faturas canceladas", "itens": cancel["itens"],
                        "texto": f"<b>{cancel['canceladas']}</b> de {cancel['total']} faturas emitidas foram canceladas (<b>{cancel['pct']:.0f}%</b>), o que gera retrabalho. "
                                 f"Maiores taxas: {piores}. Cancelar para refazer a fatura pode ser normal; o relatório não mostra o valor das canceladas."})
        sv = fg["sem_valor"]
        if sv["qtd"]:
            out.append({"nivel": "atencao", "titulo": "Faturas ativas sem valor", "itens": sv["itens"],
                        "texto": f"<b>{sv['qtd']}</b> fatura(s) não canceladas estão sem valor ({sv['a_enviar']} esperando envio). Elas ficam fora dos totais."})
        sp = fg["sem_protocolo"]
        if sp["qtd"]:
            out.append({"nivel": "info", "titulo": "Faturas enviadas sem protocolo", "itens": sp["itens"],
                        "texto": f"<b>{sp['qtd']}</b> fatura(s), <b>{pc_brl(sp['valor'])}</b>, foram enviadas sem número de protocolo ({', '.join(html.escape(x) for x in sp['nomes'])}). "
                                 f"Sem protocolo fica difícil conciliar o pagamento com o convênio."})
        pz = fg["prazos"]
        if pz["pagamento_pond"] is not None and pz["por_operadora"]:
            lentos = [x for x in pz["por_operadora"] if x["qtd"] >= 2][:3]
            txt = ", ".join(f"{html.escape(x['nome'])} ({x['mediana']:.0f} dias)" for x in lentos)
            out.append({"nivel": "info", "titulo": "Prazo de pagamento dos convênios",
                        "texto": f"Depois de enviada, a fatura vence em média em <b>{pz['pagamento_pond']:.0f} dias</b> (ponderado pelo valor). Mais lentos: {txt}."})
    if funil and funil.get("tem") and funil["produzido"]:
        if funil["sem_fatura"]:
            s = funil["sem_fatura"]
            nomes = ", ".join(f"{html.escape(x['nome'])} ({pc_brl(x['produzido'])})" for x in s[:4])
            out.append({"nivel": "atencao", "titulo": f"Convênios com produção em {ref_rotulo} e nenhuma fatura",
                        "itens": gp.tabela(["Convênio", "Produzido", "Guias"], [[x["nome"], gp.reais(x["produzido"]), x["guias"]] for x in s], numericas=(1, 2)),
                        "texto": f"<b>{len(s)}</b> convênio(s) somando <b>{pc_brl(sum(x['produzido'] for x in s))}</b> produzidos não têm nenhuma fatura emitida: {nomes}"
                                 f"{'…' if len(s) > 4 else ''}."})
        if funil["falta"] / funil["produzido"] >= LIMITE_FALTA_FATURAR:
            top = ", ".join(f"{html.escape(x['nome'])} ({pc_brl(x['falta'])})" for x in funil["por_convenio"][:3] if x["falta"] > 0)
            out.append({"nivel": "atencao", "titulo": f"Produzido de {ref_rotulo} que ainda não virou fatura",
                        "itens": gp.tabela(["Convênio", "Produzido", "Faturado", "Falta faturar"],
                                           [[x["nome"], gp.reais(x["produzido"]), gp.reais(x["faturado"]), gp.reais(x["falta"])] for x in funil["por_convenio"] if x["falta"] > 0],
                                           numericas=(1, 2, 3)),
                        "texto": f"Faltam faturar <b>{pc_brl(funil['falta'])}</b> (<b>{funil['pct_falta']:.0f}%</b> dos {pc_brl(funil['produzido'])} produzidos com convênios). Maiores: {top}."})
    return out


def montar_mes(ym: str, prod: pd.DataFrame, ctrl: pd.DataFrame, aberto: dict, hoje: date, cfg: dict,
               fat: pd.DataFrame, fg: dict, per: pc.Periodo | None = None, ref: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses: nesse caso as tabelas ja chegam reagrupadas (ver montar_periodo), 'ym' e o ultimo mes
    do periodo e o 'mes anterior' e o periodo anterior de mesmo tamanho."""
    ano, mes = int(ym[:4]), int(ym[5:])
    ultimo = monthrange(ano, mes)[1]
    fechado = per.fechado(hoje) if per else date(ano, mes, ultimo) < hoje
    ym_ant = k.mes_mais(ym, -1)
    rot = per.rotulo if per else pc.rotulo_mes(ym)
    rot_ant = per.anterior.rotulo if per else pc.rotulo_mes(ym_ant)   # base da comparacao da receita (que tem data de cada linha)
    # convenios, recebido e funil so existem por mes: num recorte de dias os rotulos desses blocos sao os dos meses inteiros que ele toca
    per_m = per.meses_inteiros if per else None
    rot_m = per_m.rotulo if per else rot
    rot_m_ant = (ref or per_m.anterior).rotulo if per else rot_ant
    p = prod[prod[k.COL_MES] == ym]
    p_ant = prod[prod[k.COL_MES] == ym_ant]
    c = ctrl[ctrl[k.COL_MES] == ym]

    receita = float(p["Valor"].sum())
    qtd = float(p["Quantidade"].sum())
    particular = float(p.loc[p["Operadora"].map(norm) == PARTICULAR, "Valor"].sum())
    pacientes = int(p["Paciente"].nunique())

    # comparacao com o mes anterior: mes fechado -> total x total; mes aberto -> mesmo ponto (dias completos)
    ref_valor, ref_txt, variacao = None, None, None
    if len(p_ant):
        if fechado:
            ref_valor, ref_txt = float(p_ant["Valor"].sum()), f"o {'período' if per else 'mês'} anterior ({rot_ant})"
        elif hoje.day - 1 >= 5 and not per:   # periodo ainda aberto: nao ha como comparar "o mesmo ponto" de varios meses
            ate = hoje.day - 1
            ref_valor = float(p_ant.loc[p_ant["Data"].dt.day <= ate, "Valor"].sum())
            receita_comp = float(p.loc[p["Data"].dt.day <= ate, "Valor"].sum())
            ref_txt = f"o mesmo ponto de {rot_ant} (até o dia {ate})"
        if ref_valor:
            variacao = ((receita if fechado else receita_comp) / ref_valor - 1) * 100

    # dias uteis e projecao (a projecao e do mes corrente; um periodo so soma os dias uteis)
    semana = set(cfg.get("dias_semana_atendimento", [0, 1, 2, 3, 4, 5]))
    feriados = {date.fromisoformat(f) for f in cfg.get("feriados", [])}
    uteis = gd.uteis_do_periodo(per, semana, feriados) if per else gd.dias_uteis(ano, mes, semana, feriados)
    completos = len(uteis) if fechado else sum(1 for d in uteis if d < hoje)
    receita_completa = receita if fechado else float(p.loc[p["Data"].dt.date < hoje, "Valor"].sum())
    ritmo = receita_completa / completos if completos else None
    projecao = ritmo * len(uteis) if (ritmo and not fechado and not per and completos >= MIN_DIAS_PROJECAO) else None

    # receita acumulada por dia (mes atual x mes anterior); num periodo de varios meses nao ha "dia do mes" que se compare
    por_dia = p.groupby(p["Data"].dt.day)["Valor"].sum()
    por_dia_ant = p_ant.groupby(p_ant["Data"].dt.day)["Valor"].sum() if len(p_ant) else pd.Series(dtype=float)
    ate_dia = ultimo if fechado else hoje.day
    dias, acum, acum_ant = [], 0.0, 0.0
    for d in range(1, 1 if per else ultimo + 1):
        acum_ant += float(por_dia_ant.get(d, 0.0))
        if d <= ate_dia:
            acum += float(por_dia.get(d, 0.0))
        dias.append({"d": d, "v": float(por_dia.get(d, 0.0)) if d <= ate_dia else None,
                     "acum": acum if d <= ate_dia else None, "acum_ant": acum_ant if len(p_ant) else None,
                     "parcial": (not fechado and d == hoje.day)})

    # convenios (relatorio 13329) + faturas em aberto do mesmo convenio
    abertos = {norm(x["nome"]): x for x in aberto["por_convenio"]}
    conv = []
    total_prod_conv = float(c["Produzido"].fillna(0).sum())
    for _, r in c.sort_values("Produzido", ascending=False).iterrows():
        ab = abertos.get(norm(r["Convênio"]), {})
        conv.append({"nome": r["Convênio"], "guias": r["Qtd. Guias"], "produzido": r["Produzido"],
                     "pct": (r["Produzido"] / total_prod_conv * 100) if total_prod_conv else 0.0,
                     "recebido": r["Recebido"], "glosa": r["Glosa"], "saldo": r["A Receber (Saldo)"],
                     "aberto": ab.get("valor"), "vencido": ab.get("vencido_valor")})
    recebido_conv = float(c["Recebido"].fillna(0).sum())
    glosa = float(c["Glosa"].fillna(0).sum())

    pagadores = pc.agrupar(p, "Operadora", "Valor", top=9, outros="Demais convênios")
    unidades = pc.agrupar(p.assign(U=p["Unidade"].map(pc.nome_curto_unidade)), "U", "Valor")
    categorias = pc.agrupar(p, "Categoria", "Valor", top=8, outros="Demais categorias")
    procs = (p.groupby("Procedimento")
             .agg(qtd=("Quantidade", "sum"), receita=("Valor", "sum"), categoria=("Categoria", "first"))
             .sort_values("receita", ascending=False).head(10).reset_index())

    # conferencia: receita de convenios no #26 x produzido do #13329
    conv_26 = float(p.loc[p["Operadora"].map(norm) != PARTICULAR, "Valor"].sum())
    conferencia = {"relatorio26": conv_26, "relatorio13329": total_prod_conv,
                   "diferenca": conv_26 - total_prod_conv,
                   "diferenca_pct": ((conv_26 - total_prod_conv) / total_prod_conv * 100) if total_prod_conv else None}

    # recebido de convenio: olha o proprio mes se ja fechou; senao, o mes anterior
    ref = c if fechado else ctrl[ctrl[k.COL_MES] == ym_ant]
    ref_ym = ym if fechado else ym_ant
    rot_ref = rot_m if fechado else rot_m_ant
    ref_prod, ref_rec = float(ref["Produzido"].fillna(0).sum()), float(ref["Recebido"].fillna(0).sum())

    # funil produzido -> faturado -> enviado -> recebido (competencia = o mes escolhido; a referencia segue a mesma regra do "recebido")
    funil = montar_funil(ym, fat, c)
    funil_ref = funil if fechado else montar_funil(ym_ant, fat, ctrl[ctrl[k.COL_MES] == ym_ant])

    alertas = []
    if aberto["vencido_qtd"]:
        alertas.append({"nivel": "critico", "titulo": "Faturas vencidas e ainda não baixadas", "itens": aberto["vencidas_itens"],
                        "texto": f"<b>{aberto['vencido_qtd']}</b> fatura(s) somando <b>{pc_brl(aberto['vencido_valor'])}</b> já passaram do vencimento"
                                 f" (a mais antiga há <b>{aberto['maior_atraso']}</b> dias). Veja a lista em “Faturas em aberto”."})
    if ref_prod > 0 and ref_rec / ref_prod < LIMITE_RECEBIDO_BAIXO:
        alertas.append({"nivel": "atencao", "titulo": "Quase nada de convênio aparece como recebido",
                        "itens": gp.tabela(["Convênio", "Produzido", "Recebido"],
                                           [[r["Convênio"], gp.reais(r["Produzido"]), gp.reais(r["Recebido"])] for _, r in ref.sort_values("Produzido", ascending=False).iterrows() if (r["Produzido"] or 0) > 0],
                                           numericas=(1, 2)),
                        "texto": f"Em {rot_ref} foram produzidos <b>{pc_brl(ref_prod)}</b> com convênios e só <b>{pc_brl(ref_rec)}</b> "
                                 f"({ref_rec / ref_prod * 100:.1f}%) constam como recebidos no Klingo. Confira se as baixas dos convênios estão sendo lançadas."})
    if glosa > 0 and total_prod_conv:
        alertas.append({"nivel": "atencao", "titulo": "Glosa registrada",
                        "itens": gp.tabela(["Convênio", "Produzido", "Glosa"], [[x["nome"], gp.reais(x["produzido"]), gp.reais(x["glosa"])] for x in conv if (x["glosa"] or 0) > 0], numericas=(1, 2)),
                        "texto": f"<b>{pc_brl(glosa)}</b> glosados ({glosa / total_prod_conv * 100:.1f}% do produzido com convênios em {rot_m})."})
    if aberto["sem_valor"]:
        alertas.append({"nivel": "atencao", "titulo": "Faturas em aberto sem valor", "itens": aberto["sem_valor_itens"],
                        "texto": f"<b>{aberto['sem_valor']}</b> fatura(s) estão com valor bruto vazio ou zero, o que reduz o total “em aberto” mostrado."})
    if variacao is not None and variacao <= -LIMITE_VARIACAO:
        alertas.append({"nivel": "atencao", "titulo": "Receita abaixo do mês anterior",
                        "texto": f"A receita está <b>{abs(variacao):.1f}% abaixo</b> de {ref_txt}."})
    if conferencia["diferenca_pct"] is not None and abs(conferencia["diferenca_pct"]) > 2:
        alertas.append({"nivel": "atencao", "titulo": "Relatórios de produção não batem",
                        "texto": f"A receita de convênios do relatório de Faturamento ({pc_brl(conv_26)}) difere do produzido do relatório de Produção por Convênio ({pc_brl(total_prod_conv)}) "
                                 f"em {conferencia['diferenca_pct']:+.1f}%."})
    if variacao is not None and variacao >= LIMITE_VARIACAO:
        alertas.append({"nivel": "ok", "titulo": "Receita acima do mês anterior",
                        "texto": f"A receita está <b>{variacao:.1f}% acima</b> de {ref_txt}."})
    top3 = sum(x["pct"] for x in conv[:3])
    if len(conv) >= 3:
        nomes = ", ".join(html.escape(str(x["nome"])) for x in conv[:3])
        alertas.append({"nivel": "info", "titulo": "Concentração em poucos convênios",
                        "texto": f"Os 3 maiores ({nomes}) respondem por <b>{top3:.0f}%</b> do produzido com convênios."})
    if receita:
        alertas.append({"nivel": "info", "titulo": "Mix de pagadores",
                        "texto": f"Particular: <b>{particular / receita * 100:.0f}%</b> da receita produzida · Convênios: <b>{(receita - particular) / receita * 100:.0f}%</b>."})
    alertas += alertas_faturas(fg, funil_ref, rot_ref)
    ordem = {"critico": 0, "atencao": 1, "ok": 2, "info": 3}
    alertas.sort(key=lambda a: ordem[a["nivel"]])
    gp.anotar("faturamento", alertas, per.chave if per else ym)

    return {
        "rotulo": rot, "fechado": fechado, "tem_dados": bool(len(p)), "ym_ant": ym_ant,        "ultimo_registro": p["Data"].max().strftime("%d/%m/%Y %H:%M") if len(p) else None,
        "kpi": {"receita": receita, "procedimentos": qtd, "pacientes": pacientes,
                "ticket": receita / qtd if qtd else None, "particular": particular,
                "particular_pct": particular / receita * 100 if receita else None,
                "variacao": variacao, "ref_txt": ref_txt, "ritmo": ritmo, "projecao": projecao,
                "uteis_total": len(uteis), "uteis_completos": completos,
                "produzido_conv": total_prod_conv, "recebido_conv": recebido_conv, "glosa": glosa,
                "ref_ym": ref_ym, "ref_rotulo": rot_ref, "ref_prod": ref_prod, "ref_rec": ref_rec},
        "dias": dias, "rotulo_ant": rot_ant, "tem_ant": bool(len(p_ant)),
        "pagadores": pagadores, "unidades": unidades, "categorias": categorias,
        "procedimentos": [{"nome": r["Procedimento"], "categoria": r["categoria"], "qtd": r["qtd"], "receita": r["receita"],
                           "ticket": r["receita"] / r["qtd"] if r["qtd"] else None} for _, r in procs.iterrows()],
        "convenios": conv, "conferencia": conferencia, "alertas": alertas,
        "funil": {x: funil[x] for x in ("tem", "produzido", "faturado", "a_enviar")},   # o proprio mes (so o resumo)
        "funil_ref": {"ym": ref_ym, "rotulo": rot_ref, **funil_ref},      # mes fechado de referencia: o proprio mes ou o anterior
    }


def pc_brl(v: float) -> str:
    """R$ no padrao brasileiro, em texto (usado nas frases dos alertas)."""
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


COLS_CONTROLE_SOMA = ["Qtd. Guias", "Produzido", "Recebido", "Glosa", "Glosa Acatada", "A Receber (Saldo)"]


def somar_convenios(c: pd.DataFrame) -> pd.DataFrame:
    """Controle por convenio: o mesmo convenio em varios meses do periodo vira uma linha so (soma das colunas de valor)."""
    if not len(c):
        return c
    soma = [x for x in COLS_CONTROLE_SOMA if x in c.columns]
    outras = {x: "first" for x in c.columns if x not in soma + [k.COL_MES, "Convênio"]}
    return c.groupby([k.COL_MES, "Convênio"], as_index=False, dropna=False).agg({**{x: (lambda s: s.sum(min_count=1)) for x in soma}, **outras})


def montar_periodo(per: pc.Periodo, prod, ctrl, aberto, hoje, cfg, fat, fg) -> dict:
    """Varios meses juntos, com a mesma conta de um mes (ver pc.reagrupar).
    Com o ultimo mes ainda aberto, "recebido" e "do produzido a fatura" olham os meses ja fechados do proprio periodo (num mes aberto
    olham o mes anterior): sem isso o periodo mostraria o recebido e o funil de um periodo anterior que pode nem ter dados."""
    atual = hoje.strftime("%Y-%m")
    ref = None
    if per.fim >= atual:
        fechados = [m for m in per.yms if m < atual]
        ref = pc.Periodo(fechados[0], fechados[-1]) if fechados else None
    prod2 = pc.reagrupar(prod, k.COL_MES, per, datacol="Data")
    ctrl2 = somar_convenios(pc.reagrupar(ctrl, k.COL_MES, per, ref=ref))   # so existe por mes: num recorte de dias entra o mes inteiro
    fat2 = pc.reagrupar(fat, "_comp", per, ref=ref) if len(fat) else fat   # competencia = mes em que comeca o periodo faturado: so existe por mes
    return montar_mes(per.fim, prod2, ctrl2, aberto, hoje, cfg, fat2, fg, per=per, ref=ref)


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    cfg = json.loads((gd.METAS).read_text(encoding="utf-8"))
    defn = k.ler_definicao(PASTA)
    abas = k.carregar(PASTA)
    prod, ctrl, ab = abas[ABA_PROD], abas[ABA_CTRL], abas[ABA_ABERTO]
    fat = preparar_faturas(abas[ABA_FAT])
    hoje = date.today()
    aberto = montar_aberto(ab, hoje) if len(ab) else {"total": 0, "qtd": 0, "sem_valor": 0, "vencido_valor": 0, "vencido_qtd": 0,
                                                      "maior_atraso": 0, "faixas": [], "por_convenio": [], "lista_vencidas": [],
                                                      "sem_valor_itens": gp.tabela([], []), "vencidas_itens": gp.tabela([], [])}
    fg = montar_faturas(fat, hoje)
    conf = conferir_abertas(fat, ab)
    meses = {}
    existentes = sorted({m for m in prod.get(k.COL_MES, pd.Series(dtype=str)).dropna().unique() if m >= defn["primeiro_mes"]})
    for ym in existentes:
        meses[ym] = montar_mes(ym, prod, ctrl, aberto, hoje, cfg, fat, fg)

    mes_padrao = hoje.strftime("%Y-%m") if hoje.strftime("%Y-%m") in meses else (max(meses) if meses else None)
    per, info = pc.periodo_pedido(de, ate, meses)
    if per:
        mes_padrao = per.chave
        if not per.unico:
            pc.acrescentar_periodo(meses, per, lambda p: montar_periodo(p, prod, ctrl, aberto, hoje, cfg, fat, fg))
            if per.exato:
                info["notas"] = ["Controle por Convênio (produzido, recebido e glosa por convênio) e o funil de faturas só existem por mês: nesses blocos entram os meses "
                                 "inteiros que o período toca. Receita, procedimentos, pacientes e dias úteis seguem exatamente os dias escolhidos."]

    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else datetime.now()
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()),
        "hoje": hoje.isoformat(),
        "mes_padrao": mes_padrao, "periodo": info,
        "meses": meses, "aberto": aberto, "faturas": fg, "conferencia_faturas": conf,
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
