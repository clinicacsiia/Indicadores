"""Guias dos alertas (guia_pendencias.py): o caminho de menu do Klingo, o aviso de repasse sem lançamento (Despesas) e o de status de fatura que o painel não conhece.

Rodar:  python -m unittest discover -s tests -v
"""
import json
import os
import re
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
sys.path.insert(0, str(RAIZ / "Despesas"))
sys.path.insert(0, str(RAIZ / "Faturamento"))

import avisos  # noqa: E402
import gerar_despesas as gdesp  # noqa: E402
import gerar_faturamento as gf  # noqa: E402
import guia_pendencias as gp  # noqa: E402
from test_faturamento_sus import HOJE, fatura  # noqa: E402


class MenuDoKlingo(unittest.TestCase):
    def test_link_do_guia_traz_o_menu_quando_a_origem_e_conhecida(self):
        [a] = gp.anotar("faturamento", [{"nivel": "atencao", "titulo": "Faturas vencidas e ainda não baixadas", "texto": "x"}])
        self.assertEqual(a["guia"]["relatorios"][0]["id"], 13328)
        self.assertIn("aba Faturas", a["guia"]["relatorios"][0]["menu"])
        [b] = gp.anotar("despesas", [{"nivel": "atencao", "titulo": "Despesas sem fornecedor", "texto": "x"}])
        self.assertTrue(all("aba Lançamento" in r["menu"] for r in b["guia"]["relatorios"]))

    def test_relatorio_sem_menu_confirmado_continua_igual(self):
        self.assertNotIn("menu", gp._relatorio(13376))   # Baixas/Conciliação: a clínica não confirmou a aba
        self.assertEqual(set(gp._relatorio(13376)), {"id", "nome", "url"})

    def test_todo_menu_e_de_um_relatorio_que_existe(self):
        self.assertTrue(set(gp.MENUS) <= set(gp.RELATORIOS))


class RepasseSemLancamento(unittest.TestCase):
    """Produção médica nos dois últimos meses e nenhum Honorário Médico: o alerta vira aviso, com guia e a fila de médicos."""

    def pagina(self):
        hoje = date.today()
        ym = hoje.strftime("%Y-%m")
        ant = gdesp.k.mes_mais(ym, -1)
        dt = lambda m: pd.Timestamp(f"{m}-05")
        bruto = pd.DataFrame([{"Categoria": "Debito", "Despesa": "Energia Elétrica", "Competência": dt(m), "Valor": 100.0, "Descrição": "luz", "Fornecedor": "COELBA", gdesp.k.COL_MES: m} for m in (ant, ym)])
        liq = pd.DataFrame([{"ID do Lançamento": i, "Despesa": "Energia Elétrica", "Competência": dt(m), "Descrição": "luz", "Fornecedor": "COELBA", "Valor Líquido": 100.0, gdesp.k.COL_MES: m}
                            for i, m in enumerate((ant, ym), 1)])
        prod = pd.DataFrame([{"Data": dt(m), "Categoria": "Consulta", "Médico": med, "Procedimento": "p", "Operadora": "SUS", "Quantidade": 1, "Valor": v, gdesp.k.COL_MES: m}
                             for m in (ant, ym) for med, v in (("ANA CLARA LEDO", 1000.0), ("JOÃO CARNEIRO", 5000.0))])
        abas = {gdesp.ABA_BRUTO: bruto, gdesp.ABA_LIQ: liq, gdesp.ABA_PROD: prod}
        env = {"PORTAL_ARMAZENAMENTO": "arquivos", "VERCEL": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(gdesp.k, "carregar", lambda pasta: abas), mock.patch.object(gdesp, "arquivo_dados", lambda: Path("/nao/existe")):
            html = gdesp.gerar(devolver_html=True)
        return json.loads(re.search(r'<script id="dados" type="application/json">(.*?)</script>', html, re.S).group(1))

    def test_alerta_tem_id_guia_e_fila_de_medicos(self):
        d = self.pagina()
        [a] = [x for x in d["atencao"] if x["titulo"].startswith("Produção médica sem Honorário")]
        self.assertEqual(a["id"], "des_repasse_sem_honorario")
        self.assertEqual(a["escopo"], "")
        self.assertIn("Apuração", " ".join(a["guia"]["passos"]))
        self.assertIn("19/10/2026", a["guia"]["dica"])
        self.assertEqual(len(a["itens"]["linhas"]), 2)
        self.assertTrue(a["itens"]["linhas"][0][0].startswith("João"))
        self.assertEqual(a["itens"]["linhas"][0][1], "R$ 10.000,00")   # o maior primeiro: 2 meses x R$ 5.000

    def test_vai_para_a_aba_avisos(self):
        d = self.pagina()
        alertas, escopos = avisos.coletar(d, "despesas")
        achado = [a for a in alertas if a["tipo"] == "des_repasse_sem_honorario"]
        self.assertEqual(len(achado), 1)
        self.assertEqual(achado[0]["escopo"], "")
        self.assertTrue(achado[0]["sensivel"])   # painel só de dinheiro: só quem tem "Dados financeiros" vê


class StatusDeFaturaNovo(unittest.TestCase):
    def test_status_fora_dos_quatro_vira_alerta(self):
        f = gf.preparar_faturas(pd.DataFrame([fatura(1, "AMIL", "Enviada", 5, 800.0, enviada_ha=5), fatura(2, "AMIL", "Aguardando Protocolo", 3, 400.0), fatura(3, "SUS", "A Enviar", 0)]))
        fg = gf.montar_faturas(f, HOJE)
        self.assertEqual((fg["status_novo"]["qtd"], fg["status_novo"]["nomes"]), (1, ["Aguardando Protocolo"]))
        [al] = [x for x in gf.alertas_faturas(fg, {}, "Outubro/2026") if x["titulo"].startswith("Faturas em um status")]
        self.assertEqual(al["nivel"], "atencao")
        self.assertIn("Aguardando Protocolo", al["texto"])
        self.assertEqual(al["itens"]["linhas"][0][0], "2")

    def test_so_status_conhecidos_nao_alerta(self):
        f = gf.preparar_faturas(pd.DataFrame([fatura(1, "AMIL", "Enviada", 5, 800.0, enviada_ha=5), fatura(3, "SUS", "A Enviar", 0), fatura(4, "SUS", "Cancelada", 9)]))
        self.assertEqual(gf.montar_faturas(f, HOJE)["status_novo"]["qtd"], 0)

    def test_regra_do_guia_existe(self):
        self.assertFalse(gp.sem_guia("faturamento", "Faturas em um status que o painel não conhece"))
        self.assertFalse(gp.sem_guia("despesas", "Produção médica sem Honorário Médico lançado"))


if __name__ == "__main__":
    unittest.main()
