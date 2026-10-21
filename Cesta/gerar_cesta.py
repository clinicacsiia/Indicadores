"""Cesta de Exames: atualiza a planilha a partir do Klingo e gera 'Dashboard Cesta.html'.

Relatorios usados (todos filtrados por "Data do Atendimento"):
  #13280  Base Cesta de Exames      uma linha por paciente, procedimento e valor (base dos combos e do ticket)
  #13284  Exames por Faixa Etaria e Sexo      atendimentos distintos por procedimento, dia, faixa e sexo
  #13285  Procedimentos por Faixa Etaria e Sexo   atendimentos distintos e valor por procedimento, dia, faixa e sexo

Uso:  python gerar_cesta.py             so regenera o dashboard com o que ja esta na planilha
      python gerar_cesta.py --forcar    consulta o Klingo agora (como o botao) e regenera
      python gerar_cesta.py --historico baixa de novo todos os meses desde o primeiro
"""
import html
import sys
import webbrowser
from collections import Counter
from datetime import date, datetime
from itertools import combinations
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
sys.path.insert(0, str(PASTA))
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import guia_pendencias as gp  # noqa: E402
from equivalencias import bonito, modalidade, padroniza, titulo  # noqa: E402

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Cesta.html"
ABA_BASE, ABA_EXAMES, ABA_PROC = "Base Cesta", "Exames por Perfil", "Procedimentos por Perfil"

# busca de combos (os mesmos padroes da analise anterior)
MIN_CONT, MIN_CONF, MIN_LIFT, MAX_K = 10, 0.30, 2.0, 5
CONVERSAO_HIPOTETICA = 0.10     # "e se 10% dos que fizeram A tambem fizessem B"
LIMITE_VARIACAO = 10.0          # variacao (%) contra o mes anterior que merece aviso
QUEDA_MULTI_PONTOS = 3.0        # queda (pontos percentuais) na taxa de 2+ exames que merece aviso
MIN_DIAS_COMPARACAO = 5


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    return k.atualizar(PASTA, forcar=forcar, historico=historico)


def br(n) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- preparo dos dados
def faixa_modelo(f) -> str:
    """90-99 e 120-129 (idade impossivel) viram '90+', como na analise anterior."""
    f = "" if pd.isna(f) else str(f).lstrip("'")
    return "90+" if f in ("90-99", "120-129") else f


def ordem_faixa(f: str) -> int:
    return 999 if f.endswith("+") else int(f.split("-")[0])


def curto_unidade(nome) -> str:
    pref = "CLÍNICA DE SAÚDE E IMAGEM - "
    nome = str(nome)
    if nome.startswith(pref):
        resto = nome[len(pref):]
        return "CSI" if resto == "CSI" else f"CSI · {resto}"
    return bonito(nome)


def preparar_base(a: pd.DataFrame) -> pd.DataFrame:
    a = a.copy()
    a["Sexo"] = a["Sexo"].fillna("N/I")
    a["Faixa"] = a["Faixa Etária"].map(faixa_modelo)
    # "Atendimento - Id" so vale 1 ou 2: e quantos atendimentos iguais a linha representa (nao e um identificador)
    a["Peso"] = a["Atendimento - Id"].fillna(1).astype(int)
    a["QtdT"] = a["Quantidade"].fillna(1) * a["Peso"]
    a["ValorT"] = a["Valor"].fillna(0) * a["Peso"]
    # o que o Klingo entregou no #13280, antes do ajuste ao Faturamento (a conferencia compara com estes)
    a["PesoCesta"], a["QtdCesta"], a["ValorCesta"] = a["Peso"], a["QtdT"], a["ValorT"]
    a["Procedimento"] = a["Procedimento"].fillna("(sem nome)")
    a["Item"] = a["Procedimento"].map(padroniza)
    a["Modalidade"] = a["Item"].map(modalidade)
    a["Operadora"] = a["Operadora"].fillna("(sem operadora)")
    # uma cesta = um paciente em um dia
    a["Cesta"] = a.groupby(["Paciente - Id", "Data"]).ngroup()
    return a


def itens_por_cesta(g: pd.DataFrame) -> pd.Series:
    return g.groupby("Cesta")["Item"].nunique()


# ---------------------------------------------------------------- busca de combos e regras
def minerar(cestas: list[tuple]) -> Counter:
    cnt = Counter()
    for itens in cestas:
        for r in range(1, min(len(itens), MAX_K) + 1):
            for cb in combinations(itens, r):
                cnt[cb] += 1
    return cnt


def combos_e_regras(a: pd.DataFrame) -> dict:
    cestas = [tuple(sorted(s)) for s in a.groupby("Cesta")["Item"].apply(set)]
    n = len(cestas)
    cnt = minerar(cestas)
    cand = {s: c for s, c in cnt.items() if len(s) >= 2 and c >= MIN_CONT}
    nao_fechado = {s[:i] + s[i + 1:] for s, c in cand.items() if len(s) >= 3 for i in range(len(s)) if cnt[s[:i] + s[i + 1:]] == c}
    combos, regras = [], []
    for s, c in cand.items():
        if s in nao_fechado:
            continue
        lift_min = min((c * n) / (cnt[x] * cnt[tuple(i for i in s if i not in x)]) for r in range(1, len(s)) for x in combinations(s, r))
        if lift_min >= MIN_LIFT:
            combos.append({"itens": s, "n": c, "suporte": c / n, "coesao": c / max(cnt[(i,)] for i in s), "lift": lift_min})
        for r in range(1, len(s)):
            for x in combinations(s, r):
                y = tuple(i for i in s if i not in x)
                conf = c / cnt[x]
                lift = conf / (cnt[y] / n)
                if conf >= MIN_CONF and lift >= MIN_LIFT:
                    regras.append({"se": x, "entao": y, "n": c, "nse": cnt[x], "conf": conf, "lift": lift})
    return {"n": n, "cnt": cnt, "combos": combos, "regras": regras}


