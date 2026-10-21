"""Metas: o Cetrus (no historico "SUS CURSO") e uma terceira categoria — conta na meta, mas nao e SUS nem pagante (painel local, gerar_dashboard)."""
import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "Acompanhamento de META"))

import gerar_dashboard as gd  # noqa: E402

UNIDADE = "CLÍNICA DE SAÚDE E IMAGEM - CSI"


def atendimentos():
    conv = ["SUS", "SUS CURSO", "CETRUS", "UNIMED", "Particular", ""]
    linhas = [{"Exames Realizados": i, "Unidade": UNIDADE, "Procedimento - Classes": "USG", "Especialidade": "ULTRASSONOGRAFIA",
               "Data do Atendimento": "2026-10-05", "Procedimento": "USG ABDOMEN", "Mês": "2026-10", "Convênio": c} for i, c in enumerate(conv)]
    df = pd.DataFrame(linhas)
    df["Data do Atendimento"] = pd.to_datetime(df["Data do Atendimento"])
    df["_uni"] = df["Unidade"].map(gd.norm)
    df["_esp"] = df["Especialidade"].map(gd.norm)
    df["_proc"] = df["Procedimento"].map(gd.norm)
    df["_sus"] = df["Convênio"].map(gd.norm) == "SUS"
    df["_cetrus"] = df["Convênio"].map(gd.norm).isin(gd.NOMES_CETRUS)
    df["_conv"] = df["Convênio"].map(gd.norm) != ""
    df["_classes"] = df["Procedimento - Classes"].map(lambda c: {c})
    return df


class MetasCetrusTest(unittest.TestCase):
    def test_cetrus_e_terceira_categoria(self):
        df = atendimentos()
        self.assertEqual(int(df["_sus"].sum()), 1)       # so o "SUS" exato
        self.assertEqual(int(df["_cetrus"].sum()), 2)    # "SUS CURSO" (historico) e "CETRUS" (novo)
        cfg = {"grupos": [{"id": "g", "nome": "G", "unidade": UNIDADE, "itens": [{"id": "usg", "nome": "USG", "meta": 100, "regra": {"classe": "USG"}}]}],
               "dias_semana_atendimento": [0, 1, 2, 3, 4, 5], "horario_atendimento": ["07:00", "18:00"], "feriados": [], "metas_por_mes": {}}
        m = gd.montar_mes(df, "2026-10", cfg, datetime(2026, 10, 20, 12, 0), [])
        i = m["grupos"][0]["itens"][0]
        self.assertEqual((i["realizado"], i["sus"], i["cetrus"], i["nao_sus"], i["sem_conv"]), (6, 1, 2, 2, 1))   # o Cetrus conta na meta e fica fora de SUS e pagante


if __name__ == "__main__":
    unittest.main()
