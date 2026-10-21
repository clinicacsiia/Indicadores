"""Metas mudadas em Configuracoes: valem do mes escolhido em diante, ate a proxima mudanca; sem mudanca vale o metas.json.
O site (metaDoMes em lib/metas/calculo.ts, roda de verdade no Node) e o painel em Python (gerar_dashboard.meta_do_mes) tem de dar a MESMA meta."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "Acompanhamento de META"))

import gerar_dashboard as gd  # noqa: E402

MESES = ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
CFG = {"metas_por_mes": {"2026-12": {"g/a": 111}},
       "alteracoes": {"g/a": [{"mes": "2026-11", "meta": 600}, {"mes": "2027-01", "meta": 650}], "g/b": [{"mes": "2026-10", "meta": 0}]}}

ROTEIRO = """
import { metaDoMes } from "./calculo.ts";
const { cfg, meses, itens } = JSON.parse(process.argv[2]);
console.log(JSON.stringify(itens.map(([chave, padrao]: [string, number]) => meses.map((m: string) => metaDoMes(cfg, chave, padrao, m)))));
"""


class MetaDoMesPythonTest(unittest.TestCase):
    def test_segue_para_os_meses_seguintes_ate_a_proxima_mudanca(self):
        v = {m: gd.meta_do_mes(CFG, "g/a", 500, m) for m in MESES}
        self.assertEqual(v, {"2026-08": 500, "2026-09": 500, "2026-10": 500,   # antes da mudanca: a do metas.json
                             "2026-11": 600, "2026-12": 600,                     # a mudanca vence o metas_por_mes (111) do mesmo mes
                             "2027-01": 650, "2027-02": 650})                    # a proxima mudanca segue adiante
        self.assertEqual(gd.meta_do_mes(CFG, "g/b", 40, "2026-09"), 40)
        self.assertEqual(gd.meta_do_mes(CFG, "g/b", 40, "2026-11"), 0)             # zero e uma meta valida
        self.assertEqual(gd.meta_do_mes({"metas_por_mes": {"2026-12": {"g/a": 111}}}, "g/a", 500, "2026-12"), 111)   # sem mudanca: o metas.json de sempre


@unittest.skipUnless(shutil.which("node"), "sem Node")
class MetaDoMesIgualNoSiteTest(unittest.TestCase):
    def test_site_igual_ao_python(self):
        itens = [["g/a", 500], ["g/b", 40], ["g/c", 7]]
        pasta = Path(tempfile.mkdtemp())
        try:
            (pasta / "calculo.ts").write_text((RAIZ / "lib" / "metas" / "calculo.ts").read_text(encoding="utf-8"), encoding="utf-8")
            (pasta / "roteiro.mts").write_text(ROTEIRO, encoding="utf-8")
            r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "roteiro.mts", json.dumps({"cfg": CFG, "meses": MESES, "itens": itens})],
                               cwd=pasta, capture_output=True, text=True, timeout=120)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        ts = json.loads(r.stdout)
        py = [[gd.meta_do_mes(CFG, chave, padrao, m) for m in MESES] for chave, padrao in itens]
        self.assertEqual(ts, py)


if __name__ == "__main__":
    unittest.main()