def montar_base(a: pd.DataFrame) -> dict:
    """Combos, oportunidades e consultas sobre TODOS os meses acumulados (precisam de volume para fazer sentido)."""
    if a.empty:
        return {}
    mb = combos_e_regras(a)
    por_item = a.groupby("Item").agg(receita=("ValorT", "sum"), exames=("Peso", "sum"))
    ticket_item = (por_item["receita"] / por_item["exames"]).to_dict()
    combos = sorted(mb["combos"], key=lambda c: (-c["n"], c["itens"]))
    oport = []
    for r in mb["regras"]:
        if len(r["entao"]) != 1 or len(r["se"]) > 2:
            continue
        ticket_b = ticket_item.get(r["entao"][0])
        sem = r["nse"] - r["n"]
        if not ticket_b or sem <= 0:
            continue
        oport.append({"se": [bonito(x) for x in r["se"]], "entao": bonito(r["entao"][0]), "nse": r["nse"], "juntos": r["n"], "sem": sem,
                      "conf": r["conf"] * 100, "lift": r["lift"], "ticket": ticket_b, "potencial": sem * ticket_b * CONVERSAO_HIPOTETICA})
    oport.sort(key=lambda o: -o["potencial"])

    cest_itens = a.groupby("Cesta").agg(itens=("Item", "nunique"), tem=("Item", lambda s: "CONSULTA" in set(s)), valor=("ValorT", "sum"))
    com = cest_itens[cest_itens["tem"]]
    com_exame, sozinha = (com["itens"] >= 2) & (com["valor"] > 0), (com["itens"] == 1) & (com["valor"] > 0)   # tickets sem os atendimentos de R$ 0
    consulta = {"cestas": int(len(com)), "com_exame": int((com["itens"] >= 2).sum()), "sozinhas": int((com["itens"] == 1).sum()),
                "ticket_com_exame": float(com.loc[com_exame, "valor"].mean()) if com_exame.any() else None,
                "ticket_sozinha": float(com.loc[sozinha, "valor"].mean()) if sozinha.any() else None}
    return {
        "cestas": mb["n"], "min_cont": MIN_CONT, "min_conf": MIN_CONF * 100, "min_lift": MIN_LIFT, "conversao": CONVERSAO_HIPOTETICA * 100,
        "periodo": f"{a['Data'].min():%d/%m/%Y} a {a['Data'].max():%d/%m/%Y}",
        "combos": [{"itens": [bonito(i) for i in c["itens"]], "n": c["n"], "pct": c["suporte"] * 100, "coesao": c["coesao"] * 100, "lift": c["lift"]} for c in combos],
        "oportunidades": oport, "consulta": consulta,
    }


# ---------------------------------------------------------------- calculos por mes
def cestas_cobradas(h: pd.DataFrame) -> int:
    """Atendimentos (paciente + dia) com algum valor: os de R$ 0 (retorno, cortesia, exame sem preco) contam como atendimento mas ficam fora do ticket."""
    return int((h.groupby("Cesta")["ValorT"].sum() > 0).sum())


def estat_grupo(h: pd.DataFrame, nome: str) -> dict:
    itens = itens_por_cesta(h)
    cest = int(h["Cesta"].nunique())
    cobradas = cestas_cobradas(h)
    receita = float(h["ValorT"].sum())
    return {"nome": nome, "atend": cest, "receita": receita, "exames": int(round(h["Peso"].sum())),
            "ticket": receita / cobradas if cobradas else None, "itens": float(itens.mean()) if len(itens) else None,
            "multi": float((itens >= 2).mean() * 100) if len(itens) else None}


def tabela_grupos(g: pd.DataFrame, por: str, rotulo, top: int, outros: str) -> list[dict]:
    ordem = g.groupby(por)["ValorT"].sum().sort_values(ascending=False)
    nomes = list(ordem.index)
    out = [estat_grupo(g[g[por] == n], rotulo(n)) for n in nomes[:top]]
    if len(nomes) > top:
        out.append(estat_grupo(g[~g[por].isin(nomes[:top])], f"{outros} ({len(nomes) - top})"))
    return out


def kpis(g: pd.DataFrame) -> dict:
    itens = itens_por_cesta(g)
    cest = int(g["Cesta"].nunique())
    cobradas = cestas_cobradas(g)
    receita = float(g["ValorT"].sum())
    return {"atend": cest, "atend_cobrados": cobradas, "sem_cobranca": cest - cobradas, "pacientes": int(g["Paciente - Id"].nunique()),
            "receita": receita, "exames": int(round(g["Peso"].sum())),
            "ticket": receita / cobradas if cobradas else None, "itens": float(itens.mean()) if len(itens) else None,
            "multi": float((itens >= 2).mean() * 100) if len(itens) else None}


