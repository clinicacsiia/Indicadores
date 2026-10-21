"""Restricao por usuario no Atendimento: quem esta limitado a um responsavel (Configuracoes) so recebe os dados dele.

Rodar:  python -m unittest discover -s tests -v
A pagina vem de dados inventados (paineis_de_mentira.py). O teste de navegador abre a pagina entregue no Chromium (CHROMIUM=/caminho ou /opt/pw-browsers/chromium);
sem ele, e pulado.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
import paineis_de_mentira as pm  # noqa: E402
import portal_nuvem as pn  # noqa: E402
import restricao  # noqa: E402

DADOS = re.compile(r'<script id="dados" type="application/json">(.*?)</script>', re.S)


def dados_da_pagina(html: str) -> dict:
    return json.loads(DADOS.search(html).group(1).replace("<\\/", "</"))


def usuario(admin=False, **permissoes) -> dict:
    return {"admin": admin, "permissoes": permissoes, "financeiro": True}


class QuemEstaRestritoTest(unittest.TestCase):
    def test_so_texto_nao_vazio_restringe(self):
        for valor, esperado in (("carla", "carla"), (" Carla ", "carla"), ("", None), ("  ", None), (None, None), (True, None), (1, None)):
            with self.subTest(valor=valor):
                self.assertEqual(restricao.visao_do_perfil({"atendimento_visao": valor}, "atendimento"), esperado)
        self.assertIsNone(restricao.visao_do_perfil({}, "atendimento"))

    def test_so_o_atendimento_tem_visoes(self):
        self.assertIsNone(restricao.visao_do_perfil({"cesta_visao": "carla"}, "cesta"))

    def test_administrador_nunca_e_restrito(self):
        self.assertIsNone(pn.visao_restrita(usuario(admin=True, atendimento_visao="carla"), "atendimento"))
        self.assertEqual(pn.visao_restrita(usuario(atendimento_visao="carla"), "atendimento"), "carla")
        self.assertIsNone(pn.visao_restrita(usuario(atendimento=True), "atendimento"))


class PaginaLimitadaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = pm.pagina_atendimento()
        cls.completo = dados_da_pagina(cls.html)
        cls.ids = [v["id"] for v in cls.completo["visoes"]]

    def test_a_pagina_de_mentira_tem_mais_de_uma_visao(self):
        self.assertGreaterEqual(len(self.ids), 2)
        self.assertTrue(self.completo["meses"])

    def test_cada_pessoa_recebe_so_a_propria_visao(self):
        for ident in self.ids:
            with self.subTest(visao=ident):
                d = dados_da_pagina(restricao.limpar_html(self.html, "atendimento", ident))
                self.assertEqual([v["id"] for v in d["visoes"]], [ident])
                self.assertEqual(d["visao_fixa"], ident)
                self.assertEqual(d["por_visao"], {})
                self.assertEqual(d["meses"], self.completo["por_visao"][ident])
                self.assertIn(d["mes_padrao"], list(d["meses"]) + [None])

    def test_nada_das_outras_visoes_nem_da_clinica_inteira_sobra_na_pagina(self):
        for ident in self.ids:
            with self.subTest(visao=ident):
                entregue = restricao.limpar_html(self.html, "atendimento", ident)
                d = dados_da_pagina(entregue)
                for outro in (i for i in self.ids if i != ident):
                    self.assertNotIn(outro, d["por_visao"])
                    self.assertNotIn(self.completo["por_visao"][outro], [d["meses"]])
                # o total da clinica de cada mes nao pode ter ficado: o mes da pessoa so tem os atendimentos dela
                for ym, mes in d["meses"].items():
                    if ym in self.completo["meses"] and ".." not in ym:
                        self.assertLess(mes["kpis"]["n"], self.completo["meses"][ym]["kpis"]["n"], f"{ym}: a visão de {ident} tem de ser menor que a clínica inteira")

    def test_visao_que_nao_existe_nega_em_vez_de_mostrar_tudo(self):
        with self.assertRaises(restricao.VisaoInexistente):
            restricao.limpar_html(self.html, "atendimento", "ninguem")
        with self.assertRaises(pn.Negado) as e:
            pn.com_marcas(self.html, "atendimento", False, visao="ninguem")
        self.assertEqual(e.exception.status, 403)

    def test_pagina_sem_os_dados_nao_e_entregue(self):
        with self.assertRaises(RuntimeError):
            restricao.limpar_html("<html></html>", "atendimento", self.ids[0])

    def test_com_marcas_aplica_a_restricao_e_o_sigilo_juntos(self):
        entregue = pn.com_marcas(self.html, "atendimento", False, sem_financeiro=True, visao=self.ids[0])
        d = dados_da_pagina(entregue)
        self.assertEqual(d["visao_fixa"], self.ids[0])
        self.assertNotIn("receita", json.dumps(d))
        sem_restricao = dados_da_pagina(pn.com_marcas(self.html, "atendimento", False))
        self.assertNotIn("visao_fixa", sem_restricao)
        self.assertEqual(sem_restricao["por_visao"].keys(), self.completo["por_visao"].keys())

    def test_sem_nenhum_dado_a_pagina_continua_sem_vazar(self):
        vazia = {**self.completo, "meses": {}, "visoes": [], "por_visao": {}, "tem_dados": False}
        html = self.html[:DADOS.search(self.html).start(1)] + json.dumps(vazia) + self.html[DADOS.search(self.html).end(1):]
        d = dados_da_pagina(restricao.limpar_html(html, "atendimento", "carla"))
        self.assertEqual(d["meses"], {})
        self.assertEqual(d["por_visao"], {})


def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


@unittest.skipUnless(_chromium(), "sem Chromium")
class NoNavegadorTest(unittest.TestCase):
    """Abre a pagina entregue no Chromium: a pessoa restrita cai direto na visao dela, sem seletor e sem a opcao "Todos", mesmo pedindo ?visao=todos no endereco."""

    @classmethod
    def setUpClass(cls):
        cls.pasta = Path(tempfile.mkdtemp())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.porta = s.getsockname()[1]
        cls.srv = subprocess.Popen([sys.executable, "-m", "http.server", str(cls.porta), "-d", str(cls.pasta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def abrir(self, html: str, query: str = ""):
        (self.pasta / "p.html").write_text(html, encoding="utf-8")
        out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=8000", "--enable-logging=stderr", "--v=0",
                              "--dump-dom", f"http://127.0.0.1:{self.porta}/p.html{query}"], capture_output=True, text=True, timeout=300)
        return out.stdout, [l for l in out.stderr.splitlines() if "CONSOLE" in l and "rror" in l]

    @staticmethod
    def seletor(dom: str) -> str:
        """So o <select id="visao"> da pagina montada (o modelo tambem tem esse texto dentro do codigo JavaScript)."""
        m = re.search(r'<select id="visao">(.*?)</select>', dom, re.S)
        return m.group(1) if m else ""

    def test_a_pessoa_restrita_cai_na_visao_dela_sem_seletor(self):
        html = pm.pagina_atendimento()
        visoes = dados_da_pagina(html)["visoes"]
        v = visoes[0]
        dom, erros = self.abrir(pn.com_marcas(html, "atendimento", False, visao=v["id"]), "?visao=todos")
        self.assertFalse(erros, erros[:2])
        self.assertRegex(dom, r'<label class="mes-pick" id="visao-pick" hidden', "o seletor de responsável tem de continuar escondido")
        self.assertIn(f"Visão de <b>{v['nome']}</b>", dom)
        self.assertNotIn("<option", self.seletor(dom), "a opção “Todos” não pode existir na tela")
        for outro in visoes[1:]:
            self.assertNotIn(f"Visão de <b>{outro['nome']}</b>", dom)

    def test_quem_nao_esta_restrito_continua_com_o_seletor(self):
        dom, erros = self.abrir(pn.com_marcas(pm.pagina_atendimento(), "atendimento", False))
        self.assertFalse(erros, erros[:2])
        self.assertNotRegex(dom, r'id="visao-pick" hidden')
        self.assertIn('<option value="">Todos', self.seletor(dom))


if __name__ == "__main__":
    unittest.main()
