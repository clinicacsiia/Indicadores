"""Faturamento: cada convenio tem o prazo de envio aprendido do historico (media de dias da emissao ao envio, sem casos isolados) e o SUS ganha uma analise
mes a mes (gerar_faturamento.prazo_tipico, prazos_aprendidos, montar_sus)."""
import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "Faturamento"))

import gerar_faturamento as gf  # noqa: E402

HOJE = date(2026, 10, 14)


def dia(atras: int):
    return pd.Timestamp(HOJE) - pd.Timedelta(days=atras)


def fatura(ident, op, status, emitida_ha, valor=1000.0, enviada_ha=None):
    emissao = dia(emitida_ha)
    envio = dia(enviada_ha) if enviada_ha is not None else pd.NaT
    return {"Fatura - Id": ident, "Operadora - Nome": op, "Fatura - Status": status, "Fatura - Valor": None if status == "Cancelada" else valor,
            "Fatura - Data Inicial": emissao - pd.Timedelta(days=20), "Fatura - Data Fim": emissao - pd.Timedelta(days=1),
            "Fatura - Data de Emissão": emissao, "Fatura - Data de Envio": envio,
            "Fatura - Data de Vencimento": envio + pd.Timedelta(days=30) if pd.notna(envio) else pd.NaT,
            "Fatura - Usuário Responsável": "ana", "Fatura - Envio - Protocolo": "123" if status == "Enviada" else None, "Fatura - Valor Retenções": 0.0}


def faturas():
    linhas = [
        # SUS: setembro (2 canceladas, 1 enviada 35 dias depois) e outubro (5 a enviar de hoje, 3 canceladas)
        fatura(1, "SUS", "Cancelada", 35), fatura(2, "SUS", "Cancelada", 35), fatura(3, "SUS", "Enviada", 35, 37809.67, enviada_ha=0),
        *[fatura(10 + i, "SUS", "A Enviar", 0, 1807.2) for i in range(5)],
        *[fatura(20 + i, "SUS", "Cancelada", 3) for i in range(3)],
        # SUS esperando ha 30 dias: passa dos 7 dias gerais, mas o SUS ja levou 35 dias para enviar (prazo aprendido: avisa depois de 52)
        fatura(30, "SUS", "A Enviar", 30, 5000.0),
        # Petrobras e Amil: prazo geral
        fatura(40, "PETROBRAS", "A Enviar", 27, 114.0), fatura(41, "PETROBRAS", "A Enviar", 9, 300.0), fatura(42, "PETROBRAS", "Enviada", 40, 200.0, enviada_ha=39),
        fatura(50, "AMIL", "Enviada", 5, 800.0, enviada_ha=5), fatura(51, "AMIL", "A Enviar", 1, 250.0),
    ]
    return gf.preparar_faturas(pd.DataFrame(linhas))


