"""Financeiro: atualiza a planilha a partir do Klingo e gera 'Dashboard Financeiro.html'.

Uso:  python gerar_financeiro.py             so regenera o dashboard com o que ja esta na planilha
      python gerar_financeiro.py --forcar    consulta o Klingo agora (como o botao) e regenera
      python gerar_financeiro.py --historico baixa de novo todos os meses desde o primeiro
"""
import html
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import gerar_dashboard as gd  # noqa: E402  (norm das Metas)
import guia_pendencias as gp  # noqa: E402

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Financeiro.html"
ABA_LANC, ABA_PART, ABA_CRED = "Lançamentos", "Recebimento Particular", "Créditos de Convênio"
MESES_A_FRENTE = 6
MIN_PARTICULAR_PCT = 80  # a partir de quanto % de receitas particulares vale avisar que convenio nao entra no Financeiro


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    return k.atualizar(PASTA, forcar=forcar, historico=historico)


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ym_de(serie: pd.Series) -> pd.Series:
    return serie.dt.strftime("%Y-%m")


def lista_despesas(df: pd.DataFrame, hoje: date, limite: int, vencidas: bool) -> list[dict]:
    d = df.copy()
    d["_dias"] = d["Vencimento"].map(lambda x: (hoje - x.date()).days if pd.notna(x) else None)
    d = d.sort_values("Valor", ascending=False) if vencidas else d.sort_values(["Vencimento", "Valor"], ascending=[True, False])
    return [{"id": r["Lançamento"], "historico": r["Histórico"], "categoria": r["Categoria"],
             "empresa": pc.nome_curto_unidade(r["Empresa"]), "vencimento": r["Vencimento"], "dias": r["_dias"],
             "valor": r["Valor"]} for _, r in d.head(limite).iterrows()]


def itens_despesas(df: pd.DataFrame, hoje: date, vencidas: bool, com_atraso: bool = False) -> dict:
    """Tabela 'quais sao' dos lancamentos: vencidas=True ordena pelo maior valor; senao, pelo vencimento mais proximo."""
    colunas = ["Lançamento", "Histórico", "Categoria", "Empresa", "Vencimento"] + (["Dias de atraso"] if com_atraso else []) + ["Valor"]
    linhas = [[x["id"], x["historico"], x["categoria"], x["empresa"], gp.dbr(x["vencimento"])] + ([x["dias"]] if com_atraso else []) + [gp.reais(x["valor"])]
              for x in lista_despesas(df, hoje, gp.MAX_ITENS, vencidas)]
    return gp.tabela(colunas, linhas, total=len(df), numericas=(0, len(colunas) - 1) + ((len(colunas) - 2,) if com_atraso else ()))


def faixas_vencidas(d: pd.DataFrame, hoje: date) -> list[dict]:
    limites = [(7, "Vencidas há 1 a 7 dias"), (30, "Vencidas há 8 a 30 dias"), (90, "Vencidas há 31 a 90 dias"), (10**6, "Vencidas há mais de 90 dias")]
    dias = d["Vencimento"].map(lambda x: (hoje - x.date()).days)
    out, anterior = [], 0
    for teto, rotulo in limites:
        sel = d[(dias > anterior) & (dias <= teto)]
        if len(sel):
            out.append({"rotulo": rotulo, "valor": float(sel["Valor"].sum()), "qtd": int(len(sel))})
        anterior = teto
    return out


def faturas_convenio_por_mes() -> dict[str, dict]:
    """Faturas de convenio ainda nao baixadas, por mes de vencimento (vem do painel de Faturamento, se ele ja foi baixado)."""
    try:
        ab = k.carregar(PASTA.parent / "Faturamento")["Faturas em Aberto"]
        ab = ab[ab["Vencimento"].notna()]
        return {ym: {"valor": float(g["Valor Bruto"].fillna(0).sum()), "qtd": int(len(g))}
                for ym, g in ab.groupby(ym_de(ab["Vencimento"]))}
    except Exception:
        return {}


