"""Painel NPS × Google (Nps/gerar_nps.py + dashboard_modelo.html): a pagina gerada de dados inventados, nos periodos do filtro, com e sem o Google, e no navegador.

Rodar:  python -m unittest discover -s tests -v
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
from unittest import mock

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
import paineis_de_mentira as pm  # noqa: E402  (poe as pastas dos paineis no sys.path)

DINHEIRO = re.compile(r'"(receita|ticket|valor|custo_unit|custo)"')


def so_arquivos():
    """Gera a pagina como no computador da clinica (arquivos), mesmo que outro teste ja tenha ligado o modo Supabase (portal_nuvem faz isso ao ser importado)."""
    return mock.patch.dict(os.environ, {"PORTAL_ARMAZENAMENTO": "arquivos", "VERCEL": ""})


def dados_da_pagina(html: str) -> dict:
    m = re.search(r'<script id="dados" type="application/json">(.*?)</script>', html, re.S)
    assert m, "a pagina nao traz o JSON de dados"
    return json.loads(m.group(1).replace("<\\/", "</"))


def pagina(nps=None, google=None, configurado=True, disponivel=True, de=None, ate=None) -> str:
    import gerar_nps as gn
    nps = pm.nps_de_mentira() if nps is None else nps
    google = pm.google_de_mentira() if google is None else google
    with so_arquivos(), mock.patch.object(gn.k, "carregar", lambda pasta: {gn.ABA: nps}), mock.patch.object(gn.gm, "ler", lambda: google), \
            mock.patch.object(gn.gm, "disponivel", lambda: disponivel), mock.patch.object(gn.gm, "configurado", lambda: configurado):
        return gn.gerar(de, ate, devolver_html=True)


class RegistroDoPainelTest(unittest.TestCase):
    def test_modulo_sem_dinheiro(self):
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        m = next(x for x in cfg["modulos"] if x["id"] == "nps")
        self.assertEqual((m["tipo"], m["financeiro"], m["pasta"], m["codigo"]), ("relatorios", "nenhum", "Nps", "gerar_nps"))
        for arq in (m["codigo"] + ".py", "dashboard_modelo.html", "metricas_nps.py", "google_maps.py", "parametros.json", "relatorios.json"):
            self.assertTrue((RAIZ / "Nps" / arq).exists(), arq)
        import armazenamento as arm
        self.assertEqual(arm.painel_de_pasta(RAIZ / "Nps"), "nps")

    def test_relatorio_13697_e_as_colunas_que_o_painel_le(self):
        defn = json.loads((RAIZ / "Nps" / "relatorios.json").read_text(encoding="utf-8"))
        rel = defn["relatorios"][0]
        self.assertEqual((rel["id"], rel["aba"], rel["chave"]), (13697, "NPS", ["Id da Marcação"]))
        import klingo_relatorios as k
        exigidas = set(k.colunas_exigidas(rel))
        self.assertEqual(exigidas, {"Id da Marcação", "NPS - Nota", "Data Agendado Para", "NPS - Data de Resposta"})
        import painel_comum as pc
        self.assertGreaterEqual(defn["primeiro_mes"], pc.INICIO_KLINGO)

    def test_vercel_e_programa_local_levam_a_pasta(self):
        funcoes = json.loads((RAIZ / "vercel.json").read_text(encoding="utf-8"))["functions"]
        for nome in ("api/painel.py", "api/atualizar.py", "api/renovar.py", "api/preaquecer.py"):
            self.assertIn("Nps/**", funcoes[nome]["includeFiles"], nome)
        import construir_exe as ce
        for arq in ("gerar_nps.py", "metricas_nps.py", "google_maps.py", "dashboard_modelo.html", "relatorios.json", "parametros.json"):
            self.assertIn(f"Nps/{arq}", ce.ARQUIVOS)

    def test_parametros(self):
        import gerar_nps as gn
        p = gn.ler_parametros()
        self.assertEqual((p["meta_nps"], p["minimo_grupo"]), (75, 5))
        self.assertIn("espera", p["temas"])
        self.assertEqual(p["google_cid"], "13831494129270129913")        # 0xbff356a0d00c04f9, o CID do link do Maps da clinica
        self.assertEqual(int("bff356a0d00c04f9", 16), int(p["google_cid"]))


class PaginaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = pagina()
        cls.D = dados_da_pagina(cls.html)
        cls.nps = pm.nps_de_mentira()

    def test_meses_e_mes_padrao(self):
        self.assertEqual(sorted(self.D["meses"]), ["2026-09", "2026-10"])
        self.assertEqual(self.D["mes_padrao"], "2026-10")
        self.assertTrue(self.D["tem_dados"])
        self.assertEqual(self.D["todos_meses"], ["2026-09", "2026-10"])
        self.assertTrue(self.D["meses"]["2026-09"]["fechado"])

    def test_numeros_do_mes_batem_com_os_dados(self):
        d = self.nps[self.nps["Mês (filtro)"] == "2026-09"]
        m = self.D["meses"]["2026-09"]
        k = m["kpis"]
        prom, det = int((d["NPS - Nota"] >= 9).sum()), int((d["NPS - Nota"] <= 6).sum())
        self.assertEqual((k["n"], k["prom"], k["det"]), (len(d), prom, det))
        self.assertEqual(k["nps"], round((prom - det) / len(d) * 100, 1))
        self.assertEqual(sum(m["distribuicao"]), len(d))
        for chave in ("unidades", "profissionais", "procedimentos"):
            self.assertEqual(sum(g["n"] for g in m[chave]), len(d), chave)
        self.assertEqual(sum(s["n"] for s in m["semana"]), len(d))
        self.assertEqual(sum(h["n"] for h in m["horas"]), len(d))
        self.assertEqual(sum(x["n"] for x in m["dias"]), len(d))
        self.assertAlmostEqual(sum(g["contribuicao"] for g in m["unidades"]), k["nps"], delta=0.3)   # as unidades somam o NPS geral

    def test_unidades_chegam_com_nome_curto(self):
        nomes = {u["nome"] for u in self.D["meses"]["2026-10"]["unidades"]}
        self.assertEqual(nomes, {"CSI", "RM/TC", "DESENVOAR"})

    def test_temas_e_a_espera_domina_os_detratores(self):
        m = self.D["meses"]["2026-10"]
        temas = {t["id"]: t for t in m["temas"]}
        self.assertEqual(m["temas"][0]["id"], "espera")                    # os dados inventados fazem a espera ser o assunto mais citado pelos detratores
        self.assertGreater(temas["espera"]["pontos"], 0)
        self.assertEqual(temas["espera"]["det_total"], m["kpis"]["det"])
        self.assertTrue(any("Espera e atraso" in l["texto"] for l in m["leituras"]))

    def test_detratores_trazem_comentarios_sem_id_de_marcacao(self):
        m = self.D["meses"]["2026-10"]
        self.assertEqual(len(m["detratores_lista"]), m["kpis"]["det"])      # menos de 200: vem todos
        self.assertTrue(all(x["nota"] <= 6 for x in m["detratores_lista"]))
        self.assertTrue(all(x["nota"] in (7, 8) and x["texto"] for x in m["neutros_lista"]))
        chaves = set()

        def coletar(no):
            if isinstance(no, dict):
                chaves.update(no)
                [coletar(v) for v in no.values()]
            elif isinstance(no, list):
                [coletar(v) for v in no]
        coletar(self.D["meses"])
        self.assertFalse(chaves & {"id_marcacao", "paciente", "cpf", "telefone", "agendado", "resposta"}, chaves)   # ("id" existe: e o do assunto, nao o da marcacao)
        self.assertNotIn("M00001", self.html)                               # o Id da Marcacao nao vai para a pagina
        self.assertFalse(DINHEIRO.search(self.html))

    def test_comentario_que_so_repete_a_nota_nao_e_comentario(self):
        m = self.D["meses"]["2026-10"]
        self.assertTrue(all(x["texto"] != "10" for x in m["detratores_lista"] + m["neutros_lista"]))
        self.assertLess(m["kpis"]["comentarios"], m["kpis"]["n"])

    def test_leituras_dizem_quando_a_diferenca_e_so_acaso(self):
        m = self.D["meses"]["2026-10"]
        textos = " ".join(l["texto"] for l in m["leituras"])
        self.assertIn("margem de erro", textos)
        self.assertTrue(all(l["nivel"] in ("critico", "atencao", "info", "ok") for l in m["leituras"]))
        self.assertIn(",", re.sub(r"<[^>]+>", "", " ".join(l["texto"] for l in m["leituras"] if "Google" in l["texto"])))   # decimais com virgula, como na tela

    def test_google_do_mes_e_a_serie(self):
        m = self.D["meses"]["2026-10"]
        g = m["google"]
        self.assertEqual((g["nota"], g["total"], g["dia"]), (4.5, 329, "2026-10-19"))
        self.assertEqual(g["novas"], 19)                                    # 329 hoje - 310 do primeiro resumo de outubro
        self.assertEqual(g["n_avaliacoes"], 12)
        self.assertEqual(g["equivalente"]["n"], 12)                         # passou do minimo de 10 avaliacoes
        self.assertEqual(g["equivalente"]["nps"], round((7 - 4) / 12 * 100, 1))
        self.assertEqual(g["distribuicao"], [2, 1, 1, 1, 7])               # avaliacoes de 1 a 5 estrelas
        self.assertTrue(any(t["id"] == "espera" for t in g["temas_baixas"]))
        # setembro e anterior ao primeiro resumo guardado: nao inventa nota
        s = self.D["meses"]["2026-09"]["google"]
        self.assertIsNone(s["nota"])
        self.assertEqual(s["avaliacoes"], [])
        serie = {x["ym"]: x for x in self.D["serie"]}
        self.assertIsNone(serie["2026-09"]["google_nota"])
        self.assertEqual((serie["2026-10"]["google_nota"], serie["2026-10"]["google_total"]), (4.5, 329))
        self.assertEqual(serie["2026-10"]["estrelas_nps"], round(self.D["meses"]["2026-10"]["kpis"]["media"] / 2, 2))
        self.assertEqual(self.D["google"]["primeiro_dia"], "2026-10-01")

    def test_caminho_ate_a_meta(self):
        m = self.D["meses"]["2026-10"]
        self.assertFalse(m["meta"]["ja"])
        self.assertEqual(m["meta"]["meta"], 75)
        k = m["kpis"]
        saldo = k["prom"] - k["det"]
        # com as respostas novas que a conta pede, o NPS chega na meta (e com uma a menos, nao)
        n = m["meta"]["novas"]
        self.assertGreaterEqual((saldo + n) / (k["n"] + n), 0.75)
        self.assertLess((saldo + n - 1) / (k["n"] + n - 1), 0.75)

    def test_periodo_de_varios_meses_e_dias_exatos(self):
        varios = dados_da_pagina(pagina(de="2026-09", ate="2026-10"))
        p = varios["meses"]["2026-09..2026-10"]
        self.assertTrue(p["periodo"])
        self.assertEqual(p["kpis"]["n"], varios["meses"]["2026-09"]["kpis"]["n"] + varios["meses"]["2026-10"]["kpis"]["n"])
        self.assertEqual(p["dias"], [])
        self.assertEqual(p["google"]["nota"], 4.5)
        exato = dados_da_pagina(pagina(de="2026-10-02", ate="2026-10-09"))
        e = exato["meses"]["2026-10-02..2026-10-09"]
        d = self.nps[(self.nps["Data Agendado Para"] >= "2026-10-02") & (self.nps["Data Agendado Para"] < "2026-10-10")]
        self.assertEqual(e["kpis"]["n"], len(d))
        self.assertIn(e["chave_anterior"], exato["meses"])
        self.assertTrue(exato["meses"][e["chave_anterior"]]["kpis"]["n"] > 0)

    def test_periodo_sem_respostas_nao_quebra(self):
        d = dados_da_pagina(pagina(de="2026-10-20", ate="2026-10-25"))
        self.assertIsNone(d["meses"]["2026-10-20..2026-10-25"]["kpis"])

    def test_unidades_que_o_google_cobre_mudam_so_o_comparavel(self):
        import gerar_nps as gn
        p = dict(gn.ler_parametros(), unidades_no_google=["CLÍNICA DE SAÚDE E IMAGEM - CSI", "CLÍNICA DE SAÚDE E IMAGEM - RM/TC"])
        with mock.patch.object(gn, "ler_parametros", lambda: p):
            d = dados_da_pagina(pagina())
        m = d["meses"]["2026-10"]
        self.assertEqual(m["comparavel"]["n"], sum(u["n"] for u in m["unidades"] if u["nome"] != "DESENVOAR"))
        self.assertEqual(m["kpis"]["n"], sum(u["n"] for u in m["unidades"]))        # o NPS da clinica continua com todas

    def test_o_payload_esta_pronto_para_a_aba_avisos(self):
        import avisos
        alertas, escopos = avisos.coletar(self.D, "nps")
        self.assertEqual(alertas, [])
        self.assertTrue(escopos)


class SemGoogleTest(unittest.TestCase):
    def test_sem_coleta_o_nps_aparece_sozinho(self):
        d = dados_da_pagina(pagina(google=pm.google_de_mentira(False), configurado=False))
        self.assertTrue(d["tem_dados"])
        self.assertFalse(d["google"]["configurado"])
        self.assertFalse(d["google"]["tem_dados"])
        m = d["meses"]["2026-10"]
        self.assertIsNone(m["google"]["nota"])
        self.assertIsNone(m["google"]["equivalente"])
        self.assertTrue(all("Google" not in l["texto"] for l in m["leituras"]))      # nada de comparar com o que nao existe
        self.assertTrue(m["kpis"]["n"] > 0)

    def test_poucas_avaliacoes_nao_formam_nps_equivalente(self):
        g = pm.google_de_mentira()
        g["avaliacoes"] = g["avaliacoes"][:4]
        m = dados_da_pagina(pagina(google=g))["meses"]["2026-10"]["google"]
        self.assertEqual(m["n_avaliacoes"], 4)
        self.assertIsNone(m["equivalente"])                                           # abaixo do minimo de 10

    def test_sem_nenhuma_resposta_nao_quebra(self):
        import gerar_nps as gn
        for abas in (pd.DataFrame(), pd.DataFrame({"Id da Marcação": []}), pm.nps_de_mentira().iloc[0:0]):
            d = dados_da_pagina(pagina(nps=abas, google=pm.google_de_mentira(False), configurado=False))
            self.assertFalse(d["tem_dados"])
            self.assertEqual(d["meses"], {})


class AtualizacaoTest(unittest.TestCase):
    def test_atualizar_junta_o_klingo_e_o_google_e_o_google_nunca_derruba(self):
        import gerar_nps as gn
        with mock.patch.object(gn.k, "atualizar", return_value={"atualizou": False, "mensagem": "NPS ok", "avisos": []}), \
                mock.patch.object(gn.gm, "atualizar", return_value={"atualizou": True, "mensagem": "Google ok", "avisos": ["x"]}):
            r = gn.atualizar(forcar=True)
        self.assertTrue(r["atualizou"])                                               # so o Google mudou: a pagina precisa se refazer
        self.assertEqual(r["mensagem"], "NPS ok Google ok")
        self.assertEqual(r["avisos"], ["x"])
        with mock.patch.object(gn.k, "atualizar", return_value={"atualizou": True, "mensagem": "NPS ok", "avisos": []}), \
                mock.patch.object(gn.gm, "atualizar", side_effect=RuntimeError("banco fora")):
            r = gn.atualizar()
        self.assertTrue(r["atualizou"])
        self.assertIn("banco fora", r["avisos"][0])


# ---------------------------------------------------------------------------------------------------------------- navegador
def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


@unittest.skipUnless(_chromium(), "sem Chromium")
class NoNavegadorTest(unittest.TestCase):
    """Abre a pagina no Chromium como o usuario abriria: sem erro de JavaScript, com todas as partes e sem sobra horizontal."""

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

    def abrir(self, html: str, largura: int = 1200):
        (self.pasta / "t.html").write_text(html.replace("</body>", '<script>setTimeout(()=>document.body.setAttribute("data-w",document.documentElement.scrollWidth+"/"+innerWidth),400)</script></body>'), encoding="utf-8")
        out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=8000", "--enable-logging=stderr", "--v=0", f"--window-size={largura},1400",
                              "--dump-dom", f"http://127.0.0.1:{self.porta}/t.html"], capture_output=True, text=True, timeout=300)
        return out.stdout, [l for l in out.stderr.splitlines() if "CONSOLE" in l and "rror" in l]

    def test_pagina_do_mes_e_do_periodo(self):
        for de, ate in ((None, None), ("2026-09", "2026-10"), ("2026-10-02", "2026-10-09")):
            with self.subTest(periodo=(de, ate)):
                dom, erros = self.abrir(pagina(de=de, ate=ate))
                self.assertEqual(erros, [])
                corpo = re.search(r'<main id="conteudo">(.*?)</main>', dom, re.S).group(1)
                for titulo in ("NPS em", "Respostas", "Detratores (nota 0 a 6)", "Nota no Google Maps", "Clínica × Google", "Distribuição das notas", "Por unidade", "O que os comentários dizem",
                               "Quando foi o agendamento", "Por profissional e por procedimento", "Caminho até a meta", "Detratores: o que disseram", "Neutros: o que faltou", "Assuntos dos comentários"):
                    self.assertIn(titulo, corpo)
                self.assertIn("<svg", corpo)
                self.assertNotRegex(corpo, r"undefined|NaN|\[object")
                self.assertFalse(DINHEIRO.search(corpo))

    def test_sem_google_mostra_os_passos_para_ligar(self):
        dom, erros = self.abrir(pagina(google=pm.google_de_mentira(False), configurado=False))
        self.assertEqual(erros, [])
        corpo = re.search(r'<main id="conteudo">(.*?)</main>', dom, re.S).group(1)
        self.assertIn("GOOGLE_PLACES_API_KEY", corpo)
        self.assertIn("Ligar a nota do Google Maps", corpo)
        self.assertNotRegex(corpo, r"undefined|NaN|\[object")

    def test_no_programa_local_diz_que_o_google_e_so_do_site(self):
        dom, erros = self.abrir(pagina(google=pm.google_de_mentira(False), configurado=False, disponivel=False))
        self.assertEqual(erros, [])
        self.assertIn("só é coletada no site", dom)

    def test_filtro_por_assunto_na_voz_do_cliente(self):
        html = pagina().replace("</body>", '<script>setTimeout(()=>{const s=document.getElementById("tema-sel");s.value="espera";s.dispatchEvent(new Event("change",{bubbles:true}));'
                                           'document.body.setAttribute("data-filtro",document.querySelectorAll("#voz-det li").length+"/"+[...document.querySelectorAll("#voz-det li")].filter(l=>l.textContent.toLowerCase().includes("esper")||l.textContent.toLowerCase().includes("demor")||l.textContent.toLowerCase().includes("atras")||l.textContent.toLowerCase().includes("hor")).length)},600)</script></body>')
        dom, erros = self.abrir(html)
        self.assertEqual(erros, [])
        total, batem = re.search(r'data-filtro="(\d+)/(\d+)"', dom).groups()
        self.assertGreater(int(total), 0)
        self.assertEqual(total, batem)                                               # todos os que sobraram falam de espera

    def test_sem_sobra_horizontal_no_celular(self):
        dom, erros = self.abrir(pagina(), largura=500)
        self.assertEqual(erros, [])
        escrito, janela = re.search(r'data-w="(\d+)/(\d+)"', dom).groups()
        self.assertLessEqual(int(escrito), int(janela))

    def test_pagina_vazia_diz_o_que_fazer(self):
        dom, erros = self.abrir(pagina(nps=pd.DataFrame(), google=pm.google_de_mentira(False), configurado=False))
        self.assertEqual(erros, [])
        self.assertIn("Ainda não há respostas de NPS", dom)


if __name__ == "__main__":
    unittest.main()