class PrazoTipicoTest(unittest.TestCase):
    def test_sem_historico_vale_o_prazo_geral(self):
        self.assertEqual(gf.prazo_tipico([]), (None, 0))
        self.assertEqual(gf.limites_de_aviso(None), (7, 30))

    def test_pouco_historico_vale_o_maior_que_ja_aconteceu(self):
        self.assertEqual(gf.prazo_tipico([90]), (90.0, 1))           # um so, de 90 dias: o normal dele e 90
        self.assertEqual(gf.prazo_tipico([1, 90]), (90.0, 2))

    def test_caso_isolado_nao_puxa_a_media(self):
        tipico, n = gf.prazo_tipico([0, 0, 1, 0, 90])
        self.assertEqual(n, 5)
        self.assertAlmostEqual(tipico, 0.25, delta=0.1)             # o 90 isolado fica de fora
        self.assertAlmostEqual(gf.prazo_tipico([30, 32, 35])[0], 32.3, delta=0.1)   # tudo na mesma faixa: media simples

    def test_se_repetir_vira_rotina_e_entra_na_media(self):
        self.assertAlmostEqual(gf.prazo_tipico([0, 0, 0, 0, 40, 45])[0], 14.2, delta=0.1)   # dois casos longos: recorrencia
        self.assertEqual(gf.prazo_tipico([0, 0, 90, 90])[0], 45.0)  # metade e metade: nada e "isolado"

    def test_limite_de_aviso(self):
        self.assertEqual(gf.limites_de_aviso(0.3), (7, 30))         # quem envia no mesmo dia continua com os 7 dias
        self.assertEqual(gf.limites_de_aviso(35), (52, 75))         # media * 1,3 + 7; critico = atencao + 23
        self.assertEqual(gf.limites_de_aviso(90), (124, 147))

    def test_quem_tem_a_analise_mes_a_mes(self):
        self.assertTrue(gf.acompanhado_mes_a_mes("SUS"))
        self.assertTrue(gf.acompanhado_mes_a_mes("sus curso"))
        self.assertFalse(gf.acompanhado_mes_a_mes("SUSEP SAUDE"))    # so o nome inteiro ou "SUS ..."
        self.assertFalse(gf.acompanhado_mes_a_mes("PETROBRAS"))
        self.assertFalse(gf.acompanhado_mes_a_mes(None))


class MontarFaturasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fg = gf.montar_faturas(faturas(), HOJE)

    def test_sus_dentro_do_prazo_aprendido_nao_conta_como_atraso(self):
        ae = self.fg["a_enviar"]
        # a Petrobras leva ~1 dia (avisa depois de 8): as de 27 e 9 dias passam. O SUS levou 35 dias (avisa depois de 52): a de 30 dias esta dentro
        self.assertEqual(ae["acima_atencao"]["qtd"], 2)
        self.assertAlmostEqual(ae["acima_atencao"]["valor"], 414.0)
        self.assertEqual(ae["acima_atencao"]["maior_espera"], 27)
        self.assertEqual(ae["acima_critica"]["qtd"], 0)
        self.assertEqual([l[1] for l in ae["itens_espera"]["linhas"]], ["PETROBRAS", "PETROBRAS"])
        proprio = ae["dentro_do_prazo_proprio"]
        self.assertEqual((proprio["qtd"], proprio["nomes"]), (1, ["SUS"]))
        self.assertAlmostEqual(proprio["valor"], 5000.0)
        por = {x["nome"]: x for x in ae["prazos_aprendidos"]}
        self.assertEqual((por["SUS"]["tipico"], por["SUS"]["amostras"], por["SUS"]["atencao"], por["SUS"]["critica"]), (35.0, 1, 52, 75))
        self.assertEqual((por["PETROBRAS"]["atencao"], por["AMIL"]["atencao"]), (8, 7))

    def test_sus_passa_do_prazo_aprendido_vira_atraso(self):
        f = faturas()
        extra = gf.preparar_faturas(pd.DataFrame([fatura(60, "SUS", "A Enviar", 60, 2000.0), fatura(61, "SUS", "A Enviar", 80, 1500.0)]))
        ae = gf.montar_faturas(pd.concat([f, extra], ignore_index=True), HOJE)["a_enviar"]
        self.assertEqual(ae["acima_atencao"]["qtd"], 4)    # 2 da Petrobras + SUS de 60 e de 80 dias (passam dos 52)
        self.assertEqual(ae["acima_critica"]["qtd"], 1)    # so a de 80 passa dos 75 do SUS; Petrobras (27) nao passa dos 31
        self.assertEqual(ae["acima_atencao"]["maior_espera"], 80)

    def test_um_caso_isolado_nao_muda_o_prazo_do_convenio_mas_a_recorrencia_muda(self):
        base = [fatura(100 + i, "ALFA", "Enviada", 40 - i, 100.0, enviada_ha=40 - i - d) for i, d in enumerate([1, 1, 2, 1])]
        isolado = gf.montar_faturas(gf.preparar_faturas(pd.DataFrame([*base, fatura(110, "ALFA", "Enviada", 90, 100.0, enviada_ha=0)])), HOJE)["a_enviar"]
        alfa = {x["nome"]: x for x in isolado["prazos_aprendidos"]}["ALFA"]
        self.assertAlmostEqual(alfa["tipico"], 1.25, delta=0.1)   # o de 90 dias nao puxou
        self.assertEqual(alfa["maximo"], 90)
        repetido = gf.montar_faturas(gf.preparar_faturas(pd.DataFrame(
            [*base, fatura(110, "ALFA", "Enviada", 90, 100.0, enviada_ha=0), fatura(111, "ALFA", "Enviada", 80, 100.0, enviada_ha=0)])), HOJE)["a_enviar"]
        alfa2 = {x["nome"]: x for x in repetido["prazos_aprendidos"]}["ALFA"]
        self.assertGreater(alfa2["tipico"], 20)                    # dois casos longos: virou rotina e a media acompanha
        self.assertGreater(alfa2["atencao"], alfa["atencao"])

    def test_analise_do_sus_mes_a_mes(self):
        sus = self.fg["sus"]
        self.assertTrue(sus["tem"])
        self.assertEqual(sus["nomes"], ["SUS"])
        self.assertEqual(sus["limite_atencao"], 52)
        self.assertEqual([(x["nome"], x["tipico"], x["amostras"]) for x in sus["prazos"]], [("SUS", 35.0, 1)])
        meses = {m["mes"]: m for m in sus["meses"]}
        self.assertEqual(sorted(meses), ["2026-09", "2026-10"])   # so os meses em que aparece
        set_, out = meses["2026-09"], meses["2026-10"]
        self.assertEqual((set_["enviadas"], set_["canceladas"], set_["a_enviar"], set_["emitidas"]), (1, 2, 1, 2))   # a SUS de 30 dias foi emitida em 14/09
        self.assertEqual(set_["dias_envio_mediana"], 35.0)
        self.assertAlmostEqual(set_["valor_enviado"], 37809.67)
        self.assertEqual((out["a_enviar"], out["canceladas"], out["enviadas"]), (5, 3, 0))
        self.assertEqual(sus["total"], 1 + 2 + 5 + 3 + 1)
        self.assertEqual(sus["canceladas"], 5)

    def test_demais_convenios_sao_a_referencia(self):
        d = self.fg["sus"]["demais"]
        self.assertEqual(d["qtd"], 2)           # Petrobras (1 dia) e Amil (0): enviadas dos convenios sem prazo proprio
        self.assertEqual(d["mediana"], 0.5)

    def test_sem_sus_nada_muda(self):
        f = faturas()
        f = f[~f["Operadora - Nome"].str.startswith("SUS")]
        fg = gf.montar_faturas(f, HOJE)
        self.assertEqual(fg["sus"], {"tem": False})
        self.assertEqual(fg["a_enviar"]["dentro_do_prazo_proprio"]["qtd"], 0)


class AlertasTest(unittest.TestCase):
    def test_alerta_cita_o_sus_que_ficou_de_fora(self):
        fg = gf.montar_faturas(faturas(), HOJE)
        alertas = gf.alertas_faturas(fg, {}, "Outubro/2026")
        espera = next(a for a in alertas if a["titulo"].startswith("Faturas esperando envio"))
        self.assertIn("<b>2</b> fatura(s)", espera["texto"])
        self.assertIn("a mais antiga há <b>27</b> dias", espera["texto"])
        self.assertIn("Ficam de fora, por estarem dentro do prazo habitual de cada convênio (SUS)", espera["texto"])

    def test_sem_sus_o_texto_e_o_de_sempre(self):
        f = faturas()
        fg = gf.montar_faturas(f[~f["Operadora - Nome"].str.startswith("SUS")], HOJE)
        espera = next(a for a in gf.alertas_faturas(fg, {}, "Outubro/2026") if a["titulo"].startswith("Faturas esperando envio"))
        self.assertNotIn("Ficam de fora", espera["texto"])


if __name__ == "__main__":
    unittest.main()
