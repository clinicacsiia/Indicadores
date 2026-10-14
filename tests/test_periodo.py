"""Periodo livre (dias exatos) do painel_comum: o mesmo filtro De/Ate dos paineis, agora com datas.

Rodar:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import painel_comum as pc  # noqa: E402


class PeriodoTest(unittest.TestCase):
    def test_mes_inteiro_continua_igual(self):
        p = pc.Periodo("2026-10", "2026-10")
        self.assertTrue(p.unico)
        self.assertFalse(p.exato)
        self.assertEqual((p.chave, p.rotulo, p.anterior.chave), ("2026-10", "Outubro/2026", "2026-09"))
        v = pc.Periodo("2026-09-01", "2026-10-31")   # datas que cobrem meses inteiros viram o filtro por mes
        self.assertFalse(v.exato)
        self.assertEqual((v.chave, v.anterior.chave), ("2026-09..2026-10", "2026-07..2026-08"))

    def test_dias_exatos(self):
        p = pc.Periodo("2026-09-10", "2026-10-25")
        self.assertTrue(p.exato and not p.unico)
        self.assertEqual((p.chave, p.rotulo, p.n, p.n_dias), ("2026-09-10..2026-10-25", "10/09/2026 a 25/10/2026", 2, 46))
        self.assertEqual(p.anterior.chave, "2026-07-26..2026-09-09")   # mesmo numero de dias, terminando na vespera
        self.assertEqual(p.anterior.n_dias, p.n_dias)
        self.assertEqual(pc.Periodo("2026-10-05", "2026-10-05").rotulo, "05/10/2026")
        # um recorte dentro de um mes NAO e a pagina de sempre
        self.assertFalse(pc.Periodo("2026-10-02", "2026-10-09").unico)
        # pontas trocadas
        self.assertEqual(pc.Periodo("2026-10-25", "2026-09-10").chave, p.chave)

    def test_fechado_e_dentro(self):
        p = pc.Periodo("2026-10-02", "2026-10-09")
        self.assertTrue(p.fechado(date(2026, 10, 10)))
        self.assertFalse(p.fechado(date(2026, 10, 9)))   # o dia de hoje ainda esta em curso
        datas = pd.Series(pd.to_datetime(["2026-10-01 23:59", "2026-10-02 00:00", "2026-10-09 18:30", "2026-10-10 00:00", None]))
        self.assertEqual(p.dentro(datas).tolist(), [False, True, True, False, False])

    def test_pedido_valido_e_recorte(self):
        existentes = ["2026-09", "2026-10"]
        per, info = pc.periodo_pedido("2026-09-10", "2026-10-25", existentes)
        self.assertEqual((per.chave, info["exato"], info["vazio"], info["recortado"]), ("2026-09-10..2026-10-25", True, False, False))
        per, info = pc.periodo_pedido("2026-08-10", "2026-12-25", existentes)   # recortado ao que o painel tem
        self.assertEqual((per.chave, info["recortado"]), ("2026-09..2026-10", True))
        per, info = pc.periodo_pedido("2027-01-02", "2027-01-20", existentes)
        self.assertIsNone(per)
        self.assertTrue(info["vazio"])
        self.assertEqual(pc.periodo_pedido("2026-02-30", "2026-03-10", existentes), (None, None))   # data que nao existe
        self.assertEqual(pc.periodo_pedido("abc", "2026-03", existentes), (None, None))

    def test_periodo_da_consulta(self):
        self.assertIsNone(pc.periodo_da_consulta("2026-10", "2026-10"))                  # um mes: pagina de sempre
        self.assertIsNone(pc.periodo_da_consulta("2026-10-01", "2026-10-31"))
        self.assertEqual(pc.periodo_da_consulta("2026-10", "2026-09"), ("2026-09", "2026-10"))
        self.assertEqual(pc.periodo_da_consulta("2026-10-09", "2026-10-02"), ("2026-10-02", "2026-10-09"))
        self.assertIsNone(pc.periodo_da_consulta("2026-13", "2026-10"))

    def test_reagrupar_recorta_por_data(self):
        df = pd.DataFrame({"mes": ["2026-09"] * 3 + ["2026-10"] * 3, "v": [1, 2, 3, 4, 5, 6],
                           "data": pd.to_datetime(["2026-09-05", "2026-09-12", "2026-09-28", "2026-10-02", "2026-10-04", "2026-10-20"])})
        per = pc.Periodo("2026-09-10", "2026-10-03")
        r = pc.reagrupar(df, "mes", per, datacol="data")
        atual = r[r["mes"] == per.fim]
        self.assertEqual(sorted(atual["v"]), [2, 3, 4])                       # 12/09, 28/09 e 02/10
        antes = r[r["mes"] == pc.mes_mais(per.fim, -1)]
        self.assertEqual(sorted(antes["v"]), [1])                              # 18/08 a 09/09: so o dia 05/09
        # dado que so existe por mes (sem coluna de data): entram os meses inteiros que o periodo toca
        m = pc.reagrupar(df, "mes", per)
        self.assertEqual(sorted(m[m["mes"] == per.fim]["v"]), [1, 2, 3, 4, 5, 6])


if __name__ == "__main__":
    unittest.main()
