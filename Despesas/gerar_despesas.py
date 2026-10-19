"""Despesas: atualiza a planilha a partir do Klingo (#13505 e #13509) e gera 'Dashboard Despesas.html'.

#13505 (Evolucao das Despesas por Categoria e Mes) filtra pela data de COMPETENCIA do lancamento e mistura dois tipos na coluna
"Categoria": Debito (despesa) e Credito (receita). A coluna "Despesa" e a categoria da despesa. Traz o valor BRUTO e nao tem ID.
#13509 (Despesas Detalhadas por Lancamento, Valor Liquido) traz as mesmas linhas com o ID do lancamento e o valor LIQUIDO, mas nao diz
se a linha e credito ou debito: o painel cruza os dois (mesmo mes, categoria, data, descricao e fornecedor, na ordem do valor).
#26 (Receita Produzida, o mesmo do Faturamento) entra so para o bloco "Repasse medico": o que cada medico produziu, ao lado do Honorario Medico lancado.

Uso:  python gerar_despesas.py             so regenera o dashboard com o que ja esta na planilha
      python gerar_despesas.py --forcar    consulta o Klingo agora (como o botao) e regenera
      python gerar_despesas.py --historico baixa de novo todos os meses desde o primeiro
"""
import html
import re
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import gerar_dashboard as gd  # noqa: E402  (norm das Metas)
import guia_pendencias as gp  # noqa: E402
import planilha_despesas as pl  # noqa: E402  (aba "Planilha": grupos x itens x meses e fornecedores CSI / CSI 2)

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Despesas.html"
ABA_BRUTO, ABA_LIQ = "Despesas", "Líquido"
COLUNAS_BRUTO = ("Categoria", "Despesa", "Competência", "Valor", "Descrição", "Fornecedor")
COLUNAS_LIQ = ("ID do Lançamento", "Despesa", "Competência", "Descrição", "Fornecedor", "Valor Líquido")
TOP = 10                    # categorias e fornecedores nos graficos (o resto vira "Demais")
SUBIDA_MIN_VALOR = 5000.0   # uma categoria so conta como "subiu" se passou de R$ 5 mil a mais...
SUBIDA_MIN_PCT = 30.0       # ...e de 30% sobre o mes anterior (ou se e nova no mes)
FALTA_MIN_VALOR = 5000.0    # categoria recorrente ainda nao lancada no mes: so avisa se faltar mais que isto
MAX_LINHAS_MES = 400        # lancamentos listados por mes na tabela completa
MIN_MESES_TENDENCIA = 3     # com menos meses fechados nao ha tendencia que se possa chamar de tendencia
COMPRA_ESTOQUE = "Compra de Estoque"   # inicio da descricao dos lancamentos que o Suprimentos gera ao comprar
ABA_PROD = "Produção"                   # #26 (Receita Produzida): o que cada medico produziu
COLUNAS_PROD = ("Data", "Categoria", "Médico", "Procedimento", "Operadora", "Quantidade", "Valor")
HONORARIO = "Honorário Médico"          # categoria das despesas que o painel trata como repasse
TOP_MEDICOS = 12                        # medicos nos rankings (o resto vira "Demais")
FAIXAS_REPASSE = ((0, 1000, "até R$ 1 mil"), (1000, 3000, "R$ 1 a 3 mil"), (3000, 10000, "R$ 3 a 10 mil"), (10000, float("inf"), "acima de R$ 10 mil"))
SEM_RUIDO = {"DE", "DA", "DO", "DOS", "DAS", "E", "HONORARIO", "HONORARIOS", "MEDICO", "MEDICOS", "MEDICA", "DR", "DRA"}   # palavras que nao identificam a pessoa
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}
# no #26 a coluna "Medico" tambem traz o equipamento/setor quando nao ha medico (RM, RX, TC, "ULTRASSONOGRAFIA UM", "DENSITOMETRIA"...)
EQUIPAMENTO = re.compile(r"^(RM|RX|TC|USG|ECG)$|^(DENSITOMETRIA|MAMOGRAFIA|ELETRO|ULTRASSONOGRAFIA|ULTRASONOGRAFIA|ELETROCARDIOGRAMA|ECOCARDIOGRAMA)", re.I)
SEM_MEDICO = "Sem médico (equipamento ou setor)"


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    """Baixa os relatorios desta pasta e, em seguida, os de Financeiro (#798: a aba Planilha usa a empresa e o vencimento dele)."""
    partes = [k.atualizar(PASTA, forcar=forcar, historico=historico)]
    try:
        pasta_fin = str(PASTA.parent / "Financeiro")
        if pasta_fin not in sys.path:
            sys.path.insert(0, pasta_fin)
        import gerar_financeiro as gfin  # noqa: E402  (so aqui: Despesas abre sem o Financeiro)
        partes.append(gfin.atualizar(forcar=forcar, historico=historico))
    except Exception as e:   # noqa: BLE001 (sem o Financeiro, so a divisao CSI / CSI 2 fica desatualizada)
        partes.append({"atualizou": False, "mensagem": f"Financeiro não atualizado ({type(e).__name__}: {e}).", "avisos": []})
    return {"atualizou": any(p.get("atualizou") for p in partes), "mensagem": " ".join(p["mensagem"] for p in partes),
            "avisos": [a for p in partes for a in p.get("avisos", [])]}


def lancamentos_do_financeiro() -> pd.DataFrame | None:
    """Aba Lançamentos (#798) do painel Financeiro, ou None se ainda nao ha. Nunca derruba o painel."""
    try:
        return k.carregar(PASTA.parent / "Financeiro").get("Lançamentos")
    except Exception:   # noqa: BLE001
        return None


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def texto(v, padrao: str = "") -> str:
    """Celula de texto da planilha (pode vir NaN quando o Klingo deixou em branco)."""
    return v.strip() if isinstance(v, str) and v.strip() else padrao


def fmt_pct(v: float) -> str:
    return f"{v:.0f}".replace(".", ",") + "%"