LIMITE_PRODUCAO_PCT = 2.0       # diferenca (%) entre a receita da Cesta e a do Faturamento que merece aviso
LIMITE_FATOR = 60.0             # ajuste maior que isso numa linha indica pareamento errado, nao correcao: a linha fica como veio


def producao_do_faturamento() -> pd.DataFrame | None:
    """Receita Produzida (#26) do painel de Faturamento, se ele ja foi baixado."""
    try:
        p = k.carregar(PASTA.parent / "Faturamento")["Receita Produzida"]
        return p if len(p) else None
    except Exception:
        return None


def nome_norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def ate_dia_comum(a: pd.DataFrame, p26: pd.DataFrame, hoje: date) -> date:
    """Primeiro dia que ainda NAO esta completo nas duas bases: o de hoje chega aos poucos e cada planilha foi baixada num horario."""
    return min(hoje, a["Data"].max().date(), p26["Data"].max().date())


def _unir(c: pd.DataFrame, f: pd.DataFrame, chave: list[str], cols: list[str]) -> pd.DataFrame:
    """Junta os fatores (indexados pela chave) as linhas; quem nao tem par fica com fator 1."""
    if len(f):
        c = c.join(f, on=chave)
    for col in cols:
        if col not in c:
            c[col] = 1.0
    c[cols] = c[cols].fillna(1.0)
    return c


def ajustar_ao_faturamento(a: pd.DataFrame, p26: pd.DataFrame | None, hoje: date) -> pd.DataFrame:
    """Faz a receita e os exames da Cesta fecharem com a Receita Produzida (#26), que e a referencia da empresa.

    O #13280 mede menos que o #26 (exame repetido no dia vira uma linha so; contraste e material nao entram no valor). O ajuste
    usa so os dias completos das duas bases e depois vale para todas as linhas do mes:
      1) por mes + exame + convenio: cada linha ganha o fator (total do #26 / total da Cesta) do seu grupo;
      2) por mes + convenio: o que sobrou (grupos que existem de um lado so) e distribuido pelas linhas do convenio.
    Linhas de R$ 0 continuam em R$ 0 e mes sem dia completo nas duas bases fica como o Klingo entregou.
    Os valores originais ficam em ValorCesta, QtdCesta e PesoCesta."""
    a = a.copy()
    if p26 is None or p26.empty or a.empty:
        return a
    ate = ate_dia_comum(a, p26, hoje)
    c = a.assign(_exame=nome_norm(a["Procedimento"]), _conv=nome_norm(a["Operadora"]))
    p = p26.assign(_exame=nome_norm(p26["Procedimento"]), _conv=nome_norm(p26["Operadora"]))
    p_ok = p[p["Data"].dt.date < ate]
    ok = (c["Data"].dt.date < ate).to_numpy()
    lim = (1 / LIMITE_FATOR, LIMITE_FATOR)

    def fatores(cesta: pd.DataFrame, chave: list[str]) -> pd.DataFrame:
        cg = cesta.groupby(chave).agg(vc=("_v", "sum"), qc=("_q", "sum"))
        pg = p_ok.groupby(chave).agg(vp=("Valor", "sum"), qp=("Quantidade", "sum"))
        j = cg.join(pg, how="inner")
        return pd.DataFrame({"fv": (j["vp"] / j["vc"].where(j["vc"] > 0)).where(lambda s: s.between(*lim)),
                             "fq": (j["qp"] / j["qc"].where(j["qc"] > 0)).where(lambda s: s.between(*lim))})

    c["_v"], c["_q"] = c["ValorCesta"], c["QtdCesta"]
    chave1, chave2 = [k.COL_MES, "_exame", "_conv"], [k.COL_MES, "_conv"]
    c = _unir(c, fatores(c[ok], chave1), chave1, ["fv", "fq"])
    c["_v"], c["_q"] = c["ValorCesta"] * c["fv"], c["QtdCesta"] * c["fq"]
    c = _unir(c, fatores(c[ok], chave2).rename(columns={"fv": "gv", "fq": "gq"}), chave2, ["gv", "gq"])
    a["ValorT"] = c["ValorCesta"] * c["fv"] * c["gv"]
    a["QtdT"] = c["QtdCesta"] * c["fq"] * c["gq"]
    a["Peso"] = c["PesoCesta"] * c["fq"] * c["gq"]
    return a


