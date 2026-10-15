"""Conferencia dos numeros dos 4 menus (Metas, Faturamento, Financeiro, Cesta).

O que faz
  1. Gera de novo os 4 paineis com o que ja esta nas planilhas (nao consulta o Klingo).
  2. Recalcula, direto das planilhas e com outra logica, os numeros que cada painel mostra (somas, percentuais, totais).
  3. Cruza os relatorios entre si (producao x faturas x cesta x metas x financeiro).
Resultado: FALHA = conta errada (corrigir); AVISO = relatorios que nao fecham 100% entre si (entender); i = informacao.

Uso:  python conferir_numeros.py                 (ou de dois cliques em "Conferir Numeros.bat")
      python conferir_numeros.py --sem-regerar   confere os paineis como estao agora
Sai com codigo 1 se houver FALHA.
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

R = Path(__file__).resolve().parent.parent / "Dados do Indicadores CSI"   # pasta de dados (precisa ter sido aberta uma vez pelo Indicadores CSI.exe, que coloca os programas la)
PAINEIS = [("Faturamento", "gerar_faturamento.py", ["--sem-abrir"]), ("Financeiro", "gerar_financeiro.py", ["--sem-abrir"]),
           ("Cesta", "gerar_cesta.py", ["--sem-abrir"]), ("Acompanhamento de META", "gerar_dashboard.py", [])]


def norm(s):
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper().strip()


def regerar():
    env = {**os.environ, "PYTHONUTF8": "1"}
    for pasta, script, args in PAINEIS:
        r = subprocess.run([sys.executable, script, *args], cwd=R / pasta, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
        if r.returncode != 0:
            print(f"Não consegui gerar o painel {pasta}:\n{(r.stdout + r.stderr)[-600:]}")
            sys.exit(2)


def payload(caminho):
    h = Path(caminho).read_text(encoding="utf-8")
    m = re.search(r'<script[^>]*id="dados"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


RES = []   # (area, descricao, obtido, esperado, ok, grau)


def chk(area, desc, got, exp, tol=0.01, grau="FALHA"):
    if got is None and exp is None:
        ok = True
    elif got is None or exp is None:
        ok = False
    else:
        ok = abs(float(got) - float(exp)) <= tol
    RES.append((area, desc, got, exp, ok, grau))


def info(area, desc, valor):
    RES.append((area, desc, valor, None, True, "INFO"))


if "--sem-regerar" not in sys.argv:
    print("Gerando os paineis com as planilhas atuais (sem consultar o Klingo)...", flush=True)
    regerar()

# ------------------------------------------------------------------ dados
FAT = pd.read_excel(R / "Faturamento" / "Faturamento.xlsx", sheet_name=None)
FIN = pd.read_excel(R / "Financeiro" / "Financeiro.xlsx", sheet_name=None)
CES = pd.read_excel(R / "Cesta" / "Cesta de Exames.xlsx", sheet_name=None)
MET = pd.read_excel(R / "Acompanhamento de META" / "Acompanhamento de META.xlsx", sheet_name="Dados")
PF = payload(R / "Faturamento" / "Dashboard Faturamento.html")
PN = payload(R / "Financeiro" / "Dashboard Financeiro.html")
PC = payload(R / "Cesta" / "Dashboard Cesta.html")
PM = payload(R / "Acompanhamento de META" / "Dashboard Metas.html")
HOJE = date.fromisoformat(PF["hoje"])
ym = lambda s: pd.to_datetime(s).dt.strftime("%Y-%m")

# ================================================================== FATURAMENTO
prod = FAT["Receita Produzida"].copy()
prod["ym"] = ym(prod["Data"])
ctrl = FAT["Controle por Convênio"]
ab = FAT["Faturas em Aberto"].copy()
fe = FAT["Faturas Emitidas"].copy()
for c in ["Fatura - Data de Emissão", "Fatura - Data de Envio", "Fatura - Data de Vencimento", "Fatura - Data Fim", "Fatura - Data Inicial"]:
    fe[c] = pd.to_datetime(fe[c], errors="coerce")
fe["comp"] = fe["Fatura - Data Inicial"].dt.strftime("%Y-%m")
fe["op"] = fe["Operadora - Nome"].astype(str)
fe["st"] = fe["Fatura - Status"]
fe["v"] = pd.to_numeric(fe["Fatura - Valor"], errors="coerce")

A = "Faturamento"
for mes, m in PF["meses"].items():
    p = prod[prod["ym"] == mes]
    k = m["kpi"]
    rec = float(p["Valor"].sum())
    chk(A, f"{mes} receita = soma do #26", k["receita"], rec)
    chk(A, f"{mes} procedimentos = soma das quantidades", k["procedimentos"], float(p["Quantidade"].sum()))
    chk(A, f"{mes} pacientes distintos", k["pacientes"], p["Paciente"].nunique(), 0)
    part = float(p.loc[p["Operadora"].map(norm) == "PARTICULAR", "Valor"].sum())
    chk(A, f"{mes} particular", k["particular"], part)
    chk(A, f"{mes} particular % + convenios % = 100", (k["particular_pct"] or 0) + ((rec - part) / rec * 100 if rec else 0), 100.0, 0.01)
    for chave in ("pagadores", "unidades", "categorias"):
        chk(A, f"{mes} soma de '{chave}' = receita", sum(x["valor"] for x in m[chave]), rec)
        chk(A, f"{mes} '{chave}' somam 100%", sum(x["pct"] for x in m[chave]), 100.0 if rec else 0.0, 0.01)
    ult = [d for d in m["dias"] if d["acum"] is not None][-1]["acum"] if m["dias"] else 0
    chk(A, f"{mes} receita acumulada no ultimo dia = receita", ult, rec)
    c = ctrl[ctrl["Mês (filtro)"] == mes]
    chk(A, f"{mes} produzido por convenio = soma do #13329", sum(x["produzido"] or 0 for x in m["convenios"]), float(c["Produzido"].fillna(0).sum()))
    chk(A, f"{mes} guias = soma do #13329", sum(x["guias"] or 0 for x in m["convenios"]), float(c["Qtd. Guias"].fillna(0).sum()), 0)
    conv26 = rec - part
    chk(A, f"{mes} conferencia: convenios do #26", m["conferencia"]["relatorio26"], conv26)
    chk(A, f"{mes} conferencia: produzido do #13329", m["conferencia"]["relatorio13329"], float(c["Produzido"].fillna(0).sum()))
    prod13329 = float(c["Produzido"].fillna(0).sum())
    if prod13329:
        chk(A, f"{mes} #26 (convenios) x #13329 dentro de 2%", abs(conv26 - prod13329) / prod13329 * 100, 0.0, 2.0, "AVISO")
    chk(A, f"{mes} recebido (KPI) = soma do #13329", m["kpi"]["recebido_conv"], float(c["Recebido"].fillna(0).sum()))

va = ab["Valor Bruto"].fillna(0)
dias = ab["Vencimento"].map(lambda d: (HOJE - pd.to_datetime(d).date()).days if pd.notna(d) else None)
aberto = PF["aberto"]
chk(A, "em aberto: total = soma do #13328", aberto["total"], float(va.sum()))
chk(A, "em aberto: quantidade", aberto["qtd"], len(ab), 0)
chk(A, "em aberto: vencido = vencimento anterior a hoje", aberto["vencido_valor"], float(va[dias.fillna(-999) > 0].sum()))
chk(A, "em aberto: faixas somam o total", sum(f["valor"] for f in aberto["faixas"]), float(va[dias.notna()].sum()))
chk(A, "em aberto: por convenio soma o total", sum(x["valor"] for x in aberto["por_convenio"]), float(va.sum()))

F = PF["faturas"]
chk(A, "faturas: Ids distintos = linhas da aba", fe["Fatura - Id"].nunique(), len(fe), 0)
chk(A, "faturas: soma dos status = total", sum(v["qtd"] for v in F["status"].values()), len(fe), 0)
chk(A, "faturas: total do painel = linhas", F["total"], len(fe), 0)
for st, v in F["status"].items():
    chk(A, f"faturas: status '{st}' quantidade", v["qtd"], int((fe["st"] == st).sum()), 0)
    chk(A, f"faturas: status '{st}' valor", v["valor"], float(fe.loc[fe["st"] == st, "v"].fillna(0).sum()))
ae = fe[(fe["st"] == "A Enviar") & (fe["v"].fillna(0) > 0)]
ae_dias = (pd.Timestamp(HOJE) - ae["Fatura - Data de Emissão"].dt.normalize()).dt.days
a = F["a_enviar"]
chk(A, "a enviar: valor", a["valor"], float(ae["v"].sum()))
chk(A, "a enviar: quantidade", a["qtd"], len(ae), 0)
chk(A, "a enviar: faixas somam o valor", sum(f["valor"] for f in a["faixas"]), float(ae["v"].sum()))
chk(A, "a enviar: faixas somam a quantidade", sum(f["qtd"] for f in a["faixas"]), len(ae), 0)
chk(A, "a enviar: por convenio soma o valor", sum(x["valor"] for x in a["por_operadora"]), float(ae["v"].sum()))
chk(A, "a enviar: espera maxima", a["maior_espera"], int(ae_dias.max()) if len(ae) else 0, 0)
# cada convenio com o seu prazo, aprendido do historico (prazos_aprendidos no gerar_faturamento.py): confere as contas com os limites que o painel mostra
limite = {x["nome"]: x["atencao"] for x in a["prazos_aprendidos"]}
lim = ae["op"].map(lambda op: limite.get(op, 7))
chk(A, "a enviar: acima do prazo (quantidade)", a["acima_atencao"]["qtd"], int((ae_dias > lim).sum()), 0)
chk(A, "a enviar: acima do prazo (valor)", a["acima_atencao"]["valor"], float(ae.loc[ae_dias > lim, "v"].sum()))
# prazo habitual: com menos de 3 faturas enviadas e o maior que ja aconteceu; com mais, fica entre o menor e o maior
env_ok = fe[fe["st"].isin(["Enviada", "Movimentada"])].dropna(subset=["Fatura - Data de Envio", "Fatura - Data de Emissão"])
dias_env = (env_ok["Fatura - Data de Envio"].dt.normalize() - env_ok["Fatura - Data de Emissão"].dt.normalize()).dt.days.clip(lower=0)
for x in a["prazos_aprendidos"]:
    d = dias_env[env_ok["op"] == x["nome"]]
    chk(A, f"prazo de envio {x['nome']}: faturas enviadas", x["amostras"], len(d), 0)
    if len(d) < 3:
        chk(A, f"prazo de envio {x['nome']}: pouco historico = maior prazo", x["tipico"], float(d.max()))
    else:
        chk(A, f"prazo de envio {x['nome']}: habitual entre o menor e o maior", 1 if d.min() - 0.05 <= x["tipico"] <= d.max() + 0.05 else 0, 1, 0)
sem_hist = set(ae["op"]) - set(fe.loc[fe["st"].isin(["Enviada", "Movimentada"]), "op"])
chk(A, "a enviar: convenios que nunca enviaram", len(a["nunca_enviou"]["nomes"]), len(sem_hist), 0)
chk(A, "a enviar: valor dos que nunca enviaram", a["nunca_enviou"]["valor"], float(ae[ae["op"].isin(sem_hist)]["v"].sum()))
env = fe[fe["st"].isin(["Enviada", "Movimentada"])].dropna(subset=["Fatura - Data de Envio", "Fatura - Data de Vencimento"])
prazo = (env["Fatura - Data de Vencimento"] - env["Fatura - Data de Envio"]).dt.days
chk(A, "prazos: mediana envio->vencimento", F["prazos"]["pagamento"], float(prazo.median()))
ev = env[env["v"].fillna(0) > 0]
chk(A, "prazos: ponderado pelo valor", F["prazos"]["pagamento_pond"], float((((ev["Fatura - Data de Vencimento"] - ev["Fatura - Data de Envio"]).dt.days) * ev["v"]).sum() / ev["v"].sum()))
chk(A, "prazos: faturas usadas", F["prazos"]["qtd"], len(env), 0)
cn = F["cancelamento"]
chk(A, "cancelamento: total", cn["total"], len(fe), 0)
chk(A, "cancelamento: canceladas", cn["canceladas"], int((fe["st"] == "Cancelada").sum()), 0)
chk(A, "cancelamento: por usuario soma emitidas", sum(x["emitidas"] for x in cn["por_usuario"]), len(fe), 0)
chk(A, "cancelamento: por usuario soma canceladas", sum(x["canceladas"] for x in cn["por_usuario"]), int((fe["st"] == "Cancelada").sum()), 0)
chk(A, "cancelamento: por mes soma emitidas", sum(x["total"] for x in cn["por_mes"]), len(fe), 0)

for mes, m in PF["meses"].items():
    f = m["funil_ref"]
    ref = f["ym"]
    c = ctrl[ctrl["Mês (filtro)"] == ref]
    ativ = fe[(fe["comp"] == ref) & (fe["st"] != "Cancelada")]
    chk(A, f"funil {mes}(ref {ref}): produzido", f["produzido"], float(c["Produzido"].fillna(0).sum()))
    chk(A, f"funil {mes}(ref {ref}): faturado", f["faturado"], float(ativ["v"].fillna(0).sum()))
    chk(A, f"funil {mes}(ref {ref}): enviado + a enviar = faturado", f["enviado"] + f["a_enviar"], f["faturado"])
    chk(A, f"funil {mes}(ref {ref}): recebido = #13329", f["recebido"], float(c["Recebido"].fillna(0).sum()))
    chk(A, f"funil {mes}(ref {ref}): faturado nao passa do produzido", max(f["faturado"] - f["produzido"], 0), 0.0, 1.0, "AVISO")
    chk(A, f"funil {mes}(ref {ref}): recebido <= enviado <= faturado <= produzido", float(f["recebido"] <= f["enviado"] <= f["faturado"] <= f["produzido"]), 1.0, 0, "AVISO")
    pc_ = c.assign(k=c["Convênio"].map(norm)).groupby("k")["Produzido"].sum()
    fc_ = ativ.assign(k=ativ["op"].map(norm)).groupby("k")["v"].sum()
    j = pd.concat([pc_.rename("p"), fc_.rename("f")], axis=1).fillna(0)
    chk(A, f"funil {mes}(ref {ref}): falta faturar = soma dos convenios", f["falta"], float((j["p"] - j["f"]).clip(lower=0).sum()))

# ================================================================== FINANCEIRO
lan = FIN["Lançamentos"].copy()
part = FIN["Recebimento Particular"].copy()
lan["Vencimento"] = pd.to_datetime(lan["Vencimento"], errors="coerce")
lan["ym"] = lan["Vencimento"].dt.strftime("%Y-%m")
lan["tipo"] = lan["Tipo"].map(norm)
lan["pago"] = lan["Conta"].notna()
desp, rec_ = lan[lan["tipo"] == "DESPESAS"], lan[lan["tipo"] == "RECEITAS"]
part["ym"] = ym(part["Data do Atendimento"])
Fi = "Financeiro"
abv = ab[ab["Vencimento"].notna()].copy()
abv["ym"] = ym(abv["Vencimento"])
conv_por_mes = abv.groupby("ym")["Valor Bruto"].sum()
for mes, m in PN["meses"].items():
    d, r = desp[desp["ym"] == mes], rec_[rec_["ym"] == mes]
    chk(Fi, f"{mes} a pagar = despesas por vencimento", m["pagar"]["total"], float(d["Valor"].sum()))
    chk(Fi, f"{mes} pago + em aberto = a pagar", m["pagar"]["pago"] + m["pagar"]["aberto"], m["pagar"]["total"])
    chk(Fi, f"{mes} pago = despesas com Conta", m["pagar"]["pago"], float(d.loc[d["pago"], "Valor"].sum()))
    chk(Fi, f"{mes} categorias somam o a pagar", sum(x["valor"] for x in m["despesas_categoria"]), m["pagar"]["total"])
    chk(Fi, f"{mes} empresas somam o a pagar", sum(x["valor"] for x in m["despesas_empresa"]), m["pagar"]["total"])
    chk(Fi, f"{mes} receitas lancadas", m["receber"]["lancadas"], float(r["Valor"].sum()))
    chk(Fi, f"{mes} formas somam as receitas lancadas", sum(x["valor"] for x in m["formas"]), m["receber"]["lancadas"])
    chk(Fi, f"{mes} faturas de convenio = Faturamento (#13328) por vencimento", m["receber"]["convenios"], float(conv_por_mes.get(mes, 0.0)))
    chk(Fi, f"{mes} a receber = lancadas + convenios", m["receber"]["total"], m["receber"]["lancadas"] + m["receber"]["convenios"])
    chk(Fi, f"{mes} saldo = a receber - a pagar", m["saldo"], m["receber"]["total"] - m["pagar"]["total"])
    pm = part[part["ym"] == mes]
    chk(Fi, f"{mes} particular: bruto (#13297)", m["particular"]["bruto"], float(pm["Valor Bruto"].sum()))
    chk(Fi, f"{mes} particular: liquido = bruto - taxa", m["particular"]["liquido"], m["particular"]["bruto"] - m["particular"]["taxa"], 0.5)
    chk(Fi, f"{mes} particular: tipos somam o bruto", sum(x["bruto"] for x in m["particular"]["por_tipo"]), m["particular"]["bruto"])
chk(Fi, "vencidas: valor", PN["vencidas"]["valor"], float(desp[(~desp["pago"]) & desp["Vencimento"].notna() & (desp["Vencimento"].dt.date < HOJE)]["Valor"].sum()))
chk(Fi, "vencidas: faixas somam o valor", sum(x["valor"] for x in PN["vencidas"]["faixas"]), PN["vencidas"]["valor"])
for f_ in PN["fluxo"]:
    chk(Fi, f"fluxo {f_['ym']}: convenios = Faturamento por vencimento", f_["convenios"], float(conv_por_mes.get(f_["ym"], 0.0)))
    chk(Fi, f"fluxo {f_['ym']}: a pagar", f_["pagar"], float(desp.loc[desp["ym"] == f_["ym"], "Valor"].sum()))
chk(Fi, "linhas liquido = bruto - taxa (todas)", float(((part["Valor Bruto"] - part["Taxa"] - part["Valor Líquido"]).abs() > 0.02).sum()), 0.0, 0, "AVISO")
chk(Fi, "lancamentos: Ids duplicados", float(lan["Lançamento"].duplicated().sum()), 0.0, 0)

# ================================================================== CESTA
base = CES["Base Cesta"].copy()
base["Data"] = pd.to_datetime(base["Data"])
base["ym"] = base["Data"].dt.strftime("%Y-%m")
base["peso"] = base["Atendimento - Id"].fillna(1).astype(int)
base["valorT"] = base["Valor"].fillna(0) * base["peso"]
Ce = "Cesta"
chk(Ce, "base: linhas sem paciente (nao entram nas cestas)", float(base["Paciente - Id"].isna().sum()), 0.0, 0, "AVISO")
for mes, m in PC["meses"].items():
    g = base[base["ym"] == mes]
    k = m["kpi"]
    atend = g.drop_duplicates(["Paciente - Id", "Data"]).shape[0]
    chk(Ce, f"{mes} atendimentos (paciente + dia)", k["atend"], atend, 0)
    chk(Ce, f"{mes} pacientes distintos", k["pacientes"], g["Paciente - Id"].nunique(), 0)
    # receita do Klingo (#13280, antes do ajuste) e receita do painel (ajustada ao Faturamento, ou igual a do Klingo se o ajuste estiver desligado)
    chk(Ce, f"{mes} receita do Klingo (#13280) = soma(valor x peso)", m["conferencia"]["receita_13280"], float(g["valorT"].sum()))
    rec_painel = k["receita"]
    cobrados = int((g.groupby(["Paciente - Id", "Data"])["valorT"].sum() > 0).sum())
    chk(Ce, f"{mes} atendimentos com cobranca (paciente + dia com valor)", k["atend_cobrados"], cobrados, 0)
    chk(Ce, f"{mes} ticket = receita / atendimentos com cobranca", k["ticket"], rec_painel / cobrados if cobrados else None, 0.01)
    chk(Ce, f"{mes} perfil: atendimentos somam", sum(x["atend"] for x in m["perfil"]), atend, 0)
    chk(Ce, f"{mes} perfil: receita soma", sum(x["receita"] for x in m["perfil"]), rec_painel)
    # um paciente com dois convenios no mesmo dia aparece nos dois: a soma passa do total, mas no maximo pela quantidade desses casos
    multi_op = int((g.groupby(["Paciente - Id", "Data"])["Operadora"].nunique() - 1).clip(lower=0).sum())
    soma_op = sum(x["atend"] for x in m["operadoras"])
    chk(Ce, f"{mes} convenios: soma dos atendimentos entre o total e o total + casos de 2 convenios no dia", float(atend <= soma_op <= atend + multi_op), 1.0, 0)
    chk(Ce, f"{mes} convenios: receita soma", sum(x["receita"] for x in m["operadoras"]), rec_painel)
    chk(Ce, f"{mes} unidades: receita soma", sum(x["receita"] for x in m["unidades"]), rec_painel)
    chk(Ce, f"{mes} dias: atendimentos somam", sum(x["atend"] for x in m["dias"]), atend, 0)
    chk(Ce, f"{mes} dias: receita soma", sum(x["receita"] for x in m["dias"]), rec_painel)
    chk(Ce, f"{mes} modalidades: receita soma", sum(x["receita"] for x in m["modalidades"]), rec_painel)
    if not k["ajustada"]:
        chk(Ce, f"{mes} receita = soma(valor x peso) (sem ajuste)", rec_painel, float(g["valorT"].sum()))
    elif m["producao"]:
        # ajuste ligado: nos dias completos a receita da Cesta tem que fechar com a Receita Produzida (#26), recalculada direto da planilha
        pr = m["producao"]
        ate = date.fromisoformat(PC["ajuste"]["ate"])
        r26 = float(prod[(prod["ym"] == mes) & (pd.to_datetime(prod["Data"]).dt.date < ate)]["Valor"].sum())
        chk(Ce, f"{mes} receita do #26 (dias completos) recalculada", pr["receita_26"], r26)
        chk(Ce, f"{mes} receita ajustada fecha com o #26 (dias completos, 0,1%)", abs(pr["receita_ajustada"] - r26) / r26 * 100 if r26 else 0.0, 0.0, 0.1)
        chk(Ce, f"{mes} causas da diferenca somam a diferenca", sum(x["valor"] for x in pr["causas"]), pr["dif"], 0.01)
    c85 = CES["Procedimentos por Perfil"]
    c85 = c85[c85["Mês (filtro)"] == mes]
    chk(Ce, f"{mes} #13280 x #13285 (receita) conferem", m["conferencia"]["receita_13285"], m["conferencia"]["receita_13280"], 1.0)
    chk(Ce, f"{mes} receita do #13285 recalculada", m["conferencia"]["receita_13285"], float((c85["Valor"].fillna(0) * c85["Atendimentos (distintos)"]).sum()))
    chk(Ce, f"{mes} multi-exame entre 0 e 100", float(0 <= (k["multi"] or 0) <= 100), 1.0, 0)

# ================================================================== METAS
met = MET.copy()
met["Data do Atendimento"] = pd.to_datetime(met["Data do Atendimento"])
met["ym"] = met["Data do Atendimento"].dt.strftime("%Y-%m")
cfg = json.loads((R / "Acompanhamento de META" / "metas.json").read_text(encoding="utf-8"))
Me = "Metas"


def conta(unidade, regra, linhas):
    n = 0
    for _, r in linhas.iterrows():
        if norm(r["Unidade"]) != norm(unidade):
            continue
        classes = {t.strip().upper() for t in str(r["Procedimento - Classes"]).split(",") if t.strip()} if isinstance(r["Procedimento - Classes"], str) else set()
        proc, esp = norm(r["Procedimento"]), norm(r["Especialidade"])
        if "classe" in regra and regra["classe"].upper() not in classes:
            continue
        if "classes_iguais" in regra and classes != {c.upper() for c in regra["classes_iguais"]}:
            continue
        if "especialidade" in regra and esp != norm(regra["especialidade"]):
            continue
        if "procedimento_igual" in regra and proc != norm(regra["procedimento_igual"]):
            continue
        if "procedimento_contem" in regra and not any(norm(t) in proc for t in regra["procedimento_contem"]):
            continue
        if "procedimento_nao_contem" in regra and any(norm(t) in proc for t in regra["procedimento_nao_contem"]):
            continue
        n += 1
    return n


for mes, m in PM["meses"].items():
    linhas = met[met["ym"] == mes]
    chk(Me, f"{mes} total de atendimentos = linhas da planilha", m["total_atendimentos"], len(linhas), 0)
    cont_g = 0
    for g in m["grupos"]:
        gcfg = next(x for x in cfg["grupos"] if x["id"] == g["id"])
        soma_cap, soma_meta = 0, 0
        for it in g["itens"]:
            icfg = next(x for x in gcfg["itens"] if x["id"] == it["id"])
            chk(Me, f"{mes} {g['nome']} / {it['nome']}: realizado", it["realizado"], conta(gcfg["unidade"], icfg["regra"], linhas), 0)
            chk(Me, f"{mes} {g['nome']} / {it['nome']}: % = realizado / meta", it["pct"], it["realizado"] / it["meta"] * 100 if it["meta"] else 0.0, 0.01)
            cont_g += it["realizado"]
            soma_cap += min(it["realizado"], it["meta"])
            soma_meta += it["meta"]
        chk(Me, f"{mes} {g['nome']}: % do grupo", g["pct"], soma_cap / soma_meta * 100 if soma_meta else 0.0, 0.01)
    chk(Me, f"{mes} realizados + fora das metas = total", cont_g + m["total_fora"], m["total_atendimentos"], 0, "AVISO")

# ================================================================== CRUZADOS (so dias completos: o dia de hoje ainda esta chegando e cada planilha foi atualizada num horario)
X = "Cruzado"
for mes in sorted(set(PF["meses"]) & set(PC["meses"])):
    p = prod[(prod["ym"] == mes) & (pd.to_datetime(prod["Data"]).dt.date < HOJE)]
    g = base[(base["ym"] == mes) & (base["Data"].dt.date < HOJE)]
    mm = met[(met["ym"] == mes) & (met["Data do Atendimento"].dt.date < HOJE)]
    rec26, recC = float(p["Valor"].sum()), float(g["valorT"].sum())
    # a Cesta do Klingo mede ~6% menos que o #26 (exame repetido no dia, contraste/material, linhas de R$ 0): com o ajuste ligado o painel usa o #26 e a
    # conta fecha na area Cesta; so se o ajuste estiver desligado essa diferenca vira aviso
    if not PC["meses"].get(mes, {}).get("kpi", {}).get("ajustada"):
        chk(X, f"{mes} receita: Cesta x #26 (Faturamento) dentro de 2%", abs(rec26 - recC) / rec26 * 100 if rec26 else 0.0, 0.0, 2.0, "AVISO")
    info(X, f"{mes} receita #26 / Cesta (valor do Klingo, antes do ajuste)", f"R$ {rec26:,.2f} / R$ {recC:,.2f} (a Cesta mede {recC / rec26 * 100:.1f}% do #26)" if rec26 else "-")
    chk(X, f"{mes} linhas: Metas x #26 dentro de 2%", abs(len(mm) - len(p)) / len(p) * 100 if len(p) else 0.0, 0.0, 2.0, "AVISO")
    info(X, f"{mes} linhas: Cesta x #26 (a Cesta junta exames repetidos no dia e traz linhas de R$ 0)", f"{len(g)} / {len(p)} ({(len(g) - len(p)) / len(p) * 100:+.1f}%)" if len(p) else "-")
    info(X, f"{mes} linhas #26 / Metas / Cesta", f"{len(p)} / {len(mm)} / {len(g)}")
chk(X, "recebido (#13329) x faturas Movimentadas (#13355)", float(ctrl["Recebido"].fillna(0).sum()), float(fe.loc[fe["st"] == "Movimentada", "v"].fillna(0).sum()), 0.01, "AVISO")
envs = fe[fe["st"].isin(["Enviada", "Movimentada"]) & fe["Fatura - Envio - Protocolo"].notna()].copy()
envs["lote"] = envs["Fatura - Envio - Protocolo"].astype(str).str.strip()
ab2 = ab[ab["Nº do Lote"].notna()].copy()
ab2["lote"] = ab2["Nº do Lote"].astype(str).str.strip()
j = pd.concat([envs.groupby("lote")["v"].sum().rename("a"), ab2.groupby("lote")["Valor Bruto"].sum().rename("b")], axis=1)
chk(X, "lotes: #13355 (enviadas) x #13328 (em aberto) com valor diferente", float(((j["a"] - j["b"]).abs() > 0.01).sum()), 0.0, 0)
chk(X, "lotes em aberto sem correspondente no #13355", float(j["a"].isna().sum()), 0.0, 0)
sp = fe[(fe["st"] == "Enviada") & fe["Fatura - Envio - Protocolo"].isna()]
chk(X, "enviadas sem protocolo (#13355) x em aberto sem lote (#13328), valor", float(sp["v"].sum()), float(ab.loc[ab["Nº do Lote"].isna(), "Valor Bruto"].sum()), 0.01, "AVISO")
for ref in sorted(set(fe["comp"].dropna())):
    if ref < "2026-09":
        continue
    c = ctrl[ctrl["Mês (filtro)"] == ref]
    pcv = c.assign(k=c["Convênio"].map(norm)).groupby("k")["Produzido"].sum()
    fcv = fe[(fe["comp"] == ref) & (fe["st"] != "Cancelada")].assign(k=lambda d: d["op"].map(norm)).groupby("k")["v"].sum()
    jj = pd.concat([pcv.rename("p"), fcv.rename("f")], axis=1).fillna(0)
    chk(X, f"{ref} convenios com faturado > produzido (R$ 1 de tolerancia)", float(len(jj[jj["f"] > jj["p"] + 1])), 0.0, 0, "AVISO")
for mes in sorted(set(PF["meses"]) & set(PN["meses"])):
    p = prod[prod["ym"] == mes]
    pp = float(p.loc[p["Operadora"].map(norm) == "PARTICULAR", "Valor"].sum())
    bruto = float(part.loc[part["ym"] == mes, "Valor Bruto"].sum())
    chk(X, f"{mes} particular: recebido bruto (#13297) x produzido (#26) dentro de 5%", abs(pp - bruto) / pp * 100 if pp else 0.0, 0.0, 5.0, "AVISO")
    info(X, f"{mes} particular produzido (#26) / recebido bruto (#13297)", f"R$ {pp:,.2f} / R$ {bruto:,.2f}")
# creditos de convenio (Financeiro, ja sem impostos) = recebido (#13329) - retencoes das faturas movimentadas (#13355)
cred = FIN["Créditos de Convênio"]
ret = float(pd.to_numeric(fe.loc[fe["st"] == "Movimentada", "Fatura - Valor Retenções"], errors="coerce").fillna(0).sum())
chk(X, "creditos de convenio (Financeiro) = recebido (#13329) - retencoes das faturas movimentadas", float(cred["Valor Recebido"].fillna(0).sum()) if len(cred) else 0.0,
    float(ctrl["Recebido"].fillna(0).sum()) - ret, 0.01, "AVISO")
for nome, caminho in [("Faturamento", R / "Faturamento" / "Faturamento.xlsx"), ("Financeiro", R / "Financeiro" / "Financeiro.xlsx"),
                      ("Cesta", R / "Cesta" / "Cesta de Exames.xlsx"), ("Metas", R / "Acompanhamento de META" / "Acompanhamento de META.xlsx")]:
    info(X, f"planilha {nome} atualizada ha", f"{(time.time() - caminho.stat().st_mtime) / 60:.0f} min")

# ------------------------------------------------------------------ saida
falhas = [r for r in RES if not r[4] and r[5] == "FALHA"]
avisos = [r for r in RES if not r[4] and r[5] == "AVISO"]
oks = [r for r in RES if r[4] and r[5] != "INFO"]
fmt = lambda v: f"{v:,.2f}" if isinstance(v, float) else str(v)
for area in ("Faturamento", "Financeiro", "Cesta", "Metas", "Cruzado"):
    linhas = [r for r in RES if r[0] == area]
    print(f"\n=== {area}: {sum(1 for r in linhas if r[4] and r[5] != 'INFO')} ok · {sum(1 for r in linhas if not r[4] and r[5] == 'FALHA')} falha(s) · {sum(1 for r in linhas if not r[4] and r[5] == 'AVISO')} aviso(s)")
    for a_, d, got, exp, ok, grau in linhas:
        if grau == "INFO":
            print(f"   i  {d}: {got}")
        elif not ok:
            print(f"   {'X' if grau == 'FALHA' else '!'}  [{grau}] {d}: obtido={fmt(got)} esperado={fmt(exp)}")
print(f"\nTOTAL: {len(oks)} ok · {len(falhas)} falha(s) · {len(avisos)} aviso(s) · {len(RES)} checagens")
sys.exit(1 if falhas else 0)
