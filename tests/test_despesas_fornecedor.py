"""Despesas: a tabela "Fornecedor mês a mês" (Despesas/gerar_despesas.py: casar_lista e fornecedor_por_mes) e os itens de fornecedores_acompanhados.

Rodar:  python -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "Despesas"))
import gerar_despesas as gdesp  # noqa: E402


def lancamento(ym, forn, cat, valor, id_=1, dia=5, desc=""):
    return {"ID": id_, "Despesa": cat, "Competência": pd.Timestamp(f"{ym}-{dia:02d}"), "Descrição": desc, "Fornecedor": forn, "Bruto": valor, "Líquido": valor, "_ym": ym}


LISTA = [
    {"nome": "FOCUS TECNOLOGIA EM SISTEMAS"},                                             # sem trechos: o nome do fornecedor esta contido no item
    {"nome": "MEZZOW"},                                                                  # sem trechos: o item esta contido no nome do fornecedor
    {"nome": "JRL - INSS + IRRF", "fornecedor": ["INSS (INSTITUTO", "irrf (imposto"]},   # varios fornecedores num item; sem diferenciar maiusculas
    {"nome": "FOLHA SALARIAL", "fornecedor": ["DEPARTAMENTO PESSOAL"], "categoria": ["Folha Salarial"]},
    {"nome": "FOLHA ADIANTAMENTO", "fornecedor": ["DEPARTAMENTO PESSOAL"], "categoria": ["Adiantamento"]},
    {"nome": "KLINGO"},                                                                  # nada no Klingo com este nome
]


class FornecedorPorMes(unittest.TestCase):
    def setUp(self):
        self.d = pd.DataFrame([
            lancamento("2026-09", "FOCUS TECNOLOGIA", "Softwares", 673.0, 1),
            lancamento("2026-10", "FOCUS TECNOLOGIA", "Softwares", 700.0, 2),
            lancamento("2026-09", "MEZZOW HEALTH TECH", "Softwares", 100.0, 3),
            lancamento("2026-09", "MEZZOW HEALTH TECH", "Softwares", 50.5, 4),
            lancamento("2026-09", "INSS (INSTITUTO NACIONAL DO SEGURO SOCIAL)", "INSS", 26000.0, 5),
            lancamento("2026-09", "IRRF (IMPOSTO DE RENDA RETIDO NA FONTE)", "IRRF", 15000.0, 6),
            lancamento("2026-09", "DEPARTAMENTO PESSOAL", "Folha Salarial", 150000.0, 7),
            lancamento("2026-09", "DEPARTAMENTO PESSOAL", "Adiantamento Salarial", 40000.0, 8),
            lancamento("2026-09", "DEPARTAMENTO PESSOAL", "Férias", 9000.0, 9),
            lancamento("2026-10", None, "Tarifas", 90.0, 10),
            lancamento("2026-12", "FORA DOS MESES", "X", 1.0, 11),   # mes que nao esta na lista de meses: nao entra
        ])
        self.meses = ["2026-09", "2026-10", "2026-11"]
        self.r = gdesp.fornecedor_por_mes(self.d, self.meses, LISTA)
        self.lista = {x["nome"]: x for x in self.r["lista"]}
        self.todos = {x["nome"]: x for x in self.r["todos"]}

    def test_nomes_casam_nos_dois_sentidos(self):
        self.assertEqual(self.lista["FOCUS TECNOLOGIA EM SISTEMAS"]["valores"], [673.0, 700.0, 0.0])
        self.assertEqual(self.lista["MEZZOW"]["valores"], [150.5, 0.0, 0.0])
        self.assertEqual(self.lista["MEZZOW"]["qtds"], [2, 0, 0])

    def test_item_junta_varios_fornecedores(self):
        item = self.lista["JRL - INSS + IRRF"]
        self.assertEqual(item["valores"][0], 41000.0)
        self.assertEqual(len(item["fornecedores"]), 2)

    def test_categoria_separa_o_mesmo_fornecedor(self):
        self.assertEqual(self.lista["FOLHA SALARIAL"]["valores"][0], 150000.0)
        self.assertEqual(self.lista["FOLHA ADIANTAMENTO"]["valores"][0], 40000.0)   # as Férias (9 mil) nao entram em nenhum dos dois

    def test_item_sem_correspondencia_continua_na_lista(self):
        k = self.lista["KLINGO"]
        self.assertFalse(k["achou"])
        self.assertEqual(k["valores"], [0.0, 0.0, 0.0])
        self.assertEqual([x["nome"] for x in self.r["lista"]], [i["nome"] for i in LISTA])   # a ordem e a da lista

    def test_todos_os_fornecedores_somam_tudo_dos_meses_da_tabela(self):
        self.assertAlmostEqual(sum(x["total"] for x in self.r["todos"]), float(self.d["Bruto"].sum()) - 1.0)
        self.assertIn("(sem fornecedor)", self.todos)
        self.assertNotIn("FORA DOS MESES", self.todos)
        self.assertEqual(self.r["todos"][0]["nome"], "DEPARTAMENTO PESSOAL")   # do maior para o menor

    def test_lancamentos_apontam_para_o_fornecedor_e_o_item(self):
        nomes = [x["nome"] for x in self.r["todos"]]
        achados = [l for l in self.r["lancs"] if l[3] == 7]   # a folha salarial
        self.assertEqual(len(achados), 1)
        mes, forn, item, id_, dia, cat, desc, valor = achados[0]
        self.assertEqual((mes, nomes[forn], LISTA[item]["nome"], dia, cat, valor), (0, "DEPARTAMENTO PESSOAL", "FOLHA SALARIAL", "2026-09-05", "Folha Salarial", 150000.0))
        ferias = next(l for l in self.r["lancs"] if l[3] == 9)
        self.assertEqual(ferias[2], -1)   # lancamento de fornecedor da lista que nao pertence a nenhum item
        self.assertEqual(len(self.r["lancs"]), 10)

    def test_sem_lista_so_traz_todos(self):
        r = gdesp.fornecedor_por_mes(self.d, self.meses, [])
        self.assertEqual(r["lista"], [])
        self.assertTrue(all(l[2] == -1 for l in r["lancs"]))

    def test_cabe_em_json(self):
        json.dumps(self.r, allow_nan=False)


class ListaDoRelatoriosJson(unittest.TestCase):
    def test_lista_declarada(self):
        cfg = json.loads((RAIZ / "Despesas" / "relatorios.json").read_text(encoding="utf-8"))
        itens = cfg["fornecedores_acompanhados"]
        nomes = [i["nome"] for i in itens]
        self.assertEqual(len(nomes), len(set(nomes)))
        for i in itens:
            self.assertLessEqual(set(i), {"nome", "fornecedor", "categoria"})


if __name__ == "__main__":
    unittest.main()
