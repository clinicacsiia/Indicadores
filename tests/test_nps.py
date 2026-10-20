"""Contas do NPS (Nps/metricas_nps.py), conferidas com respostas feitas à mão, e o cliente do Google (Nps/google_maps.py) com a API simulada.

Rodar:  python -m unittest discover -s tests -v
"""
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
import paineis_de_mentira as pm  # noqa: E402,F401  (poe as pastas dos paineis no sys.path)
import metricas_nps as mn  # noqa: E402


def base(notas, comentarios=None, **extra):
    d = pd.DataFrame({"nota": notas})
    d["classe"] = d["nota"].apply(mn.classe)
    d["comentario"] = comentarios if comentarios is not None else ""
    for c, v in extra.items():
        d[c] = v
    return d


class ClasseENpsTest(unittest.TestCase):
    def test_limites_das_classes(self):
        self.assertEqual([mn.classe(n) for n in (0, 6, 7, 8, 9, 10)], ["Detrator", "Detrator", "Neutro", "Neutro", "Promotor", "Promotor"])
        self.assertIsNone(mn.classe(None))
        self.assertIsNone(mn.classe(float("nan")))
        self.assertIsNone(mn.classe(11))
        self.assertIsNone(mn.classe(-1))

    def test_nps_e_a_diferenca_de_percentuais(self):
        # 6 promotores, 3 neutros, 1 detrator em 10 respostas: 60% - 10% = 50
        self.assertEqual(mn.nps_de(6, 1, 10), 50.0)
        self.assertEqual(mn.nps_de(0, 4, 4), -100.0)
        self.assertEqual(mn.nps_de(4, 0, 4), 100.0)
        self.assertIsNone(mn.nps_de(0, 0, 0))

    def test_resumo_do_grupo(self):
        r = mn.resumo(base([10, 10, 9, 9, 9, 9, 8, 7, 7, 3], ["a", "", "b", "10", "", "", "", "", "", "ruim"]))
        self.assertEqual((r["n"], r["prom"], r["neut"], r["det"]), (10, 6, 3, 1))
        self.assertEqual(r["nps"], 50.0)
        self.assertEqual(r["media"], 8.1)
        self.assertEqual((r["pct_prom"], r["pct_neut"], r["pct_det"]), (60.0, 30.0, 10.0))
        self.assertEqual(r["comentarios"], 4)           # aqui "10" ainda conta: quem descarta e `preparar`
        self.assertEqual(mn.resumo(base([]))["nps"], None)

    def test_distribuicao_tem_as_11_notas(self):
        self.assertEqual(mn.distribuicao(base([10, 10, 0, 7])), [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 2])
        self.assertEqual(mn.distribuicao(base([])), [0] * 11)


class MargemDeErroTest(unittest.TestCase):
    def test_margem_pela_variancia_da_diferenca(self):
        # p = 0,6 e d = 0,1 em n = 100: var = (0,7 - 0,25) / 100 = 0,0045 -> erro padrao 6,708% -> 1,96 x = 13,1 pontos
        self.assertEqual(mn.margem_de(60, 10, 100), 13.1)
        self.assertGreater(mn.margem_de(6, 1, 10), mn.margem_de(60, 10, 100))      # menos respostas, mais incerteza
        self.assertEqual(mn.margem_de(10, 0, 10), 0.0)                              # todos promotores: sem variacao
        self.assertIsNone(mn.margem_de(0, 0, 0))

    def test_diferenca_dentro_da_margem_nao_e_mudanca(self):
        a = {"nps": 60.0, "margem": 13.1}
        self.assertFalse(mn.diferenca_confiavel(a, {"nps": 52.0, "margem": 13.1}))      # 8 pontos < raiz(2) x 13,1 = 18,5
        self.assertTrue(mn.diferenca_confiavel(a, {"nps": 30.0, "margem": 13.1}))
        self.assertIsNone(mn.diferenca_confiavel(a, None))
        self.assertIsNone(mn.diferenca_confiavel(a, {"nps": None, "margem": None}))


