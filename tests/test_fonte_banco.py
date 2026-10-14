"""Os paineis lendo os dados do BANCO (coleta unica do Supabase) em vez de consultar o Klingo.

Rodar:  python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_v, None)
os.environ.update(NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
import mock_nuvem as mn  # noqa: E402

BANCO = mn.BancoSimulado()
SERVIDORES = []
HOJE = date.today()
HOJE_YM = HOJE.strftime("%Y-%m")


def setUpModule():
    sup, url = mn.subir(mn.criar_supabase(BANCO))
    SERVIDORES.append(sup)
    os.environ.update(SUPABASE_URL=url, SUPABASE_SERVICE_ROLE_KEY="svc", NEXT_PUBLIC_SUPABASE_ANON_KEY="anon",
                      PORTAL_ARMAZENAMENTO="supabase")
    os.environ.pop("PAINEL_FONTE", None)   # o padrao e o banco
    import portal_nuvem  # noqa: F401  (poe as pastas dos paineis no sys.path)
    # Nenhum Klingo sobe aqui: se o codigo tentasse consulta-lo, a conexao seria recusada e o teste quebraria.
    import extrair_laudo as ex
    ex.API_EXTERNA = "http://127.0.0.1:9/api/info/relatorio"


def tearDownModule():
    for s in SERVIDORES:
        s.shutdown()


def agora_utc(dias_atras: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=dias_atras)


def meses(inicio: str, fim: str) -> list[str]:
    out, a, m = [], int(inicio[:4]), int(inicio[5:])
    while f"{a}-{m:02d}" <= fim:
        out.append(f"{a}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


class Semeador:
    """Monta no banco simulado o que a coleta do Supabase deixaria: cadastro, dicionario de colunas, execucoes e linhas vigentes."""

    def __init__(self):
        self.proximo = 0

    def relatorio(self, rid: int, titulos: list[str], granularidade="mes", filtro="periodo0", validado=True, ativo=True) -> dict:
        self.proximo += 1
        info = {"id": f"rel-{rid}", "klingo_id": str(rid), "nome": f"Relatório {rid}", "ativo": ativo, "supersedido_por": None,
                "granularidade": granularidade, "filtro_periodo": filtro,
                "periodo_validado_em": agora_utc().isoformat() if validado else None}
        BANCO.relatorios.append(info)
        for i, t in enumerate(titulos):
            BANCO.colunas.append({"relatorio_id": info["id"], "coluna_key": f"col{i}", "titulo_klingo": t})
        return info

    def execucao(self, info: dict, periodo: str, quando: datetime | None = None):
        BANCO.execucoes.append({"relatorio_id": info["id"], "periodo": periodo, "status": "success",
                                "finished_at": (quando or agora_utc()).isoformat()})

    def linhas(self, info: dict, periodo: str, linhas: list[dict], repeticoes: int = 1):
        for linha in linhas:
            self.proximo += 1
            BANCO.linhas_dw.append({"id": self.proximo, "relatorio_id": info["id"], "periodo": periodo, "linha": linha, "repeticoes": repeticoes})


def limpar_banco():
    for lista in (BANCO.relatorios, BANCO.colunas, BANCO.execucoes, BANCO.linhas_dw, BANCO.dados, BANCO.atualizacoes):
        lista.clear()
    BANCO.mes.clear()
    BANCO.paginas.clear()
    BANCO.pedidos.clear()


def semear_cesta(sem: Semeador, validado=True) -> dict:
    """Painel Cesta inteiro no banco: 3 relatorios mensais, de 2026-09 ate o mes atual."""
    import klingo_relatorios as k
    defn = k.ler_definicao(RAIZ / "Cesta")
    infos = {}
    for rel in defn["relatorios"]:
        titulos = list(dict.fromkeys([*rel.get("chave", []), *rel.get("numeros", []), *rel.get("datas", {}), "Faixa Etária", "Operador", "Sexo", "Procedimento", "Operadora", "Unidade"]))
        info = sem.relatorio(rel["id"], titulos, validado=validado)
        infos[rel["aba"]] = (info, titulos, rel)
        for ym in meses(defn["primeiro_mes"], HOJE_YM):
            linhas = []
            for n in range(3):
                linha = {}
                for i, t in enumerate(titulos):
                    if t in rel.get("numeros", []):
                        linha[f"col{i}"] = str(100 + n + i)   # a coleta grava numeros como texto
                    elif t in rel.get("datas", {}):
                        linha[f"col{i}"] = f"{ym}-{n + 1:02d} 09:58:25"
                    elif t == "Faixa Etária":
                        linha[f"col{i}"] = "'10-19"
                    elif t == "Sexo":
                        linha[f"col{i}"] = ("F", "M")[n % 2]
                    else:
                        linha[f"col{i}"] = f"{t[:10]} {n}"
                linhas.append(linha)
            sem.linhas(info, f"{ym}-01", linhas)
            sem.execucao(info, f"{ym}-01")
    return infos


class PainelDoBancoTest(unittest.TestCase):
    def setUp(self):
        limpar_banco()
        import armazenamento as arm
        arm._CACHE_VERSAO.clear()

    def test_copia_o_mes_do_banco_para_o_painel_com_os_tipos_certos(self):
        import armazenamento as arm
        import klingo_relatorios as k
        infos = semear_cesta(Semeador())
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertTrue(r["atualizou"], r)
        self.assertIn("a partir do banco", r["mensagem"])
        aba = "Base Cesta"
        linhas = arm.ler_aba("cesta", aba)
        _, _, rel = infos[aba]
        n_meses = len(meses("2026-09", HOJE_YM))
        self.assertEqual(len(linhas), 3 * n_meses)
        primeira = linhas[0]
        for c in rel.get("numeros", []):
            self.assertIsInstance(primeira[c], (int, float), c)   # texto do banco virou numero, como no caminho do Klingo
        for c in rel.get("datas", {}):
            self.assertRegex(str(primeira[c]), r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(primeira["Faixa Etária"], "10-19")   # limpar_apostrofo do relatorios.json
        self.assertEqual(primeira["Mês (filtro)"], "2026-09")
        self.assertEqual(r["avisos"], [])

    def test_nao_consulta_o_klingo_e_nao_regrava_o_que_nao_mudou(self):
        import klingo_relatorios as k
        semear_cesta(Semeador())
        k.atualizar_do_banco(RAIZ / "Cesta")
        BANCO.pedidos.clear()
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertFalse(r["atualizou"], r)
        self.assertFalse([p for p in BANCO.pedidos if p[0] == "POST"], "regravou dado igual")

    def test_coleta_nova_no_banco_substitui_o_mes(self):
        import armazenamento as arm
        import klingo_relatorios as k
        sem = Semeador()
        infos = semear_cesta(sem)
        k.atualizar_do_banco(RAIZ / "Cesta")
        info, titulos, rel = infos["Base Cesta"]
        # a coleta refaz o mes atual com uma linha a mais
        BANCO.linhas_dw[:] = [l for l in BANCO.linhas_dw if not (l["relatorio_id"] == info["id"] and l["periodo"] == f"{HOJE_YM}-01")]
        nova = {f"col{i}": f"x{i}" for i, _ in enumerate(titulos)}
        for i, t in enumerate(titulos):
            if t in rel.get("numeros", []):
                nova[f"col{i}"] = "7"
            elif t in rel.get("datas", {}):
                nova[f"col{i}"] = f"{HOJE_YM}-02 10:00:00"
        sem.linhas(info, f"{HOJE_YM}-01", [nova, {**nova}], repeticoes=2)   # 2 linhas distintas?  mesmas -> uma com repeticoes=2
        BANCO.linhas_dw[-1]["repeticoes"] = 2
        BANCO.execucoes[:] = [e for e in BANCO.execucoes if not (e["relatorio_id"] == info["id"] and e["periodo"] == f"{HOJE_YM}-01")]
        sem.execucao(info, f"{HOJE_YM}-01", agora_utc() + timedelta(minutes=5))
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertTrue(r["atualizou"], r)
        arm._CACHE_VERSAO.clear()
        do_mes = [l for l in arm.ler_aba("cesta", "Base Cesta") if l["Mês (filtro)"] == HOJE_YM]
        self.assertEqual(len(do_mes), 4, "2 linhas x repeticoes=2: as duplicatas devolvidas pelo Klingo continuam contando, como antes")

    def test_filtro_de_periodo_nao_comprovado_nao_entra(self):
        import klingo_relatorios as k
        semear_cesta(Semeador(), validado=False)
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertFalse(r["atualizou"], r)
        self.assertEqual(len(BANCO.dados), 0)
        self.assertIn("filtro de período", r["mensagem"])

    def test_mes_que_o_banco_ainda_nao_coletou_fica_como_estava(self):
        import klingo_relatorios as k
        semear_cesta(Semeador())
        BANCO.execucoes[:] = [e for e in BANCO.execucoes if not (e["relatorio_id"] == "rel-13280" and e["periodo"] == f"{HOJE_YM}-01")]
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertTrue(r["parcial"], r)
        self.assertIn("ainda não foram coletados", r["mensagem"])
        meses_gravados = {(a, m) for (p, a, m) in BANCO.mes}
        self.assertNotIn(("Base Cesta", HOJE_YM), meses_gravados)
        self.assertIn(("Base Cesta", "2026-09"), meses_gravados) if HOJE_YM != "2026-09" else None

    def test_relatorio_sem_coluna_exigida_e_recusado(self):
        import klingo_relatorios as k
        semear_cesta(Semeador())
        BANCO.colunas[:] = [c for c in BANCO.colunas if not (c["relatorio_id"] == "rel-13284" and c["coluna_key"] == "col0")]
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertTrue(any("Exames por Perfil" in a for a in r["avisos"]), r)
        self.assertFalse([1 for (p, a, m) in BANCO.mes if a == "Exames por Perfil"])

    def test_desativado_no_banco_nao_alimenta_o_painel(self):
        import klingo_relatorios as k
        semear_cesta(Semeador())
        for r in BANCO.relatorios:
            if r["klingo_id"] == "13285":
                r["ativo"] = False
        r = k.atualizar_do_banco(RAIZ / "Cesta")
        self.assertTrue(any("desativado" in a for a in r["avisos"]), r)

    def test_relatorio_sem_filtro_de_data_usa_a_ultima_coleta_e_substitui_tudo(self):
        import armazenamento as arm
        import klingo_relatorios as k
        sem = Semeador()
        defn = k.ler_definicao(RAIZ / "Indicadores")
        for rel in defn["relatorios"]:
            titulos = list(dict.fromkeys([*rel.get("chave", []), *rel.get("numeros", []), *rel.get("datas", {})]))
            if rel.get("sem_periodo"):
                info = sem.relatorio(rel["id"], titulos, granularidade="dia", filtro=None, validado=False)   # sem filtro: nada a comprovar
                hoje = HOJE.isoformat()
                sem.linhas(info, hoje, [{f"col{i}": str(i + 1) for i, _ in enumerate(titulos)}])
                sem.execucao(info, hoje)
        r = k.atualizar_do_banco(RAIZ / "Indicadores")
        self.assertTrue(r["atualizou"], r)
        guias = arm.ler_aba("indicadores", "Guias")
        self.assertEqual(len(guias), 1)
        self.assertEqual(guias[0]["Mês (filtro)"], HOJE_YM)

    def test_botao_atualizar_usa_o_banco_e_deixa_a_pagina_pronta(self):
        import portal_nuvem as pn
        semear_cesta(Semeador())
        resp = pn.atualizar("cesta", "csiadmin@csi.local")
        self.assertTrue(resp["ok"] and resp["atualizou"], resp)
        self.assertIn("a partir do banco", resp["mensagem"])
        self.assertIn(("cesta", "padrao"), BANCO.paginas)
        self.assertEqual(BANCO.atualizacoes[-1]["painel"], "cesta")


class SincroniaAutomaticaTest(unittest.TestCase):
    def setUp(self):
        limpar_banco()
        import armazenamento as arm
        arm._CACHE_VERSAO.clear()

    def test_copia_do_banco_sozinha_a_cada_5_horas(self):
        import portal_nuvem as pn
        semear_cesta(Semeador())
        pn.sincronizar_se_vencido("cesta")   # nunca atualizado: copia
        self.assertEqual(len(BANCO.atualizacoes), 1)
        self.assertIn("automático", BANCO.atualizacoes[0]["usuario"])
        self.assertTrue(BANCO.mes, "nao copiou")
        pn.sincronizar_se_vencido("cesta")   # acabou de atualizar: nao repete
        self.assertEqual(len(BANCO.atualizacoes), 1)
        BANCO.atualizacoes[0]["criado_em"] = (agora_utc() - timedelta(hours=5, minutes=1)).isoformat()
        pn.sincronizar_se_vencido("cesta")   # passou de 5 h: confere de novo
        self.assertEqual(len(BANCO.atualizacoes), 2)

    def test_falha_na_sincronia_nao_derruba_a_abertura_do_painel(self):
        import portal_nuvem as pn
        # sem nada no banco simulado o relatorio nao existe: o painel segue com o que tem, sem excecao
        pn.sincronizar_se_vencido("cesta")


class MetasDoBancoTest(unittest.TestCase):
    def setUp(self):
        limpar_banco()
        import armazenamento as arm
        arm._CACHE_VERSAO.clear()

    def semear(self, validado=True):
        import extrair_laudo as ex
        sem = Semeador()
        titulos = list(ex.COLUNAS_API) + ["Operadora"]
        info = sem.relatorio(ex.ID_RELATORIO, titulos, granularidade="dia", validado=validado)
        for dia in (HOJE.replace(day=1) + timedelta(days=i) for i in range(HOJE.day)):
            d = dia.isoformat()
            sem.linhas(info, d, [{
                "col0": f"{dia.day}00{n}", "col1": "CLÍNICA CSI 1", "col2": '["RESSONANCIA"]', "col3": "RESSONÂNCIA",
                "col4": f"{d}T10:00:00", "col5": "RM CRANIO", "col6": "SUS" if n else "UNIMED"} for n in range(2)])
            sem.execucao(info, d)
        return info

    def test_metas_do_banco_viram_a_base_do_atendimento(self):
        import armazenamento as arm
        import extrair_laudo as ex
        self.semear()
        r = ex.atualizar_nuvem(forcar=True)
        self.assertTrue(r["atualizou"], r)
        self.assertIn("a partir do banco", r["mensagem"])
        df = arm.ler_metas_dados()
        self.assertEqual(len(df), 2 * HOJE.day)
        self.assertEqual(set(df["Mês"]), {HOJE_YM})
        self.assertEqual(set(df["Convênio"]), {"SUS", "UNIMED"})
        # segunda vez: nada mais novo no banco, nada regravado
        BANCO.pedidos.clear()
        r2 = ex.atualizar_nuvem(forcar=True)
        self.assertFalse(r2["atualizou"], r2)
        self.assertFalse([p for p in BANCO.pedidos if p[0] == "POST"])

    def test_mes_com_dia_faltando_no_banco_nao_entra(self):
        import extrair_laudo as ex
        if HOJE.day < 3:
            self.skipTest("precisa de pelo menos 3 dias no mes")
        info = self.semear()
        BANCO.execucoes[:] = [e for e in BANCO.execucoes if e["periodo"] != HOJE.replace(day=2).isoformat()]
        r = ex.atualizar_nuvem(forcar=True)
        self.assertFalse(r["atualizou"], r)
        self.assertEqual(len(BANCO.mes), 0)

    def test_filtro_nao_comprovado_nao_entra(self):
        import extrair_laudo as ex
        self.semear(validado=False)
        r = ex.atualizar_nuvem(forcar=True)
        self.assertFalse(r["atualizou"], r)
        self.assertIn("filtro de período", r["mensagem"])


class CoberturaTest(unittest.TestCase):
    def test_dia_passado_coletado_no_proprio_dia_nao_vale(self):
        import fonte_banco as fb
        info = {"granularidade": "dia"}
        ontem = (HOJE - timedelta(days=1))
        if ontem.month != HOJE.month:
            self.skipTest("primeiro dia do mes")
        execs = {}
        for i in range(HOJE.day):
            d = HOJE.replace(day=i + 1)
            execs[d.isoformat()] = datetime(d.year, d.month, d.day, 15, 0, tzinfo=timezone.utc) if d < HOJE else agora_utc()
        # todos os dias passados foram coletados as 15h do proprio dia: podem estar incompletos
        self.assertIsNone(fb.cobertura_mes(info, HOJE_YM, execs, HOJE))
        # recoletados no dia seguinte: valem
        for d in list(execs):
            if d < HOJE.isoformat():
                dia = date.fromisoformat(d) + timedelta(days=1)
                execs[d] = datetime(dia.year, dia.month, dia.day, 1, 0, tzinfo=timezone.utc)
        self.assertIsNotNone(fb.cobertura_mes(info, HOJE_YM, execs, HOJE))

    def test_mes_futuro_sem_dias_nao_tem_cobertura(self):
        import fonte_banco as fb
        futuro = (HOJE.replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
        self.assertIsNone(fb.cobertura_mes({"granularidade": "dia"}, futuro, {}, HOJE))


if __name__ == "__main__":
    unittest.main()
