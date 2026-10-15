"""Métricas de tempo (Tempo/metricas_tempo.py): TAT, ociosidade, janelas, outliers e formato de saída.

Rodar:  python -m unittest discover -s tests -v
Os casos pequenos têm a resposta calculada à mão; o grande (log sintético) confere propriedades que não podem quebrar."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "Tempo"))
import exemplo_tempo as ex  # noqa: E402
import metricas_tempo as mt  # noqa: E402

T = pd.Timestamp


def etapas(*linhas):
    return pd.DataFrame(linhas, columns=["atendimento_id", "etapa", "inicio", "fim", "setor"]).assign(
        inicio=lambda d: pd.to_datetime(d["inicio"]), fim=lambda d: pd.to_datetime(d["fim"]))


class DuracaoETatTest(unittest.TestCase):
    def test_para_timedelta_aceita_numero_texto_e_lixo(self):
        self.assertEqual(mt.para_timedelta(pd.Series([90, 3600])).tolist(), [pd.Timedelta(seconds=90), pd.Timedelta(hours=1)])
        self.assertEqual(mt.para_timedelta(pd.Series(["00:01:30", "01:00:00"])).tolist(), [pd.Timedelta(seconds=90), pd.Timedelta(hours=1)])
        self.assertTrue(mt.para_timedelta(pd.Series(["abc"])).isna().all())

    def test_tat_espera_e_repasse(self):
        e = etapas(
            (1, "Cadastro", "2026-09-07 08:00:00", "2026-09-07 08:02:00", "A"),
            (1, "Chamado", "2026-09-07 08:03:00", "2026-09-07 08:33:00", "A"),     # repasse de 1 min, fila de 30
            (1, "Em Atendimento", "2026-09-07 08:34:00", "2026-09-07 08:49:00", "A"),
            (1, "Finalizado", "2026-09-07 08:50:00", "2026-09-07 08:55:00", "A"),  # repasse de 1 min
            (2, "Cadastro", "2026-09-07 09:00:00", "2026-09-07 09:01:00", "A"),
            (2, "Finalizado", "2026-09-07 09:00:30", "2026-09-07 09:10:00", "A"),  # começa antes de a anterior acabar: repasse 0, não negativo
            (3, "Cadastro", "2026-09-07 10:00:00", None, "B"),                     # sem fim e sem etapa final
        )
        _, v = mt.ciclo_por_atendimento(e.sample(frac=1, random_state=1))          # a ordem de entrada não pode importar
        v = v.set_index("atendimento_id")
        self.assertEqual(v.loc[1, "tat_min"], 55)
        self.assertEqual(v.loc[1, "fila_min"], 30)
        self.assertEqual(v.loc[1, "espera_min"], 34)                 # chegada 08:00 até o início de Em Atendimento, 08:34
        self.assertEqual(v.loc[1, "repasse_min"], 3)
        self.assertEqual(v.loc[2, "tat_min"], 10)
        self.assertEqual(v.loc[2, "repasse_min"], 0)
        self.assertTrue(pd.isna(v.loc[2, "fila_min"]) and pd.isna(v.loc[2, "espera_min"]))   # não passou pela fila nem pelo atendimento: vazio, não zero
        self.assertTrue(pd.isna(v.loc[3, "tat_min"]) and v.loc[3, "aberto"])


class RatearTest(unittest.TestCase):
    def test_intervalo_reparte_os_segundos_em_cada_hora(self):
        iv = pd.DataFrame({"recurso": ["RM"], "inicio": [T("2026-09-07 10:30:00")], "fim": [T("2026-09-07 12:15:30")]})
        r = mt.ratear_por_janela(iv, "h")
        self.assertEqual(r["janela"].dt.hour.tolist(), [10, 11, 12])
        self.assertEqual(r["minutos"].round(4).tolist(), [30, 60, 15.5])

    def test_atravessa_a_meia_noite_e_soma_bate(self):
        iv = pd.DataFrame({"recurso": ["A", "B"], "inicio": [T("2026-09-07 23:10:00"), T("2026-09-07 08:00:00")],
                           "fim": [T("2026-09-08 01:20:00"), T("2026-09-07 08:00:00")]})                  # B tem comprimento zero
        r = mt.ratear_por_janela(iv, "h")
        self.assertEqual(set(r["recurso"]), {"A"})
        self.assertAlmostEqual(r["minutos"].sum(), 130)
        self.assertEqual(len(r), 3)                                            # 23h, 00h e 01h

    def test_meia_hora(self):
        iv = pd.DataFrame({"inicio": [T("2026-09-07 10:20:00")], "fim": [T("2026-09-07 11:10:00")]})
        self.assertEqual(mt.ratear_por_janela(iv, "30min")["minutos"].tolist(), [10, 30, 10])


class OciosidadeTest(unittest.TestCase):
    def setUp(self):
        self.periodo = (T("2026-09-07"), T("2026-09-08"))                       # segunda-feira inteira

    def test_buracos_com_sentinelas(self):
        usos = pd.DataFrame({"recurso": ["RM", "RM"], "inicio": [T("2026-09-07 08:10"), T("2026-09-07 09:00")],
                             "fim": [T("2026-09-07 08:40"), T("2026-09-07 09:30")]})
        h = mt.ocupacao_por_janela(mt.intervalos_de_uso(usos, self.periodo), (7, 18), (0,))
        self.assertTrue(np.allclose(h["min_disponivel"], 60))                    # ocupado + ocioso fecha a hora, sempre
        self.assertAlmostEqual(h["min_ocupado"].sum(), 60)
        self.assertAlmostEqual(h["min_ocioso"].sum(), 11 * 60 - 60)
        h8 = h[h["janela"].dt.hour == 8].iloc[0]
        self.assertEqual((h8["min_ocupado"], h8["min_ocioso"]), (30, 30))
        self.assertEqual(len(h), 11)                                            # 07h..17h; a noite fica fora do expediente

    def test_sobreposicao_nao_conta_duas_vezes(self):
        usos = pd.DataFrame({"recurso": ["RM", "RM"], "inicio": [T("2026-09-07 08:00"), T("2026-09-07 08:20")],
                             "fim": [T("2026-09-07 08:40"), T("2026-09-07 09:00")]})
        h = mt.ocupacao_por_janela(mt.intervalos_de_uso(usos, self.periodo), (7, 18), (0,))
        self.assertEqual(h[h["janela"].dt.hour == 8].iloc[0]["min_ocupado"], 60)
        self.assertTrue((h["min_ocupado"] <= 60.0001).all())

    def test_buraco_da_noite_so_conta_dentro_do_expediente(self):
        usos = pd.DataFrame({"recurso": ["RM", "RM"], "inicio": [T("2026-09-07 17:30"), T("2026-09-08 08:10")],
                             "fim": [T("2026-09-07 17:50"), T("2026-09-08 08:20")]})
        h = mt.ocupacao_por_janela(mt.intervalos_de_uso(usos, (T("2026-09-07 17:00"), T("2026-09-08 09:00"))), (7, 18), (0, 1))
        pontos = h.set_index("janela")
        self.assertEqual((pontos.loc["2026-09-07 17:00", "min_ocupado"], pontos.loc["2026-09-07 17:00", "min_ocioso"]), (20, 40))
        self.assertEqual(pontos.loc["2026-09-08 07:00", "min_ocioso"], 60)
        self.assertNotIn(T("2026-09-07 20:00"), pontos.index)

    def test_domingo_e_feriado_ficam_fora(self):
        usos = pd.DataFrame({"recurso": ["RM"], "inicio": [T("2026-09-07 08:00")], "fim": [T("2026-09-07 08:30")]})
        iv = mt.intervalos_de_uso(usos, (T("2026-09-06"), T("2026-09-09")))
        h = mt.ocupacao_por_janela(iv, (7, 18), (0, 1, 2, 3, 4, 5), feriados=("2026-09-08",))
        self.assertEqual(sorted(h["janela"].dt.day.unique()), [7])                # 06 é domingo e 08 é feriado: só segunda sobra

    def test_log_de_transicoes_de_status(self):
        tr = pd.DataFrame({"recurso": ["RM"] * 4, "ts": [T("2026-09-07 07:00"), T("2026-09-07 08:00"), T("2026-09-07 09:00"), T("2026-09-07 09:30")],
                           "status": ["livre", "ocupado", "manutencao", "livre"]})
        iv = mt.intervalos_de_status(tr.sample(frac=1, random_state=3), T("2026-09-07 10:00"))
        h = mt.ocupacao_por_janela(iv.assign(estado=iv["estado"].replace({"livre": "ocioso"})), (7, 18), (0,))
        self.assertEqual(h["min_ocupado"].sum(), 60)
        self.assertEqual(h["min_ocioso"].sum(), 60 + 30)
        self.assertEqual(h["min_outros"].sum(), 30)                             # manutenção não é ociosidade
        self.assertAlmostEqual(h[h["janela"].dt.hour == 9].iloc[0]["pct_ociosidade"], 50)

    def test_dia_soma_as_horas(self):
        usos = ex.gerar_log_sintetico(dias=3)[1]
        iv = mt.intervalos_de_uso(usos, (T("2026-09-07"), T("2026-09-10")))
        h = mt.ocupacao_por_janela(iv)
        d = mt.ocupacao_diaria(h)
        self.assertAlmostEqual(d["min_ocioso"].sum(), h["min_ocioso"].sum(), places=3)
        self.assertTrue(np.allclose(d["min_disponivel"], 660))


class OutlierTest(unittest.TestCase):
    def amostra(self):
        rng = np.random.default_rng(0)
        x = rng.lognormal(np.log(20), 0.6, 2000)
        x[:10] = [900, 1200, 3000, 9000, 20000, 30000, 45000, 600, 700, 800]       # esquecimentos
        return pd.DataFrame({"min": x, "etapa": np.where(np.arange(2000) % 2, "A", "B")})

    def test_iqr_e_mad_pegam_os_esquecidos_e_poupam_o_normal(self):
        d = self.amostra()
        for metodo in ("iqr", "mad"):
            r = mt.sinalizar_outliers(d, "min", ["etapa"], metodo)
            self.assertTrue(r["outlier"][:10].all(), metodo)
            self.assertLess(r["outlier"][10:].mean(), 0.04, metodo)             # perda de casos normais pequena

    def test_zscore_classico_e_mascarado_pelos_proprios_outliers(self):
        d = self.amostra()
        z = mt.sinalizar_outliers(d, "min", None, "zscore", log=False)
        iqr = mt.sinalizar_outliers(d, "min", None, "iqr")
        self.assertLess(z["outlier"][:10].sum(), iqr["outlier"][:10].sum())     # média e desvio inflados escondem os casos de 600 a 1200

    def test_cerca_por_grupo_e_grupo_pequeno_usa_o_global(self):
        d = pd.DataFrame({"min": [1, 1.1, 0.9, 1.2, 1, 100, 100, 110, 90, 105] + [1.0, 1.05, 0.95, 1.1] * 10 + [100, 105, 95, 110] * 10,
                          "g": ["rapido"] * 5 + ["lento"] * 5 + ["rapido"] * 40 + ["lento"] * 40})
        r = mt.sinalizar_outliers(d, "min", ["g"], "iqr", n_min=30)
        self.assertLess(r.loc[d["g"] == "rapido", "limite"].max(), 5)           # 100 min é normal no grupo lento, absurdo no rápido
        self.assertGreater(r.loc[d["g"] == "lento", "limite"].min(), 100)
        r2 = mt.sinalizar_outliers(d.head(10), "min", ["g"], "iqr", n_min=30)    # grupos de 5: estatística global
        self.assertEqual(r2["limite"].nunique(), 1)

    def test_piso_protege_etapa_de_segundos_e_teto_por_etapa(self):
        rng = np.random.default_rng(1)
        d = pd.DataFrame({"min": rng.lognormal(np.log(0.1), 0.3, 500), "etapa": "rapida"})      # mediana de 6 segundos
        d.loc[0, "min"] = 3                                                                      # 3 min: estatisticamente absurdo, na prática normal
        sem_piso = mt.sinalizar_outliers(d, "min", ["etapa"])
        com_piso = mt.sinalizar_outliers(d, "min", ["etapa"], piso_limite=5)
        self.assertTrue(sem_piso["outlier"][0])
        self.assertEqual(com_piso["outlier"].sum(), 0)
        tetos = pd.Series(2.0, index=d.index)                                                    # teto vence o piso
        self.assertTrue(mt.sinalizar_outliers(d, "min", ["etapa"], piso_limite=5, teto=tetos)["outlier"][0])

    def test_teto_duro_e_nulos(self):
        d = pd.DataFrame({"min": [5, 6, 7, 5, 6, 2000, np.nan]})
        r = mt.sinalizar_outliers(d, "min", None, "iqr", teto=1440, n_min=1)
        self.assertEqual(r["outlier"].tolist(), [False] * 5 + [True, False])    # NaN nunca é outlier
        with self.assertRaises(ValueError):
            mt.sinalizar_outliers(d, "min", None, "nao_existe")


class PipelineEFormatoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.etapas, cls.usos = ex.gerar_log_sintetico(dias=8)
        cls.t = mt.construir_tabelas(cls.etapas, cls.usos, ("2026-09-07", "2026-09-14"))

    def test_todas_as_tabelas_sao_planas_e_sem_timedelta(self):
        for nome, df in self.t.items():
            self.assertIsInstance(df.index, pd.RangeIndex, nome)
            self.assertFalse(isinstance(df.columns, pd.MultiIndex), nome)
            self.assertFalse(any(pd.api.types.is_timedelta64_dtype(df[c]) for c in df), nome)
            self.assertGreater(len(df), 0, nome)

    def test_chaves_nunca_nulas_e_sem_linha_repetida(self):
        chaves = {"janelas_hora": ["janela_inicio", "setor", "metrica"], "janelas_dia": ["janela_inicio", "setor", "metrica"],
                  "ocupacao_hora": ["janela_inicio", "recurso"], "ocupacao_dia": ["janela_inicio", "recurso"], "gargalo_dia": ["dia", "setor"]}
        for nome, ch in chaves.items():
            df = self.t[nome]
            self.assertFalse(df[ch].isna().any().any(), nome)
            self.assertFalse(df.duplicated(ch).any(), nome)

    def test_dia_calculado_do_atendimento_nao_das_medias_das_horas(self):
        v, h, d = self.t["atendimentos"], self.t["janelas_hora"], self.t["janelas_dia"]
        dia = d[(d["metrica"] == "tat_min") & (d["setor"] == "CSI 1")].iloc[0]
        base = v[(v["setor"] == "CSI 1") & (v["dia"] == dia["janela_inicio"]) & ~v["tat_outlier"]]["tat_min"]
        self.assertAlmostEqual(float(dia["mediana_min"]), float(base.median()), places=1)
        self.assertEqual(int(dia["n"]), len(base))

    def test_outliers_ficam_fora_das_estatisticas_e_contados(self):
        v, d = self.t["atendimentos"], self.t["janelas_dia"]
        self.assertGreater(v["tat_outlier"].sum(), 0)
        self.assertEqual(int(d[d["metrica"] == "tat_min"]["n_outliers"].sum()), int((v["tat_outlier"] & v["tat_min"].notna()).sum()))
        self.assertLess(float(d["p90_min"].max()), 2000)                         # nenhum esquecimento de dias vazou para o p90

    def test_pico_esta_no_horario_de_maior_chegada(self):
        g = self.t["gargalo_dia"]
        self.assertGreaterEqual(g["n"].min(), 10)
        self.assertTrue(g["hora"].between(7, 17).all())
        self.assertTrue(g["hora"].isin([9, 10, 14]).mean() > 0.6)                # o gerador concentra as chegadas nesses horários

    def test_janela_aberta_e_marcada(self):
        h = self.t["janelas_hora"]
        ultima = h["janela_inicio"] == h["janela_inicio"].max()
        self.assertTrue(h["janela_fechada"].dtype == bool)
        self.assertFalse(h.loc[ultima, "janela_fechada"].any())                  # a hora em que chegou o último paciente ainda está aberta
        self.assertTrue(h.loc[~ultima, "janela_fechada"].all())

    def test_exportar_json_csv_e_numeros_limpos(self):
        with tempfile.TemporaryDirectory() as pasta:
            saidas = mt.exportar({"janelas_hora": self.t["janelas_hora"]}, Path(pasta), meta={"origem": "teste"})
            js = json.loads(saidas["janelas_hora.json"].read_text(encoding="utf-8"))
            self.assertEqual(js["meta"], {"origem": "teste"})
            self.assertEqual(js["columns"], list(self.t["janelas_hora"].columns))
            self.assertEqual(len(js["data"]), len(self.t["janelas_hora"]))
            linha = dict(zip(js["columns"], js["data"][0]))
            self.assertRegex(linha["janela_inicio"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
            self.assertEqual(round(linha["p90_min"], 2), linha["p90_min"])         # 58.87, não 58.869998931884766
            csv = pd.read_csv(saidas["janelas_hora.csv"], encoding="utf-8-sig")
            self.assertEqual(list(csv.columns), list(self.t["janelas_hora"].columns))


class AdaptadorKlingoTest(unittest.TestCase):
    def test_fluxo_do_13404_vira_etapas_e_usos_de_equipamento(self):
        f = pd.DataFrame({
            "Data do Atendimento": ["2026-09-07 08:00"] * 3 + ["2026-09-07 09:00"],
            "Profissional / Equipamento": ["RM", "RM", "RM", "DRA FULANA"], "Convênio": ["SUS", "SUS", "SUS", "PARTICULAR"],
            "Setor (CSI/RM/RX/TC)": ["CSI - 2"] * 3 + ["CSI"], "Etapa": ["Cadastro", "Em Atendimento", "Finalizado", "Em Atendimento"],
            "Início da Etapa": ["2026-09-07 08:01:10", "2026-09-07 08:20:05", "2026-09-07 08:50:00", "2026-09-07 09:10:00"],
            "Fim da Etapa": ["2026-09-07 08:03:00", "2026-09-07 08:49:30", "2026-09-07 08:52:00", "2026-09-07 09:30:00"]})
        et, usos = mt.adaptar_fluxo_klingo(f, ["RM", "TC"], ["ULTRASSONOGRAFIA "], {"CSI - 2": "CSI 2"})
        self.assertEqual(et["atendimento_id"].nunique(), 2)
        self.assertEqual(et["setor"].tolist(), ["CSI 2"] * 3 + ["CSI"])
        self.assertEqual(usos["recurso"].tolist(), ["RM"])                         # a doutora não é equipamento
        _, v = mt.ciclo_por_atendimento(et)
        self.assertAlmostEqual(v.sort_values("chegada")["tat_min"].iloc[0], 50.8333, places=3)


if __name__ == "__main__":
    unittest.main()
