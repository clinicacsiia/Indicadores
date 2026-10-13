"""Testes do cálculo dos painéis (Python) com dados sintéticos: o painel monta, traz o D esperado e o período De/até funciona.

Roda com:  python -m unittest discover -s tests/python -v      (precisa de pandas e numpy: pip install -r requirements.txt)
O "golden master" contra o legado (mesmos dados reais, comparação campo a campo) está descrito em docs/PREMISSAS.md: precisa dos .xlsx reais,
que ficam fora do Git.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PAINEL = RAIZ / "painel_py"
sys.path.insert(0, str(PAINEL))

_tmp = tempfile.mkdtemp(prefix="dados_sinteticos_")
subprocess.run([sys.executable, str(RAIZ / "scripts" / "gerar_dados_sinteticos.py"), _tmp], check=True, stdout=subprocess.DEVNULL)
os.environ["DADOS_DIR"] = _tmp

from painel_runtime import gerar_html  # noqa: E402
import painel_comum as pc  # noqa: E402


def dados_da_pagina(html: str) -> dict:
    m = re.search(r'<script[^>]*id="dados"[^>]*>(.*?)</script>', html, re.S)
    assert m, "a página não tem o bloco de dados"
    return json.loads(m.group(1).replace("<\\/", "</"))


class PeriodoTest(unittest.TestCase):
    def test_meses(self):
        self.assertEqual(pc.mes_mais("2026-12", 1), "2027-01")
        self.assertEqual(pc.mes_mais("2026-01", -1), "2025-12")
        self.assertEqual(pc.meses_entre("2026-09", "2026-11"), ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(pc.rotulo_mes("2026-10"), "Outubro/2026")

    def test_periodo_anterior_tem_o_mesmo_tamanho(self):
        p = pc.Periodo("2026-09", "2026-11")
        self.assertEqual(p.yms, ["2026-09", "2026-10", "2026-11"])
        self.assertEqual((p.anterior.ini, p.anterior.fim), ("2026-06", "2026-08"))
        self.assertEqual(p.chave, "2026-09..2026-11")
        self.assertTrue(pc.Periodo("2026-10", "2026-10").unico)

    def test_pedido_sem_dados_avisa_e_recorte_parcial_diz_qual(self):
        meses = {"2026-09": {}, "2026-10": {}}
        per, info = pc.periodo_pedido("2025-01", "2025-03", meses)
        self.assertIsNone(per)
        self.assertIn("Não há dados", info["aviso"])
        per, info = pc.periodo_pedido("2026-08", "2026-10", meses)
        self.assertEqual((per.ini, per.fim), ("2026-09", "2026-10"))
        self.assertIn("Só há dados", info["aviso"])
        per, info = pc.periodo_pedido(None, None, meses)
        self.assertIsNone(per)
        self.assertFalse(info["pedido"])

    def test_limpo_serializa_nan_e_timestamps(self):
        import numpy as np
        import pandas as pd
        out = pc.limpo({"a": float("nan"), "b": pd.Timestamp("2026-10-07 08:30:00"), "c": np.int64(3), "d": pd.NaT, "e": {1, 2}})
        self.assertEqual(out, {"a": None, "b": "2026-10-07T08:30:00", "c": 3, "d": None, "e": [1, 2]})
        json.dumps(out, allow_nan=False)


class PainelTest(unittest.TestCase):
    def test_metas_monta_e_traz_os_grupos_do_metas_json(self):
        d = dados_da_pagina(gerar_html("metas"))
        self.assertEqual(d["menu"], "metas")
        self.assertIn("2026-10", d["meses"])
        self.assertEqual([g["nome"] for g in d["meses"]["2026-10"]["grupos"]], ["CSI 2", "CSI 1", "CSI Pediatria"])

    def test_faturamento_monta_com_alertas_e_guia(self):
        d = dados_da_pagina(gerar_html("faturamento"))
        self.assertEqual(d["mes_padrao"], "2026-10")
        alertas = d["meses"]["2026-10"]["alertas"]
        problemas = [a for a in alertas if a["nivel"] in ("critico", "atencao")]
        self.assertTrue(problemas)
        for a in problemas:   # todo alerta de problema tem chave estável (escopo|id) e guia "como achar o problema"
            self.assertRegex(a["chave"], r"^2026-10\|[a-z0-9-]+$")
            self.assertTrue(a["guia"]["passos"])
            self.assertIn("klingo.app/#/relatorio/", a["guia"]["url"])
        for a in alertas:
            if a["nivel"] in ("ok", "info"):
                self.assertNotIn("chave", a)   # só os informativos ficam sem botões

    def test_periodo_de_varios_meses_acrescenta_o_periodo_e_marca_os_campos(self):
        d = dados_da_pagina(gerar_html("faturamento", "2026-09", "2026-10"))
        self.assertEqual(d["mes_padrao"], "2026-09..2026-10")
        m = d["meses"]["2026-09..2026-10"]
        self.assertTrue(m["periodo"])
        self.assertEqual(m["meses_do_periodo"], ["2026-09", "2026-10"])
        self.assertEqual(d["periodo"]["linha"], "Período: de 01/09/2026 a 13/10/2026")

    def test_um_mes_pedido_vale_o_painel_de_sempre(self):
        d = dados_da_pagina(gerar_html("faturamento", "2026-09", "2026-09"))
        self.assertEqual(d["mes_padrao"], "2026-09")
        self.assertNotIn("2026-09..2026-09", d["meses"])

    def test_pagina_nao_traz_segredos_nem_ids_de_relatorio_na_tela(self):
        html = gerar_html("faturamento")
        self.assertNotIn("KLINGO_APP_TOKEN", html)
        self.assertNotIn("X-APP-TOKEN", html)
        visivel = re.sub(r"<script.*?</script>", "", html, flags=re.S)
        self.assertNotRegex(visivel, r"#1[0-9]{4}\b")   # ids do Klingo (#13329...) não aparecem nas telas


class ConferirTest(unittest.TestCase):
    def test_conferir_roda_e_devolve_checagens_com_esperado_e_obtido(self):
        from conferir import conferir
        itens = conferir()
        self.assertTrue(itens)
        for i in itens:
            self.assertEqual(set(i), {"nome", "ok", "esperado", "obtido", "detalhe"})
        json.dumps(itens, default=str)


if __name__ == "__main__":
    unittest.main()