# ---------------------------------------------------------------- cruzamento #13505 x #13509
def juntar(bruto: pd.DataFrame, liq: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(debitos, creditos, conferencia). Debitos: ID, Despesa, Competência, Descrição, Fornecedor, Bruto, Líquido, _ym.

    Cada mes e baixado inteiro dos dois relatorios, entao as linhas casam uma a uma: dentro do mesmo mes/categoria/data/descricao/fornecedor
    as linhas sao pareadas pela ordem do valor (bruto com liquido). Sobra de um lado so (lancamento criado entre as duas consultas) e contada
    em 'conferencia' e tratada com o que se sabe: sem o liquido, liquido = bruto."""
    conf = {"liquido": False, "sem_par_13509": 0, "sem_par_13505": 0, "liquido_maior": 0}
    b = bruto.copy()
    b["_tipo"] = b["Categoria"].map(gd.norm)
    creditos = b[b["_tipo"] == "CREDITO"].copy()
    tem_liq = liq is not None and len(liq) > 0 and set(COLUNAS_LIQ) <= set(liq.columns)
    if not tem_liq:
        d = b[b["_tipo"] == "DEBITO"].rename(columns={"Valor": "Bruto"})
        d = d.assign(ID=np.nan, Bruto=d["Bruto"].fillna(0.0))
        d["Líquido"] = d["Bruto"]
        d["_ym"] = d["Competência"].dt.strftime("%Y-%m").fillna(d[k.COL_MES])
        return d, creditos, conf
    conf["liquido"] = True

    chave = [k.COL_MES, "Despesa", "_data", "Descrição", "Fornecedor"]

    def preparar(df: pd.DataFrame, valor: str) -> pd.DataFrame:
        x = df.copy()
        for c in ("Despesa", "Descrição", "Fornecedor"):
            x[c] = x[c].fillna("").astype(str).str.strip()
        x["_data"] = x["Competência"].dt.strftime("%Y-%m-%d").fillna("")
        x = x.sort_values(chave + [valor], kind="stable")
        x["_o"] = x.groupby(chave).cumcount()
        return x

    n = preparar(liq, "Valor Líquido")
    b = preparar(b, "Valor")
    m = n.merge(b[chave + ["_o", "Valor", "_tipo"]], on=chave + ["_o"], how="outer", indicator=True)
    cat_deb, cat_cred = set(b.loc[b["_tipo"] == "DEBITO", "Despesa"]), set(b.loc[b["_tipo"] == "CREDITO", "Despesa"])

    so_liq = m["_merge"] == "left_only"       # so no #13509: o tipo vem da categoria (ou de ter fornecedor)
    conf["sem_par_13509"] = int(so_liq.sum())
    def tipo_por_categoria(r) -> str:
        if r["Despesa"] in cat_deb and r["Despesa"] not in cat_cred:
            return "DEBITO"
        if r["Despesa"] in cat_cred and r["Despesa"] not in cat_deb:
            return "CREDITO"
        return "DEBITO" if r["Fornecedor"] else "CREDITO"
    if so_liq.any():
        m.loc[so_liq, "_tipo"] = m[so_liq].apply(tipo_por_categoria, axis=1)
    m = m[m["_tipo"] == "DEBITO"].copy()
    so_bruto = m["_merge"] == "right_only"    # so no #13505: sem ID e sem o liquido
    conf["sem_par_13505"] = int(so_bruto.sum())
    m["Bruto"] = m["Valor"].where(m["Valor"].notna(), m["Valor Líquido"]).fillna(0.0)
    m["Líquido"] = m["Valor Líquido"].where(m["Valor Líquido"].notna(), m["Bruto"])
    conf["liquido_maior"] = int((m["Líquido"] > m["Bruto"] + 0.005).sum())
    m["ID"] = m["ID do Lançamento"]
    m["Competência"] = pd.to_datetime(m["_data"].replace("", np.nan), errors="coerce")
    m["_ym"] = m["Competência"].dt.strftime("%Y-%m").fillna(m[k.COL_MES])
    return m[["ID", "Despesa", "Competência", "Descrição", "Fornecedor", "Bruto", "Líquido", "_ym"]], creditos, conf


# ---------------------------------------------------------------- mes de VENCIMENTO
def aplicar_vencimento(d: pd.DataFrame, lanc: pd.DataFrame | None, inicio: str, ultimo_ym: str) -> tuple[pd.DataFrame, dict]:
    """O painel conta cada despesa no mes em que ela VENCE, nao no da competencia (a competencia continua na tabela, so deixa de mandar).

    O vencimento vem do Financeiro (#798, pelo ID do lancamento, que o #13509 traz). Sem vencimento (relatorio do Financeiro ainda nao baixado,
    ou lancamento emitido antes do periodo baixado dele) a linha fica no mes da competencia e entra na contagem 'sem_vencimento' (avisada no painel).
    Colunas novas: Vencimento (data usada pelo painel em TUDO, inclusive no repasse medico; a da competencia so quando falta) e _ym (mes dela);
    _comp_ym guarda o mes da competencia so para contar o que mudou de mes. Linhas que vencem depois do ultimo mes baixado ficam de fora: o que tem competencia
    ainda mais a frente nao foi baixado, entao esses meses estariam incompletos."""
    d = d.copy()
    d["_comp_ym"] = d["_ym"]
    ven = {}
    if lanc is not None and len(lanc) and {"Lançamento", "Vencimento"} <= set(lanc.columns):
        v = lanc[lanc["Lançamento"].notna() & lanc["Vencimento"].notna()].drop_duplicates(subset=["Lançamento"], keep="last")   # o #798 repete o lancamento (uma linha por conta)
        ven = {int(i): t for i, t in zip(v["Lançamento"], v["Vencimento"])}
    d["Vencimento"] = d["ID"].map(lambda i: ven.get(int(i)) if pd.notna(i) else None)
    d["Vencimento"] = pd.to_datetime(d["Vencimento"], errors="coerce")
    falta = d["Vencimento"].isna()
    sem = d[falta & (d["_comp_ym"] >= inicio)]
    d["Vencimento"] = d["Vencimento"].fillna(d["Competência"])
    d["_ym"] = d["Vencimento"].dt.strftime("%Y-%m").fillna(d["_comp_ym"])
    fora = d["_ym"] > ultimo_ym
    info = {"com_vencimento": int((~falta).sum()), "sem_vencimento": int(len(sem)), "valor_sem_vencimento": float(sem["Bruto"].sum()),
            "mudaram_de_mes": int(((~falta) & (d["_ym"] != d["_comp_ym"])).sum()), "alem_do_baixado": int(fora.sum()), "financeiro": bool(ven)}
    return d[~fora].copy(), info


# ---------------------------------------------------------------- agrupamentos
def agrupar(x: pd.DataFrame, campo: str, top: int | None = None, ref: dict | None = None) -> list[dict]:
    """Soma bruto, liquido e quantidade por categoria/fornecedor (maior primeiro). 'ref' = valor de referencia por nome (media dos meses
    fechados). O que passa de 'top' vira 'Demais (n)'."""
    if x.empty:
        return []
    g = x.groupby(campo).agg(valor=("Bruto", "sum"), liq=("Líquido", "sum"), qtd=("Bruto", "count")).sort_values("valor", ascending=False)
    total = float(g["valor"].sum())
    itens = [{"nome": str(n), "valor": float(r["valor"]), "liq": float(r["liq"]), "ret": float(r["valor"] - r["liq"]), "qtd": int(r["qtd"]),
              "pct": float(r["valor"] / total * 100) if total else 0.0, "media": (float(ref.get(str(n), 0.0)) if ref is not None else None)} for n, r in g.iterrows()]
    if top and len(itens) > top:
        resto = itens[top:]
        itens = itens[:top] + [{"nome": f"Demais ({len(resto)})", "valor": sum(i["valor"] for i in resto), "liq": sum(i["liq"] for i in resto),
                                "ret": sum(i["ret"] for i in resto), "qtd": sum(i["qtd"] for i in resto), "pct": sum(i["pct"] for i in resto),
                                "media": sum(i["media"] for i in resto) if ref is not None else None}]
    return itens


def ultimo_valor(tab_x: pd.DataFrame, ordem: list[str], ym: str, inicio: str) -> dict[str, tuple[float, str]]:
    """Nome (indice de tab_x) -> (valor, rotulo do mes) do ultimo mes confiavel ANTES de 'ym' em que o nome teve lancamento (>0).
    Fica de fora quem nunca apareceu num mes confiavel anterior a 'ym'."""
    anteriores = [m for m in ordem if inicio <= m < ym and m in tab_x.columns]
    saida = {}
    for nome in tab_x.index:
        for m in reversed(anteriores):
            v = float(tab_x.loc[nome, m])
            if v > 0:
                saida[str(nome)] = (v, pc.rotulo_mes(m))
                break
    return saida


def mudancas(atual: list[dict], anterior: list[dict], hist: dict[str, tuple[float, str]] | None = None) -> dict:
    """O que mudou por categoria/fornecedor. 'Caiu'/'sumiu' contra o mes imediatamente anterior (todos os nomes dos dois meses).
    'Subiu'/'novo' contra o ULTIMO mes confiavel em que o nome teve lancamento ('hist'), para nao marcar como "novo" ou "subiu"
    algo que so pulou um mes sem lancamento (ex.: fornecedor pago a cada 2 meses)."""
    hist = hist or {}
    ant = {i["nome"]: i["valor"] for i in anterior}
    nomes = {i["nome"]: i["valor"] for i in atual}
    todas = []
    for nome in nomes.keys() | ant.keys() | hist.keys():
        a, b = nomes.get(nome, 0.0), ant.get(nome, 0.0)
        hv, hrot = hist.get(nome, (0.0, None))
        todas.append({"nome": nome, "valor": a, "anterior": b, "dif": a - b, "pct": (a - b) / b * 100 if b else None, "sumiu": a == 0 and b > 0,
                      "hist_valor": hv, "hist_rotulo": hrot, "hist_dif": a - hv, "hist_pct": (a - hv) / hv * 100 if hv else None, "nova": hrot is None and a > 0})
    subiram = sorted((t for t in todas if t["hist_dif"] > 0), key=lambda t: -t["hist_dif"])
    cairam = sorted((t for t in todas if t["dif"] < 0), key=lambda t: t["dif"])
    return {"subiram": subiram[:8], "cairam": cairam[:8], "novos": [t for t in subiram if t["nova"]][:8], "sumiram": [t for t in cairam if t["sumiu"]][:8]}


def linha_lancamento(r) -> dict:
    return {"id": None if pd.isna(r["ID"]) else int(r["ID"]), "vencimento": r["Vencimento"], "categoria": r["Despesa"], "fornecedor": r["Fornecedor"],
            "descricao": r["Descrição"], "valor": float(r["Bruto"]), "liquido": float(r["Líquido"])}


def itens_lancamentos(x: pd.DataFrame) -> dict:
    """Tabela 'quais sao' dos alertas sobre lancamentos."""
    linhas = [["" if pd.isna(r["ID"]) else int(r["ID"]), gp.dbr(r["Vencimento"]), r["Despesa"], texto(r["Fornecedor"], "(sem fornecedor)"), texto(r["Descrição"]), gp.reais(r["Bruto"])]
              for _, r in x.iterrows()]
    return gp.tabela(["Lançamento", "Vencimento", "Categoria", "Fornecedor", "Descrição", "Valor"], linhas, total=len(x), numericas=(0, 5))


# ---------------------------------------------------------------- previsao
def prever(tab: pd.DataFrame, recor: pd.Series, ym_hoje: str, inicio: str) -> dict:
    """Quanto cada mes (o atual e os que vem) deve chegar a ter, a partir do que ja esta lancado.

    - piso: o que ja esta lancado (certo).
    - esperado: cada categoria RECORRENTE (lancada em 2+ meses) completa o seu valor tipico, a mediana dos meses confiaveis ja lancados
      (fechados e futuros; o mes atual fica de fora porque esta incompleto). Quem so apareceu em 1 mes (avulsa) nao se repete aqui.
    - teto: esperado + o total medio de despesas avulsas dos meses fechados (se aparecerem avulsas como antes).
    Com poucos meses de historico e so um ponto de partida: melhora a cada mes que fecha."""
    ordem = list(tab.columns)
    conf = [m for m in ordem if m >= inicio]
    fechados = [m for m in conf if m < ym_hoje]
    cols_tipico = [m for m in conf if m != ym_hoje]
    a_prever = [m for m in ordem if m >= ym_hoje]
    base = {"ok": False, "fechados": len(fechados), "inicio": pc.rotulo_mes(inicio)}
    if not cols_tipico or not a_prever:
        return base
    tipico = tab[cols_tipico].apply(lambda r: float(r[r > 0].median()) if (r > 0).any() else 0.0, axis=1)
    tipico_rec = tipico.where(recor, 0.0)
    avulso = float(tab.loc[~recor, fechados].sum().mean()) if fechados else None
    meses, faltas = [], []
    for m in a_prever:
        lan = tab[m]
        esperado_cat = pd.concat([lan, tipico_rec], axis=1).max(axis=1)
        piso, esperado = float(lan.sum()), float(esperado_cat.sum())
        meses.append({"ym": m, "rotulo": pc.rotulo_mes(m), "situacao": "em_curso" if m == ym_hoje else "previsto", "piso": piso, "esperado": esperado,
                      "teto": esperado + avulso if avulso is not None else None})
        if m == ym_hoje:
            for nome, falta in (esperado_cat - lan).sort_values(ascending=False).items():
                if falta >= 1.0:
                    faltas.append({"nome": str(nome), "tipico": float(tipico_rec[nome]), "lancado": float(lan[nome]), "falta": float(falta)})
    tendencia = None
    if len(fechados) >= MIN_MESES_TENDENCIA:
        y = np.array([float(tab[m].sum()) for m in fechados])
        inclinacao = float(np.polyfit(np.arange(len(y)), y, 1)[0])
        tendencia = {"por_mes": inclinacao, "pct_mes": inclinacao / float(y.mean()) * 100 if y.mean() else None, "meses": len(fechados)}
    avulsas = tab.loc[~recor, [m for m in conf]].sum(axis=1)
    return {**base, "ok": True, "meses": meses, "faltas": faltas, "avulso_medio": avulso, "tendencia": tendencia,
            "recorrentes": int(recor.sum()), "avulsas": [{"nome": str(n), "valor": float(v)} for n, v in avulsas[avulsas > 0].sort_values(ascending=False).items()],
            "fechados_rotulos": [pc.rotulo_mes(m) for m in fechados]}


# ---------------------------------------------------------------- repasse medico
def tokens_nome(s) -> frozenset:
    return frozenset(t for t in re.findall(r"[A-Z]+", gd.norm(s)) if t not in SEM_RUIDO and len(t) > 1)


def nome_do_lancamento(desc) -> str:
    """'HONORÁRIO MÉDICO - JULIANA MAGALHÃES', 'Honorário Médico Joana Barreto', 'HONORÁRIO GUSTAVO TEDESQUI' -> só o nome da pessoa."""
    t = re.sub(r"(?i)^\s*honor[aá]rios?\s*(m[eé]dic[oa]s?)?\s*[-–:]*\s*", "", texto(desc))
    return re.sub(r"(?i)^(dr|dra)\.?\s+", "", t).strip()


def bonito(nome: str) -> str:
    return " ".join(p if (i and p in PARTICULAS) else p.capitalize() for i, p in enumerate(nome.lower().split()))


def casar_nomes(pagos: list[str], produtores: dict[str, float]) -> dict[str, str]:
    """Nome escrito no lançamento -> nome completo do médico no relatório de produção, para os dois lados falarem da mesma pessoa.

    Casa quando 2+ palavras do nome coincidem (ou a única palavra, se só houver uma). Quem não aparece na produção fica com o próprio nome; dois
    lançamentos que se parecem entre si (2+ palavras) também são tratados como a mesma pessoa."""
    tk = {p: tokens_nome(p) for p in produtores}
    saida, sobras = {}, []
    for nome in pagos:
        t = tokens_nome(nome)
        melhor = None
        for prod, tp in tk.items():
            comuns = len(t & tp)
            if comuns >= 2 or (len(t) == 1 and comuns == 1):
                if melhor is None or (comuns, produtores[prod]) > melhor[0]:
                    melhor = ((comuns, produtores[prod]), prod)
        if melhor:
            saida[nome] = melhor[1]
        else:
            sobras.append(nome)
    escolhidos: list[tuple[frozenset, str]] = []
    for nome in sorted(sobras, key=lambda n: -len(tokens_nome(n))):
        t = tokens_nome(nome)
        igual = next((c for tc, c in escolhidos if len(t & tc) >= 2), None)
        saida[nome] = igual or nome
        if not igual:
            escolhidos.append((t, nome))
    return saida


def faixa_de(valor: float) -> str:
    return next(r for a, b, r in FAIXAS_REPASSE if a <= valor < b)


def concentracao(valores: list[float]) -> dict:
    """Quanto os maiores levam do total (valores já em ordem decrescente) e quantos bastam para 80%."""
    tot = sum(valores)
    if tot <= 0:
        return {"top1": 0.0, "top3": 0.0, "top5": 0.0, "n80": 0}
    acum, n80 = 0.0, 0
    for i, v in enumerate(valores, 1):
        acum += v
        if not n80 and acum >= tot * 0.8:
            n80 = i
    return {"top1": sum(valores[:1]) / tot * 100, "top3": sum(valores[:3]) / tot * 100, "top5": sum(valores[:5]) / tot * 100, "n80": n80}


def bloco_repasse(hh: pd.DataFrame, pp: pd.DataFrame | None) -> dict:
    """Honorário Médico lançado no mês, por médico; com a produção do mês ao lado quando o relatório de produção cobre o mês."""
    prod_med = pp.groupby("M")["Valor"].sum().to_dict() if pp is not None else None
    medicos = []
    for nome, g in hh.groupby("M"):
        bruto, liq = float(g["Bruto"].sum()), float(g["Líquido"].sum())
        produzido = float(prod_med.get(nome, 0.0)) if prod_med is not None else None
        medicos.append({"nome": nome, "bruto": bruto, "liq": liq, "ret": bruto - liq, "qtd": int(len(g)), "empresas": sorted(set(g["Empresa"])),
                        "produzido": produzido, "taxa": bruto / produzido * 100 if produzido else None,
                        "lanc": [{"id": None if pd.isna(r["ID"]) else int(r["ID"]), "empresa": r["Empresa"], "descricao": texto(r["Descrição"]), "valor": float(r["Bruto"]), "liquido": float(r["Líquido"])}
                                 for _, r in g.sort_values("Bruto", ascending=False).iterrows()]})
    medicos.sort(key=lambda m: -m["bruto"])
    total = sum(m["bruto"] for m in medicos)
    for m in medicos:
        m["pct"] = m["bruto"] / total * 100 if total else 0.0
    bruto, liq = float(hh["Bruto"].sum()), float(hh["Líquido"].sum())
    faixas = []
    for _, _, rotulo in FAIXAS_REPASSE:
        sel = [m for m in medicos if faixa_de(m["bruto"]) == rotulo]
        faixas.append({"faixa": rotulo, "medicos": len(sel), "valor": sum(m["bruto"] for m in sel)})
    comparavel = prod_med is not None and any(m["produzido"] for m in medicos)
    sem_prod = [{"nome": m["nome"], "valor": m["bruto"]} for m in medicos if prod_med is not None and not m["produzido"]]
    return {"bruto": bruto, "liquido": liq, "retido": bruto - liq, "retido_pct": (bruto - liq) / bruto * 100 if bruto else 0.0, "qtd": int(len(hh)), "n_medicos": len(medicos),
            "medicos": medicos, "conc": concentracao([m["bruto"] for m in medicos]), "faixas": faixas, "ticket": bruto / len(medicos) if medicos else 0.0,
            "com_producao": comparavel, "sem_producao": sem_prod}


def bloco_producao(pp: pd.DataFrame, pagos: dict[str, float] | None) -> dict:
    """Produção (receita produzida) do mês por médico, operadora e centro de resultado. 'pagos' = repasse bruto por médico no mesmo mês (None = mês sem repasse lançado)."""
    pessoas = pp[pp["M"] != SEM_MEDICO]
    total = float(pp["Valor"].sum())
    medicos = []
    for nome, g in pessoas.groupby("M"):
        valor, qtd = float(g["Valor"].sum()), int(g["Quantidade"].sum())
        por_centro = g.groupby("Categoria")["Valor"].sum().sort_values(ascending=False)
        particular = float(g.loc[g["Operadora"] == "Particular", "Valor"].sum())
        medicos.append({"nome": nome, "valor": valor, "qtd": qtd, "ticket": valor / qtd if qtd else 0.0, "pct": valor / total * 100 if total else 0.0,
                        "particular_pct": particular / valor * 100 if valor else 0.0, "centro": str(por_centro.index[0]) if len(por_centro) else "",
                        "convenios": int(g["Operadora"].nunique()), "repasse": float(pagos.get(nome, 0.0)) if pagos is not None else None})
    medicos.sort(key=lambda m: -m["valor"])
    for m in medicos:
        m["taxa"] = m["repasse"] / m["valor"] * 100 if m["repasse"] and m["valor"] else None

    def ranking(campo: str) -> list[dict]:
        g = pp.groupby(campo)["Valor"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        return [{"nome": texto(str(n), "(sem informação)"), "valor": float(r["sum"]), "qtd": int(r["count"]), "pct": float(r["sum"] / total * 100) if total else 0.0} for n, r in g.iterrows()]
    sem_medico = float(pp.loc[pp["M"] == SEM_MEDICO, "Valor"].sum())
    return {"total": total, "qtd": int(pp["Quantidade"].sum()), "n_medicos": len(medicos), "sem_medico": sem_medico, "medicos": medicos,
            "conc": concentracao([m["valor"] for m in medicos]), "operadoras": ranking("Operadora"), "centros": ranking("Categoria"),
            "particular": float(pp.loc[pp["Operadora"] == "Particular", "Valor"].sum()),
            "sem_repasse": [{"nome": m["nome"], "valor": m["valor"]} for m in medicos if pagos is not None and not m["repasse"]]}


def montar_repasse(d: pd.DataFrame, prod: pd.DataFrame | None, meses: dict, ym_hoje: str, inicio: str, per: pc.Periodo | None = None) -> dict:
    """Tudo sobre o repasse médico: o Honorário Médico lançado nas despesas (por mês, médico e empresa) e a produção de cada médico (#26) para comparar."""
    h = d[d["Despesa"] == HONORARIO].copy()
    tem_prod = prod is not None and len(prod) > 0 and set(COLUNAS_PROD) <= set(prod.columns)
    p = None
    if tem_prod:
        p = prod.copy()
        p["_ym"] = p["Data"].dt.strftime("%Y-%m").fillna(p[k.COL_MES])
        p["Médico"] = p["Médico"].map(texto)
        p["_pessoa"] = p["Médico"].ne("") & ~p["Médico"].map(lambda v: bool(EQUIPAMENTO.search(v)))
        for c in ("Valor", "Quantidade"):
            p[c] = p[c].fillna(0.0)
        p["Operadora"] = p["Operadora"].map(texto)
        p["Categoria"] = p["Categoria"].map(texto)
    if h.empty and p is None:
        return {"ok": False}
    h["_nome"] = h["Descrição"].map(nome_do_lancamento)
    produtores = p[p["_pessoa"]].groupby("Médico")["Valor"].sum().to_dict() if p is not None else {}
    nomes = casar_nomes(sorted(set(h["_nome"][h["_nome"] != ""])), produtores)
    h["M"] = h["_nome"].map(lambda n: bonito(nomes.get(n, n)) if n else "(nome não informado)")
    h["Empresa"] = h["Fornecedor"].map(lambda v: texto(v, "(sem fornecedor)"))
    if p is not None:
        p["M"] = [bonito(m) if pes else SEM_MEDICO for m, pes in zip(p["Médico"], p["_pessoa"])]
    prod_meses = sorted(p["_ym"].unique()) if p is not None else []
    prod_ini = prod_meses[0] if prod_meses else None
    rep_meses = [m for m in sorted(set(h["_ym"]) | set(prod_meses)) if m <= ym_hoje]
    if not rep_meses:
        return {"ok": False}

    por_mes, evolucao, anterior_rep = {}, [], None
    for ym in k.meses_entre(rep_meses[0], ym_hoje):
        hh = h[h["_ym"] == ym]
        com_prod = prod_ini is not None and ym >= prod_ini
        pp = p[p["_ym"] == ym] if (p is not None and com_prod) else None
        if pp is not None and not len(pp):
            pp = None
        bruto, liq = float(hh["Bruto"].sum()), float(hh["Líquido"].sum())
        desp = meses[ym]["total"] if ym in meses else 0.0
        producao = float(pp["Valor"].sum()) if pp is not None else None
        producao_medico = float(pp.loc[pp["M"] != SEM_MEDICO, "Valor"].sum()) if pp is not None else None
        evolucao.append({"ym": ym, "rotulo": pc.rotulo_mes(ym), "situacao": "fechado" if ym < ym_hoje else "em_curso", "parcial": ym < inicio, "bruto": bruto, "liquido": liq,
                         "retido": bruto - liq, "n_medicos": int(hh["M"].nunique()), "qtd": int(len(hh)), "despesas": desp, "pct_despesas": bruto / desp * 100 if desp else None,
                         "producao": producao, "producao_medico": producao_medico, "taxa": bruto / producao * 100 if (producao and bruto) else None, "tem_producao": pp is not None})
        if not len(hh) and pp is None:
            continue
        rep = bloco_repasse(hh, pp) if len(hh) else None
        pagos = {m["nome"]: m["bruto"] for m in rep["medicos"]} if rep else None
        pro = bloco_producao(pp, pagos) if pp is not None else None
        mud = None
        if rep and anterior_rep and anterior_rep[0] == pc_mes_anterior(ym):
            mud = {"anterior": pc.rotulo_mes(anterior_rep[0]), "parcial": anterior_rep[0] < inicio or ym < inicio,
                   **mudancas([{"nome": m["nome"], "valor": m["bruto"]} for m in rep["medicos"]], anterior_rep[1])}
        por_mes[ym] = {"rotulo": pc.rotulo_mes(ym), "situacao": "fechado" if ym < ym_hoje else "em_curso", "parcial": ym < inicio, "repasse": rep, "producao": pro, "mudancas": mud}
        if rep:
            anterior_rep = (ym, [{"nome": m["nome"], "valor": m["bruto"]} for m in rep["medicos"]])

    # ---- o periodo escolhido no filtro De/Ate (varios meses juntos), com a mesma conta de um mes; fica fora de por_mes (que soma meses)
    por_periodo = {}
    if per and not per.unico and any(y in rep_meses for y in per.yms):
        hh = h[per.dentro(h["Vencimento"])] if per.exato else h[h["_ym"].isin(per.yms)]
        yp = [y for y in per.yms if prod_ini is not None and y >= prod_ini]
        if p is not None and yp:
            pp = p[per.dentro(p["Data"]) & p["_ym"].isin(yp)] if per.exato else p[p["_ym"].isin(yp)]
        else:
            pp = None
        if pp is not None and not len(pp):
            pp = None
        if len(hh) or pp is not None:
            bruto, liq = float(hh["Bruto"].sum()), float(hh["Líquido"].sum())
            desp = float(d.loc[per.dentro(d["Vencimento"]), "Bruto"].sum()) if per.exato else sum(meses[y]["total"] for y in per.yms if y in meses)
            producao = float(pp["Valor"].sum()) if pp is not None else None
            rep = bloco_repasse(hh, pp) if len(hh) else None
            pagos = {m["nome"]: m["bruto"] for m in rep["medicos"]} if rep else None
            sit = "fechado" if per.fim < ym_hoje else "em_curso"
            ev = {"ym": per.chave, "rotulo": per.rotulo, "situacao": sit, "parcial": per.ini < inicio, "bruto": bruto, "liquido": liq, "retido": bruto - liq,
                  "n_medicos": int(hh["M"].nunique()), "qtd": int(len(hh)), "despesas": desp, "pct_despesas": bruto / desp * 100 if desp else None,
                  "producao": producao, "taxa": bruto / producao * 100 if (producao and bruto) else None, "tem_producao": pp is not None}
            por_periodo[per.chave] = {"rotulo": per.rotulo, "situacao": sit, "parcial": per.ini < inicio, "repasse": rep, "producao": bloco_producao(pp, pagos) if pp is not None else None,
                                      "mudancas": None, "periodo": True, "ev": ev}

    # ---- por medico, no periodo todo
    acum = []
    for nome, g in h.groupby("M"):
        meses_pagos = sorted(set(g["_ym"]))
        prod_total = float(p.loc[p["M"] == nome, "Valor"].sum()) if p is not None else None
        acum.append({"nome": nome, "bruto": float(g["Bruto"].sum()), "liq": float(g["Líquido"].sum()), "qtd": int(len(g)), "meses": [pc.rotulo_mes(m) for m in meses_pagos],
                     "n_meses": len(meses_pagos), "empresas": sorted(set(g["Empresa"])), "maior": float(g["Bruto"].max()), "produzido": prod_total})
    acum.sort(key=lambda m: -m["bruto"])
    empresas = []
    for emp, g in h.groupby("Empresa"):
        empresas.append({"nome": emp, "bruto": float(g["Bruto"].sum()), "qtd": int(len(g)), "medicos": sorted(set(g["M"]))})
    empresas.sort(key=lambda e: -e["bruto"])
    mais_de_uma = [m for m in acum if len(m["empresas"]) > 1]
    repetidos = []   # mesmo medico com 2+ lancamentos na mesma competencia (pode ser parcela, ajuste ou duplicidade)
    for (ym, nome), g in h.groupby(["_ym", "M"]):
        if len(g) >= 2:
            repetidos.append({"ym": ym, "mes": pc.rotulo_mes(ym), "nome": nome, "qtd": int(len(g)), "valor": float(g["Bruto"].sum())})
    com_repasse = [m for m in rep_meses if len(h[h["_ym"] == m])]
    sem_repasse = [e for e in evolucao if e["ym"] >= inicio and e["producao"] and not e["bruto"]]
    return {"ok": True, "meses": rep_meses, "mes_padrao": com_repasse[-1] if com_repasse else rep_meses[-1], "evolucao": evolucao, "por_mes": por_mes, "por_periodo": por_periodo, "acumulado": acum,
            "empresas": empresas, "tem_producao": p is not None, "producao_desde": pc.rotulo_mes(prod_ini) if prod_ini else None,
            "total": {"bruto": float(h["Bruto"].sum()), "liquido": float(h["Líquido"].sum()), "qtd": int(len(h)), "n_medicos": len(acum)},
            "mais_de_uma_empresa": [{"nome": m["nome"], "empresas": m["empresas"]} for m in mais_de_uma], "repetidos": repetidos,
            "sem_repasse": [{"ym": e["ym"], "rotulo": e["rotulo"], "producao": e["producao"], "em_curso": e["situacao"] == "em_curso"} for e in sem_repasse],
            "ultimo_repasse": {"rotulo": pc.rotulo_mes(com_repasse[-1]), "bruto": float(h.loc[h["_ym"] == com_repasse[-1], "Bruto"].sum())} if com_repasse else None}


def pc_mes_anterior(ym: str) -> str:
    return k.mes_mais(ym, -1)


# ---------------------------------------------------------------- alertas e meses
def alertas_do_mes(rotulo: str, sit: str, parcial: bool, x: pd.DataFrame, mud: dict | None, prev_rotulo: str | None, falta: list[dict] | None) -> list[dict]:
    alertas = []
    zeradas = x[x["Bruto"] == 0]
    if len(zeradas) and sit != "previsto":   # em mes futuro, valor zero e contrato com valor ainda nao definido: ainda ha tempo
        alertas.append({"nivel": "atencao", "titulo": "Despesas lançadas com valor zero", "itens": itens_lancamentos(zeradas),
                        "texto": f"<b>{len(zeradas)}</b> despesa(s) de {rotulo} estão com valor <b>R$ 0,00</b> (ex.: {html.escape(texto(zeradas.iloc[0]['Fornecedor']) or texto(zeradas.iloc[0]['Descrição'], 'sem descrição'))}). "
                                 "Elas não entram nos totais. Se o valor ainda vai ser definido, preencha antes do vencimento; se o lançamento não é mais necessário, exclua."})
    # as "Compra de Estoque: ..." nascem da compra no Suprimentos, onde repetir o mesmo item e preco e normal: ficam fora desta conferencia
    manual = x[(x["Bruto"] != 0) & ~x["Descrição"].fillna("").astype(str).str.startswith(COMPRA_ESTOQUE)]
    chave = ["Despesa", "Fornecedor", "Descrição", "Bruto"]
    grupos = manual.fillna({"Fornecedor": "", "Descrição": ""}).groupby(chave)
    repetidos = [(g, idx) for g, idx in grupos.groups.items() if len(idx) >= 2]
    if repetidos and sit != "previsto":
        linhas, a_mais = [], 0.0
        for (cat, forn, desc, valor), idx in sorted(repetidos, key=lambda t: -t[0][3] * (len(t[1]) - 1)):
            a_mais += valor * (len(idx) - 1)
            ids = ", ".join(str(int(i)) for i in sorted(manual.loc[idx, "ID"].dropna().unique()))
            linhas.append([cat, forn or "(sem fornecedor)", desc, gp.reais(valor), len(idx), ids or "—"])
        alertas.append({"nivel": "atencao", "titulo": "Possíveis lançamentos repetidos",
                        "itens": gp.tabela(["Categoria", "Fornecedor", "Descrição", "Valor", "Vezes", "Lançamentos"], linhas, total=len(linhas), numericas=(3, 4)),
                        "texto": f"Em {rotulo} há <b>{len(repetidos)}</b> grupo(s) de lançamentos idênticos (mesma categoria, fornecedor, descrição e valor), somando <b>{brl(a_mais)}</b> a mais do que se fossem um só cada. "
                                 "Podem ser parcelas ou itens iguais; se algum foi lançado duas vezes por engano, o total do mês está inflado. A tabela traz o número dos lançamentos para você procurar."})
    sem_forn = x[x["Fornecedor"].isna() | (x["Fornecedor"].astype(str).str.strip() == "")]
    if len(sem_forn):
        alertas.append({"nivel": "atencao", "titulo": "Despesas sem fornecedor", "itens": itens_lancamentos(sem_forn),
                        "texto": f"<b>{len(sem_forn)}</b> despesa(s) de {rotulo}, somando <b>{brl(float(sem_forn['Bruto'].sum()))}</b>, não têm fornecedor. Sem ele não dá para saber para quem a clínica paga."})
    if mud and sit != "previsto" and not parcial and prev_rotulo:
        # o mes anterior ja fechou; no mes em andamento so a ALTA vale (a queda pode ser lancamento que ainda nao entrou)
        sobem = [t for t in mud["subiram"] if t["hist_dif"] >= SUBIDA_MIN_VALOR and (t["nova"] or (t["hist_pct"] is not None and t["hist_pct"] >= SUBIDA_MIN_PCT))]
        if sobem:
            def desc(t):
                if t["nova"]:
                    return f"<b>{html.escape(t['nome'])}</b> {brl(t['hist_dif'])} (nova no mês)"
                return f"<b>{html.escape(t['nome'])}</b> {brl(t['hist_dif'])} a mais desde {html.escape(t['hist_rotulo'])} (+{fmt_pct(t['hist_pct'])})"
            lista = "; ".join(desc(t) for t in sobem[:4])
            resto = f" e mais {len(sobem) - 4}" if len(sobem) > 4 else ""
            aberto = " O mês ainda recebe lançamentos, então esses valores podem crescer." if sit == "em_curso" else ""
            alertas.append({"nivel": "info", "titulo": "Categorias que gastaram bem mais que no último mês em que apareceram",
                            "texto": f"Em {rotulo}: {lista}{resto}.{aberto} Ver “O que mudou” na Análise."})
    if falta and sit == "em_curso":
        grandes = [f for f in falta if f["falta"] >= FALTA_MIN_VALOR]
        if grandes:
            lista = "; ".join(f"<b>{html.escape(f['nome'])}</b> (típico {brl(f['tipico'])}, lançado {brl(f['lancado'])})" for f in grandes[:4])
            alertas.append({"nivel": "info", "titulo": "Despesas recorrentes que ainda não foram lançadas neste mês",
                            "texto": f"Em {rotulo} ainda não apareceu o valor típico de: {lista}{' e mais ' + str(len(grandes) - 4) if len(grandes) > 4 else ''}. "
                                     f"Somam <b>{brl(sum(f['falta'] for f in grandes))}</b> que devem entrar até o fim do mês. Ver “Previsão”."})
    return alertas


def montar_mes(ym: str, d: pd.DataFrame, ctx: dict, prev: dict | None, per: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses: "ym" e o ultimo mes dele, as linhas de todos entram juntas e a referencia dos outros meses
    fechados (media mensal) vale pelo tamanho do periodo. `prev` e o mes (ou periodo) anterior ja calculado."""
    yms = per.yms if per else [ym]
    x = d[per.dentro(d["Vencimento"])] if (per and per.exato) else d[d["_ym"].isin(yms)]
    sit = "fechado" if ym < ctx["hoje"] else ("em_curso" if ym == ctx["hoje"] else "previsto")
    parcial = (per.ini if per else ym) < ctx["inicio"]              # antes do Klingo: historico que pode estar incompleto
    rotulo = per.rotulo if per else pc.rotulo_mes(ym)
    tab = ctx["tab"]
    yms_tab = [m for m in yms if m in tab.columns]
    outros = [m for m in ctx["fechados"] if m not in yms]
    tamanho = per.n_dias / 30.4375 if (per and per.exato) else len(yms)   # em "meses": a media dos meses fechados vale pelo tamanho do periodo
    ref_cat = {str(n): float(v) * tamanho for n, v in tab[outros].mean(axis=1).items()} if (outros and not parcial) else None
    media_total = float(np.mean([tab[m].sum() for m in outros])) * tamanho if (outros and not parcial) else None
    cats_todas = agrupar(x, "Despesa", ref=ref_cat)
    forn_x = x.assign(F=x["Fornecedor"].map(lambda v: texto(v, "(sem fornecedor)")))
    forn_todos = agrupar(forn_x, "F")
    comparavel = prev is not None and not prev["parcial"] and not parcial
    ym_hist = per.ini if per else ym   # limite do historico: antes do periodo/mes, nunca dentro dele
    hist_cat = ultimo_valor(tab, ctx["ordem"], ym_hist, ctx["inicio"])
    hist_forn = ultimo_valor(ctx["tab_forn"], ctx["ordem"], ym_hist, ctx["inicio"])
    mud = mudancas(cats_todas, prev["_cats"], hist_cat) if comparavel else None
    mud_forn = mudancas(forn_todos, prev["_forn"], hist_forn) if comparavel else None
    # ---- cruzamento para o clique nos graficos: categoria -> fornecedores e lancamentos dela; fornecedor -> categorias e lancamentos dele
    detalhe_categoria = {str(nome): {"fornecedores": agrupar(g.assign(F=g["Fornecedor"].map(lambda v: texto(v, "(sem fornecedor)"))), "F"),
                                      "lancamentos": [linha_lancamento(r) for _, r in g.sort_values("Bruto", ascending=False).iterrows()]}
                          for nome, g in x.groupby("Despesa")}
    detalhe_fornecedor = {str(nome): {"categorias": agrupar(g, "Despesa"),
                                       "lancamentos": [linha_lancamento(r) for _, r in g.sort_values("Bruto", ascending=False).iterrows()]}
                           for nome, g in forn_x.groupby("F")}
    alertas = alertas_do_mes(rotulo, sit, parcial, x, mud, prev["rotulo"] if comparavel else None, ctx["previsao"].get("faltas") if sit == "em_curso" else None)
    gp.anotar("despesas", alertas, per.chave if per else ym)
    bruto, liq = float(x["Bruto"].sum()), float(x["Líquido"].sum())
    if per and per.exato:
        col = x.groupby("Despesa")["Bruto"].sum()   # recorte de dias: a conta sai das proprias linhas, nao da tabela categoria x mes
    else:
        col = tab[yms_tab[0]] if len(yms_tab) == 1 else tab[yms_tab].sum(axis=1)   # a(s) coluna(s) do periodo na tabela categoria x mes
    rec = float(sum(v for n, v in col.items() if ctx["recor"].get(n) and v > 0))
    avulsas = [{"nome": str(n), "valor": float(v)} for n, v in col.sort_values(ascending=False).items() if v > 0 and not ctx["recor"].get(n)]
    top5 = sum(i["pct"] for i in cats_todas[:5])
    return {
        "rotulo": rotulo, "situacao": sit, "parcial": parcial, "total": bruto, "liquido": liq, "retido": bruto - liq, "retido_pct": (bruto - liq) / bruto * 100 if bruto else 0.0,
        "qtd": int(len(x)), "n_categorias": len(cats_todas), "n_fornecedores": len(forn_todos),
        "categorias": agrupar(x, "Despesa", TOP, ref=ref_cat), "fornecedores": agrupar(forn_x, "F", TOP), "fornecedores_todos": forn_todos,
        "retencoes": [{"nome": i["nome"], "valor": i["ret"], "pct": i["ret"] / i["valor"] * 100 if i["valor"] else 0.0} for i in cats_todas if i["ret"] > 0.005][:TOP],
        "media_total": media_total, "n_ref": len(outros) if media_total is not None else 0,
        "recorrente": {"valor": rec, "avulso": bruto - rec, "avulsas": avulsas[:6]}, "top5_pct": top5,
        "mudancas": mud, "mudancas_forn": mud_forn, "mes_anterior": prev["rotulo"] if comparavel else None,
        "anterior_parcial": bool(prev and prev["parcial"] and not parcial),
        "detalhe_categoria": detalhe_categoria, "detalhe_fornecedor": detalhe_fornecedor,
        "maiores": [linha_lancamento(r) for _, r in x.sort_values("Bruto", ascending=False).head(15).iterrows()],
        "lancamentos": [linha_lancamento(r) for _, r in x.sort_values(["Bruto", "Despesa"], ascending=[False, True]).head(MAX_LINHAS_MES).iterrows()], "lancamentos_total": int(len(x)),
        "alertas": alertas, "_cats": cats_todas, "_forn": forn_todos,
    }


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    defn = k.ler_definicao(PASTA)
    abas = k.carregar(PASTA)
    bruto, liq = abas[ABA_BRUTO], abas.get(ABA_LIQ)
    hoje = date.today()
    ym_hoje = hoje.strftime("%Y-%m")
    inicio = defn.get("inicio_confiavel", defn["primeiro_mes"])

    meses, extras, atencao = {}, {}, []
    per, info = None, None
    if len(bruto) and set(COLUNAS_BRUTO) <= set(bruto.columns):
        d, creditos, conf = juntar(bruto, liq)
        d["Despesa"] = d["Despesa"].fillna("(sem categoria)")
        d, venc = aplicar_vencimento(d, lancamentos_do_financeiro(), inicio, str(bruto[k.COL_MES].max()))
        if len(d):
            ordem = k.meses_entre(defn["primeiro_mes"], max(ym_hoje, d["_ym"].max()))
            tab = d[d["_ym"].isin(ordem)].pivot_table(index="Despesa", columns="_ym", values="Bruto", aggfunc="sum", fill_value=0.0).reindex(columns=ordem, fill_value=0.0)
            d_forn = d.assign(F=d["Fornecedor"].map(lambda v: texto(v, "(sem fornecedor)")))
            tab_forn = d_forn[d_forn["_ym"].isin(ordem)].pivot_table(index="F", columns="_ym", values="Bruto", aggfunc="sum", fill_value=0.0).reindex(columns=ordem, fill_value=0.0)
            recor = (tab > 0).sum(axis=1) >= 2          # categoria lancada em 2+ meses = recorrente; em 1 so = avulsa
            fechados = [m for m in ordem if inicio <= m < ym_hoje]
            previsao = prever(tab, recor, ym_hoje, inicio)
            ctx = {"hoje": ym_hoje, "inicio": inicio, "tab": tab, "tab_forn": tab_forn, "ordem": ordem, "recor": recor.to_dict(), "fechados": fechados, "previsao": previsao}
            prev = None
            for ym in ordem:
                meses[ym] = montar_mes(ym, d, ctx, prev)
                prev = meses[ym]
            for m in meses.values():
                m.pop("_cats"), m.pop("_forn")
            per, info = pc.periodo_pedido(de, ate, meses)

            # ---- historico mes a mes, matriz categoria x mes e totais do periodo
            hist, anterior = [], None
            for ym, m in meses.items():
                var = (m["total"] - anterior["total"]) / anterior["total"] * 100 if (anterior and m["situacao"] == "fechado" and not anterior["parcial"] and not m["parcial"] and anterior["total"]) else None
                hist.append({"ym": ym, "rotulo": m["rotulo"], "situacao": m["situacao"], "parcial": m["parcial"], "total": m["total"], "liquido": m["liquido"], "retido": m["retido"],
                             "retido_pct": m["retido_pct"], "qtd": m["qtd"], "n_categorias": m["n_categorias"], "var_pct": var,
                             "maior": m["categorias"][0]["nome"] if m["categorias"] else None})
                anterior = m
            extras["evolucao"] = hist
            tab_o = tab.assign(_t=tab.sum(axis=1)).sort_values("_t", ascending=False)
            extras["matriz"] = [{"nome": str(n), "valores": [float(r[ym]) for ym in ordem], "total": float(r["_t"]), "recorrente": bool(recor[n])} for n, r in tab_o.iterrows()]
            realizado = [m for ym, m in meses.items() if inicio <= ym <= ym_hoje]
            soma = sum(m["total"] for m in realizado)
            extras["acumulado"] = {"desde": pc.rotulo_mes(inicio), "total": soma, "meses": len(realizado), "media": soma / len(realizado) if realizado else None}
            extras["previsao"] = previsao
            if previsao.get("ok"):   # retencao media dos meses confiaveis: o que sai da conta do fornecedor em relacao ao bruto
                conf_m = [meses[m] for m in fechados]
                tot = sum(m["total"] for m in conf_m)
                previsao["retencao_pct"] = sum(m["retido"] for m in conf_m) / tot * 100 if tot else 0.0
            estoque = d[d["Descrição"].fillna("").astype(str).str.startswith(COMPRA_ESTOQUE) & d["_ym"].isin(meses)]
            extras["compras_estoque"] = {"qtd": int(len(estoque)), "valor": float(estoque["Bruto"].sum())}
            extras["creditos_ignorados"] = {"qtd": int(len(creditos)), "valor": float(creditos["Valor"].fillna(0).sum())}
            extras["conferencia"] = conf
            extras["vencimento"] = venc
            if venc["sem_vencimento"]:
                atencao.append({"nivel": "atencao", "titulo": "Despesas sem data de vencimento (contadas pela competência)",
                                "texto": f"<b>{venc['sem_vencimento']}</b> lançamento(s), somando <b>{brl(venc['valor_sem_vencimento'])}</b>, não têm vencimento no Financeiro (#798) e ficaram no mês da competência. "
                                         + ("Costuma ser lançamento emitido antes do período que o Financeiro baixa, ou o Financeiro ainda não atualizado: use <b>Atualizar agora</b>." if venc["financeiro"]
                                            else "O relatório do Financeiro ainda não foi baixado: use <b>Atualizar agora</b>. Enquanto isso, todos os meses estão pela competência.")})
            extras["planilha"] = pl.montar(d, lancamentos_do_financeiro(), inicio, ym_hoje)

            # ---- repasse medico (Honorario Medico lancado x producao de cada medico)
            repasse = montar_repasse(d, abas.get(ABA_PROD), meses, ym_hoje, inicio, per=per)
            extras["repasse"] = repasse
            if repasse.get("ok") and repasse["sem_repasse"]:
                sr, ult = repasse["sem_repasse"], repasse["ultimo_repasse"]
                lista = ", ".join(f"<b>{e['rotulo']}</b> ({brl(e['producao'])})" for e in sr)
                atencao.append({"nivel": "atencao", "titulo": "Produção médica sem Honorário Médico lançado",
                                "texto": f"Há produção em {lista}, mas nenhum <b>Honorário Médico</b> com vencimento nesses meses"
                                         + (f"; o último repasse lançado é de <b>{ult['rotulo']}</b> ({brl(ult['bruto'])})." if ult else ".")
                                         + " Ou o repasse ainda não foi lançado, ou é pago fora do Klingo, ou está em outra categoria: enquanto isso, o total de despesas desses meses não inclui o repasse. Ver “Repasse médico”."})

            # ---- aviso global: a retencao existia no historico e sumiu
            ret_antes = sum(m["retido"] for ym, m in meses.items() if ym < inicio)
            ret_depois = sum(m["retido"] for ym, m in meses.items() if ym >= inicio and m["situacao"] != "previsto")
            if conf["liquido"] and ret_antes > 0 and ret_depois == 0 and any(m["total"] for ym, m in meses.items() if ym >= inicio):
                cats = d[(d["_ym"] < inicio) & (d["Bruto"] - d["Líquido"] > 0.005)]["Despesa"].unique()
                atencao.append({"nivel": "info", "titulo": "Nenhuma retenção registrada desde o início do Klingo",
                                "texto": f"Antes de {pc.rotulo_mes(inicio)} o valor líquido era <b>{brl(ret_antes)}</b> menor que o bruto ({html.escape(', '.join(map(str, cats[:3])))}, com retenção de imposto). "
                                         "Desde então o líquido é igual ao bruto em todas as despesas. Se os prestadores ainda têm imposto retido, ele não está sendo lançado no Klingo e o líquido mostrado aqui fica maior que o desembolso real."})
            if conf["sem_par_13509"] or conf["sem_par_13505"] or conf["liquido_maior"]:
                atencao.append({"nivel": "info", "titulo": "Os dois relatórios não casaram linha a linha",
                                "texto": f"{conf['sem_par_13509']} linha(s) só no relatório de líquido, {conf['sem_par_13505']} só no de bruto e {conf['liquido_maior']} com líquido maior que o bruto. "
                                         "Costuma ser lançamento criado entre as duas consultas: use <b>Atualizar agora</b> de novo."})

            # ---- o periodo escolhido no filtro De/Ate (varios meses juntos): entra por ultimo, para nao somar nos historicos acima
            if per and not per.unico:
                if per.exato:
                    info["notas"] = ["As despesas são contadas pela data de vencimento de cada lançamento; as médias dos outros meses valem pelo tamanho do período."]

                def anterior_de(q: pc.Periodo):
                    a = q.anterior
                    return montar_mes(a.fim, d, ctx, None, per=a) if any(y in tab.columns for y in a.yms) else None
                pc.acrescentar_periodo(meses, per, lambda q: montar_mes(q.fim, d, ctx, anterior_de(q), per=q))
                for m in meses.values():
                    m.pop("_cats", None), m.pop("_forn", None)

    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else datetime.now()
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()), "hoje": hoje.isoformat(), "inicio_confiavel": pc.rotulo_mes(inicio),
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
