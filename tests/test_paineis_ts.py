"""O site (lib/paineis.ts) e o servidor (portal_nuvem.py) tem de decidir IGUAL quem ve cada painel: o site esconde o menu, o servidor entrega os dados.

Roda o podeVerPainel de verdade no Node (so o que o Node 22 le sozinho: --experimental-strip-types) e compara com portal_nuvem.pode_ver_painel
para todos os paineis e para muitas combinacoes de permissao, inclusive valores estranhos ("true" em texto, 1, ausente).
"""
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ROTEIRO = """
import { PAINEIS, podeVerPainel, veDadosFinanceiros } from "./paineis.ts";
const casos = JSON.parse(process.argv[2]);
const saida = casos.map(([perfil, painel]: [any, string]) => [podeVerPainel(perfil, painel), veDadosFinanceiros(perfil)]);
console.log(JSON.stringify({ paineis: PAINEIS.map(p => [p.id, p.financeiro]), saida }));
"""


@unittest.skipUnless(shutil.which("node"), "sem Node")
class RegraDoSiteIgualAoServidorTest(unittest.TestCase):
    def test_podeVerPainel_igual_a_pode_ver_painel(self):
        import portal_nuvem as pn
        paineis = list(pn.modulos())
        valores = [True, False, None, "true", 1, 0]            # None = a chave nao existe no perfil
        perfis = [None]
        for role in ("admin", "viewer"):
            for v_painel, v_fin in itertools.product(valores, valores):
                for outro in (False, True):                    # outro painel liberado nao pode valer para este
                    perms = {}
                    if v_painel is not None:
                        perms["__painel__"] = v_painel
                    if v_fin is not None:
                        perms["dados_financeiros"] = v_fin
                    if outro:
                        perms["__outro__"] = True
                    perfis.append({"role": role, "permissions": perms})
        casos = []
        for perfil in perfis:
            for painel in paineis:
                if perfil is None:
                    casos.append([None, painel])
                    continue
                perms = {("__painel__" == k and painel) or ("__outro__" == k and "metas") or k: v for k, v in perfil["permissions"].items()}
                casos.append([{"role": perfil["role"], "permissions": perms}, painel])

        pasta = Path(tempfile.mkdtemp())
        try:
            (pasta / "modulos.json").write_text((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"), encoding="utf-8")
            (pasta / "paineis.ts").write_text((RAIZ / "lib" / "paineis.ts").read_text(encoding="utf-8").replace('from "@/modulos.json";', 'from "./modulos.json" with { type: "json" };'), encoding="utf-8")
            (pasta / "roteiro.mts").write_text(ROTEIRO, encoding="utf-8")
            r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "roteiro.mts", json.dumps(casos)], cwd=pasta, capture_output=True, text=True, timeout=120)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        ts = json.loads(r.stdout)
        self.assertEqual({p: m for p, m in ts["paineis"]}, {p: pn.modo_financeiro(p) for p in paineis}, "o modo financeiro de cada painel difere entre site e servidor")
        divergencias = []
        for (perfil, painel), (ts_pode, ts_fin) in zip(casos, ts["saida"]):
            if perfil is None:
                esperado, fin = False, False
            else:
                u = {"admin": perfil["role"] == "admin", "permissoes": perfil["permissions"],
                     "financeiro": perfil["role"] == "admin" or perfil["permissions"].get("dados_financeiros") is True}
                esperado, fin = pn.pode_ver_painel(u, painel), u["financeiro"]
            if (ts_pode, ts_fin) != (esperado, fin):
                divergencias.append((perfil, painel, "site", ts_pode, ts_fin, "servidor", esperado, fin))
        if divergencias:
            self.fail(f"{len(divergencias)} divergências entre site e servidor; as primeiras: {divergencias[:3]}")
        self.assertGreater(len(casos), 500)


if __name__ == "__main__":
    unittest.main()