class GruposTest(unittest.TestCase):
    def test_contribuicao_soma_o_nps_geral(self):
        d = base([10, 10, 9, 8, 3, 10, 2, 9, 7, 10], unidade=["A", "A", "A", "A", "A", "B", "B", "B", "C", "C"])
        g = mn.grupos(d, "unidade", minimo=3)
        total = mn.resumo(d)["nps"]
        self.assertAlmostEqual(sum(x["contribuicao"] for x in g), total, delta=0.2)     # arredondamento a 1 casa em cada grupo
        a = next(x for x in g if x["nome"] == "A")
        self.assertEqual((a["n"], a["prom"], a["det"], a["poucos"]), (5, 3, 1, False))
        self.assertEqual(a["contribuicao"], 20.0)       # (3 - 1) / 10 x 100
        self.assertTrue(next(x for x in g if x["nome"] == "C")["poucos"])
        self.assertEqual(a["pct_det_total"], 50.0)      # 1 dos 2 detratores
        self.assertEqual([x["nome"] for x in g], ["A", "B", "C"])                       # do maior para o menor grupo

    def test_valor_vazio_vira_sem_informacao(self):
        d = base([10, 9], profissional=[None, ""])
        self.assertEqual([x["nome"] for x in mn.grupos(d, "profissional", 1)], ["(sem informação)"])

    def test_hora_e_dia_da_semana_do_agendamento(self):
        quando = pd.to_datetime(["2026-10-05 09:00", "2026-10-05 09:30", "2026-10-06 15:00", "2026-10-06 15:10"])   # segunda e terca
        d = base([10, 3, 2, 10], agendado=quando)
        h = {x["h"]: x for x in mn.por_hora(d, 2)}
        self.assertEqual((h[9]["n"], h[9]["pct_det"], h[15]["pct_det"]), (2, 50.0, 50.0))
        self.assertEqual([x["d"] for x in mn.por_dia_da_semana(d, 2)], [0, 1])
        self.assertEqual([x["d"] for x in mn.por_dia(d)], ["2026-10-05", "2026-10-06"])


class TemasTest(unittest.TestCase):
    TEMAS = mn.compilar_temas({"espera": {"rotulo": "Espera", "palavras": ["esper", "demor", "atras"]}, "recepcao": {"rotulo": "Recepção", "palavras": ["recep"]},
                               "elogio": {"rotulo": "Elogio", "palavras": ["excelente", "recomend"], "negacao": True}})

    def test_normaliza_acento_e_caixa(self):
        self.assertEqual(mn.normalizar("  DEMORÓU   Muito\r\nà Recepção "), "demorou muito a recepcao")

    def test_palavra_inteira_comecando_pelo_trecho(self):
        achar = lambda t: mn.temas_do_texto(t, self.TEMAS)
        self.assertEqual(achar("A demora foi grande"), ["espera"])
        self.assertEqual(achar("ESPEREI duas horas, atraso enorme"), ["espera"])
        self.assertEqual(achar("Recepção ruim e atrasou"), ["espera", "recepcao"])
        self.assertEqual(achar("Excelente"), ["elogio"])
        self.assertEqual(achar("sem relação nenhuma"), [])
        self.assertEqual(achar(""), [])
        self.assertEqual(achar(None), [])
        self.assertEqual(mn.temas_do_texto("o exame foi desesperador", self.TEMAS), [])   # "esper" no meio da palavra nao conta: so no comeco

    def test_negacao_so_vale_nos_temas_que_pedem(self):
        achar = lambda t: mn.temas_do_texto(t, self.TEMAS)
        self.assertEqual(achar("Recomendo muito"), ["elogio"])
        self.assertEqual(achar("Não recomendo, atraso enorme"), ["espera"])           # "nao" anula so o elogio; o atraso continua contando
        self.assertEqual(achar("nem sempre excelente"), [])
        self.assertEqual(achar("Excelente. Não gostei da espera"), ["espera", "elogio"])   # o "nao" esta depois do elogio e fora do alcance dele: o elogio fica

    def test_assuntos_do_parametros_json_com_comentarios_de_verdade(self):
        import json
        cfg = json.loads((RAIZ / "Nps" / "parametros.json").read_text(encoding="utf-8"))["temas"]
        temas = mn.compilar_temas(cfg)
        achar = lambda t: set(mn.temas_do_texto(t, temas))
        self.assertIn("espera", achar("Não cumpriu o horário marcado!"))
        self.assertIn("espera", achar("Esperei mais de duas horas, o exame estava marcado para as 14h"))
        self.assertIn("espera", achar("Demora demais o atendimento"))
        self.assertNotIn("espera", achar("O atendimento foi no horário e muito bom"))
        self.assertIn("agendamento", achar("A marcação pelo WhatsApp é péssima"))
        self.assertIn("resultado", achar("Demora muito para entregar o laudo no portal"))
        self.assertIn("recepcao", achar("A recepcionista não deu nem bom dia"))
        self.assertIn("estrutura", achar("O banheiro precisa de mais limpeza"))
        self.assertIn("elogio", achar("Atendimento excelente"))
        self.assertNotIn("elogio", achar("Não recomendo"))
        self.assertEqual(achar("Gostaria de registrar uma ocorrência"), set())

    def test_pontos_de_nps_que_o_tema_custa(self):
        textos = ["demora enorme", "demorou", "recepção fria", "excelente", "", "tudo bem"]
        d = base([2, 5, 4, 10, 3, 9], textos)
        d["temas"] = d["comentario"].apply(lambda t: mn.temas_do_texto(t, self.TEMAS))
        t = {x["id"]: x for x in mn.analisar_temas(d, self.TEMAS)}
        self.assertEqual((t["espera"]["det"], t["espera"]["n"]), (2, 2))
        self.assertEqual(t["espera"]["pontos"], round(2 / 6 * 100, 1))      # 2 detratores em 6 respostas: o NPS subiria 33,3 pontos
        self.assertEqual(t["espera"]["pct_det_com_comentario"], 66.7)        # 3 detratores comentaram (o quarto nao), 2 deles falam de espera
        self.assertEqual(t["elogio"]["prom"], 1)
        self.assertEqual(mn.analisar_temas(d, self.TEMAS)[0]["id"], "espera")   # o mais citado pelos detratores primeiro


