"""Paginas COM DADOS dos paineis mistos (Atendimento, Cesta, Suprimentos), geradas de DataFrames inventados.

O Klingo simulado de mock_nuvem.py so devolve as colunas declaradas no relatorios.json, e com elas esses paineis saem vazios ("Ainda nao ha dados").
Para testar o que a pagina mostra de verdade (por exemplo, sem os valores em R$ para quem nao tem "Dados financeiros"), aqui os DataFrames que o
gerador leria do banco sao montados na mao e entregues no lugar de `k.carregar`.
"""
import functools
import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent


def so_arquivos(f):
    """Gera a pagina como no computador da clinica (planilhas), mesmo que outro teste ja tenha ligado o modo Supabase (portal_nuvem faz isso ao ser importado).
    O resultado fica guardado: os testes pedem a mesma pagina varias vezes."""
    @functools.cache
    @functools.wraps(f)
    def interno():
        with mock.patch.dict(os.environ, {"PORTAL_ARMAZENAMENTO": "arquivos"}), mock.patch.dict(os.environ, {"VERCEL": ""}):
            return f()
    return interno


for _p in (RAIZ, RAIZ / "Atendimento", RAIZ / "Cesta", RAIZ / "Suprimentos", RAIZ / "Acompanhamento de META"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ------------------------------------------------------------------ Atendimento
@so_arquivos
def pagina_atendimento() -> str:
    import gerar_atendimento as ga
    rnd = random.Random(7)
    setores = ["CLÍNICA DE SAÚDE E IMAGEM - CSI 1", "CLÍNICA DE SAÚDE E IMAGEM - CSI 2", "CLÍNICA DE SAÚDE E IMAGEM - PEDIATRIA"]
    profs = [("DR ANA LIMA", "CARDIOLOGIA"), ("DR BRUNO REIS", "ORTOPEDIA"), ("DRA CARLA SOUZA", "PEDIATRIA"), ("RM 1", "RESSONANCIA"), ("TC 1", "TOMOGRAFIA")]
    linhas, fluxo = [], []
    d = datetime(2026, 9, 1)
    while d <= datetime(2026, 10, 14):
        if d.weekday() < 6:
            for _ in range(rnd.randint(8, 14)):
                prof, esp = rnd.choice(profs)
                conv, proc = rnd.choice(["UNIMED", "SUS", "PARTICULAR", "GEAP"]), rnd.choice(["CONSULTA", "RM CRANIO", "TC TORAX", "ECG"])
                dt = d.replace(hour=rnd.randint(7, 17), minute=rnd.randint(0, 59))
                ci = dt - timedelta(minutes=rnd.randint(2, 20))
                ini = dt + timedelta(minutes=rnd.randint(0, 50))
                fim = ini + timedelta(minutes=rnd.randint(10, 40))
                valor = rnd.choice([0, 120, 250, 380, 520, 900.5])
                linhas.append({ga.C_DATA: dt, ga.C_SETOR: rnd.choice(setores), ga.C_ESP: esp, ga.C_PROF: prof, ga.C_CONV: conv, ga.C_PROC: proc, ga.C_STATUS: "Finalizado",
                               ga.C_USER: rnd.choice(["recepcao.a", "recepcao.b"]), ga.C_VALOR: valor, ga.C_INI: ini, ga.C_FIM: fim, ga.C_DUR: (fim - ini).seconds / 60,
                               "Atendimentos (Qtde)": 1, "Idade do Paciente": 30, "Horário Agendado": 0, "Ticket Médio": valor})
                t = ci
                for etapa, dur in [("Cadastro", 4), ("Pagamento", 3), ("Chamado", max((ini - ci).seconds // 60 - 7, 1)), ("Em Atendimento", (fim - ini).seconds // 60), ("Finalizado", 1)]:
                    e0 = ini if etapa == "Em Atendimento" else t
                    e1 = e0 + timedelta(minutes=dur)
                    fluxo.append({ga.C_DATA: dt, ga.C_PROF: prof, ga.C_CONV: conv, "Etapa": etapa, "Check-In": ci, "Início da Etapa": e0, "Fim da Etapa": e1,
                                  ga.C_SETOR: "CSI", "Fila": "A", "Atendimentos (Qtde)": 1, "Espera após Check-In (min)": 1, "Duração da Etapa (min)": dur})
                    t = e1
        d += timedelta(days=1)
    abas = {ga.ABA: pd.DataFrame(linhas), ga.ABA_FLUXO: pd.DataFrame(fluxo)}

    def sem_metas(*a, **k):
        raise FileNotFoundError("sem metas")
    with mock.patch.object(ga, "lido_com_cache", lambda arq, nome, fn: abas if nome == "atendimento" else pd.DataFrame()), \
            mock.patch.object(ga.gd, "carregar_dados", sem_metas):
        return ga.gerar(devolver_html=True)


# ------------------------------------------------------------------ Cesta
@so_arquivos
def pagina_cesta() -> str:
    import gerar_cesta as gc
    rnd = random.Random(11)
    procs = [("CONSULTA", 150), ("US ABDOME TOTAL", 220), ("US TRANSVAGINAL", 200), ("RX TÓRAX PA", 90), ("RESSONANCIA CRANIO", 800), ("TOMOGRAFIA TORAX", 650),
             ("MAMOGRAFIA BILATERAL", 180), ("ELETROCARDIOGRAMA (ECG)", 60)]
    unidades = ["CLÍNICA DE SAÚDE E IMAGEM - CSI 1", "CLÍNICA DE SAÚDE E IMAGEM - CSI 2"]
    faixas = ["0-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70+"]
    a, b, c, p26 = [], [], [], []
    d, pid = date(2026, 9, 1), 1000
    while d <= date(2026, 10, 13):
        if d.weekday() < 6:
            for _ in range(rnd.randint(8, 14)):
                pid += 1
                sexo, faixa, conv, unid = rnd.choice(["F", "M"]), rnd.choice(faixas), rnd.choice(["UNIMED", "SUS", "PARTICULAR", "GEAP"]), rnd.choice(unidades)
                r = rnd.random()   # combos frequentes, para a venda cruzada aparecer
                escolha = [procs[0], procs[7]] if r < 0.4 else [procs[1], procs[2]] if r < 0.6 else [procs[0]] if r < 0.75 else rnd.sample(procs, rnd.choice([1, 2]))
                for nome, preco in escolha:
                    valor, ym, dia = rnd.choice([preco, preco, preco * 1.1, 0]), d.strftime("%Y-%m"), pd.Timestamp(d)
                    a.append({"Sexo": sexo, "Faixa Etária": faixa, "Atendimento - Id": 1, "Quantidade": 1, "Valor": valor, "Procedimento": nome, "Operadora": conv,
                              "Paciente - Id": pid, "Data": dia, "Unidade": unid, "Mês (filtro)": ym, "Procedimento - Id": 1, "Combo - Id": 0, "Idade": 30})
                    b.append({"Data": dia, "Procedimento": nome, "Faixa Etária": faixa, "Sexo": sexo, "Atendimentos (distintos)": 1, "Qtde de Procedimentos": 1, "Mês (filtro)": ym})
                    c.append({"Data": dia, "Procedimento": nome, "Faixa Etária": faixa, "Sexo": sexo, "Atendimentos (distintos)": 1, "Valor": valor, "Mês (filtro)": ym})
                    p26.append({"Data": dia, "Unidade": unid, "Procedimento": nome, "Operadora": conv, "Valor": valor * 1.02, "Quantidade": 1, "Paciente": f"P{pid}", "Mês (filtro)": ym})
        d += timedelta(days=1)
    abas = {gc.ABA_BASE: pd.DataFrame(a), gc.ABA_EXAMES: pd.DataFrame(b), gc.ABA_PROC: pd.DataFrame(c)}
    with mock.patch.object(gc.k, "carregar", lambda pasta: abas), mock.patch.object(gc, "producao_do_faturamento", lambda: pd.DataFrame(p26)):
        return gc.gerar(devolver_html=True)


# ------------------------------------------------------------------ Suprimentos
@so_arquivos
def pagina_suprimentos() -> str:
    import gerar_suprimentos as gs
    rnd = random.Random(3)
    itens = [("LUVA DE PROCEDIMENTO", "UN", "DESCARTAVEIS", 0.9), ("CONTRASTE GADOLINIO", "ML", "CONTRASTE", 12.5), ("SERINGA 10ML", "UN", "DESCARTAVEIS", 0.4),
             ("PAPEL LENCOL", "UN", "HIGIENE", 7.0), ("GEL USG", "ML", "CONSUMO", 0.0)]
    setores, locais = ["RESSONANCIA", "TOMOGRAFIA", "RECEPCAO", "PEDIATRIA"], ["ESTOQUE PRINCIPAL", "ESTOQUE RM", "ESTOQUE TC"]
    mov, sol = [], []
    d = datetime(2026, 9, 1)
    while d <= datetime(2026, 10, 14):
        for _ in range(rnd.randint(4, 9)):
            item, un, grupo, custo = rnd.choice(itens)
            tipo, q = rnd.choice(["Consumo", "Consumo", "Consumo", "Compra", "Transferência", "Inventário", "Doação Recebida"]), rnd.randint(1, 50)
            ent = q if tipo in ("Compra", "Inventário", "Doação Recebida") else 0
            sai = q if tipo in ("Consumo", "Transferência") else 0
            entrada_paga = custo and tipo in ("Compra", "Inventário")
            mov.append({gs.M_ES: "Entrada" if ent else "Saída", gs.M_DATA: d.replace(hour=9), gs.M_TIPO: tipo, gs.M_ITEM: item, gs.M_UN: un, gs.M_GRUPO: grupo,
                        gs.M_FORN: "FORNECEDOR X" if tipo == "Compra" else None, gs.M_ENT: ent, gs.M_SAI: sai, gs.M_CONS: ent - sai,
                        gs.M_VT: custo * q if entrada_paga else 0.0, gs.M_VU: custo if entrada_paga else 0.0,
                        gs.M_LOCAL: rnd.choice(locais), gs.M_CC: rnd.choice(setores), gs.M_USU: "u1"})
        for _ in range(rnd.randint(2, 6)):
            item, un, grupo, custo = rnd.choice(itens)
            pend = rnd.random() < 0.25
            sol.append({gs.S_USU: "user1", gs.S_ID: rnd.randint(1000, 9999), gs.S_DATA: d.replace(hour=10), gs.S_ITEM: item, gs.S_GRUPO: grupo, gs.S_UN: un,
                        gs.S_PEND: "S" if pend else "N", gs.S_OBS: "", gs.S_QS: 10.0, gs.S_QA: 0.0 if pend else 10.0, gs.S_VA: 0.0 if pend else custo * 10,
                        gs.S_CC: rnd.choice(setores), gs.S_LOCAL: rnd.choice(locais)})
        d += timedelta(days=1)
    abas = {gs.ABA_MOV: pd.DataFrame(mov), gs.ABA_SOL: pd.DataFrame(sol)}
    with mock.patch.object(gs.k, "carregar", lambda pasta: abas), \
            mock.patch.object(gs, "exames_por_dia", lambda: {date(2026, 10, i): 40 for i in range(1, 14)}), \
            mock.patch.object(gs, "gravar_modelo_custos", lambda *a, **k: None):
        return gs.gerar(devolver_html=True)


PAGINAS = {"atendimento": pagina_atendimento, "cesta": pagina_cesta, "suprimentos": pagina_suprimentos}