def convenio_a_faturar(ym: str) -> dict | None:
    """Produzido com convenios no mes e quanto ainda nao virou fatura: a mesma conta do painel de Faturamento (se ele ja foi baixado)."""
    try:
        pasta_fat = str(PASTA.parent / "Faturamento")
        if pasta_fat not in sys.path:
            sys.path.insert(0, pasta_fat)
        import gerar_faturamento as gfat  # noqa: E402
        abas = k.carregar(PASTA.parent / "Faturamento")
        ctrl = abas["Controle por Convênio"]
        funil = gfat.montar_funil(ym, gfat.preparar_faturas(abas["Faturas Emitidas"]), ctrl[ctrl[k.COL_MES] == ym])
        return {"ref": pc.rotulo_mes(ym), "produzido": funil["produzido"], "faturado": funil["faturado"], "falta": funil["falta"]} if funil["tem"] and funil["produzido"] else None
    except Exception:
        return None


def totais_do_mes(ym: str, desp: pd.DataFrame, rec: pd.DataFrame, conv: dict) -> dict:
    """A pagar, a receber e saldo de um mes (por vencimento), na mesma conta do cartao 'Saldo previsto do mes'."""
    d, r = desp[desp["_ym"] == ym], rec[rec["_ym"] == ym]
    lancadas, convenios, pagar = float(r["Valor"].sum()), conv.get(ym, {"valor": 0.0})["valor"], float(d["Valor"].sum())
    return {"rotulo": pc.rotulo_mes(ym), "pagar": pagar, "lancadas": lancadas, "convenios": convenios, "receber": lancadas + convenios, "saldo": lancadas + convenios - pagar}