class MetaTest(unittest.TestCase):
    def test_ja_esta_na_meta(self):
        self.assertEqual(mn.caminho_para_a_meta(9, 0, 1, 70), {"ja": True, "meta": 70})

    def test_quantos_detratores_converter_e_quantas_respostas_novas(self):
        # 50 promotores, 30 neutros, 20 detratores: NPS 30; meta 50. Cada conversao soma 2 pontos (2/100 x 100): faltam 20 -> 10 conversoes
        c = mn.caminho_para_a_meta(50, 30, 20, 50)
        self.assertEqual((c["ja"], c["converter"], c["converter_cabe"], c["faltam_pontos"]), (False, 10, True, 20.0))
        # com k novos promotores: (30 + k) / (100 + k) >= 0,5  ->  k >= 40
        self.assertEqual(c["novas"], 40)
        self.assertAlmostEqual((50 + 40 - 20) / 140 * 100, 50.0)
        # meta que nem converter todos os detratores alcanca: 5 prom, 4 neutros, 1 det -> NPS 40; meta 90 pede 3 conversoes e so ha 1 detrator
        c = mn.caminho_para_a_meta(5, 4, 1, 90)
        self.assertFalse(c["converter_cabe"])
        self.assertEqual(c["novas"], 50)                                  # (0,9 x 10 - 4) / 0,1
        self.assertEqual(mn.caminho_para_a_meta(0, 0, 0, 50), None)


class GoogleEquivalenteTest(unittest.TestCase):
    def test_estrelas_viram_promotor_neutro_e_detrator(self):
        e = mn.nps_equivalente([5, 5, 5, 5, 4, 4, 3, 1, 2, 5])
        self.assertEqual((e["prom"], e["neut"], e["det"], e["n"]), (5, 2, 3, 10))
        self.assertEqual(e["nps"], 20.0)
        self.assertEqual(e["media"], 3.9)
        self.assertEqual((e["pct_5"], e["pct_baixas"]), (50.0, 30.0))
        self.assertIsNone(mn.nps_equivalente([]))

    def test_nota_do_nps_na_escala_de_estrelas(self):
        self.assertEqual(mn.estrelas_do_nps(9.0), 4.5)
        self.assertIsNone(mn.estrelas_do_nps(None))


