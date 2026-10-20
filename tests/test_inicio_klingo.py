"""O Klingo so passou a ser usado em setembro/2026: o que vem de antes e teste ou do sistema anterior (Clinical).
Nenhum painel pode usar isso como historico, media, comparacao ou previsao.

Rodar:  python -m unittest discover -s tests -v
"""
import json
import re
import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import painel_comum as pc  # noqa: E402


class InicioKlingoTest(unittest.TestCase):
    def test_vem_do_modulos_json(self):
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(cfg["inicio_klingo"], "2026-09")
        self.assertEqual((pc.INICIO_KLINGO, pc.INICIO_KLINGO_DIA), ("2026-09", "2026-09-01"))
        self.assertTrue(pc.antes_do_klingo("2026-08") and pc.antes_do_klingo("2026-08-31"))
        self.assertFalse(pc.antes_do_klingo("2026-09") or pc.antes_do_klingo("2026-09-01"))
        self.assertEqual(pc.a_partir_do_klingo(["2026-10", "2026-07", "2026-09"]), ["2026-09", "2026-10"])
        self.assertEqual(pc.a_partir_do_klingo(["2026-07", "2026-09"], permitir_antes=True), ["2026-07", "2026-09"])

    def test_nenhum_painel_comeca_antes_do_klingo(self):
        # so a Despesas traz o historico da planilha antiga (marcado como "parcial" e fora de media, comparacao e previsao)
        for pasta in sorted(RAIZ.glob("*/relatorios.json")):
            defn = json.loads(pasta.read_text(encoding="utf-8-sig"))
            if pasta.parent.name == "Despesas":
                continue
            self.assertGreaterEqual(defn["primeiro_mes"], pc.INICIO_KLINGO, f"{pasta.parent.name}: primeiro_mes antes do Klingo")

    def test_periodo_pedido_ignora_meses_de_antes(self):
        meses = {"2026-07": {}, "2026-08": {}, "2026-09": {}, "2026-10": {}}
        per, info = pc.periodo_pedido("2026-07", "2026-10", meses)
        self.assertEqual((per.ini, per.fim), ("2026-09", "2026-10"))
        self.assertTrue(info["antes_klingo"] and info["recortado"])
        per, info = pc.periodo_pedido("2026-07", "2026-08", meses)   # tudo de antes: nao ha o que mostrar
        self.assertIsNone(per)
        self.assertTrue(info["vazio"] and info["antes_klingo"])
        per, info = pc.periodo_pedido("2026-09", "2026-10", meses)
        self.assertFalse(info["antes_klingo"])
        # a Despesas pode pedir o historico da planilha antiga
        per, info = pc.periodo_pedido("2026-07", "2026-10", meses, permitir_antes=True)
        self.assertEqual((per.ini, per.fim, info["antes_klingo"]), ("2026-07", "2026-10", False))

    def test_periodo_anterior_nao_vai_para_antes_do_klingo(self):
        meses = {"2026-08": {}, "2026-09": {}, "2026-10": {}, "2026-11": {}}
        montar = lambda p: {}
        # setembro..outubro: o periodo anterior seria julho..agosto (teste): sem comparacao
        per = pc.Periodo("2026-09", "2026-10")
        pc.acrescentar_periodo(meses, per, montar)
        self.assertIsNone(meses["2026-09..2026-10"]["chave_anterior"])
        # recorte de dias que comeca em setembro: o anterior invadiria agosto
        per = pc.Periodo("2026-09-10", "2026-09-25")
        pc.acrescentar_periodo(meses, per, montar)
        self.assertIsNone(meses["2026-09-10..2026-09-25"]["chave_anterior"])
        # tudo depois do inicio: compara normalmente
        meses.update({"2026-12": {}, "2027-01": {}})
        per = pc.Periodo("2026-12", "2027-01")
        pc.acrescentar_periodo(meses, per, montar)
        self.assertEqual(meses["2026-12..2027-01"]["chave_anterior"], "2026-10..2026-11")
        # a Despesas decide por conta propria (mes de antes e "parcial" e ja fica fora da comparacao)
        meses2 = {"2026-07": {}, "2026-08": {}, "2026-09": {}}
        pc.acrescentar_periodo(meses2, pc.Periodo("2026-08", "2026-09"), montar, permitir_antes=True)
        self.assertIsNotNone(meses2["2026-08..2026-09"]["chave_anterior"])

    def test_payload_sem_meses_de_antes(self):
        p = pc.completar_payload({"meses": {"2026-08": {}, "2026-09": {}, "2026-10": {}}})
        self.assertEqual(sorted(p["meses"]), ["2026-09", "2026-10"])
        self.assertEqual(p["todos_meses"], ["2026-09", "2026-10"])
        self.assertEqual(p["inicio_klingo"], "2026-09")
        self.assertIn("setembro/2026", p["aviso_klingo"])
        d = pc.completar_payload({"meses": {"2026-07": {}, "2026-09": {}}, "historico_antes_klingo": True})
        self.assertEqual(d["todos_meses"], ["2026-07", "2026-09"])