def causas_da_diferenca(g: pd.DataFrame, p: pd.DataFrame) -> list[dict]:
    """Separa a diferenca (#26 menos Cesta, so dias completos) em causas, pareando as linhas por dia, unidade, exame e convenio:
    1o) mesmas linhas e mesmo valor; 2o) mesmo exame com valor diferente; o que sobra de cada lado e linha a mais ou a menos."""
    c = g.assign(_d=g["Data"].dt.date, _u=nome_norm(g["Unidade"]), _p=nome_norm(g["Procedimento"]), _o=nome_norm(g["Operadora"]), _v=g["Valor"].fillna(0).round(2))
    q = p.assign(_d=p["Data"].dt.date, _u=nome_norm(p["Unidade"]), _p=nome_norm(p["Procedimento"]), _o=nome_norm(p["Operadora"]),
                 _v=p["Valor"].fillna(0).round(2), _pac=nome_norm(p["Paciente"]))
    q["_rep"] = q.duplicated(["_pac", "_d", "_p", "_o"], keep="first")   # mesmo paciente, dia, exame e convenio: a 2a linha em diante

    def parear(x, y, chave):
        x, y = x.sort_values("_v", ascending=False, kind="stable"), y.sort_values("_v", ascending=False, kind="stable")
        x, y = x.assign(_n=x.groupby(chave).cumcount()), y.assign(_n=y.groupby(chave).cumcount())
        com = chave + ["_n"]
        em_y = x[com].merge(y[com].assign(_par=True), on=com, how="left")["_par"].notna().to_numpy()
        em_x = y[com].merge(x[com].assign(_par=True), on=com, how="left")["_par"].notna().to_numpy()
        return x[em_y], x[~em_y], y[em_x], y[~em_x]

    _, c_resto, _, q_resto = parear(c, q, ["_d", "_u", "_p", "_o", "_v"])
    c2, c_so, q2, q_so = parear(c_resto, q_resto, ["_d", "_u", "_p", "_o"])
    peso = float(g["ValorCesta"].sum() - g["Valor"].fillna(0).sum())   # atendimento com peso 2 vale em dobro na Cesta
    rep, outras = q_so[q_so["_rep"]], q_so[~q_so["_rep"]]
    return [
        {"id": "repetidas", "titulo": "Exame repetido no mesmo dia", "valor": float(rep["_v"].sum()), "linhas": int(len(rep)),
         "texto": "O mesmo paciente fez o mesmo exame mais de uma vez no dia (duas articulações, dois órgãos no Doppler...). O Faturamento traz cada um; a Cesta traz uma linha só."},
        {"id": "valor", "titulo": "Valor maior no Faturamento para o mesmo exame", "valor": float(q2["_v"].sum() - c2["_v"].sum()), "linhas": int(len(q2)),
         "texto": "Provável contraste, material ou pacote do convênio somado ao exame no Faturamento (a diferença se repete por convênio e por exame)."},
        {"id": "outras", "titulo": "Linhas que só existem no Faturamento", "valor": float(outras["_v"].sum()), "linhas": int(len(outras)),
         "texto": "Exames sem linha igual na Cesta no mesmo dia, unidade e convênio."},
        {"id": "so_cesta", "titulo": "Linhas que só existem na Cesta", "valor": -(float(c_so["_v"].sum()) + peso), "linhas": int(len(c_so)),
         "texto": "Itens avulsos (contraste, bisnaga) e atendimentos que a Cesta conta em dobro."},
    ]


def onde_esta_a_diferenca(g: pd.DataFrame, p: pd.DataFrame) -> dict:
    """Tabela 'quais sao' para o guia: exame x convenio com maior diferenca entre o Faturamento e a Cesta (dias completos)."""
    gc = g.assign(_e=nome_norm(g["Procedimento"]), _o=nome_norm(g["Operadora"])).groupby(["_o", "_e"]).agg(qc=("QtdCesta", "sum"), vc=("ValorCesta", "sum"))
    pf = p.assign(_e=nome_norm(p["Procedimento"]), _o=nome_norm(p["Operadora"])).groupby(["_o", "_e"]).agg(qp=("Quantidade", "sum"), vp=("Valor", "sum"))
    j = gc.join(pf, how="outer").fillna(0.0)
    j["dif"] = j["vp"] - j["vc"]
    j = j.reindex(j["dif"].abs().sort_values(ascending=False).index)
    linhas = [[titulo(o), bonito(e), br(r["qc"]), br(r["qp"]), brl(r["vc"]), brl(r["vp"]), brl(r["dif"])] for (o, e), r in j.iterrows() if abs(r["dif"]) >= 0.01]
    return gp.tabela(["Convênio", "Exame", "Qtd. Cesta", "Qtd. Faturamento", "Valor Cesta", "Valor Faturamento", "Diferença"], linhas, total=len(linhas), numericas=(2, 3, 4, 5, 6))


def conciliar_producao(ym: str, g: pd.DataFrame, p26: pd.DataFrame | None, ate: date | None) -> dict | None:
    """Receita da Cesta (#13280) x Receita Produzida (#26) no mesmo mes, so com dias completos (o dia de hoje ainda esta chegando).
    A diferenca e separada em causas (ver `causas_da_diferenca`) e, por exame, em 'linhas a menos' (quantidade) e 'valor unitario diferente' (preco).
    Compara o que o Klingo entregou (ValorCesta); 'receita_ajustada' e o valor que o painel usa depois do ajuste."""
    if p26 is None or ate is None:
        return None
    g = g[g["Data"].dt.date < ate]
    p = p26[(p26[k.COL_MES] == ym) & (p26["Data"].dt.date < ate)]
    if g.empty or p.empty:
        return None
    nome = nome_norm
    gc = g.assign(_p=nome(g["Procedimento"])).groupby("_p").agg(qtd_c=("QtdCesta", "sum"), val_c=("ValorCesta", "sum"))
    pf = p.assign(_p=nome(p["Procedimento"])).groupby("_p").agg(qtd_p=("Quantidade", "sum"), val_p=("Valor", "sum"))
    j = gc.join(pf, how="outer").fillna(0.0)
    unit_c = j["val_c"] / j["qtd_c"].where(j["qtd_c"] > 0)
    unit_p = j["val_p"] / j["qtd_p"].where(j["qtd_p"] > 0)
    j["dif"] = j["val_p"] - j["val_c"]
    j["efeito_qtd"] = (j["qtd_p"] - j["qtd_c"]) * unit_c.fillna(unit_p)
    receita_c, receita_p = float(j["val_c"].sum()), float(j["val_p"].sum())
    top = j.assign(unit_c=unit_c, unit_p=unit_p).reindex(j["dif"].abs().sort_values(ascending=False).index).head(5)
    return {
        "ate_dia": int(g["Data"].dt.day.max()), "receita_cesta": receita_c, "receita_26": receita_p, "dif": receita_p - receita_c,
        "receita_ajustada": float(g["ValorT"].sum()),
        "pct_cesta": receita_c / receita_p * 100 if receita_p else None,
        "linhas_cesta": int(len(g)), "linhas_26": int(len(p)),
        "efeito_qtd": float(j["efeito_qtd"].sum()), "efeito_valor": float(j["dif"].sum() - j["efeito_qtd"].sum()),
        "zero_cesta": int((g["Valor"].fillna(0) <= 0).sum()),
        "causas": causas_da_diferenca(g, p), "onde": onde_esta_a_diferenca(g, p),
        "top": [{"nome": bonito(n), "qtd_cesta": float(r["qtd_c"]), "qtd_26": float(r["qtd_p"]), "unit_cesta": r["unit_c"], "unit_26": r["unit_p"], "dif": float(r["dif"])}
                for n, r in top.iterrows()],
    }


