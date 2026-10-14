"""Indicadores: os 16 indicadores de Produção/Faturamento, Financeiro e Glosas, com a origem de cada um.

Junta o que o Klingo entrega nos relatorios de Faturamento (#26, #13329, #13328, #13355), Financeiro (#13297, #13295)
e nos relatorios novos desta pasta (#13374 guias, #13375 glosas e recursos, #13376 baixas). Quando um dado ainda nao
existe no Klingo, o indicador aparece como "sem fonte" e diz o que falta, em vez de mostrar zero.

Uso:  python gerar_indicadores.py             so regenera o dashboard com o que ja esta nas planilhas
      python gerar_indicadores.py --forcar    consulta o Klingo agora (como o botao) e regenera
"""
import html
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
sys.path.insert(0, str(PASTA.parent / "Faturamento"))
sys.path.insert(0, str(PASTA.parent / "Financeiro"))
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import guia_pendencias as gp  # noqa: E402
import gerar_dashboard as gd  # noqa: E402  (norm das Metas)

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Indicadores.html"
ABA_GUIAS, ABA_GLOSAS, ABA_BAIXAS = "Guias", "Glosas e Recursos", "Baixas"
PARTICULAR = "PARTICULAR"
A_ENVIAR, ENVIADA, MOVIMENTADA, CANCELADA = "A Enviar", "Enviada", "Movimentada", "Cancelada"
ENVIADAS = (ENVIADA, MOVIMENTADA)

# classes de confianca de cada indicador (aparecem como etiqueta no cartao)
DIRETO, DERIVADO, PROXY, SEM_FONTE = "direto", "derivado", "proxy", "semfonte"
ROTULO_CLASSE = {DIRETO: "Direto", DERIVADO: "Derivado", PROXY: "Aproximação", SEM_FONTE: "Sem fonte"}


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    """Baixa os relatorios desta pasta e, em seguida, os de Faturamento e Financeiro (que os indicadores tambem usam)."""
    partes = [k.atualizar(PASTA, forcar=forcar, historico=historico)]
    import gerar_faturamento as gfat  # noqa: E402  (so aqui: o menu Indicadores nao depende deles para abrir)
    import gerar_financeiro as gfin  # noqa: E402
    for modulo in (gfat, gfin):
        partes.append(modulo.atualizar(forcar=forcar, historico=historico))
    msg = " ".join(p["mensagem"] for p in partes)
    return {"atualizou": any(p.get("atualizou") for p in partes), "mensagem": msg, "avisos": [a for p in partes for a in p.get("avisos", [])]}


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def nz(v) -> float:
    return 0.0 if pd.isna(v) else float(v)


def norm(s) -> str:
    return gd.norm(s)


def ym_de(serie: pd.Series) -> pd.Series:
    return serie.dt.strftime("%Y-%m")


def carregar_outra(pasta: str) -> dict[str, pd.DataFrame]:
    try:
        return k.carregar(PASTA.parent / pasta)
    except Exception:
        return {}


def tem_colunas(df: pd.DataFrame, *colunas: str) -> bool:
    return len(df) > 0 and all(c in df.columns for c in colunas)