class SuprimentosTest(unittest.TestCase):
    def test_historico_e_pendencias_so_do_klingo_em_diante(self):
        sys.path.insert(0, str(RAIZ / "Suprimentos"))
        import gerar_suprimentos as gs
        movs = pd.DataFrame([{gs.M_ES: "Saída", gs.M_DATA: datetime(2026, d[0], d[1], 9), gs.M_TIPO: "Consumo", gs.M_ITEM: "LUVA", gs.M_UN: "UN", gs.M_GRUPO: "G",
                              gs.M_FORN: None, gs.M_ENT: 0, gs.M_SAI: 1, gs.M_CONS: -1, gs.M_VT: 0.0, gs.M_VU: 0.0, gs.M_LOCAL: "ESTOQUE PRINCIPAL", gs.M_CC: "RM",
                              gs.M_USU: "u1"} for d in ((7, 10), (8, 20), (9, 5), (10, 5))])
        sols = pd.DataFrame([{gs.S_USU: "u1", gs.S_ID: i, gs.S_DATA: datetime(2026, mes, 10, 10), gs.S_ITEM: "LUVA", gs.S_GRUPO: "G", gs.S_UN: "UN", gs.S_PEND: "S",
                              gs.S_OBS: "", gs.S_QS: 10.0, gs.S_QA: 0.0, gs.S_VA: 0.0, gs.S_CC: "RM", gs.S_LOCAL: "ESTOQUE PRINCIPAL"} for i, mes in enumerate((7, 8, 9, 10))])
        m, s = gs.preparar_mov(movs), gs.preparar_sol(sols, datetime(2026, 10, 20).date())
        self.assertEqual([x["ym"] for x in gs.montar_evolucao(m, s)], ["2026-09", "2026-10"])

    def test_consumo_medio_por_setor(self):
        sys.path.insert(0, str(RAIZ / "Suprimentos"))
        import gerar_suprimentos as gs
        hoje = datetime(2026, 10, 20).date()
        linhas = [(1, (9, 1), "FOLHA A4", "RM", 100.0), (2, (9, 11), "FOLHA A4", "RM", 100.0), (3, (9, 11), "FOLHA A4", "RECEPCAO", 50.0),
                  (4, (10, 20), "FOLHA A4", "RECEPCAO", 50.0), (5, (8, 5), "FOLHA A4", "RM", 999.0), (6, (9, 5), "LUVA", "RM", 10.0)]
        sols = pd.DataFrame([{gs.S_USU: "u1", gs.S_ID: i, gs.S_DATA: datetime(2026, d[0], d[1], 10), gs.S_ITEM: item, gs.S_GRUPO: "G", gs.S_UN: "FL", gs.S_PEND: "N",
                              gs.S_OBS: "", gs.S_QS: q, gs.S_QA: q, gs.S_VA: 0.0, gs.S_CC: cc, gs.S_LOCAL: "ESTOQUE PRINCIPAL"} for i, d, item, cc, q in linhas])
        s = gs.preparar_sol(sols, hoje)
        s = s[s["_ym"] >= pc.INICIO_KLINGO]   # o pedido de agosto e de teste e nao entra (como em gerar)
        uso = gs.montar_uso(s, hoje)
        self.assertEqual(uso["dias_base"], 50)   # 1/set a 20/out
        folha = next(x for x in uso["itens"] if x["item"] == "FOLHA A4")
        self.assertEqual(folha["total"], 300.0)
        self.assertEqual([x["nome"] for x in folha["setores"]], ["RM", "RECEPCAO"])
        self.assertEqual(folha["setores"][0]["total"], 200.0)
        self.assertAlmostEqual(folha["setores"][0]["pct"], 66.67, places=1)
        self.assertAlmostEqual(folha["por_dia"] * uso["mes"], 300 / 50 * 30.4375, places=3)
        self.assertEqual(folha["dias_com_pedido"], 3)   # dois pedidos em 11/09 contam um dia so
        self.assertAlmostEqual(folha["a_cada_dias"], 50 / 3)
        self.assertEqual([x["ym"] for x in folha["meses"]], ["2026-09", "2026-10"])
        self.assertEqual(gs.montar_uso(s.iloc[0:0], hoje)["itens"], [])


class FaturamentoTest(unittest.TestCase):
    def test_fatura_de_antes_do_klingo_fica_fora(self):
        sys.path.insert(0, str(RAIZ / "Faturamento"))
        import gerar_faturamento as gf
        f = pd.DataFrame({"Fatura - Id": [1, 2, 3, 4], "Fatura - Data de Emissão": pd.to_datetime(["2026-06-10", "2026-08-31", "2026-09-01", None])})
        self.assertEqual(gf.faturas_do_klingo(f)["Fatura - Id"].tolist(), [3, 4])
        self.assertTrue(gf.faturas_do_klingo(f.iloc[0:0]).empty)


class PaineisTest(unittest.TestCase):
    """Os paineis montados de verdade: nenhuma pagina oferece mes de antes do Klingo (a Despesas, que traz a planilha antiga, e a unica excecao)."""

    def test_paginas_sem_meses_de_antes(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import paineis_de_mentira as pm
        for nome, pagina in {**pm.PAGINAS, **pm.PAGINAS_SO_DINHEIRO}.items():
            html = pagina()
            achou = re.search(r'<script[^>]*id="dados"[^>]*>(.*?)</script>', html, re.S)
            with self.subTest(painel=nome):
                self.assertIsNotNone(achou, "a pagina nao traz os dados")
                dados = json.loads(achou.group(1).replace("<\\/", "</"))
                self.assertEqual(dados.get("inicio_klingo"), pc.INICIO_KLINGO)
                self.assertTrue(all(m >= pc.INICIO_KLINGO for m in dados.get("todos_meses", [])), dados.get("todos_meses"))


if __name__ == "__main__":
    unittest.main()