def montar_mes(ym: str, desp: pd.DataFrame, rec: pd.DataFrame, part: pd.DataFrame, hoje: date, conv: dict, a_faturar: dict | None = None,
               per: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses ja reagrupado (ver montar_periodo): "ym" e o ultimo mes do periodo."""
    rot = per.rotulo if per else pc.rotulo_mes(ym)
    d = desp[desp["_ym"] == ym]
    r = rec[rec["_ym"] == ym]
    pago = d[d["_pago"]]
    aberto = d[~d["_pago"]]
    cv = conv.get(ym, {"valor": 0.0, "qtd": 0})
    a_pagar, lancadas = float(d["Valor"].sum()), float(r["Valor"].sum())
    a_receber = lancadas + cv["valor"]
    fechado = date(int(ym[:4]), int(ym[5:]), 1) < date(hoje.year, hoje.month, 1)

    pm = part[part["_ym_atend"] == ym]
    cartao = pm[pm["Tipo de Pagamento"].map(gd.norm).str.contains("CARTAO", na=False)]
    por_tipo = []
    for nome, g in pm.groupby("Tipo de Pagamento", dropna=False):
        bruto, taxa = float(g["Valor Bruto"].sum()), float(g["Taxa"].sum())
        por_tipo.append({"nome": "(vazio)" if pd.isna(nome) else str(nome), "bruto": bruto, "taxa": taxa,
                         "taxa_pct": taxa / bruto * 100 if bruto else None, "liquido": float(g["Valor Líquido"].sum()), "qtd": int(len(g))})
    por_tipo.sort(key=lambda x: -x["bruto"])
    taxa_cartao, bruto_cartao = float(cartao["Taxa"].sum()), float(cartao["Valor Bruto"].sum())

    cats = pc.agrupar(d, "Categoria", "Valor", top=10, outros="Demais categorias")
    alertas = []
    if not fechado and a_pagar > a_receber:
        alertas.append({"nivel": "atencao", "titulo": "Mais a pagar do que a receber no mês", "itens": itens_despesas(aberto, hoje, vencidas=True),
                        "texto": f"Em {rot} vencem <b>{brl(a_pagar)}</b> em despesas e há <b>{brl(a_receber)}</b> previstos a receber "
                                 f"({brl(lancadas)} lançados + {brl(cv['valor'])} em faturas de convênio), uma diferença de <b>{brl(a_pagar - a_receber)}</b>. "
                                 "O que ainda vai ser vendido no mês não está nessa conta."})
    if cats and cats[0]["pct"] >= 25:
        alertas.append({"nivel": "info", "titulo": "Uma categoria pesa muito nas despesas",
                        "texto": f"<b>{html.escape(cats[0]['nome'])}</b> é <b>{cats[0]['pct']:.0f}%</b> das despesas com vencimento em {rot}."})
    if bruto_cartao:
        alertas.append({"nivel": "info", "titulo": "Custo da maquininha",
                        "texto": f"Nas vendas de {rot} no cartão, a taxa foi de <b>{brl(taxa_cartao)}</b> (<b>{taxa_cartao / bruto_cartao * 100:.2f}%</b> de {brl(bruto_cartao)})."})
    gp.anotar("financeiro", alertas, per.chave if per else ym)

    # por que o saldo esta negativo: o cartao so mostra a conta (a receber - a pagar), aqui vao os motivos
    motivos = None
    if a_receber < a_pagar:
        top = [x for x in cats if not x["nome"].startswith("Demais")][:3]
        prox = totais_do_mes(k.mes_mais(ym, 1), desp, rec, conv) if not per else {"pagar": 0, "receber": 0}   # o mes seguinte a um periodo nao esta nas tabelas reagrupadas
        motivos = {"falta": a_pagar - a_receber, "top": top, "maior_cobre": bool(top) and top[0]["valor"] >= a_pagar - a_receber,
                   "a_faturar": None if fechado else a_faturar, "proximo": prox if (prox["pagar"] or prox["receber"]) else None}
    return {
        "rotulo": rot, "fechado": fechado, "saldo_motivos": motivos,
        "pagar": {"total": a_pagar, "pago": float(pago["Valor"].sum()), "aberto": float(aberto["Valor"].sum()),
                  "qtd": int(len(d)), "qtd_aberto": int(len(aberto))},
        "receber": {"total": a_receber, "lancadas": lancadas, "qtd": int(len(r)), "convenios": cv["valor"], "qtd_convenios": cv["qtd"]},
        "saldo": a_receber - a_pagar,
        "formas": pc.agrupar(r.assign(F=r["Forma de Pagamento"].fillna("(sem forma)")), "F", "Valor"),
        "despesas_categoria": cats, "despesas_empresa": pc.agrupar(d.assign(E=d["Empresa"].map(pc.nome_curto_unidade)), "E", "Valor"),
        "particular": {"bruto": float(pm["Valor Bruto"].sum()), "taxa": float(pm["Taxa"].sum()), "liquido": float(pm["Valor Líquido"].sum()),
                       "taxa_cartao": taxa_cartao, "bruto_cartao": bruto_cartao,
                       "taxa_cartao_pct": taxa_cartao / bruto_cartao * 100 if bruto_cartao else None, "por_tipo": por_tipo},
        "maiores": lista_despesas(d, hoje, 10, vencidas=True),
        "alertas": alertas,
    }


def montar_periodo(per: pc.Periodo, desp, rec, part, hoje, conv, a_faturar) -> dict:
    """Varios meses juntos, com a mesma conta de um mes (ver pc.reagrupar)."""
    def faturas(yms):
        return {"valor": sum(conv.get(m, {}).get("valor", 0.0) for m in yms), "qtd": sum(conv.get(m, {}).get("qtd", 0) for m in yms)}
    conv2 = {per.fim: faturas(per.yms), k.mes_mais(per.fim, -1): faturas(per.anterior.yms)}
    return montar_mes(per.fim, pc.reagrupar(desp, "_ym", per), pc.reagrupar(rec, "_ym", per), pc.reagrupar(part, "_ym_atend", per), hoje, conv2, a_faturar, per=per)


def convenio_produzido(ym: str) -> float | None:
    """Produzido com convenios no mes (vem do painel de Faturamento), se ele ja foi baixado."""
    pasta = PASTA.parent / "Faturamento"
    try:
        ctrl = k.carregar(pasta)["Controle por Convênio"]
        return float(ctrl.loc[ctrl[k.COL_MES] == ym, "Produzido"].fillna(0).sum()) or None
    except Exception:
        return None


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    defn = k.ler_definicao(PASTA)
    abas = k.carregar(PASTA)
    lanc, part, cred = abas[ABA_LANC], abas[ABA_PART], abas[ABA_CRED]
    hoje = date.today()
    ym_hoje = hoje.strftime("%Y-%m")

    meses, atencao, extras = {}, [], {}
    per, info = None, None
    dados = len(lanc) > 0
    if dados:
        lanc = lanc.copy()
        lanc["_ym"] = ym_de(lanc["Vencimento"])
        lanc["_pago"] = lanc["Conta"].notna()
        tipo = lanc["Tipo"].map(gd.norm)
        desp, rec = lanc[tipo == "DESPESAS"], lanc[tipo == "RECEITAS"]
        part = part.copy()
        part["_ym_atend"] = ym_de(part["Data do Atendimento"])
        conv = faturas_convenio_por_mes()
        a_faturar = convenio_a_faturar(k.mes_mais(ym_hoje, -1))   # produzido do ultimo mes fechado que ainda nao virou fatura (nao esta no "a receber")
        for ym in k.meses_entre(defn["primeiro_mes"], ym_hoje):
            meses[ym] = montar_mes(ym, desp, rec, part, hoje, conv, a_faturar)
        per, info = pc.periodo_pedido(de, ate, meses)
        if per and not per.unico:
            pc.acrescentar_periodo(meses, per, lambda p: montar_periodo(p, desp, rec, part, hoje, conv, a_faturar))

        # ---- atencao agora (nao depende do mes escolhido)
        ja_venceu = desp[desp["Vencimento"].notna() & (desp["Vencimento"].dt.date < hoje) & ~desp["_pago"]]
        a_vencer = desp[desp["Vencimento"].notna() & (desp["Vencimento"].dt.date >= hoje) & ~desp["_pago"]]
        dias_ate = a_vencer["Vencimento"].map(lambda x: (x.date() - hoje).days)
        prox = {"hoje": a_vencer[dias_ate == 0], "sete": a_vencer[dias_ate <= 7], "trinta": a_vencer[dias_ate <= 30]}
        extras["vencidas"] = {"qtd": int(len(ja_venceu)), "valor": float(ja_venceu["Valor"].sum()),
                              "faixas": faixas_vencidas(ja_venceu, hoje) if len(ja_venceu) else [],
                              "lista": lista_despesas(ja_venceu, hoje, 15, vencidas=True)}
        extras["proximos"] = {n: {"qtd": int(len(v)), "valor": float(v["Valor"].sum())} for n, v in prox.items()}
        extras["proximos"]["lista"] = lista_despesas(a_vencer, hoje, 12, vencidas=False)

        if extras["vencidas"]["qtd"]:
            atencao.append({"nivel": "critico", "titulo": "Contas vencidas sem baixa", "itens": itens_despesas(ja_venceu, hoje, vencidas=True, com_atraso=True),
                            "texto": f"<b>{extras['vencidas']['qtd']}</b> despesa(s) somando <b>{brl(extras['vencidas']['valor'])}</b> já venceram e estão sem Conta de pagamento registrada. "
                                     "Se já foram pagas, falta dar baixa no Klingo; se não, estão em atraso."})
        p = extras["proximos"]
        if p["sete"]["qtd"]:
            atencao.append({"nivel": "atencao", "titulo": "Vencimentos nos próximos 7 dias", "itens": itens_despesas(a_vencer[dias_ate <= 7], hoje, vencidas=False),
                            "texto": f"<b>{brl(p['sete']['valor'])}</b> em {p['sete']['qtd']} despesa(s) vencem até 7 dias"
                                     f"{(' (hoje: ' + brl(p['hoje']['valor']) + ')') if p['hoje']['qtd'] else ''}; em 30 dias são <b>{brl(p['trinta']['valor'])}</b>."})
        ref = k.mes_mais(ym_hoje, -1)
        prod_conv = convenio_produzido(ref)
        cred_ref = cred[cred[k.COL_MES] == ref] if len(cred) else cred
        rec_conv = float(cred_ref["Valor Recebido"].fillna(0).sum()) if len(cred_ref) else 0.0
        extras["convenio"] = {"ref": pc.rotulo_mes(ref), "produzido": prod_conv, "recebido": rec_conv, "creditos": int(len(cred_ref))}
        if prod_conv and rec_conv / prod_conv < 0.10:
            atencao.append({"nivel": "atencao", "titulo": "Convênios: quase nenhum crédito identificado",
                            "texto": f"Em {pc.rotulo_mes(ref)} a clínica produziu <b>{brl(prod_conv)}</b> com convênios, mas só <b>{brl(rec_conv)}</b> "
                                     f"({rec_conv / prod_conv * 100:.1f}%) aparecem como créditos identificados. Sem identificar os créditos, o caixa dos convênios não fecha."})
        invalidas = lanc[lanc["Alerta"].notna()] if "Alerta" in lanc else lanc.iloc[0:0]
        extras["invalidas"] = [{"id": r["Lançamento"], "historico": r["Histórico"], "alerta": r["Alerta"], "emissao": r["Emissão"], "valor": r["Valor"]}
                               for _, r in invalidas.head(20).iterrows()]
        if len(invalidas):
            atencao.append({"nivel": "atencao", "titulo": "Lançamentos com data inválida",
                            "itens": gp.tabela(["Lançamento", "Histórico", "Data com erro", "Emissão", "Valor"],
                                               [[r["Lançamento"], r["Histórico"], r["Alerta"], gp.dbr(r["Emissão"]), gp.reais(r["Valor"])] for _, r in invalidas.iterrows()],
                                               total=len(invalidas), numericas=(0, 4)),
                            "texto": f"<b>{len(invalidas)}</b> lançamento(s) têm data com erro de digitação (ex.: {html.escape(str(invalidas.iloc[0]['Alerta']))}, lançamento {int(invalidas.iloc[0]['Lançamento'])}). "
                                     "Eles ficam fora dos cálculos por vencimento até a data ser corrigida no Klingo."})
        conciliados = float(lanc["Conciliado"].notna().mean() * 100) if "Conciliado" in lanc else 0.0
        extras["conciliado_pct"] = conciliados
        if conciliados < 1:
            atencao.append({"nivel": "info", "titulo": "Nenhum lançamento conciliado com o extrato",
                            "texto": f"{len(lanc):,} lançamentos, {conciliados:.0f}% conciliados.".replace(",", ".") + " Enquanto a conciliação não for feita, o painel não consegue dizer o que realmente entrou ou saiu do banco."})
        part_pct = float((rec["Plano"].map(gd.norm) == "PARTICULAR").mean() * 100) if len(rec) else 0.0
        extras["particular_pct"] = part_pct
        if part_pct >= MIN_PARTICULAR_PCT:
            atencao.append({"nivel": "info", "titulo": "Receitas lançadas são quase só de particulares",
                            "texto": f"<b>{part_pct:.0f}%</b> das receitas lançadas são de pacientes particulares. A receita de convênios só vira lançamento quando o crédito é identificado; "
                                     "por isso o “a receber” deste painel soma as receitas lançadas com as faturas de convênio em aberto do painel de Faturamento."})
        # ---- fluxo dos proximos meses (por vencimento)
        fluxo = []
        for ym in k.meses_entre(ym_hoje, k.mes_mais(ym_hoje, MESES_A_FRENTE)):
            d, r = desp[desp["_ym"] == ym], rec[rec["_ym"] == ym]
            lanc_v, conv_v = float(r["Valor"].sum()), conv.get(ym, {}).get("valor", 0.0)
            fluxo.append({"ym": ym, "rotulo": pc.rotulo_mes(ym), "pagar": float(d["Valor"].sum()), "pagar_aberto": float(d.loc[~d["_pago"], "Valor"].sum()),
                          "lancadas": lanc_v, "convenios": conv_v, "receber": lanc_v + conv_v,
                          "saldo": lanc_v + conv_v - float(d["Valor"].sum())})
        extras["fluxo"] = fluxo
        extras["creditos"] = [{"data": r["Data do Recebimento"], "convenio": r["Convênio"], "recebido": r["Valor Recebido"],
                               "impostos": r["Total de Impostos"], "liquido": r["Valor Líquido"], "glosa": r["Glosa (calculada)"]}
                              for _, r in cred.sort_values("Data do Recebimento", ascending=False).head(15).iterrows()] if len(cred) else []
        ordem = {"critico": 0, "atencao": 1, "ok": 2, "info": 3}
        atencao.sort(key=lambda a: ordem[a["nivel"]])
        gp.anotar("financeiro", atencao)

    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else datetime.now()
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()), "hoje": hoje.isoformat(),
        "mes_padrao": per.chave if per else (ym_hoje if ym_hoje in meses else (max(meses) if meses else None)), "periodo": info,
        "meses": meses, "atencao": atencao, **extras,
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