class PrepararTest(unittest.TestCase):
    def test_descarta_nota_invalida_limpa_comentario_e_acha_o_mes(self):
        bruto = pd.DataFrame({"Id da Marcação": ["1", "2", "3", "4"], "Data Agendado Para": pd.to_datetime(["2026-09-30 23:50", "2026-10-01 08:00", None, "2026-10-02 09:00"]),
                              "NPS - Nota": [10, None, 4, 15], "NPS - Data de Resposta": pd.to_datetime(["2026-10-01"] * 4),
                              "NPS - Comentário": ["Ótimo\r\n atendimento", "x", "10", None], "Profissional": ["A"] * 4, "Procedimento": ["P"] * 4, "Unidade": ["U"] * 4,
                              "Mês (filtro)": ["2026-09", "2026-10", "2026-10", "2026-10"]})
        d = mn.preparar(bruto, TemasTest.TEMAS)
        self.assertEqual(list(d["id"]), ["1", "3"])                       # sem nota (2) e nota 15 (4) saem
        self.assertEqual(list(d["ym"]), ["2026-09", "2026-10"])           # o mes e o do agendamento; sem data, o do filtro
        self.assertEqual(d["comentario"].iloc[0], "Ótimo atendimento")     # quebra de linha vira espaco
        self.assertEqual(d["comentario"].iloc[1], "")                      # "10": so repetiu a nota
        self.assertEqual(list(d["classe"]), ["Promotor", "Detrator"])
        self.assertEqual(len(mn.preparar(pd.DataFrame(), {})), 0)


