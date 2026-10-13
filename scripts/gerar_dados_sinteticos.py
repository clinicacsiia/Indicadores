"""Gera dados SINTETICOS (inventados, sem paciente real) no formato de fonte.py (DADOS_DIR) para testar os paineis sem o Klingo.

Uso:  python scripts/gerar_dados_sinteticos.py <pasta de saida>
Depois: DADOS_DIR=<pasta> python painel_py/rodar_local.py faturamento > /tmp/faturamento.html
"""
import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(7)
HOJE = date(2026, 10, 13)
MESES = ["2026-09", "2026-10"]
CONVENIOS = ["UNIMED", "BRADESCO SAUDE", "GEAP", "AMOR SAUDE", "SUS CURSO", "PARTICULAR"]
UNIDADES = ["CSI", "CSI - 2", "PEDIATRIA"]


def dias_do_mes(ym):
    a, m = int(ym[:4]), int(ym[5:])
    d = date(a, m, 1)
    while d.month == m and d <= HOJE:
        yield d
        d += timedelta(days=1)


def iso(d, h=None):
    return d.strftime("%Y-%m-%d") if h is None else datetime(d.year, d.month, d.day, h, random.randint(0, 59), random.randint(0, 59)).strftime("%Y-%m-%d %H:%M:%S")


def bloco(aba, mes, colunas, linhas):
    return {"aba": aba, "mes": mes, "colunas": colunas, "linhas": linhas}


def metas():
    cols = ["Exames Realizados", "Unidade", "Procedimento - Classes", "Especialidade", "Data do Atendimento", "Procedimento", "Mês", "Convênio"]
    procs = [("RESSONANCIA MAGNETICA DE CRANIO", "RM", "DIAGNOSTICO POR IMAGEM"), ("ULTRASSONOGRAFIA DE ABDOME TOTAL", "US", "DIAGNOSTICO POR IMAGEM"),
             ("CONSULTA", "CONSULTA", "PEDIATRIA"), ("PREVENTIVO", "COLETA", "GINECOLOGIA")]
    out, i = [], 1000
    for ym in MESES:
        linhas = []
        for d in dias_do_mes(ym):
            if d.weekday() == 6:
                continue
            for _ in range(random.randint(8, 25)):
                i += 1
                p = random.choice(procs)
                linhas.append([i, random.choice(UNIDADES), p[1], p[2], iso(d, random.randint(7, 17)), p[0], ym, random.choice(CONVENIOS)])
        out.append(bloco("Dados", ym, cols, linhas))
    return out


def faturamento():
    out = []
    ops = CONVENIOS
    for ym in MESES:
        prod = []
        for d in dias_do_mes(ym):
            for _ in range(random.randint(10, 30)):
                op = random.choice(ops)
                prod.append([iso(d, random.randint(7, 17)), op, round(random.uniform(60, 900), 2), 1, random.choice(UNIDADES), random.choice(["Exame", "Consulta", "Imagem"]),
                             random.choice(["US ABDOME", "RM CRANIO", "CONSULTA", "TC TORAX"]), f"Paciente {random.randint(1, 400)}"])
        out.append(bloco("Receita Produzida", ym, ["Data", "Operadora", "Valor", "Quantidade", "Unidade", "Categoria", "Procedimento", "Paciente"], prod))
        ctrl = []
        for op in ops[:-1]:
            produzido = round(random.uniform(20000, 90000), 2)
            ctrl.append([op, random.randint(50, 300), produzido, round(produzido * random.uniform(0, .6), 2), round(produzido * random.uniform(0, .03), 2), 0.0, round(produzido * .4, 2)])
        out.append(bloco("Controle por Convênio", ym, ["Convênio", "Qtd. Guias", "Produzido", "Recebido", "Glosa", "Glosa Acatada", "A Receber (Saldo)"], ctrl))
        ab = []
        for n in range(15):
            venc = date(int(ym[:4]), int(ym[5:]), random.randint(1, 28))
            ab.append([9000 + n + (100 if ym == MESES[1] else 0), random.choice(ops[:-1]), iso(venc - timedelta(days=30)), iso(venc), round(random.uniform(0, 30000), 2), n])
        out.append(bloco("Faturas em Aberto", ym, ["Nº do Lote", "Convênio", "Data da Fatura", "Vencimento", "Valor Bruto", "Fatura"], ab))
        fat = []
        for n in range(40):
            em = date(int(ym[:4]), int(ym[5:]), random.randint(1, 12))
            st = random.choice(["A Enviar", "Enviada", "Movimentada", "Movimentada", "Cancelada"])
            env = iso(em + timedelta(days=random.randint(0, 3))) if st in ("Enviada", "Movimentada") else None
            fat.append([ (1 if ym == MESES[0] else 2) * 1000 + n, random.choice(ops[:-1]), st, None if st == "Cancelada" else round(random.uniform(3000, 40000), 2),
                       iso(em), env, iso(em + timedelta(days=35)) if env else None, iso(em - timedelta(days=2)), iso(date(int(ym[:4]), int(ym[5:]), 1)),
                       random.choice(["ana", "bia", "carlos"]), f"P{n}" if env and random.random() > .1 else None, 0.0, 0.0, random.randint(1, 9)])
        out.append(bloco("Faturas Emitidas", ym, ["Fatura - Id", "Operadora - Nome", "Fatura - Status", "Fatura - Valor", "Fatura - Data de Emissão", "Fatura - Data de Envio",
                                                  "Fatura - Data de Vencimento", "Fatura - Data Fim", "Fatura - Data Inicial", "Fatura - Usuário Responsável",
                                                  "Fatura - Envio - Protocolo", "Fatura - Valor Retenções", "Lançamento - Valor", "Operadora - Id"], fat))
    return out


GERADORES = {"metas": metas, "faturamento": faturamento}

if __name__ == "__main__":
    saida = Path(sys.argv[1])
    saida.mkdir(parents=True, exist_ok=True)
    for menu, fn in GERADORES.items():
        (saida / f"{menu}.json").write_text(json.dumps({"versao": time.time() - 600, "blocos": fn()}, ensure_ascii=False), encoding="utf-8")
    print("ok:", ", ".join(GERADORES), "->", saida)
