"""Contas do quadro da Jornada em TypeScript (lib/jornada.ts e lib/coleta-ritmo.ts): filtros, períodos, busca sem acento, estado da barra de atualização.
Roda tests/jornada_quadro.check.mts com o Node (22.6 ou mais); sem Node, o teste é pulado."""
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def versao_node():
    node = shutil.which("node")
    if not node:
        return None
    saida = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return (int(saida[0]), int(saida[1])) if len(saida) >= 2 and saida[0].isdigit() and saida[1].isdigit() else None


class QuadroJornadaTsTest(unittest.TestCase):
    @unittest.skipUnless((versao_node() or (0, 0)) >= (22, 6), "precisa do Node 22.6 ou mais")
    def test_contas_do_quadro(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(Path(__file__).parent / "jornada_quadro.check.mts")],
                           capture_output=True, text=True, cwd=RAIZ, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertIn("JORNADA TS OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
