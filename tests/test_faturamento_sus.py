"""Faturamento: o SUS tem prazo de envio proprio (nao entra nos 7/30 dias dos outros convenios) e ganha uma analise mes a mes (gerar_faturamento.montar_sus)."""
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
        # SUS CURSO esperando ha 30 dias: passa dos 7 dias gerais, mas esta dentro dos 45 do SUS
        fatura(30, "SUS CURSO", "A Enviar", 30, 5000.0),
        # Petrobras e Amil: prazo geral
        fatura(40, "PETROBRAS", "A Enviar", 27, 114.0), fatura(41, "PETROBRAS", "A Enviar", 9, 300.0), fatura(42, "PETROBRAS", "Enviada", 40, 200.0, enviada_ha=39),
        fatura(50, "AMIL", "Enviada", 5, 800.0, enviada_ha=5), fatura(51, "AMIL", "A Enviar", 1, 250.0),
    ]
    return gf.preparar_faturas(pd.DataFrame(linhas))


class PrazoProprioTest(unittest.TestCase):
    def test_quem_tem_prazo_proprio(self):
        self.assertEqual(gf.prazo_proprio("SUS"), (45, 75))
        self.assertEqual(gf.prazo_proprio("sus curso"), (45, 75))
        self.assertEqual(gf.prazo_proprio("S.U.S"), None)
        self.assertIsNone(gf.prazo_proprio("SUSEP SAUDE"))   # so o nome inteiro ou "SUS ..."
        self.assertIsNone(gf.prazo_proprio("PETROBRAS"))
        self.assertIsNone(gf.prazo_proprio(None))


class MontarFaturasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fg = gf.montar_faturas(faturas(), HOJE)

    def test_sus_dentro_do_prazo_nao_conta_como_atraso(self):
        ae = self.fg["a_enviar"]
        # so a Petrobras de 27 e 9 dias passam dos 7 dias; a SUS CURSO de 30 dias esta dentro dos 45 dela
        self.assertEqual(ae["acima_atencao"]["qtd"], 2)
        self.assertAlmostEqual(ae["acima_atencao"]["valor"], 414.0)
        self.assertEqual(ae["acima_atencao"]["maior_espera"], 27)
        self.assertEqual(ae["acima_critica"]["qtd"], 0)
        self.assertEqual([l[1] for l in ae["itens_espera"]["linhas"]], ["PETROBRAS", "PETROBRAS"])
        proprio = ae["dentro_do_prazo_proprio"]
        self.assertEqual((proprio["qtd"], proprio["nomes"]), (1, ["SUS CURSO"]))
        self.assertAlmostEqual(proprio["valor"], 5000.0)

    def test_sus_passa_do_prazo_proprio_vira_atraso(self):
        f = faturas()
        extra = gf.preparar_faturas(pd.DataFrame([fatura(60, "SUS", "A Enviar", 50, 2000.0), fatura(61, "SUS", "A Enviar", 80, 1500.0)]))
        ae = gf.montar_faturas(pd.concat([f, extra], ignore_index=True), HOJE)["a_enviar"]
        self.assertEqual(ae["acima_atencao"]["qtd"], 4)    # 2 da Petrobras + SUS de 50 e de 80 dias
        self.assertEqual(ae["acima_critica"]["qtd"], 1)    # a de 80 passa dos 75 do SUS; Petrobras (27) nao passa dos 30
        self.assertEqual(ae["acima_atencao"]["maior_espera"], 80)

    def test_analise_do_sus_mes_a_mes(self):
        sus = self.fg["sus"]
        self.assertTrue(sus["tem"])
        self.assertEqual(sus["nomes"], ["SUS", "SUS CURSO"])
        self.assertEqual((sus["limite_atencao"], sus["limite_critica"]), (45, 75))
        meses = {m["mes"]: m for m in sus["meses"]}
        self.assertEqual(sorted(meses), ["2026-09", "2026-10"])   # so os meses em que aparece
        set_, out = meses["2026-09"], meses["2026-10"]
        self.assertEqual((set_["enviadas"], set_["canceladas"], set_["a_enviar"], set_["emitidas"]), (1, 2, 1, 2))   # a SUS CURSO de 30 dias foi emitida em 14/09
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
        self.assertIn("SUS CURSO fica de fora enquanto estiver dentro do seu prazo próprio", espera["texto"])

    def test_sem_sus_o_texto_e_o_de_sempre(self):
        f = faturas()
        fg = gf.montar_faturas(f[~f["Operadora - Nome"].str.startswith("SUS")], HOJE)
        espera = next(a for a in gf.alertas_faturas(fg, {}, "Outubro/2026") if a["titulo"].startswith("Faturas esperando envio"))
        self.assertNotIn("prazo próprio", espera["texto"])


if __name__ == "__main__":
    unittest.main()
