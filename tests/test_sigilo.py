"""Dados financeiros: o que um usuario SEM a permissao recebe dos paineis mistos (Atendimento, Cesta, Suprimentos).

Rodar:  python -m unittest discover -s tests -v
As paginas vem de dados inventados (paineis_de_mentira.py). O teste do navegador so roda se houver um Chromium (CHROMIUM=/caminho ou /opt/pw-browsers/chromium).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
import guia_pendencias as gp  # noqa: E402
import paineis_de_mentira as pm  # noqa: E402
import sigilo  # noqa: E402

DADOS = re.compile(r'<script id="dados" type="application/json">(.*?)</script>', re.S)
# nomes de campo que seriam dinheiro; o que e so CONTAGEM de problema de cadastro ("valor zerado") fica de fora de proposito
CAMPO_DINHEIRO = re.compile(r"receita|ticket|custo|valor|potencial|preco|producao|compra_valor|em_jogo", re.I)
PERMITIDOS = {
    "atendimento": {"valor_zero"},                       # quantos registros estao com valor R$ 0,00: problema de cadastro
    "cesta": set(),
    "suprimentos": set(),                                # nada: tudo de custo sai
}
REAIS_NAO_ZERO = re.compile(r"R\$(?:&nbsp;|\s)*(?!0[,.]00\b)\d")


def dados_da_pagina(html: str) -> dict:
    return json.loads(DADOS.search(html).group(1).replace("<\\/", "</"))


def chaves(no, achadas=None):
    achadas = set() if achadas is None else achadas
    if isinstance(no, dict):
        for k, v in no.items():
            achadas.add(k)
            chaves(v, achadas)
    elif isinstance(no, list):
        for v in no:
            chaves(v, achadas)
    return achadas


def textos(no):
    if isinstance(no, dict):
        for v in no.values():
            yield from textos(v)
    elif isinstance(no, list):
        for v in no:
            yield from textos(v)
    elif isinstance(no, str):
        yield no


class PaginasSemDinheiroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paginas = {nome: gerar() for nome, gerar in pm.PAGINAS.items()}

    def test_as_paginas_de_mentira_tem_dinheiro_para_quem_pode_ver(self):
        # sem isto os testes abaixo passariam por uma pagina vazia
        for nome, html in self.paginas.items():
            with self.subTest(painel=nome):
                d = dados_da_pagina(html)
                self.assertTrue(d["meses"], "a pagina de mentira saiu sem meses")
                self.assertTrue(any(CAMPO_DINHEIRO.search(c) for c in chaves(d)), "esperava campos de dinheiro na pagina completa")
                self.assertTrue(REAIS_NAO_ZERO.search(html) or any(REAIS_NAO_ZERO.search(t) for t in textos(d)) or "receita" in html)

    def test_nenhum_campo_de_dinheiro_sobra_no_json(self):
        for nome, html in self.paginas.items():
            with self.subTest(painel=nome):
                limpo = dados_da_pagina(sigilo.limpar_html(html, nome))
                sobrou = {c for c in chaves(limpo) if CAMPO_DINHEIRO.search(c)} - PERMITIDOS[nome]
                self.assertFalse(sobrou, f"campos de dinheiro que continuam no JSON de {nome}: {sorted(sobrou)}")

    def test_nenhum_valor_em_reais_sobra_nos_textos(self):
        for nome, html in self.paginas.items():
            with self.subTest(painel=nome):
                limpo = dados_da_pagina(sigilo.limpar_html(html, nome))
                achados = [t[:120] for t in textos(limpo) if REAIS_NAO_ZERO.search(t)]
                self.assertFalse(achados, f"textos com valor em R$ em {nome}: {achados[:3]}")

    def test_alertas_de_dinheiro_saem_e_os_demais_ficam(self):
        for nome, html in self.paginas.items():
            with self.subTest(painel=nome):
                inteiro = dados_da_pagina(html)
                limpo = dados_da_pagina(sigilo.limpar_html(html, nome))

                def alertas(no, acc):
                    if isinstance(no, dict):
                        if "titulo" in no and "nivel" in no:
                            acc.append(no)
                        for v in no.values():
                            alertas(v, acc)
                    elif isinstance(no, list):
                        for v in no:
                            alertas(v, acc)
                    return acc
                antes, depois = alertas(inteiro, []), alertas(limpo, [])
                self.assertFalse([a["titulo"] for a in depois if gp.sensivel(nome, a)], "sobrou alerta sensivel")
                self.assertEqual(len(depois), len([a for a in antes if not gp.sensivel(nome, a)]), "saiu alerta que nao era de dinheiro")

    def test_o_que_nao_e_dinheiro_continua(self):
        # a limpeza nao pode levar junto o que nao e dinheiro (atendimentos, esperas, pedidos...)
        casos = {"atendimento": ("kpis", "n"), "cesta": ("kpi", "atend"), "suprimentos": ("sol", "solicitacoes")}
        for nome, (bloco, campo) in casos.items():
            with self.subTest(painel=nome):
                inteiro, limpo = dados_da_pagina(self.paginas[nome]), dados_da_pagina(sigilo.limpar_html(self.paginas[nome], nome))
                ym = inteiro["mes_padrao"]
                self.assertEqual(limpo["meses"][ym][bloco][campo], inteiro["meses"][ym][bloco][campo])

    def test_atendimento_por_pessoa_tambem_e_limpo(self):
        # "por_visao" repete o painel inteiro para cada responsavel
        limpo = dados_da_pagina(sigilo.limpar_html(self.paginas["atendimento"], "atendimento"))
        self.assertTrue(limpo["por_visao"])
        self.assertFalse({c for c in chaves(limpo["por_visao"]) if re.search(r"receita|ticket", c)})

    def test_ordem_das_listas_nao_entrega_o_ranking_de_receita(self):
        # o gerador ordena profissionais, convenios e unidades por receita; sem o campo, a pagina reordena por quantidade (ver modelos). Aqui: a lista de
        # procedimentos da Cesta (os 12 que mais faturam) nem sai da pagina de quem nao ve dinheiro? ela fica, mas o modelo nao a mostra (acordeao fin).
        modelo = (RAIZ / "Cesta" / "dashboard_modelo.html").read_text(encoding="utf-8")
        self.assertIn("{ fin: 1, dica: `${m.procedimentos.length} exames` }", modelo)

    def test_falha_fechada_sem_dados_na_pagina(self):
        with self.assertRaises(RuntimeError):
            sigilo.limpar_html("<html>sem dados</html>", "atendimento")


class AlertasSensiveisTest(unittest.TestCase):
    def test_painel_so_de_dinheiro_tem_todo_alerta_sensivel(self):
        for painel in ("faturamento", "financeiro", "despesas", "indicadores"):
            self.assertTrue(gp.sensivel(painel, {"id": "qualquer", "titulo": "Sem dinheiro nenhum", "texto": "x", "nivel": "atencao"}), painel)

    def test_painel_misto_so_esconde_o_que_fala_de_dinheiro(self):
        def a(i, titulo, texto="", **extra):
            return {"id": i, "titulo": titulo, "texto": texto, "nivel": "atencao", **extra}
        self.assertTrue(gp.sensivel("cesta", a("cesta_menor_fat", "A receita da Cesta é menor que a do Faturamento")))
        self.assertTrue(gp.sensivel("atendimento", a("ate_x", "Algo", "A receita caiu <b>R$ 1.200,00</b>")))
        self.assertTrue(gp.sensivel("suprimentos", a("sup_sem_custo", "Custo registrado nas movimentações")))
        self.assertTrue(gp.sensivel("atendimento", a("ate_y", "Algo", itens={"colunas": ["Data", "Valor"], "linhas": [], "total": 1})))
        self.assertFalse(gp.sensivel("atendimento", a("ate_espera", "Espera acima do aceitável", "Mediana de 36 min")))
        self.assertFalse(gp.sensivel("suprimentos", a("sup_sem_setor", "Pedidos sem centro de custo")))   # centro de custo = setor
        self.assertFalse(gp.sensivel("atendimento", a("ate_valor_zero", "Atendimentos com valor R$ 0,00")))   # problema de cadastro
        self.assertFalse(gp.sensivel("metas", a("x", "Receita")))   # painel desconhecido / sem dinheiro


class ModoFinanceiroTest(unittest.TestCase):
    def test_painel_sem_o_campo_conta_como_so_dinheiro(self):
        import portal_nuvem as pn
        original = pn.modulos
        try:
            pn.modulos = lambda: {"novo": {"id": "novo", "tipo": "relatorios"}, "x": {"id": "x", "financeiro": "nenhum"}, "m": {"id": "m", "financeiro": "parcial"}}
            self.assertEqual(pn.modo_financeiro("novo"), "total")       # esqueceram de preencher: bloqueia
            self.assertIsNone(pn.modo_financeiro("x"))                  # "nenhum" diz que nao tem dinheiro
            self.assertEqual(pn.modo_financeiro("m"), "parcial")
            self.assertIsNone(pn.modo_financeiro("desconhecido"))
        finally:
            pn.modulos = original

    def test_modulos_json_declara_o_modo_de_todos_os_paineis(self):
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        for m in cfg["modulos"]:
            if m["tipo"] == "relatorios":
                self.assertIn(m.get("financeiro"), ("total", "parcial", "nenhum"), f"{m['id']}: falta \"financeiro\" no modulos.json")
        # os painéis com modo parcial precisam ter regra de limpeza em sigilo.py
        for m in cfg["modulos"]:
            if m.get("financeiro") == "parcial":
                self.assertTrue(sigilo.CHAVES.get(m["id"]), f"{m['id']}: sem campos de dinheiro em sigilo.CHAVES")


@unittest.skipUnless(os.environ.get("CHROMIUM") or Path("/opt/pw-browsers/chromium").exists(), "sem Chromium")
class NoNavegadorTest(unittest.TestCase):
    """Abre a pagina no Chromium como o usuario abriria: sem erro de JavaScript e sem nenhum valor em R$ no que aparece na tela."""

    def renderizar(self, html: str) -> tuple[str, list[str]]:
        chromium = os.environ.get("CHROMIUM") or "/opt/pw-browsers/chromium"
        pasta = Path(tempfile.mkdtemp())
        try:
            (pasta / "p.html").write_text(html, encoding="utf-8")
            srv = subprocess.Popen([sys.executable, "-m", "http.server", "8797", "-d", str(pasta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
            try:
                out = subprocess.run([chromium, "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=8000", "--enable-logging=stderr", "--v=0",
                                      "--dump-dom", "http://127.0.0.1:8797/p.html"], capture_output=True, text=True, timeout=120)
            finally:
                srv.terminate()
                srv.wait()
            return out.stdout, [l for l in out.stderr.splitlines() if "CONSOLE" in l and "rror" in l]
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def test_painel_misto_sem_dados_financeiros(self):
        import portal_nuvem as pn
        for nome, gerar in pm.PAGINAS.items():
            with self.subTest(painel=nome):
                html = gerar()
                completo, erros = self.renderizar(pn.com_marcas(html, nome, admin=True))
                self.assertFalse(erros, erros[:2])
                self.assertRegex(completo, r"R\$(?:&nbsp;|\s)*[1-9]")   # com permissao, o dinheiro aparece (senao o teste abaixo nao prova nada)
                dom, erros = self.renderizar(pn.com_marcas(html, nome, admin=False, sem_financeiro=True))
                self.assertFalse(erros, erros[:2])
                conteudo = re.search(r'<main id="conteudo">(.*?)</main>', dom, re.S).group(1)
                self.assertFalse(REAIS_NAO_ZERO.search(conteudo), re.findall(r".{40}R\$.{20}", conteudo)[:3])
                self.assertNotIn("NaN", conteudo)
                self.assertNotRegex(conteudo, r"(?i)ticket|receita(?! - Mensal)")


if __name__ == "__main__":
    unittest.main()
