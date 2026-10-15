"""Painel Tempo (Tempo/gerar_tempo.py + dashboard_modelo.html): a pagina gerada de dados inventados, nos periodos do filtro, e no navegador.

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


def dados_da_pagina(html: str) -> dict:
    m = re.search(r'<script id="dados" type="application/json">(.*?)</script>', html, re.S)
    assert m, "a pagina nao traz o JSON de dados"
    return json.loads(m.group(1).replace("<\\/", "</"))


class RegistroDoPainelTest(unittest.TestCase):
    def test_modulo_sem_dinheiro_que_le_os_dados_do_atendimento(self):
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        m = next(x for x in cfg["modulos"] if x["id"] == "tempo")
        self.assertEqual((m["tipo"], m["financeiro"], m["pasta"], m["codigo"]), ("relatorios", "nenhum", "Tempo", "gerar_tempo"))
        for arq in (m["codigo"] + ".py", "dashboard_modelo.html", "metricas_tempo.py", "parametros.json"):
            self.assertTrue((RAIZ / "Tempo" / arq).exists(), arq)
        import armazenamento as arm
        self.assertEqual(arm.DEPENDENCIAS["tempo"], ["atendimento"])     # a pagina se refaz quando o Atendimento atualiza
        self.assertEqual(arm.painel_de_pasta(RAIZ / "Atendimento"), "atendimento")

    def test_vercel_inclui_a_pasta_nas_funcoes_que_geram_paginas(self):
        funcoes = json.loads((RAIZ / "vercel.json").read_text(encoding="utf-8"))["functions"]
        for nome in ("api/painel.py", "api/atualizar.py", "api/renovar.py", "api/preaquecer.py"):
            self.assertIn("Tempo/**", funcoes[nome]["includeFiles"], nome)

    def test_empacotamento_do_programa_local_leva_os_arquivos(self):
        import construir_exe as ce
        for arq in ("gerar_tempo.py", "metricas_tempo.py", "dashboard_modelo.html", "parametros.json"):
            self.assertIn(f"Tempo/{arq}", ce.ARQUIVOS)

    def test_parametros_herdam_os_limites_do_atendimento(self):
        import gerar_tempo as gt
        p = gt.ler_parametros()
        atendimento = json.loads((RAIZ / "Atendimento" / "parametros.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(p["espera_meta_min"], atendimento["espera_meta_min"])
        self.assertEqual(p["equipamentos"], atendimento["equipamentos"])
        self.assertEqual(p["piso_outlier_min"], 5)
        cal = gt.ler_calendario()
        self.assertEqual(cal["expediente"], (7, 18))
        self.assertIn("2026-10-12", cal["feriados"])


class PaginaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = pm.pagina_tempo()
        cls.D = dados_da_pagina(cls.html)

    def test_meses_e_mes_padrao(self):
        self.assertEqual(sorted(self.D["meses"]), ["2026-09", "2026-10"])
        self.assertEqual(self.D["mes_padrao"], "2026-10")
        self.assertTrue(self.D["tem_dados"])
        self.assertEqual(self.D["todos_meses"], ["2026-09", "2026-10"])      # o filtro De/Ate do painel_base.js
        self.assertTrue(self.D["meses"]["2026-09"]["fechado"])

    def test_nao_tem_dinheiro_nem_paciente_na_pagina(self):
        self.assertFalse(DINHEIRO.search(self.html))
        self.assertNotIn("Valor do Atendimento", self.html)
        chaves = set()

        def coletar(no):
            if isinstance(no, dict):
                chaves.update(no)
                [coletar(v) for v in no.values()]
            elif isinstance(no, list):
                [coletar(v) for v in no]
        coletar(self.D["meses"])
        self.assertFalse(chaves & {"atendimento_id", "paciente", "profissional", "convenio", "usuario", "checkin", "chegada"}, chaves)   # so agregados: nada de linha por atendimento
        for nome in ("DR ANA LIMA", "DR BRUNO REIS", "DRA CARLA SOUZA", "UNIMED", "PARTICULAR"):     # nem o profissional nem o convenio de ninguem
            self.assertNotIn(nome, self.html)

    def test_numeros_do_mes_batem_com_os_dados(self):
        f = pm.fluxo_de_mentira()
        out = f[(f["Etapa"] == "Cadastro") & (f["Check-In"] >= "2026-09-01") & (f["Check-In"] < "2026-10-01")]
        m = self.D["meses"]["2026-09"]
        self.assertEqual(m["kpis"]["n"], len(out))                          # uma chegada por visita
        self.assertEqual(sum(h["n"] for h in m["horas"]), len(out))
        self.assertEqual(sum(c["n"] for c in m["semana"]), len(out))
        self.assertEqual(sum(s["n"] for s in m["setores"]), len(out))

    def test_hora_do_pico_e_a_do_gerador(self):
        k = self.D["meses"]["2026-09"]["kpis"]
        self.assertEqual(k["hora_cheia"], 9)                                  # o gerador concentra as chegadas as 9h e as 14h
        self.assertIn(k["pior_hora"], (9, 10, 14))                            # e faz as esperas ali serem maiores
        horas = {h["h"]: h for h in self.D["meses"]["2026-09"]["horas"]}
        self.assertGreater(horas[10]["esp_p90"], horas[16]["esp_p90"])
        self.assertTrue(all(h["na_clinica"] is not None for h in horas.values() if h["n"] > 20))

    def test_esquecidos_ficam_fora_das_medianas(self):
        m = self.D["meses"]["2026-09"]
        self.assertGreater(m["kpis"]["outliers"], 0)
        self.assertLess(m["kpis"]["tat"]["p90"], 12 * 60)                    # nenhum encerramento esquecido de dias vazou para o p90
        self.assertTrue(any(l["outliers"] for l in m["limites"]))
        self.assertTrue(all(l["limite"] >= self.D["limites"]["piso_outlier_min"] or l["limite"] is None for l in m["limites"]))

    def test_equipamentos_trazem_a_cobertura(self):
        q = self.D["meses"]["2026-09"]["equipamentos"]
        self.assertEqual({r["nome"] for r in q["recursos"]}, {"RM", "TC", "DENSITOMETRIA", "MAMOGRAFIA"})
        for c in q["cobertura"]:
            self.assertLessEqual(c["identificados"], c["total"])
        for r in q["recursos"]:
            self.assertAlmostEqual(r["min_ocupado"] + r["min_ocioso"], r["min_disponivel"], delta=1)
        cel = [c for c in q["horas"] if c["pct_ocupado"] is not None]
        self.assertTrue(cel and all(0 <= c["pct_ocupado"] <= 100 for c in cel))
        self.assertTrue(all(7 <= c["h"] < 18 for c in q["horas"]))              # so dentro do expediente

    def test_dia_a_dia_so_no_mes(self):
        m = self.D["meses"]["2026-09"]
        self.assertTrue(m["dias"])
        self.assertTrue(all(d["pico_h"] is None or 7 <= d["pico_h"] <= 17 for d in m["dias"]))
        self.assertEqual(sum(d["n"] for d in m["dias"]), m["kpis"]["n"])

    def test_periodo_de_varios_meses_e_dias_exatos(self):
        varios = dados_da_pagina(pm.pagina_tempo("2026-09", "2026-10"))
        p = varios["meses"]["2026-09..2026-10"]
        self.assertTrue(p["periodo"])
        self.assertEqual(p["kpis"]["n"], varios["meses"]["2026-09"]["kpis"]["n"] + varios["meses"]["2026-10"]["kpis"]["n"])
        self.assertEqual(p["dias"], [])                                          # o dia a dia so existe dentro de um mes
        exato = dados_da_pagina(pm.pagina_tempo("2026-10-02", "2026-10-09"))
        e = exato["meses"]["2026-10-02..2026-10-09"]
        self.assertEqual(e["kpis"]["dias"], 7)                                    # segunda a sabado: 02/10 (sexta) a 09/10 (sexta), sem o domingo
        self.assertEqual(exato["periodo"]["chave"], "2026-10-02..2026-10-09")
        self.assertIsNotNone(e["chave_anterior"])                                 # o periodo anterior vai junto, para as comparacoes
        self.assertIn(e["chave_anterior"], exato["meses"])

    def test_sem_dados_nao_quebra(self):
        import gerar_tempo as gt
        for abas in ({}, {gt.ABA_FLUXO: pd.DataFrame()}, {gt.ABA_FLUXO: pd.DataFrame({"Etapa": []})}):
            with mock.patch.object(gt, "lido_com_cache", lambda arq, nome, fn, a=abas: a):
                d = dados_da_pagina(gt.gerar(devolver_html=True))
            self.assertFalse(d["tem_dados"])
            self.assertEqual(d["meses"], {})

    def test_o_payload_esta_pronto_para_a_aba_avisos(self):
        import avisos
        alertas, escopos = avisos.coletar(self.D, "tempo")
        self.assertEqual(alertas, [])                                             # a aba nao gera avisos (nada com "guia"): so leitura automatica
        self.assertTrue(escopos)


class AtualizacaoTest(unittest.TestCase):
    def test_atualizar_aqui_e_atualizar_o_atendimento(self):
        import gerar_tempo as gt
        with mock.patch.object(gt.k, "atualizar", return_value={"mensagem": "ok"}) as f:
            self.assertEqual(gt.atualizar(forcar=True)["mensagem"], "ok")
        self.assertEqual(f.call_args.args[0], RAIZ / "Atendimento")
        self.assertTrue(f.call_args.kwargs["forcar"])


# ---------------------------------------------------------------------------------------------------------------- navegador
def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


@unittest.skipUnless(_chromium(), "sem Chromium")
class NoNavegadorTest(unittest.TestCase):
    """Abre a pagina no Chromium como o usuario abriria: sem erro de JavaScript, com as tres partes e sem sobra horizontal."""

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
                dom, erros = self.abrir(pm.pagina_tempo(de, ate))
                self.assertEqual(erros, [])
                corpo = re.search(r'<main id="conteudo">(.*?)</main>', dom, re.S).group(1)
                for titulo in ("Chegadas em", "Espera (mediana)", "Pior hora para chegar", "Hora a hora", "Dia da semana × hora", "Equipamentos identificados", "Casos fora do normal", "Cerca de cada etapa"):
                    self.assertIn(titulo, corpo)
                self.assertIn('class="mapa"', corpo)
                self.assertIn("<svg", corpo)
                self.assertNotRegex(corpo, r"undefined|NaN|\[object")
                self.assertFalse(DINHEIRO.search(corpo))

    def test_sem_sobra_horizontal_no_celular(self):
        dom, erros = self.abrir(pm.pagina_tempo(), largura=500)
        self.assertEqual(erros, [])
        escrito, janela = re.search(r'data-w="(\d+)/(\d+)"', dom).groups()
        self.assertLessEqual(int(escrito), int(janela))

    def test_pagina_vazia_diz_o_que_fazer(self):
        import gerar_tempo as gt
        with mock.patch.object(gt, "lido_com_cache", lambda arq, nome, fn: {}):
            dom, erros = self.abrir(gt.gerar(devolver_html=True))
        self.assertEqual(erros, [])
        self.assertIn("Ainda não há dados", dom)


if __name__ == "__main__":
    unittest.main()
