"""Aba Avisos: o que sai do payload de um painel para o banco (avisos.py). A regra de novo/resolvido/voltou fica no banco (supabase/tests/avisos.sql)."""
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import avisos  # noqa: E402
import guia_pendencias as gp  # noqa: E402


def alerta(ident, escopo="", nivel="atencao", itens=None, texto="<b>3</b> coisas &amp; mais", titulo=None):
    a = {"id": ident, "escopo": escopo, "nivel": nivel, "titulo": titulo or f"Título {ident}", "texto": texto,
         "guia": {"relatorios": [], "passos": ["a"], "resolve": "b"}}
    if itens is not None:
        a["itens"] = {"colunas": ["N"], "linhas": [["1"]], "total": itens, "numericas": []}
    return a


def payload(meses, **extra):
    return {"mes_padrao": sorted(meses)[-1], "meses": {m: {"alertas": al} for m, al in meses.items()}, **extra}


class ColetarTest(unittest.TestCase):
    def test_janela_e_o_mes_padrao_e_o_anterior(self):
        p = payload({"2026-07": [], "2026-08": [], "2026-09": [], "2026-10": []})
        self.assertEqual(avisos.janela(p), ["2026-09", "2026-10"])
        p["mes_padrao"] = "2026-08"                      # o mes padrao nao e o ultimo: a janela termina nele
        self.assertEqual(avisos.janela(p), ["2026-07", "2026-08"])
        self.assertEqual(avisos.janela(payload({"2026-10": []})), ["2026-10"])
        self.assertEqual(avisos.janela({"meses": {"2026-09..2026-10": {}}}), [])   # chave de periodo nao e mes

    def test_chave_texto_e_escopos(self):
        p = payload({"2026-09": [alerta("des_zero", "2026-09")], "2026-10": [alerta("des_zero", "2026-10", itens=4), alerta("fin_vencidas", "", "critico")]})
        alertas, escopos = avisos.coletar(p)
        self.assertEqual(escopos, ["", "2026-09", "2026-10"])
        por = {a["chave"]: a for a in alertas}
        self.assertEqual(set(por), {"2026-09|des_zero", "2026-10|des_zero", "|fin_vencidas"})
        a = por["2026-10|des_zero"]
        self.assertEqual((a["tipo"], a["escopo"], a["nivel"], a["itens_total"]), ("des_zero", "2026-10", "atencao", 4))
        self.assertEqual(a["texto"], "3 coisas & mais")   # sem HTML
        self.assertEqual(a["guia"]["passos"], ["a"])
        self.assertIsNone(por["|fin_vencidas"]["itens_total"])

    def test_mesmo_alerta_em_varios_meses_vale_o_do_mes_mais_novo(self):
        p = payload({"2026-09": [alerta("fin_vencidas", "", titulo="antigo")], "2026-10": [alerta("fin_vencidas", "", titulo="novo")]})
        alertas, _ = avisos.coletar(p)
        self.assertEqual([a["titulo"] for a in alertas], ["novo"])

    def test_fora_da_janela_ok_e_sem_guia_ficam_de_fora(self):
        p = payload({"2026-08": [alerta("des_zero", "2026-08")], "2026-09": [], "2026-10": [alerta("a", "2026-10", "ok"), {"nivel": "info", "titulo": "sem guia", "texto": "x"},
                                                                                   alerta("b", "2026-10", "info")]})
        alertas, escopos = avisos.coletar(p)
        self.assertEqual([a["chave"] for a in alertas], ["2026-10|b"])
        self.assertNotIn("2026-08", escopos)

    def test_alerta_com_escopo_fora_da_janela_e_ignorado_onde_quer_que_esteja(self):
        p = payload({"2026-10": []}, conferencia=[alerta("x", "2026-03"), alerta("y", "")])
        self.assertEqual([a["chave"] for a in avisos.coletar(p)[0]], ["|y"])

    def test_acha_alertas_fora_de_meses_(self):
        p = payload({"2026-10": []}, alertas=[alerta("ind_sem_conciliacao")], atencao=[alerta("fin_vencidas", "", "critico")], qualidade={"lista": [alerta("cesta_idade")]})
        self.assertEqual(sorted(a["tipo"] for a in avisos.coletar(p)[0]), ["cesta_idade", "fin_vencidas", "ind_sem_conciliacao"])

    def test_persistente_vem_do_guia(self):
        alertas, _ = avisos.coletar(payload({"2026-10": [alerta("fat_glosa", "2026-10"), alerta("fat_vencidas", "2026-10")]}))
        self.assertEqual({a["tipo"]: a["persistente"] for a in alertas}, {"fat_glosa": True, "fat_vencidas": False})
        self.assertTrue(gp.PERSISTENTES <= {r[2] for r in gp.REGRAS})   # nenhum id inventado

    def test_sem_meses_nao_sincroniza(self):
        chamadas = []
        antes = avisos.arm.sincronizar_avisos
        avisos.arm.sincronizar_avisos = lambda *a: chamadas.append(a) or {}
        try:
            self.assertIsNone(avisos.sincronizar("x", {"meses": {}, "alertas": [alerta("a")]}, 1))   # painel sem dados: nada e dado como resolvido
            self.assertEqual(chamadas, [])
            avisos.sincronizar("x", payload({"2026-10": [alerta("a", "2026-10")]}), 7)
            self.assertEqual((chamadas[0][0], chamadas[0][1], chamadas[0][2], len(chamadas[0][3])), ("x", ["", "2026-10"], 7, 1))
        finally:
            avisos.arm.sincronizar_avisos = antes


if __name__ == "__main__":
    unittest.main()