class GoogleMapsTest(unittest.TestCase):
    CFG = {"google_busca": "Clínica CSI", "google_cid": "13831494129270129913"}

    def setUp(self):
        import google_maps as gm
        self.gm = gm
        self.guardado = {gm.ABA_RESUMO: [], gm.ABA_AVALIACOES: []}

        def ler_aba(painel, aba):
            return list(self.guardado[aba])

        def gravar_mes(painel, aba, mes, linhas, exclusivo=False):
            chave = "dia" if aba == gm.ABA_RESUMO else "visto_em"           # o mes de cada aba e o da data de resumo / da primeira vez que a avaliacao foi vista
            self.guardado[aba] = [r for r in self.guardado[aba] if str(r.get(chave, ""))[:7] != mes] + list(linhas)
            return len(linhas)
        ambiente = mock.patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": "chave-de-teste", "PORTAL_ARMAZENAMENTO": "supabase"}, clear=False)
        ambiente.start()
        self.addCleanup(ambiente.stop)
        for alvo, valor in (("ler_aba", ler_aba), ("gravar_mes", gravar_mes)):
            m = mock.patch.object(gm.arm, alvo, valor)
            m.start()
            self.addCleanup(m.stop)
        self.chamadas = []

        def http(metodo, caminho, campos, corpo=None):
            self.chamadas.append((metodo, caminho))
            if caminho == "/places:searchText":
                return {"places": [{"id": "ChIJoutro", "googleMapsUri": "https://maps.google.com/?cid=111"}, {"id": "ChIJcsi", "googleMapsUri": "https://maps.google.com/?cid=13831494129270129913"}]}
            return {"id": "ChIJcsi", "displayName": {"text": "Clínica CSI"}, "rating": 4.6, "userRatingCount": 321, "googleMapsUri": "https://maps.google.com/?cid=13831494129270129913",
                    "reviews": [{"name": "places/ChIJcsi/reviews/a", "rating": 5, "publishTime": "2026-10-18T23:30:00Z", "relativePublishTimeDescription": "há 2 dias", "text": {"text": "Ótimo!"}},
                                {"name": "places/ChIJcsi/reviews/b", "rating": 1, "publishTime": "2026-10-10T12:00:00Z", "originalText": {"text": "Péssimo, esperei muito"}}]}
        m = mock.patch.object(gm, "_http", http)
        m.start()
        self.addCleanup(m.stop)

    def test_acha_o_perfil_pelo_cid_e_guarda_resumo_e_avaliacoes(self):
        r = self.gm.atualizar(self.CFG)
        self.assertTrue(r["atualizou"], r)
        self.assertEqual(self.chamadas[0], ("POST", "/places:searchText"))             # o perfil certo e o do CID, nao o primeiro da lista
        resumo = self.guardado[self.gm.ABA_RESUMO][0]
        self.assertEqual((resumo["nota"], resumo["total"], resumo["place_id"]), (4.6, 321, "ChIJcsi"))
        av = {a["id"]: a for a in self.guardado[self.gm.ABA_AVALIACOES]}
        self.assertEqual(av["places/ChIJcsi/reviews/a"]["dia"], "2026-10-18")          # 23:30 UTC ainda e dia 18 em Brasilia (UTC-3)
        self.assertEqual(av["places/ChIJcsi/reviews/b"]["texto"], "Péssimo, esperei muito")

    def test_nao_consulta_de_novo_antes_do_intervalo_e_nao_repete_avaliacao(self):
        self.gm.atualizar(self.CFG)
        n = len(self.chamadas)
        r = self.gm.atualizar(self.CFG)
        self.assertFalse(r["atualizou"])
        self.assertEqual(len(self.chamadas), n)                                          # nada de ir ao Google duas vezes seguidas
        self.guardado[self.gm.ABA_RESUMO][0]["coletado_em"] = "2020-01-01T00:00:00+00:00"   # a ultima consulta ja e velha
        self.gm.atualizar(self.CFG)
        self.assertEqual(len(self.guardado[self.gm.ABA_AVALIACOES]), 2)                  # as mesmas avaliacoes nao entram duas vezes
        self.assertEqual([c[1] for c in self.chamadas].count("/places:searchText"), 1)  # e o perfil ja conhecido nao e buscado de novo

    def test_sem_chave_diz_o_que_fazer_e_nao_quebra(self):
        with mock.patch.dict("os.environ", {"GOOGLE_PLACES_API_KEY": ""}):
            r = self.gm.atualizar(self.CFG)
        self.assertFalse(r["atualizou"])
        self.assertIn("GOOGLE_PLACES_API_KEY", r["mensagem"])
        self.assertEqual(r["avisos"], [])                                                # nao e erro: e so um passo que falta

    def test_erro_do_google_vira_aviso(self):
        def recusa(*a, **k):
            raise self.gm.GoogleErro("Google Maps: a chave não tem a Places API (New) ativada (HTTP 403).")
        with mock.patch.object(self.gm, "_http", recusa):
            r = self.gm.atualizar(self.CFG)
        self.assertFalse(r["atualizou"])
        self.assertIn("403", r["avisos"][0])

    def test_perfil_nao_encontrado_pelo_cid(self):
        def so_outros(metodo, caminho, campos, corpo=None):
            return {"places": [{"id": "ChIJoutro", "googleMapsUri": "https://maps.google.com/?cid=111"}]}
        with mock.patch.object(self.gm, "_http", so_outros):
            r = self.gm.atualizar(self.CFG)
        self.assertIn("GOOGLE_PLACE_ID", r["mensagem"])

    def test_place_id_da_vercel_dispensa_a_busca(self):
        with mock.patch.dict("os.environ", {"GOOGLE_PLACE_ID": "ChIJfixo"}):
            self.gm.atualizar(self.CFG)
        self.assertNotIn(("POST", "/places:searchText"), self.chamadas)
        self.assertEqual(self.chamadas[0], ("GET", "/places/ChIJfixo?languageCode=pt-BR"))

    def test_fora_da_nuvem_nao_faz_nada(self):
        with mock.patch.dict("os.environ", {"PORTAL_ARMAZENAMENTO": "arquivos", "VERCEL": ""}):
            self.assertEqual(self.gm.atualizar(self.CFG), {"atualizou": False, "mensagem": "", "avisos": []})
            self.assertEqual(self.gm.ler(), {"resumos": [], "avaliacoes": []})


if __name__ == "__main__":
    unittest.main()