def preco_usual(a: pd.DataFrame) -> tuple[dict, dict]:
    """Preco de referencia por (exame, convenio) e por exame (mediana das linhas com valor): serve para estimar o que as linhas de R$ 0 valeriam."""
    com_valor = a[a["Valor"].fillna(0) > 0]
    return com_valor.groupby(["Item", "Operadora"])["Valor"].median().to_dict(), com_valor.groupby("Item")["Valor"].median().to_dict()


def causas_texto(causas: list[dict], dif: float) -> str:
    """'Exame repetido no mesmo dia R$ 8,9 mil (44%); ...' so com as causas que pesam (mais de 3% da diferenca)."""
    partes = []
    for x in sorted(causas, key=lambda x: -x["valor"]):
        if not dif or abs(x["valor"]) / abs(dif) < 0.03:
            continue
        nome = html.escape(x["titulo"][0].lower() + x["titulo"][1:])
        partes.append(f"{nome}: <b>{brl(x['valor'])}</b> ({x['valor'] / dif * 100:.0f}%)" if x["valor"] > 0 else f"{nome}: reduzem a diferença em <b>{brl(-x['valor'])}</b>")
    return "; ".join(partes)


def montar_mes(ym: str, a: pd.DataFrame, b: pd.DataFrame, c: pd.DataFrame, hoje: date, p26: pd.DataFrame | None = None,
               ajustada: bool = False, ate_comum: date | None = None, per: pc.Periodo | None = None, a_todos: pd.DataFrame | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses ja reagrupado (ver montar_periodo): "ym" e o ultimo mes dele e o "mes anterior" e o periodo anterior.
    `a_todos` = a base de todos os meses (para o preco usual), quando `a` traz so o periodo."""
    ano, mes = int(ym[:4]), int(ym[5:])
    rot = per.rotulo if per else pc.rotulo_mes(ym)
    rot_ant = per.anterior.rotulo if per else pc.rotulo_mes(k.mes_mais(ym, -1))
    g = a[a[k.COL_MES] == ym]
    ym_ant = k.mes_mais(ym, -1)
    g_ant = a[a[k.COL_MES] == ym_ant]
    fechado = per.fechado(hoje) if per else date(ano, mes, 1) < date(hoje.year, hoje.month, 1)
    kp = kpis(g)

    # comparacao com o mes anterior (mes aberto: so os dias ja completos; mes fechado: totais)
    ref_txt, var_atend, var_ticket, var_multi = None, None, None, None
    if len(g_ant):
        if fechado:
            ref_g, atual_g, ref_txt = g_ant, g, f"o {'período' if per else 'mês'} anterior ({rot_ant})"
        elif hoje.day - 1 >= MIN_DIAS_COMPARACAO and not per:   # periodo ainda aberto: nao ha "o mesmo ponto" de varios meses
            ate = hoje.day - 1
            ref_g, atual_g = g_ant[g_ant["Data"].dt.day <= ate], g[g["Data"].dt.day <= ate]
            ref_txt = f"o mesmo ponto de {rot_ant} (até o dia {ate})"
        else:
            ref_g = None
        if ref_g is not None and len(ref_g):
            kr, ka = kpis(ref_g), kpis(atual_g)
            var_atend = (ka["atend"] / kr["atend"] - 1) * 100 if kr["atend"] else None
            var_ticket = (ka["ticket"] / kr["ticket"] - 1) * 100 if kr["ticket"] else None
            var_multi = ka["multi"] - kr["multi"] if kr["multi"] is not None and ka["multi"] is not None else None
    kp.update({"var_atend": var_atend, "var_ticket": var_ticket, "var_multi": var_multi, "ref_txt": ref_txt, "ajustada": ajustada})

    # perfil: exames por faixa e sexo (#13284) + atendimentos, ticket e % de 2+ exames (#13280)
    be = b[b[k.COL_MES] == ym].assign(Faixa=lambda d: d["Faixa Etária"].map(faixa_modelo), Sexo=lambda d: d["Sexo"].fillna("N/I"))
    exames_perfil = be.groupby(["Faixa", "Sexo"])["Atendimentos (distintos)"].sum()
    perfil = []
    for faixa in sorted(set(g["Faixa"]) | set(be["Faixa"]), key=ordem_faixa):
        h = g[g["Faixa"] == faixa]
        st = estat_grupo(h, faixa) if len(h) else {"atend": 0, "receita": 0.0, "ticket": None, "multi": None}
        perfil.append({"faixa": faixa, "atend": st["atend"], "receita": st["receita"], "ticket": st["ticket"], "multi": st["multi"],
                       "exames_f": float(exames_perfil.get((faixa, "F"), 0)), "exames_m": float(exames_perfil.get((faixa, "M"), 0))})

    # procedimentos e modalidades: quantidade e valor (#13285) + quem faz (#13284)
    cm = c[c[k.COL_MES] == ym].assign(Item=lambda d: d["Procedimento"].map(padroniza))
    cm["Total"] = cm["Valor"].fillna(0) * cm["Atendimentos (distintos)"]
    be["Item"] = be["Procedimento"].map(padroniza)
    if ajustada:   # com o ajuste, a receita por exame e tipo sai das linhas ajustadas (o #13285 so traz o valor do Klingo)
        por_proc = g.groupby("Item").agg(exames=("Peso", "sum"), receita=("ValorT", "sum")).sort_values("receita", ascending=False)
    else:
        por_proc = cm.groupby("Item").agg(exames=("Atendimentos (distintos)", "sum"), receita=("Total", "sum")).sort_values("receita", ascending=False)
    procs = []
    for item, r in por_proc.head(12).iterrows():
        quem = be[be["Item"] == item]
        tot = quem["Atendimentos (distintos)"].sum()
        mulheres = quem.loc[quem["Sexo"] == "F", "Atendimentos (distintos)"].sum()
        top_faixa = quem.groupby("Faixa")["Atendimentos (distintos)"].sum().sort_values(ascending=False)
        procs.append({"nome": bonito(item), "modalidade": modalidade(item), "exames": float(r["exames"]), "receita": float(r["receita"]),
                      "ticket": float(r["receita"] / r["exames"]) if r["exames"] else None,
                      "pct_mulheres": float(mulheres / tot * 100) if tot else None,
                      "faixa_top": top_faixa.index[0] if len(top_faixa) else None})
    if ajustada:
        mods = g.groupby("Modalidade").agg(exames=("Peso", "sum"), receita=("ValorT", "sum"))
    else:
        mods = cm.assign(Modalidade=cm["Item"].map(modalidade)).groupby("Modalidade").agg(exames=("Atendimentos (distintos)", "sum"), receita=("Total", "sum"))
    mods = mods.sort_values("receita", ascending=False)
    modalidades = [{"nome": n, "exames": float(r["exames"]), "receita": float(r["receita"]),
                    "pct": float(r["receita"] / mods["receita"].sum() * 100) if mods["receita"].sum() else 0.0} for n, r in mods.iterrows()]

    # evolucao por dia
    ult = 0 if per else (int(g["Data"].dt.day.max()) if len(g) else 0)   # num periodo de varios meses nao ha "dia do mes" que se compare
    por_dia = g.groupby(g["Data"].dt.day).agg(atend=("Cesta", "nunique"), receita=("ValorT", "sum"))
    cobrados_dia = (g.groupby([g["Data"].dt.day.rename("d"), "Cesta"])["ValorT"].sum() > 0).groupby(level=0).sum()
    dias = [{"d": d, "atend": int(por_dia["atend"].get(d, 0)), "cobrados": int(cobrados_dia.get(d, 0)), "receita": float(por_dia["receita"].get(d, 0.0))} for d in range(1, ult + 1)]

    # conferencia entre os tres relatorios (os valores do Klingo, antes do ajuste ao Faturamento)
    rec_13285 = float(cm["Total"].sum())
    conf = {"receita_13280": float(g["ValorCesta"].sum()), "receita_13285": rec_13285,
            "exames_13280": int(g["PesoCesta"].sum()), "exames_13285": int(cm["Atendimentos (distintos)"].sum()),
            "exames_13284": int(be["Atendimentos (distintos)"].sum())}

    producao = conciliar_producao(ym, g, p26, ate_comum)

    # pontos de atencao do mes
    alertas = []
    if producao and producao["pct_cesta"] is not None and abs(100 - producao["pct_cesta"]) >= LIMITE_PRODUCAO_PCT:
        abertura = (f"Nos dias completos de {rot} (até o dia {producao['ate_dia']}), o relatório da Cesta soma <b>{brl(producao['receita_cesta'])}</b>, "
                    f"<b>{producao['pct_cesta']:.1f}%</b> dos <b>{brl(producao['receita_26'])}</b> de receita produzida do Faturamento.")
        causas = causas_texto(producao["causas"], producao["dif"])
        if ajustada:
            texto = (f"{abertura} Este painel já usa o valor do Faturamento: a diferença de <b>{brl(abs(producao['dif']))}</b> foi distribuída pelos exames e convênios onde ela aparece "
                     f"(receita ajustada: <b>{brl(producao['receita_ajustada'])}</b>). De onde vem: {causas}.")
        else:
            nomes = ", ".join(html.escape(x["nome"]) for x in producao["top"][:3])
            parte_qtd = producao["efeito_qtd"] / producao["dif"] * 100 if producao["dif"] else 0.0
            texto = (f"{abertura} Cerca de {parte_qtd:.0f}% da diferença é por linhas a menos e o resto por valor unitário menor (mais afetados: {nomes}). "
                     "Use o Faturamento para o total de receita e a Cesta para comparar comportamento (combos, perfil, ticket relativo).")
        alertas.append({"nivel": "info", "titulo": "A receita da Cesta é menor que a do Faturamento" + (": valores ajustados" if ajustada else ""),
                        "itens": producao["onde"], "texto": texto})
    if var_atend is not None and abs(var_atend) >= LIMITE_VARIACAO:
        sobe = var_atend > 0
        alertas.append({"nivel": "ok" if sobe else "atencao", "titulo": "Atendimentos " + ("acima" if sobe else "abaixo") + " do mês anterior",
                        "texto": f"Os atendimentos estão <b>{abs(var_atend):.1f}% {'acima' if sobe else 'abaixo'}</b> de {ref_txt}."})
    if var_ticket is not None and abs(var_ticket) >= LIMITE_VARIACAO:
        sobe = var_ticket > 0
        alertas.append({"nivel": "ok" if sobe else "atencao", "titulo": "Ticket médio " + ("subiu" if sobe else "caiu"),
                        "texto": f"O ticket médio por atendimento {'subiu' if sobe else 'caiu'} <b>{abs(var_ticket):.1f}%</b> contra {ref_txt}."})
    if var_multi is not None and var_multi <= -QUEDA_MULTI_PONTOS:
        alertas.append({"nivel": "atencao", "titulo": "Menos pacientes fazendo mais de um exame",
                        "texto": f"A taxa de atendimentos com 2 ou mais exames caiu <b>{abs(var_multi):.1f} pontos</b> contra {ref_txt}."})
    zero = g[g["Valor"].fillna(0) <= 0]
    if len(g) and len(zero) / len(g) >= 0.01:
        por_conv, por_item = preco_usual(a if a_todos is None else a_todos)
        por_zero = zero.groupby(["Item", "Operadora"]).agg(n=("Peso", "size"), peso=("PesoCesta", "sum"))
        por_zero["preco"] = [por_conv.get((i, o), por_item.get(i, 0.0)) for i, o in por_zero.index]
        por_zero["em_jogo"] = por_zero["preco"] * por_zero["peso"]
        por_zero = por_zero.sort_values(["n", "em_jogo"], ascending=False)
        em_jogo = float(por_zero["em_jogo"].sum())
        consultas = int(zero["Modalidade"].eq("Consultas e avaliações").sum())
        exs = "; ".join(f"{html.escape(bonito(i))} · {html.escape(titulo(o))} ({int(r['n'])})" for (i, o), r in por_zero.head(2).iterrows())
        sem_cobr = f" {br(kp['sem_cobranca'])} atendimento(s) tinham só linhas de R$ 0." if kp["sem_cobranca"] else ""
        alertas.append({"nivel": "atencao", "titulo": "Linhas com valor zero",
                        "itens": gp.tabela(["Exame", "Convênio", "Linhas com R$ 0", "Preço usual", "Valor em jogo"],
                                           [[bonito(i), titulo(o), int(r["n"]), brl(r["preco"]) if r["preco"] else "—", brl(r["em_jogo"]) if r["em_jogo"] else "—"] for (i, o), r in por_zero.iterrows()],
                                           total=len(por_zero), numericas=(2, 3, 4)),
                        "texto": f"<b>{br(len(zero))}</b> linhas ({len(zero) / len(g) * 100:.1f}%) estão com valor R$ 0,00 ({br(consultas)} são consultas). Elas contam como atendimento, mas ficam fora do ticket médio "
                                 f"e do valor dos exames, então não distorcem mais a média.{sem_cobr} Se todas fossem cobradas pelo preço usual de cada convênio seriam cerca de <b>{brl(em_jogo)}</b>: "
                                 f"é um teto, porque retorno e cortesia não se cobram. Mais comuns: {exs}."})
    operadoras = tabela_grupos(g, "Operadora", titulo, 10_000, "Demais operadoras")
    for o in operadoras:
        if kp["multi"] and kp["multi"] >= 20 and o["atend"] >= 100 and o["multi"] is not None and o["multi"] <= 2 and not o["nome"].startswith("Demais"):
            alertas.append({"nivel": "info", "titulo": f"{o['nome']}: quase nenhum atendimento com 2+ exames",
                            "texto": f"São <b>{br(o['atend'])}</b> atendimentos e só <b>{o['multi']:.1f}%</b> têm 2 ou mais exames (a clínica toda: {kp['multi']:.1f}%). "
                                     "Pode ser regra do convênio ou cada exame registrado como um atendimento separado: vale conferir no Klingo."})
    if kp["multi"] is not None:
        alertas.append({"nivel": "info", "titulo": "Cesta de exames do mês",
                        "texto": f"Em média cada atendimento tem <b>{kp['itens']:.2f}</b> exames diferentes e <b>{kp['multi']:.1f}%</b> dos atendimentos têm 2 ou mais."})
    ordem = {"critico": 0, "atencao": 1, "ok": 2, "info": 3}
    alertas.sort(key=lambda x: ordem[x["nivel"]])
    gp.anotar("cesta", alertas, per.chave if per else ym)

    return {
        "rotulo": rot, "rotulo_ant": rot_ant, "fechado": fechado, "tem_dados": bool(len(g)),
        "ultimo_dia": f"{g['Data'].max():%d/%m/%Y}" if len(g) else None,
        "kpi": kp, "perfil": perfil, "procedimentos": procs, "modalidades": modalidades,
        "operadoras": operadoras,
        "unidades": tabela_grupos(g, "Unidade", curto_unidade, 10, "Demais unidades"),
        "dias": dias, "conferencia": conf, "producao": producao, "alertas": alertas,
    }


def montar_periodo(per: pc.Periodo, a, b, c, hoje, p26, ajustada, ate_comum) -> dict:
    """Varios meses juntos, com a mesma conta de um mes (ver pc.reagrupar)."""
    return montar_mes(per.fim, pc.reagrupar(a, k.COL_MES, per, datacol="Data"), pc.reagrupar(b, k.COL_MES, per, datacol="Data"),
                      pc.reagrupar(c, k.COL_MES, per, datacol="Data"), hoje,
                      pc.reagrupar(p26, k.COL_MES, per, datacol="Data") if p26 is not None else None, ajustada, ate_comum, per=per, a_todos=a)


def qualidade(a_completo: pd.DataFrame) -> list[dict]:
    q = []
    if a_completo.empty:
        return q
    q.append({"nivel": "atencao", "titulo": "Combos e grupos de procedimento vazios no Klingo",
              "texto": "As colunas “Combo” e “Grupo do Procedimento” do relatório de Base da Cesta vêm vazias, ou seja, não há combos cadastrados. "
                       "Os combos deste painel são descobertos observando o que os pacientes fazem juntos no mesmo dia, e o tipo de exame (ultrassom, ressonância etc.) é deduzido pelo nome."})
    pesos = int((a_completo["PesoCesta"] > 1).sum())
    q.append({"nivel": "info", "titulo": "“Atendimento - Id” não identifica o atendimento",
              "texto": f"A coluna só vale 1 ou 2 (2 em {pesos} linhas) e diz quantos atendimentos iguais a linha representa. Por isso um atendimento aqui é <b>um paciente em um dia</b>, "
                       f"e o valor de cada linha é multiplicado por esse número (assim a receita fecha com o relatório de Procedimentos por Perfil)."})
    maior = a_completo.loc[a_completo["Idade"].idxmax()]
    if maior["Idade"] >= 110:
        q.append({"nivel": "atencao", "titulo": f"Paciente com {int(maior['Idade'])} anos",
                  "texto": f"A idade é impossível (paciente {int(maior['Paciente - Id'])}, provável erro de cadastro). Ela foi agrupada em “90+” para não distorcer as faixas etárias."})
    n_ni = int((a_completo["Sexo"] == "N/I").sum())
    if n_ni:
        q.append({"nivel": "info", "titulo": f"{n_ni} linhas sem sexo informado", "texto": "Aparecem como “N/I” e ficam fora do gráfico de exames por sexo."})
    nomes = a_completo["Procedimento"].nunique()
    itens = a_completo["Item"].nunique()
    q.append({"nivel": "info", "titulo": "O mesmo exame aparece com nomes diferentes",
              "texto": f"{nomes} nomes de procedimento viram {itens} exames depois de unificar os nomes equivalentes (tabelas de convênios diferentes e nomes cortados). A lista de equivalências fica em equivalencias.py."})
    cetrus = a_completo[a_completo["Operadora"].str.upper().isin(["CETRUS", "SUS CURSO"])]   # o Klingo trazia o Cetrus como "SUS CURSO"
    if len(cetrus):
        q.append({"nivel": "info", "titulo": "Convênio Cetrus (antes “SUS CURSO”) está incluído",
                  "texto": f"São {br(len(cetrus))} linhas e {brl(cetrus['ValorT'].sum())} no total. Na análise anterior (pasta “Relatório Visão atendimento 13280 a 13285”) esse convênio era retirado dos números; aqui ele entra, porque também entra na receita do Faturamento."})
    return q


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    defn = k.ler_definicao(PASTA)
    abas = k.carregar(PASTA)
    a, b, c = abas[ABA_BASE], abas[ABA_EXAMES], abas[ABA_PROC]
    hoje = date.today()
    meses, base, qual = {}, {}, []
    per, info = None, None
    ajuste = {"ativo": False, "ate": None}
    if len(a):
        a = preparar_base(a)
        existentes = sorted({m for m in a[k.COL_MES].dropna().unique() if m >= defn["primeiro_mes"]})
        p26 = producao_do_faturamento()
        ate_comum = ate_dia_comum(a, p26, hoje) if p26 is not None else None
        ajustada = bool(defn.get("ajustar_ao_faturamento", True)) and p26 is not None
        if ajustada:
            a = ajustar_ao_faturamento(a, p26, hoje)
            ajuste = {"ativo": True, "ate": ate_comum.isoformat()}
        for ym in existentes:
            meses[ym] = montar_mes(ym, a, b, c, hoje, p26, ajustada, ate_comum)
        per, info = pc.periodo_pedido(de, ate, meses)
        if per and not per.unico:
            pc.acrescentar_periodo(meses, per, lambda p: montar_periodo(p, a, b, c, hoje, p26, ajustada, ate_comum))
        base = montar_base(a)
        qual = gp.anotar("cesta", qualidade(a))

    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else datetime.now()
    ym_hoje = hoje.strftime("%Y-%m")
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()), "hoje": hoje.isoformat(),
        "mes_padrao": per.chave if per else (ym_hoje if ym_hoje in meses else (max(meses) if meses else None)), "periodo": info,
        "meses": meses, "base": base, "qualidade": qual, "ajuste": ajuste,
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