# ---------------------------------------------------------------- guias (#13374)
def preparar_guias(g: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por guia. O relatorio repete a guia (uma vez por procedimento), por isso se conta por 'Guia - Id'."""
    if not tem_colunas(g, "Guia - Id", "Guia - Status - Descrição", "Guia - Data"):
        return g.iloc[0:0]
    x = g.sort_values(["Guia - Id", "Fatura - Id"], na_position="first").drop_duplicates("Guia - Id", keep="last").copy()
    x["_ym"] = ym_de(x["Guia - Data"])
    x["_st"] = x["Guia - Status - Descrição"].fillna("(sem situação)")
    return x


# ---------------------------------------------------------------- glosas e recursos (#13375): colunas descobertas pelo nome
def achar(df: pd.DataFrame, tem: list[str], nao: list[str] | None = None) -> str | None:
    for c in df.columns:
        n = norm(c)
        if all(t in n for t in tem) and not any(x in n for x in (nao or [])):
            return c
    return None


def ler_glosas(gl: pd.DataFrame) -> dict:
    """Totais da aba 'Glosas e Recursos' quando o relatorio ja traz dados; devolve as colunas usadas para a pessoa conferir."""
    vazio = {"tem": False, "linhas": 0, "colunas": {}}
    if not len(gl) or len([c for c in gl.columns if c not in (k.COL_MES, k.COL_EM)]) == 0:
        return vazio
    papeis = {
        "glosado": achar(gl, ["GLOSAD", "VALOR"], ["RECURS", "DEFER", "PERDA"]) or achar(gl, ["VALOR", "GLOSA"], ["RECURS", "DEFER", "PERDA", "PRAZO", "DATA"]),
        "recursado": achar(gl, ["RECURSAD", "VALOR"]) or achar(gl, ["VALOR", "RECURSO"], ["DEFER", "PERDA"]),
        "deferido": achar(gl, ["DEFERID"]) or achar(gl, ["RECUPERAD"]),
        "perda": achar(gl, ["PERDA"]) or achar(gl, ["ACATAD"]),
    }
    def soma(papel):
        c = papeis[papel]
        return float(pd.to_numeric(gl[c], errors="coerce").fillna(0).sum()) if c else None
    return {"tem": True, "linhas": int(len(gl)), "colunas": {p: c for p, c in papeis.items() if c},
            "glosado": soma("glosado"), "recursado": soma("recursado"), "deferido": soma("deferido"), "perda": soma("perda")}


# ---------------------------------------------------------------- faturas emitidas (#13355)
def preparar_faturas(fat: pd.DataFrame) -> pd.DataFrame:
    if not tem_colunas(fat, "Fatura - Status", "Fatura - Valor", "Fatura - Data Inicial"):
        return fat.iloc[0:0]
    f = fat.copy()
    f["_op"] = f["Operadora - Nome"].fillna("(sem operadora)").astype(str)
    f["_st"] = f["Fatura - Status"]
    f["_valor"] = f["Fatura - Valor"]
    f["_comp"] = ym_de(f["Fatura - Data Inicial"])
    return f


def card(id_, bloco, nome, classe, valor, formato, sub, fonte, base, ajuda=None):
    """Um indicador. formato: 'brl' (dinheiro) ou 'qtd' (contagem); valor None = nao ha como calcular."""
    return {"id": id_, "bloco": bloco, "nome": nome, "classe": classe, "classe_rotulo": ROTULO_CLASSE[classe],
            "valor": valor, "formato": formato, "sub": sub, "fonte": fonte, "base": base, "ajuda": ajuda}


def montar_mes(ym: str, hoje: date, d: dict, per: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses: cada filtro "do mes" vira "dos meses do periodo" (a conta e a mesma, sobre as linhas de todos)."""
    g, f, ab, prod, ctrl, part, baixas, glosas = d["g"], d["f"], d["ab"], d["prod"], d["ctrl"], d["part"], d["baixas"], d["glosas"]
    yms = per.yms if per else [ym]
    pp = per or pc.Periodo(ym, ym)   # os dias do mes (ou do periodo): cada filtro "do mes" olha a data de cada linha
    rot = per.rotulo if per else pc.rotulo_mes(ym)
    rot_m = pp.meses_inteiros.rotulo   # os blocos por competencia (faturas, recebido por convenio) so existem por mes
    hoje_ts = pd.Timestamp(hoje)
    gm = g[pp.dentro(g["Guia - Data"])] if len(g) else g
    gm_ativas = gm[gm["_st"] != "Cancelada"] if len(gm) else gm

    # ---------------------------------------------------------------- bloco 1: producao e faturamento
    if pp.exato and tem_colunas(prod, "Data", "Valor"):
        p = prod[pp.dentro(prod["Data"])]
    else:
        p = prod[prod[k.COL_MES].isin(yms)] if tem_colunas(prod, k.COL_MES, "Valor") else prod.iloc[0:0]
    produzido = float(p["Valor"].sum()) if len(p) else 0.0
    particular = float(p.loc[p["Operadora"].map(norm) == PARTICULAR, "Valor"].sum()) if len(p) else 0.0
    c = ctrl[ctrl[k.COL_MES].isin(yms)] if tem_colunas(ctrl, k.COL_MES) else ctrl.iloc[0:0]
    prod_conv = float(c["Produzido"].fillna(0).sum()) if len(c) else 0.0
    cards = []
    cards.append(card("produzido", 1, "Produzido", DIRETO, produzido, "brl",
                      f"Convênios <b>{brl(produzido - particular)}</b> · particular <b>{brl(particular)}</b>" + (f" · <b>{len(gm_ativas):,}</b> guias".replace(",", ".") if len(gm_ativas) else ""),
                      "Faturamento · Receita Produzida (Valor); convênios conferidos no relatório de Produção por Convênio", f"Competência: {rot}"))

    fm = f[f["_comp"].isin(yms)] if len(f) else f   # competencia = mes em que comeca o periodo faturado: so existe por mes
    fa = fm[fm["_st"] == A_ENVIAR] if len(fm) else fm
    guias_ef = int((gm_ativas["_st"] == "Em Fatura").sum()) if len(gm_ativas) else 0
    cards.append(card("pre_fatura", 1, "Pré-fatura", PROXY, float(fa["_valor"].fillna(0).sum()) if len(fa) else 0.0, "brl",
                      f"<b>{len(fa)}</b> fatura(s) “A enviar” · <b>{guias_ef:,}</b> guia(s) “Em fatura”".replace(",", "."),
                      "Faturas Emitidas · status A Enviar (FA); guias “Em fatura” do relatório de Guias",
                      f"Competência: {rot_m}", "O Klingo não tem uma etapa de “auditoria interna”: “A enviar” é fatura emitida e ainda não transmitida."))

    fe = fm[fm["_st"].isin(ENVIADAS)] if len(fm) else fm
    sem_prot = fe[fe["Fatura - Envio - Protocolo"].isna()] if len(fe) else fe
    guias_ft = int(gm_ativas["_st"].isin(["Faturada", "Recebida"]).sum()) if len(gm_ativas) else 0
    cards.append(card("faturado", 1, "Faturado", DERIVADO, float(fe["_valor"].fillna(0).sum()) if len(fe) else 0.0, "brl",
                      f"<b>{len(fe)}</b> fatura(s) enviadas, <b>{len(fe) - len(sem_prot)}</b> com protocolo · <b>{guias_ft:,}</b> guia(s)".replace(",", ".")
                      + (f" · sem protocolo: <b>{brl(float(sem_prot['_valor'].fillna(0).sum()))}</b>" if len(sem_prot) else ""),
                      "Faturas Emitidas · status Enviada + Movimentada; protocolo como sinal de envio por XML", f"Competência: {rot_m}"))

    pend = gm[gm["_st"] == "Pendente Recepção"] if len(gm) else gm
    pend_total = int((g["_st"] == "Pendente Recepção").sum()) if len(g) else 0
    cards.append(card("pendente", 1, "Pendente", DIRETO if len(g) else SEM_FONTE, float(len(pend)) if len(g) else None, "qtd",
                      (f"guia(s) “Pendente Recepção” em {rot}; <b>{pend_total}</b> no total, de todos os meses. O relatório não traz o valor da guia."
                       if len(g) else "O relatório de Guias ainda não tem dados."),
                      "Guias: situação Pendente Recepção e “Pendência / Motivo”", f"Competência: {rot}",
                      "Falta a coluna de valor da guia no relatório de Guias para somar em reais."))

    prot = int((gm_ativas["_st"] == "Protocolada").sum()) if len(gm_ativas) else 0
    cards.append(card("bloqueado", 1, "Bloqueado", SEM_FONTE, None, "qtd",
                      "O Klingo não registra guia retida pela operadora."
                      + (f" Candidata a confirmar: <b>{prot}</b> guia(s) “Protocolada” em {rot}." if prot else ""),
                      "Sem relatório no Klingo: a informação está no portal da operadora", "Posição de hoje"))

    # ---------------------------------------------------------------- bloco 2: financeiro
    ativas = fm[fm["_st"] != CANCELADA] if len(fm) else fm
    cards.append(card("fatura_mes", 2, "Fatura do período" if per else "Fatura do mês", DERIVADO, float(ativas["_valor"].fillna(0).sum()) if len(ativas) else 0.0, "brl",
                      f"<b>{len(ativas)}</b> fatura(s): a enviar <b>{brl(float(fa['_valor'].fillna(0).sum())) if len(fa) else 'R$ 0,00'}</b> · enviadas <b>{brl(float(fe['_valor'].fillna(0).sum())) if len(fe) else 'R$ 0,00'}</b>"
                      + (f" · {int((fm['_st'] == CANCELADA).sum())} cancelada(s), fora da soma" if len(fm) and (fm["_st"] == CANCELADA).any() else ""),
                      "Faturas Emitidas · Fatura - Valor (sem canceladas)", f"Competência: {rot_m}"))

    ab_ok = tem_colunas(ab, "Vencimento", "Valor Bruto")
    aberto_hoje = ab[ab["Vencimento"].dt.normalize() >= hoje_ts] if ab_ok else ab
    vencidas = ab[ab["Vencimento"].dt.normalize() < hoje_ts] if ab_ok else ab
    ab_mes = ab[pp.dentro(ab["Vencimento"])] if ab_ok else ab
    cards.append(card("em_aberto", 2, "Em aberto", DIRETO, float(aberto_hoje["Valor Bruto"].fillna(0).sum()) if ab_ok else 0.0, "brl",
                      f"<b>{len(aberto_hoje)}</b> fatura(s) a vencer · vencidas sem baixa <b>{brl(float(vencidas['Valor Bruto'].fillna(0).sum())) if ab_ok else 'R$ 0,00'}</b> ({len(vencidas)}) · vencem em {rot}: <b>{brl(float(ab_mes['Valor Bruto'].fillna(0).sum())) if ab_ok else 'R$ 0,00'}</b>",
                      "Faturas em Aberto (Valor Bruto, Vencimento)", "Posição de hoje"))

    pt_ok = tem_colunas(part, "Data de Recebimento", "Valor Líquido", "Data do Atendimento")
    prev_part = part[pp.dentro(part["Data de Recebimento"]) & (part["Data de Recebimento"].dt.normalize() > hoje_ts)] if pt_ok else part
    prev_conv = float(ab_mes["Valor Bruto"].fillna(0).sum()) if ab_ok else 0.0
    prev_p = float(prev_part["Valor Líquido"].fillna(0).sum()) if pt_ok else 0.0
    cards.append(card("previsto", 2, "Previsto pagamento", PROXY, prev_conv + prev_p, "brl",
                      f"Convênios <b>{brl(prev_conv)}</b> (vencimento da fatura) · particular <b>{brl(prev_p)}</b> (parcelas de cartão ainda por cair)",
                      "Faturas em Aberto · Vencimento + Recebimento Particular · Data de Recebimento futura", f"Para entrar em {rot}",
                      "O vencimento vem do prazo cadastrado no convênio, não do calendário de pagamento da operadora."))

    cards.append(card("antecipado", 2, "Antecipado", SEM_FONTE, None, "brl",
                      "Nenhum relatório traz antecipação de recebíveis (o relatório de Baixas não tem campo de antecipação).",
                      "Falta no Klingo: campo “antecipado” e valor antecipado no relatório de baixas", "—"))

    rec_conv = float(c["Recebido"].fillna(0).sum()) if len(c) else 0.0
    pt_rec = part[pp.dentro(part["Data do Atendimento"]) & (part["Data de Recebimento"].dt.normalize() <= hoje_ts)] if pt_ok else part
    rec_part = float(pt_rec["Valor Líquido"].fillna(0).sum()) if pt_ok else 0.0
    bx_ok = tem_colunas(baixas, "Baixa - Conciliado", "Valor Bruto")
    if bx_ok:
        conc = baixas[baixas["Baixa - Conciliado"].astype(str).str.upper() == "S"]
        conc_txt = (f"Conciliadas no Klingo: <b>{len(conc)} de {len(baixas)}</b> baixas ({brl(float(conc['Valor Bruto'].fillna(0).sum()))} de {brl(float(baixas['Valor Bruto'].fillna(0).sum()))})")
    else:
        conc_txt = "Conciliação: relatório de Baixas sem dados"
    cards.append(card("recebido", 2, "Recebido", DERIVADO, rec_conv + rec_part, "brl",
                      f"Convênios <b>{brl(rec_conv)}</b> · particular já liquidado <b>{brl(rec_part)}</b>. {conc_txt}",
                      "Produção por Convênio · Recebido (convênios) + Recebimento Particular · Valor Líquido com recebimento até hoje (particular); conciliação do relatório de Baixas",
                      f"Competência: {rot_m}",
                      "“Liquidado” é o que foi baixado; “conciliado” depende de marcar a baixa como conciliada no Klingo (hoje nenhuma está)."))

    faturado_conv = float(fe["_valor"].fillna(0).sum()) if len(fe) else 0.0
    acatada_ctrl = float(ctrl["Glosa Acatada"].fillna(0).sum()) if tem_colunas(ctrl, "Glosa Acatada") else 0.0
    gl_mes_acat = float(c["Glosa Acatada"].fillna(0).sum()) if len(c) and "Glosa Acatada" in c else 0.0
    saldo_conv = faturado_conv - rec_conv - gl_mes_acat
    a_rec_part = float(part[pp.dentro(part["Data do Atendimento"]) & (part["Data de Recebimento"].dt.normalize() > hoje_ts)]["Valor Líquido"].fillna(0).sum()) if pt_ok else 0.0
    cards.append(card("saldo", 2, "A receber / Saldo", DERIVADO, saldo_conv + a_rec_part, "brl",
                      f"Convênios: faturado <b>{brl(faturado_conv)}</b> − recebido <b>{brl(rec_conv)}</b> − glosa acatada <b>{brl(gl_mes_acat)}</b> = <b>{brl(saldo_conv)}</b> · particular a cair <b>{brl(a_rec_part)}</b>",
                      "Faturado − Recebido − Glosa acatada, mais parcelas futuras do relatório de Recebimento Particular",
                      f"Competência: {rot_m}",
                      "O campo “A Receber (Saldo)” do relatório de Produção por Convênio só vem preenchido para um convênio; por isso o saldo é calculado aqui."))

    # ---------------------------------------------------------------- bloco 3: glosas (acumulado, de todas as competencias)
    gl_total_ctrl = float(ctrl["Glosa"].fillna(0).sum()) if tem_colunas(ctrl, "Glosa") else 0.0
    gl_guias = float(g["Movimentação Guia - Valor Glosado"].fillna(0).sum()) if tem_colunas(g, "Movimentação Guia - Valor Glosado") else 0.0
    gl = glosas
    nota_arq = ("O relatório de Glosas e Recursos está ligado, mas ainda não tem nenhuma linha (nenhuma glosa lançada no Klingo). Aparece aqui quando houver." if not gl["tem"] else "")
    total = gl["glosado"] if (gl["tem"] and gl.get("glosado") is not None) else max(gl_total_ctrl, gl_guias)
    cls_total = DIRETO if (gl["tem"] and gl.get("glosado") is not None) else PROXY
    cards.append(card("glosa_total", 3, "Glosa total", cls_total, total, "brl",
                      (f"Produção por Convênio: <b>{brl(gl_total_ctrl)}</b> · guias: <b>{brl(gl_guias)}</b>. " if not gl["tem"] else "") + (nota_arq or f"{gl['linhas']} linha(s) no relatório de Glosas e Recursos."),
                      "Glosas e Recursos · valor glosado; sem ele, Produção por Convênio Glosa e Guias Valor Glosado", "Acumulado desde set/2026",
                      "Hoje o Klingo não registra nenhuma glosa." if total == 0 else None))

    rec_ok = gl["tem"] and gl.get("recursado") is not None
    cards.append(card("glosa_recursada", 3, "Glosa recursada", DIRETO if rec_ok else SEM_FONTE, gl["recursado"] if rec_ok else None, "brl",
                      (f"{gl['linhas']} linha(s) no relatório de Glosas e Recursos." if rec_ok else nota_arq or "O relatório de Glosas e Recursos não tem uma coluna de valor recursado."),
                      "Glosas e Recursos · valor recursado", "Acumulado desde set/2026"))
    sem_rec = (gl["glosado"] - gl["recursado"]) if (rec_ok and gl.get("glosado") is not None) else None
    cards.append(card("glosa_sem_recurso", 3, "Glosa sem recurso", DERIVADO if sem_rec is not None else SEM_FONTE, sem_rec, "brl",
                      "Glosa total − glosa recursada." if sem_rec is not None else "Depende da glosa recursada.",
                      "Glosa total − Glosa recursada", "Acumulado desde set/2026",
                      "Só é “perda sem recurso” depois do prazo de recurso da operadora." if sem_rec is not None else None))
    rcb_ok = gl["tem"] and gl.get("deferido") is not None
    cards.append(card("glosa_recebida", 3, "Glosa recebida", DIRETO if rcb_ok else SEM_FONTE, gl["deferido"] if rcb_ok else None, "brl",
                      "Valor deferido nos recursos." if rcb_ok else nota_arq or "O relatório de Glosas e Recursos não tem uma coluna de valor deferido/recuperado.",
                      "Glosas e Recursos · valor deferido", "Acumulado desde set/2026"))
    acat_ok = gl["tem"] and gl.get("perda") is not None
    cards.append(card("glosa_acatada", 3, "Glosa acatada", DIRETO if acat_ok else PROXY, gl["perda"] if acat_ok else acatada_ctrl, "brl",
                      "Perda definitiva no relatório de Glosas e Recursos." if acat_ok else f"Coluna “Glosa Acatada” do relatório de Produção por Convênio. Ela não separa “sem recurso” de “recurso indeferido”.",
                      "Glosas e Recursos · perda definitiva; sem ele, Produção por Convênio Glosa Acatada", "Acumulado desde set/2026"))

    # ---------------------------------------------------------------- detalhes do mes
    por_sit = []
    if len(gm):
        ordem = ["Disponível", "A Faturar", "Em Fatura", "Faturada", "Protocolada", "Recebida", "Pendente Recepção", "Cancelada"]
        cont = gm["_st"].value_counts()
        cor = {"Pendente Recepção": "var(--crit)", "Cancelada": "var(--muted)", "Recebida": "var(--good)"}
        for s in sorted(cont.index, key=lambda x: ordem.index(x) if x in ordem else 99):
            por_sit.append({"nome": s, "qtd": int(cont[s]), "cor": cor.get(s, "var(--s1)")})
    motivos = []
    if len(pend) and "Guia - Pendência / Motivo Glosa" in pend:
        for m, n in pend["Guia - Pendência / Motivo Glosa"].fillna("(sem motivo)").value_counts().head(10).items():
            motivos.append({"nome": str(m), "qtd": int(n)})
    lista_pend = []
    if len(pend):
        for _, r in pend.sort_values("Guia - Data").head(15).iterrows():
            lista_pend.append({"operadora": r["Operadora - Nome"], "guia": str(r["Guia - Número da Guia do Prestador"]), "data": r["Guia - Data"],
                               "paciente": r["Paciente - Nome"], "motivo": r.get("Guia - Pendência / Motivo Glosa")})
    convenios = []
    nomes = {}
    for _, r in c.iterrows():
        nomes[norm(r["Convênio"])] = r["Convênio"]
    for op in fm["_op"].unique() if len(fm) else []:
        nomes.setdefault(norm(op), op)
    for ch, nome in nomes.items():
        rc = c[c["Convênio"].map(norm) == ch]
        ff = fm[(fm["_op"].map(norm) == ch) & fm["_st"].isin(ENVIADAS)] if len(fm) else fm
        fp = fm[(fm["_op"].map(norm) == ch) & (fm["_st"] == A_ENVIAR)] if len(fm) else fm
        pr, rcb = float(rc["Produzido"].fillna(0).sum()), float(rc["Recebido"].fillna(0).sum())
        fat_v, pre_v = float(ff["_valor"].fillna(0).sum()) if len(ff) else 0.0, float(fp["_valor"].fillna(0).sum()) if len(fp) else 0.0
        ga = float(rc["Glosa Acatada"].fillna(0).sum()) if "Glosa Acatada" in rc else 0.0
        if pr or fat_v or pre_v or rcb:
            convenios.append({"nome": nome, "produzido": pr, "pre_fatura": pre_v, "faturado": fat_v, "recebido": rcb, "saldo": fat_v - rcb - ga})
    convenios.sort(key=lambda x: -x["produzido"])

    return {"rotulo": rot, "cards": cards, "por_situacao": por_sit, "pendentes_motivos": motivos, "pendentes_lista": lista_pend,
            "convenios": convenios, "guias_mes": int(len(gm_ativas)),
            "pend_total": pend_total, "tem_guias": bool(len(gm))}


def alertas_gerais(d: dict, glosas: dict, hoje: date) -> list[dict]:
    out = []
    g, f, baixas = d["g"], d["f"], d["baixas"]
    if len(g):
        pend = g[g["_st"] == "Pendente Recepção"]
        if len(pend):
            top = ", ".join(f"{html.escape(str(m))} ({n})" for m, n in pend["Guia - Pendência / Motivo Glosa"].fillna("(sem motivo)").value_counts().head(3).items())
            ops = ", ".join(f"{html.escape(str(o))} ({n})" for o, n in pend["Operadora - Nome"].value_counts().head(3).items())
            out.append({"nivel": "atencao", "titulo": "Guias pendentes de correção",
                        "itens": gp.tabela(["Guia (Id)", "Nº da guia (prestador)", "Data", "Convênio", "Paciente", "Pendência / motivo"],
                                           [[r["Guia - Id"], r["Guia - Número da Guia do Prestador"], gp.dbr(r["Guia - Data"]), r["Operadora - Nome"], r["Paciente - Nome"],
                                             r["Guia - Pendência / Motivo Glosa"]] for _, r in pend.sort_values("Guia - Data").iterrows()], total=len(pend), numericas=(0,)),
                        "texto": f"<b>{len(pend)}</b> guia(s) estão “Pendente Recepção” (todas as competências). Motivos mais comuns: {top}. Mais guias nas operadoras: {ops}."})
    if len(f):
        enviadas = f[f["_st"].isin(ENVIADAS)]
        sp = enviadas[enviadas["Fatura - Envio - Protocolo"].isna()]
        if len(sp):
            out.append({"nivel": "info", "titulo": "Faturas enviadas sem protocolo",
                        "itens": gp.tabela(["Fatura (Id)", "Convênio", "Status", "Enviada em", "Valor"],
                                           [[r["Fatura - Id"], r["_op"], r["_st"], gp.dbr(r["Fatura - Data de Envio"]), gp.reais(r["_valor"])]
                                            for _, r in sp.sort_values("Fatura - Data de Envio").iterrows()], total=len(sp), numericas=(0, 4)),
                        "texto": f"<b>{len(sp)}</b> fatura(s), <b>{brl(float(sp['_valor'].fillna(0).sum()))}</b>, constam como enviadas sem número de protocolo. "
                                 f"Elas contam como Faturado, mas não dá para confirmar o envio por XML."})
    if tem_colunas(baixas, "Baixa - Conciliado"):
        conc = int((baixas["Baixa - Conciliado"].astype(str).str.upper() == "S").sum())
        if conc == 0:
            out.append({"nivel": "info", "titulo": "Nenhuma baixa conciliada",
                        "texto": f"As {len(baixas)} baixas do relatório de Baixas estão como não conciliadas. “Recebido” aqui significa liquidado, não conciliado com o extrato."})
        if "Lançamento - Descrição" in baixas:
            out.append({"nivel": "info", "titulo": "O relatório de baixas mistura pagamentos e recebimentos",
                        "texto": "O relatório de Baixas não diz se a baixa é de receita ou de despesa (há honorários e folha junto com recebimentos). Para separar, inclua “Lançamento - Tipo” no relatório."})
    if not glosas["tem"]:
        out.append({"nivel": "info", "titulo": "Relatório de glosas e recursos ainda sem linhas",
                    "texto": "O relatório de Glosas e Recursos está ativo (filtro “Guia - Data”) e não devolveu nenhuma linha: o Klingo não tem glosa lançada. "
                             "Glosa recursada, sem recurso e recebida aparecem quando a primeira glosa for registrada; confira então se as colunas foram reconhecidas."})
    else:
        out.append({"nivel": "ok", "titulo": "Relatório de glosas e recursos lendo dados",
                    "texto": f"{glosas['linhas']} linha(s). Colunas reconhecidas: " + ", ".join(f"{p} ← {html.escape(c)}" for p, c in glosas["colunas"].items()) + "."})
    if len(g) and tem_colunas(d["ctrl"], "Recebido"):
        v_guias = float(g["Movimentação Guia - Valor Recebido"].fillna(0).sum())
        v_ctrl = float(d["ctrl"]["Recebido"].fillna(0).sum())
        if abs(v_guias - v_ctrl) > 0.01:
            out.append({"nivel": "atencao", "titulo": "Recebido das guias não bate com o relatório de Produção por Convênio",
                        "texto": f"Guias recebidas somam <b>{brl(v_guias)}</b> e o Controle por Convênio mostra <b>{brl(v_ctrl)}</b>."})
    out.append({"nivel": "info", "titulo": "Sem fonte no Klingo: Bloqueado e Antecipado",
                "texto": "Guia retida na operadora e antecipação de recebíveis não existem nos relatórios. Bloqueado só aparece no portal da operadora; "
                         "Antecipado precisa de um campo de antecipação no relatório de baixas."})
    return out


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    hoje = date.today()
    defn = k.ler_definicao(PASTA)
    proprias = k.carregar(PASTA)
    fat_abas, fin_abas = carregar_outra("Faturamento"), carregar_outra("Financeiro")
    vazio = pd.DataFrame()
    g = preparar_guias(proprias.get(ABA_GUIAS, vazio))
    d = {"g": g, "f": preparar_faturas(fat_abas.get("Faturas Emitidas", vazio)), "ab": fat_abas.get("Faturas em Aberto", vazio),
         "prod": fat_abas.get("Receita Produzida", vazio), "ctrl": fat_abas.get("Controle por Convênio", vazio),
         "part": fin_abas.get("Recebimento Particular", vazio), "baixas": proprias.get(ABA_BAIXAS, vazio),
         "glosas": ler_glosas(proprias.get(ABA_GLOSAS, vazio))}
    meses = {}
    ym_hoje = hoje.strftime("%Y-%m")
    for ym in k.meses_entre(defn["primeiro_mes"], ym_hoje):
        meses[ym] = montar_mes(ym, hoje, d)
    per, info = pc.periodo_pedido(de, ate, meses)
    if per and not per.unico:
        pc.acrescentar_periodo(meses, per, lambda p: montar_mes(p.fim, hoje, d, per=p))
        if per.exato:
            info["notas"] = ["O Controle por Convênio (produzido, recebido e glosa por convênio) e as faturas por competência só existem por mês: nesses valores entram os meses "
                             "inteiros que o período toca. Receita produzida, guias, vencimentos e recebimentos seguem exatamente os dias escolhidos."]
    alertas = alertas_gerais(d, d["glosas"], hoje) if (len(g) or len(d["f"]) or len(d["prod"])) else []
    ordem = {"critico": 0, "atencao": 1, "ok": 2, "info": 3}
    alertas.sort(key=lambda a: ordem[a["nivel"]])
    gp.anotar("indicadores", alertas)

    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else datetime.now()
    conciliacao = []
    if tem_colunas(d["baixas"], "Conta - Nome", "Baixa - Conciliado"):
        b = d["baixas"]
        for conta, gr in b.groupby("Conta - Nome", dropna=False):
            conciliacao.append({"conta": "(sem conta)" if pd.isna(conta) else str(conta), "baixas": int(len(gr)),
                                "conciliadas": int((gr["Baixa - Conciliado"].astype(str).str.upper() == "S").sum()),
                                "valor": float(gr["Valor Bruto"].fillna(0).sum())})
        conciliacao.sort(key=lambda x: -x["valor"])
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()), "hoje": hoje.isoformat(),
        "mes_padrao": per.chave if per else (ym_hoje if ym_hoje in meses else (max(meses) if meses else None)), "periodo": info,
        "meses": meses, "alertas": alertas, "conciliacao": conciliacao,
        "glosas_colunas": d["glosas"]["colunas"], "tem_dados": bool(len(g) or len(d["f"]) or len(d["prod"])),
        "guias_total": int(len(g)),
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
