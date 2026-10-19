"""Aba "Planilha" do painel de Despesas (Despesas/planilha_despesas.py): matriz grupo x item x mes e fornecedores CSI / CSI 2, com dados inventados.

Rodar:  python -m unittest discover -s tests -v
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "Despesas"))
sys.path.insert(0, str(RAIZ / "Acompanhamento de META"))
import planilha_despesas as pl  # noqa: E402

BASE = pl._base_do_arquivo()


def debitos(linhas):
    """linhas = (categoria, 'AAAA-MM', valor, fornecedor, id)"""
    return pd.DataFrame([{"Despesa": c, "_ym": ym, "Bruto": v, "Fornecedor": f, "ID": i} for c, ym, v, f, i in linhas])


class BaseDaPlanilhaTest(unittest.TestCase):
    def test_historico_bate_com_os_totais_da_planilha_original(self):
        # "Total das despesas" da planilha (linha 100), mes a mes; fev/26 e o unico em que a propria planilha nao fecha (815.406,09 contra 827.433,06 dos grupos)
        esperado = {"2025-10": 1040067.63, "2025-11": 788415.99, "2025-12": 1012501.67, "2026-01": 1083244.96, "2026-02": 827433.06, "2026-03": 880938.61,
                    "2026-04": 1091161.52, "2026-05": 971160.63, "2026-06": 1010934.48, "2026-07": 1086515.65, "2026-08": 979496.86}
        for ym, total in esperado.items():
            self.assertAlmostEqual(sum(BASE["historico"][ym].values()), total, places=2, msg=ym)

    def test_toda_ligacao_do_de_para_aponta_para_um_item_que_existe(self):
        itens = {(g["grupo"], i) for g in BASE["grupos"] for i in g["itens"]}
        for cat, dst in BASE["de_para"].items():
            self.assertIn((dst["grupo"], dst["item"]), itens, cat)

    def test_json_e_migrations_tem_a_mesma_base(self):
        sql = (RAIZ / "supabase/migrations/20261019120100_despesas_planilha_base.sql").read_text(encoding="utf-8")
        for cat in BASE["de_para"]:
            self.assertIn("'" + cat.replace("'", "''") + "'", sql, cat)
        n_hist = sum(len(v) for v in BASE["historico"].values())
        hist = (RAIZ / "supabase/migrations/20261019120200_despesas_planilha_historico.sql").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"\(\d+,\d+,'\d{4}-\d{2}',[\d.]+\)", hist)), n_hist, "linhas do histórico na migration")


class MatrizTest(unittest.TestCase):
    def matriz(self, linhas, inicio="2026-09", hoje="2026-10"):
        return pl.montar_matriz(debitos(linhas), BASE, inicio, hoje)

    def test_meses_antigos_vem_da_planilha_e_os_novos_do_klingo(self):
        m = self.matriz([("Folha Salarial", "2026-09", 1000.0, "DP", 1), ("Folha Salarial", "2026-10", 400.0, "DP", 2),
                         ("Honorário Médico", "2026-08", 5.0, "X", 3)])    # ago/26 do Klingo e incompleto: vale a planilha
        self.assertEqual([x["ym"] for x in m["meses"]][0], "2025-10")
        self.assertEqual([x["ym"] for x in m["meses"]][-1], "2026-10")
        self.assertEqual({x["ym"]: x["fonte"] for x in m["meses"]}["2026-08"], "planilha")
        self.assertEqual({x["ym"]: x["fonte"] for x in m["meses"]}["2026-09"], "klingo")
        item = {i["item"]: i for g in m["grupos"] for i in g["itens"]}
        ix = [x["ym"] for x in m["meses"]]
        self.assertEqual(item["FOLHA SALARIAL"]["valores"][ix.index("2026-08")], 72294.63)   # planilha
        self.assertEqual(item["FOLHA SALARIAL"]["valores"][ix.index("2026-09")], 1000.0)     # Klingo
        self.assertEqual(item["HONORÁRIO MÉDICO"]["valores"][ix.index("2026-08")], 367702.77)  # os R$ 5 do Klingo em ago/26 nao entram
        self.assertEqual(m["meses"][-1]["situacao"], "em_curso")

    def test_categorias_ligadas_ao_mesmo_item_somam(self):
        m = self.matriz([("Iss - Declarado", "2026-09", 100.0, "S", 1), ("Iss - Substituto Tributário", "2026-09", 50.5, "S", 2)])
        iss = next(i for g in m["grupos"] for i in g["itens"] if i["item"] == "ISS")
        self.assertEqual(iss["valores"][-2], 150.5)
        self.assertEqual(sorted(iss["categorias"]), ["Iss - Declarado", "Iss - Substituto Tributário"])
        self.assertTrue(iss["a_confirmar"])

    def test_categoria_desconhecida_nao_some_e_o_total_fecha(self):
        m = self.matriz([("Categoria Nova", "2026-09", 777.0, "Z", 1), ("Folha Salarial", "2026-09", 100.0, "DP", 2)])
        self.assertEqual(m["sem_destino"], [{"categoria": "Categoria Nova", "valor": 777.0}])
        grupo = next(g for g in m["grupos"] if g["grupo"] == pl.SEM_DESTINO)
        self.assertEqual(grupo["total"], 777.0)
        self.assertAlmostEqual(m["geral"][-2], 877.0)
        self.assertAlmostEqual(m["total"], sum(m["geral"]), places=2)

    def test_item_sem_categoria_no_klingo_so_tem_historico(self):
        m = self.matriz([("Folha Salarial", "2026-09", 100.0, "DP", 1)])
        pis = next(i for g in m["grupos"] for i in g["itens"] if i["item"] == "PIS E COFINS - UNIFICADO")
        self.assertTrue(pis["sem_klingo"])
        self.assertEqual(pis["valores"][-1], 0.0)
        self.assertIn("PIS E COFINS - UNIFICADO", m["itens_sem_klingo"])

    def test_sem_nenhum_lancamento_do_klingo_a_planilha_ainda_monta(self):
        m = pl.montar_matriz(pd.DataFrame(), BASE, "2026-09", "2026-10")
        self.assertTrue(m["ok"])
        self.assertEqual(m["meses"][-1]["ym"], "2026-10")
        self.assertAlmostEqual(m["geral"][0], 1040067.63, places=2)
        self.assertEqual(m["geral"][-1], 0.0)


def lancamentos(linhas):
    """linhas = (id, empresa, vencimento, categoria, valor, tipo)"""
    return pd.DataFrame([{"Lançamento": i, "Empresa": e, "Vencimento": pd.Timestamp(v), "Categoria": c, "Valor": val, "Tipo": t} for i, e, v, c, val, t in linhas])


class FornecedoresTest(unittest.TestCase):
    CSI = pl.EMPRESA_RATEIO

    def rodar(self, lanc, d):
        return pl.montar_fornecedores(d, lanc, BASE, "2026-09", "2026-10")

    def test_soma_por_nome_da_planilha_e_divide_entre_csi_e_csi2(self):
        d = debitos([("Softwares e Assinaturas", "2026-09", 2222.22, "YOTECH CONSULTORIA EM SISTEMAS", 10), ("Folha Salarial", "2026-08", 13166.79, "DEPARTAMENTO PESSOAL", 11),
                     ("INSS", "2026-08", 26411.88, "DEPARTAMENTO PESSOAL", 12), ("IRRF", "2026-08", 4304.02, "DEPARTAMENTO PESSOAL", 13)])
        l = lancamentos([(10, self.CSI, "2026-09-14", "Softwares e Assinaturas", 2222.22, "DESPESAS"), (11, self.CSI, "2026-09-04", "Folha Salarial", 13166.79, "DESPESAS"),
                         (12, self.CSI, "2026-09-18", "INSS", 26411.88, "DESPESAS"), (13, self.CSI, "2026-09-18", "IRRF", 4304.02, "DESPESAS")])
        m = self.rodar(l, d)["meses"]["2026-09"]
        por = {x["nome"]: x for x in m["lista"]}
        self.assertEqual(por["KLINGO"]["total"], 2222.22)
        self.assertEqual((por["KLINGO"]["csi"], por["KLINGO"]["csi2"]), (1111.11, 1111.11))
        self.assertEqual(por["JRL - FOLHA SALARIAL"]["total"], 13166.79)
        self.assertEqual(por["JRL - INSS + IRRF"]["total"], 30715.90)    # os dois (como na planilha de set/26)
        self.assertEqual(m["total"], round(2222.22 + 13166.79 + 30715.90, 2))
        self.assertEqual(m["total_outros"], 0.0)

    def test_so_a_empresa_csi_e_so_despesa_e_so_o_mes_do_vencimento(self):
        d = debitos([("Softwares e Assinaturas", "2026-09", 100.0, "UDOK SERVICOS ONLINE E SOFTWARE", 1), ("Softwares e Assinaturas", "2026-09", 200.0, "UDOK SERVICOS ONLINE E SOFTWARE", 2),
                     ("Softwares e Assinaturas", "2026-09", 300.0, "UDOK SERVICOS ONLINE E SOFTWARE", 3), ("Softwares e Assinaturas", "2026-09", 400.0, "UDOK SERVICOS ONLINE E SOFTWARE", 4)])
        l = lancamentos([(1, self.CSI, "2026-09-15", "Softwares e Assinaturas", 100.0, "DESPESAS"), (2, "JJ INTELIGÊNCIA", "2026-09-15", "Softwares e Assinaturas", 200.0, "DESPESAS"),
                         (3, self.CSI, "2026-10-15", "Softwares e Assinaturas", 300.0, "DESPESAS"), (4, self.CSI, "2026-09-15", "Softwares e Assinaturas", 400.0, "RECEITAS")])
        r = self.rodar(l, d)["meses"]
        self.assertEqual({x["nome"]: x["total"] for x in r["2026-09"]["lista"]}["UDOK"], 100.0)
        self.assertEqual({x["nome"]: x["total"] for x in r["2026-10"]["lista"]}["UDOK"], 300.0)

    def test_lancamento_repetido_no_financeiro_conta_uma_vez(self):
        d = debitos([("Segurança e Monitoramento", "2026-09", 871.0, "MAISSELBA SEGURANÇA ELETRONICA", 1967)])
        l = lancamentos([(1967, self.CSI, "2026-09-25", "Segurança e Monitoramento", 871.0, "DESPESAS")] * 2)   # o #798 repete o lancamento (uma linha por conta/conciliacao)
        self.assertEqual({x["nome"]: x["total"] for x in self.rodar(l, d)["meses"]["2026-09"]["lista"]}["MAISSSELBA"], 871.0)

    def test_fornecedor_fora_da_lista_e_lancamento_sem_fornecedor(self):
        d = debitos([("Materiais de Consumo Técnico", "2026-09", 10500.0, "GADALI MEDICAL", 1)])
        l = lancamentos([(1, self.CSI, "2026-09-10", "Materiais de Consumo Técnico", 10500.0, "DESPESAS"), (99, self.CSI, "2026-09-11", "Limpeza e Higiene", 50.0, "DESPESAS")])
        m = self.rodar(l, d)["meses"]["2026-09"]
        self.assertEqual({o["nome"]: o["total"] for o in m["outros"]}, {"GADALI MEDICAL": 10500.0, pl.FORN_SEM_ID: 50.0})
        self.assertEqual(m["sem_fornecedor"], 1)
        self.assertEqual(m["total"], 0.0)

    def test_sem_lancamentos_do_financeiro_avisa_em_vez_de_quebrar(self):
        self.assertFalse(pl.montar_fornecedores(pd.DataFrame(), None, BASE, "2026-09", "2026-10")["ok"])
        self.assertFalse(pl.montar_fornecedores(pd.DataFrame(), pd.DataFrame(), BASE, "2026-09", "2026-10")["ok"])


class MontarTest(unittest.TestCase):
    def test_falha_na_base_vira_aviso_e_nao_derruba_o_painel(self):
        with mock.patch.object(pl, "carregar_base", side_effect=RuntimeError("sem banco")):
            r = pl.montar(pd.DataFrame(), None, "2026-09", "2026-10")
        self.assertFalse(r["matriz"]["ok"])
        self.assertIn("sem banco", r["matriz"]["motivo"])
        self.assertFalse(r["fornecedores"]["ok"])

    def test_banco_fora_do_ar_usa_o_arquivo_do_repositorio(self):
        import armazenamento as arm
        with mock.patch.object(arm, "ativo", return_value=True), mock.patch.object(arm, "ler_tabela", side_effect=arm.ErroArmazenamento("fora do ar")):
            base = pl.carregar_base()
        self.assertEqual(base["fonte"], "arquivo")

    def test_base_do_banco_tem_o_mesmo_formato_da_do_arquivo(self):
        import armazenamento as arm
        itens = [{"grupo": g["grupo"], "item": i, "ordem_grupo": gi, "ordem_item": ii} for gi, g in enumerate(json.loads((RAIZ / "Despesas/planilha_base.json").read_text(encoding="utf-8"))["grupos"], 1)
                 for ii, i in enumerate([x["item"] for x in g["itens"]], 1)]
        tabelas = {"despesa_item": itens,
                   "despesa_historico": [{"mes": "2025-10-01", "grupo": "PESSOAL", "item": "INSS", "valor": "20620.37"}],
                   "despesa_de_para": [{"categoria_klingo": "INSS", "grupo": "PESSOAL", "item": "INSS", "confirmado": True, "observacao": None}],
                   "despesa_fornecedor": [{"id": 1, "ordem": 1, "nome_planilha": "KLINGO", "fornecedor_klingo": "YOTECH", "categoria_klingo": None, "pct_csi": "50.00"},
                                          {"id": 2, "ordem": 2, "nome_planilha": "SECURE", "fornecedor_klingo": None, "categoria_klingo": None, "pct_csi": "50.00"}]}
        with mock.patch.object(arm, "ativo", return_value=True), mock.patch.object(arm, "ler_tabela", side_effect=lambda nome, ordem: tabelas[nome]):
            base = pl.carregar_base()
        self.assertEqual(base["fonte"], "banco")
        self.assertEqual(base["historico"]["2025-10"][("PESSOAL", "INSS")], 20620.37)
        self.assertEqual([f["nome"] for f in base["fornecedores"]], ["KLINGO", "SECURE"])
        self.assertEqual(base["fornecedores"][1]["regras"], [])
        self.assertEqual(base["fornecedores"][0]["regras"], [{"fornecedor": "YOTECH", "categoria": None}])


# ---------------------------------------------------------------------------------------------------------------- pagina inteira
import os  # noqa: E402
import re as _re  # noqa: E402,F401
import shutil  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402


def abas_inventadas():
    """Despesas (#13505 + #13509) de set e out/2026 e os Lancamentos do Financeiro (#798), com os mesmos IDs."""
    brutos, liqs, lancs = [], [], []
    base = [  # id, categoria, competencia, valor, fornecedor, descricao, empresa, vencimento
        (1, "Folha Salarial", "2026-09-01", 13166.79, "DEPARTAMENTO PESSOAL", "FOLHA SALARIAL", pl.EMPRESA_RATEIO, "2026-09-04"),
        (2, "Honorário Médico", "2026-09-01", 9000.0, "HYRS SERVIÇOS MÉDICOS", "Honorário Médico", pl.EMPRESA_RATEIO, "2026-09-25"),
        (3, "Softwares e Assinaturas", "2026-09-01", 2222.22, "YOTECH CONSULTORIA EM SISTEMAS", "IMPLANTAÇÃO DO KLINGO", pl.EMPRESA_RATEIO, "2026-09-14"),
        (4, "Categoria Nova", "2026-09-01", 300.0, "FORNECEDOR NOVO", "x", "JJ INTELIGÊNCIA", "2026-09-20"),
        (5, "Folha Salarial", "2026-10-01", 15651.16, "DEPARTAMENTO PESSOAL", "FOLHA SALARIAL", pl.EMPRESA_RATEIO, "2026-10-06"),
    ]
    for i, cat, comp, v, forn, desc, emp, venc in base:
        brutos.append({"Categoria": "Debito", "Despesa": cat, "Competência": pd.Timestamp(comp), "Valor": v, "Descrição": desc, "Fornecedor": forn, "Mês (filtro)": comp[:7]})
        liqs.append({"ID do Lançamento": float(i), "Despesa": cat, "Competência": pd.Timestamp(comp), "Descrição": desc, "Fornecedor": forn, "Valor Líquido": v, "Mês (filtro)": comp[:7]})
        lancs.append({"Lançamento": float(i), "Empresa": emp, "Vencimento": pd.Timestamp(venc), "Categoria": cat, "Valor": v, "Tipo": "DESPESAS", "Mês (filtro)": comp[:7]})
    return {"Despesas": pd.DataFrame(brutos), "Líquido": pd.DataFrame(liqs)}, {"Lançamentos": pd.DataFrame(lancs)}


def pagina():
    import gerar_despesas as gd
    desp, fin = abas_inventadas()
    with mock.patch.dict(os.environ, {"PORTAL_ARMAZENAMENTO": "arquivos", "VERCEL": ""}), \
            mock.patch.object(gd.k, "carregar", lambda p: fin if Path(p).name == "Financeiro" else desp):
        return gd.gerar(devolver_html=True)


def dados_da_pagina(html):
    m = re.search(r'<script id="dados" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


class PaginaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RAIZ / "Financeiro"))
        cls.html = pagina()
        cls.dados = dados_da_pagina(cls.html)

    def test_pagina_traz_a_planilha_com_klingo_e_historico(self):
        P = self.dados["planilha"]["matriz"]
        self.assertTrue(P["ok"])
        ix = [m["ym"] for m in P["meses"]]
        self.assertEqual((ix[0], ix[-1]), ("2025-10", self.dados["hoje"][:7] if self.dados["hoje"][:7] >= "2026-09" else "2026-09"))
        folha = next(i for g in P["grupos"] for i in g["itens"] if i["item"] == "FOLHA SALARIAL")
        self.assertEqual(folha["valores"][ix.index("2026-09")], 13166.79)
        self.assertEqual(folha["valores"][ix.index("2025-10")], 65423.48)
        self.assertEqual([c["categoria"] for c in P["sem_destino"]], ["Categoria Nova"])

    def test_pagina_traz_os_fornecedores_do_mes(self):
        F = self.dados["planilha"]["fornecedores"]
        self.assertTrue(F["ok"])
        set_ = {x["nome"]: x for x in F["meses"]["2026-09"]["lista"]}
        self.assertEqual(set_["JRL - FOLHA SALARIAL"]["total"], 13166.79)
        self.assertEqual(set_["KLINGO"]["csi"], 1111.11)
        self.assertEqual([o["nome"] for o in F["meses"]["2026-09"]["outros"]], ["HYRS SERVIÇOS MÉDICOS"])    # a empresa JJ (categoria nova) fica de fora

    def test_o_painel_depende_do_financeiro_para_a_pagina_se_refazer(self):
        import armazenamento as arm
        self.assertEqual(arm.DEPENDENCIAS["despesas"], ["financeiro"])

    def test_sem_financeiro_o_resto_da_aba_continua(self):
        import gerar_despesas as gd
        desp, _ = abas_inventadas()
        with mock.patch.dict(os.environ, {"PORTAL_ARMAZENAMENTO": "arquivos", "VERCEL": ""}), mock.patch.object(gd.k, "carregar", lambda p: {} if Path(p).name == "Financeiro" else desp):
            d = dados_da_pagina(gd.gerar(devolver_html=True))["planilha"]
        self.assertTrue(d["matriz"]["ok"])
        self.assertFalse(d["fornecedores"]["ok"])


def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


@unittest.skipUnless(_chromium(), "sem Chromium")
class NoNavegadorTest(unittest.TestCase):
    """Abre a pagina no Chromium: sem erro de JavaScript, com a planilha e a lista de fornecedores desenhadas."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RAIZ / "Financeiro"))
        cls.pasta = Path(tempfile.mkdtemp())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.porta = s.getsockname()[1]
        cls.srv = subprocess.Popen([sys.executable, "-m", "http.server", str(cls.porta), "-d", str(cls.pasta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        cls.html = pagina()

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def abrir(self, largura=1200):
        (self.pasta / "t.html").write_text(self.html.replace("</body>", '<script>setTimeout(()=>document.body.setAttribute("data-w",document.documentElement.scrollWidth+"/"+innerWidth),400)</script></body>'), encoding="utf-8")
        out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=8000", "--enable-logging=stderr", "--v=0", f"--window-size={largura},1400",
                              "--dump-dom", f"http://127.0.0.1:{self.porta}/t.html"], capture_output=True, text=True, timeout=300)
        return out.stdout, [l for l in out.stderr.splitlines() if "CONSOLE" in l and "rror" in l]

    def test_aba_planilha_desenha_as_duas_tabelas(self):
        dom, erros = self.abrir()
        self.assertEqual(erros, [])
        corpo = re.search(r'<main id="conteudo">(.*?)</main>', dom, re.S).group(1)
        for texto in ("Despesas por grupo e mês", "FOLHA SALARIAL", "Total das despesas", "SEM CLASSIFICAÇÃO", "Categoria Nova", "Fornecedores do mês", "JRL - FOLHA SALARIAL", "KLINGO", "só histórico", "a confirmar"):
            self.assertIn(texto, corpo)
        self.assertNotRegex(corpo, r"undefined|NaN|\[object")

    def test_sem_sobra_horizontal_no_celular(self):
        dom, erros = self.abrir(500)
        self.assertEqual(erros, [])
        escrito, janela = re.search(r'data-w="(\d+)/(\d+)"', dom).groups()
        self.assertLessEqual(int(escrito), int(janela))


class MesDeVencimentoTest(unittest.TestCase):
    """O painel conta cada despesa no mes em que ela VENCE (vindo do Financeiro #798 pelo ID), nao no da competencia."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RAIZ / "Financeiro"))

    def pagina(self, linhas):
        import gerar_despesas as gd
        brutos, liqs, lancs = [], [], []
        for i, cat, comp, v, venc, mes_filtro in linhas:   # venc None = o Financeiro nao tem o lancamento
            brutos.append({"Categoria": "Debito", "Despesa": cat, "Competência": pd.Timestamp(comp), "Valor": v, "Descrição": cat, "Fornecedor": "FORN " + cat, "Mês (filtro)": mes_filtro})
            liqs.append({"ID do Lançamento": float(i), "Despesa": cat, "Competência": pd.Timestamp(comp), "Descrição": cat, "Fornecedor": "FORN " + cat, "Valor Líquido": v, "Mês (filtro)": mes_filtro})
            if venc:
                lancs.append({"Lançamento": float(i), "Empresa": pl.EMPRESA_RATEIO, "Vencimento": pd.Timestamp(venc), "Categoria": cat, "Valor": v, "Tipo": "DESPESAS", "Mês (filtro)": mes_filtro})
        desp, fin = {"Despesas": pd.DataFrame(brutos), "Líquido": pd.DataFrame(liqs)}, {"Lançamentos": pd.DataFrame(lancs)}
        with mock.patch.dict(os.environ, {"PORTAL_ARMAZENAMENTO": "arquivos", "VERCEL": ""}), \
                mock.patch.object(gd.k, "carregar", lambda p: fin if Path(p).name == "Financeiro" else desp):
            return dados_da_pagina(gd.gerar(devolver_html=True))

    def test_boleto_de_setembro_que_vence_em_outubro_entra_em_outubro(self):
        d = self.pagina([(1, "INSS", "2026-08-01", 100.0, "2026-09-18", "2026-08"),    # competencia agosto, vence em setembro: conta em setembro
                         (2, "INSS", "2026-09-01", 200.0, "2026-10-20", "2026-09"),    # competencia setembro, vence em outubro: conta em outubro
                         (3, "INSS", "2026-10-01", 7.0, "2026-10-05", "2026-10"),
                         (4, "Aluguel", "2026-10-01", 9.0, "2026-11-18", "2026-10")])  # vence depois do ultimo mes baixado (outubro): fica de fora
        m = d["meses"]
        self.assertEqual(m["2026-09"]["total"], 100.0)
        self.assertEqual(m["2026-10"]["total"], 207.0)
        self.assertNotIn("2026-11", m)
        self.assertEqual(d["vencimento"]["mudaram_de_mes"], 3)
        self.assertEqual(d["vencimento"]["alem_do_baixado"], 1)
        self.assertEqual(d["vencimento"]["sem_vencimento"], 0)
        self.assertFalse([a for a in d["atencao"] if "sem data de vencimento" in a["titulo"]])
        self.assertEqual([x["total"] for x in d["evolucao"] if x["ym"] in ("2026-09", "2026-10")], [100.0, 207.0])

    def test_sem_vencimento_no_financeiro_fica_na_competencia_e_avisa(self):
        d = self.pagina([(1, "INSS", "2026-09-01", 100.0, "2026-10-20", "2026-09"), (2, "Aluguel", "2026-09-01", 50.0, None, "2026-09"),
                         (3, "Luz", "2026-10-01", 1.0, "2026-10-02", "2026-10")])   # o mes de outubro foi baixado: o vencimento de 20/10 cabe
        self.assertEqual(d["meses"]["2026-09"]["total"], 50.0)
        self.assertEqual(d["meses"]["2026-10"]["total"], 101.0)
        self.assertEqual(d["vencimento"]["sem_vencimento"], 1)
        aviso = [a for a in d["atencao"] if "sem data de vencimento" in a["titulo"]]
        self.assertEqual(len(aviso), 1)
        self.assertIn("R$ 50,00", aviso[0]["texto"])

    def test_lancamentos_do_mes_trazem_vencimento_e_competencia(self):
        d = self.pagina([(1, "INSS", "2026-09-01", 100.0, "2026-10-20", "2026-09"), (3, "Luz", "2026-10-01", 1.0, "2026-10-02", "2026-10")])
        l = next(x for x in d["meses"]["2026-10"]["lancamentos"] if x["categoria"] == "INSS")
        self.assertTrue(l["vencimento"].startswith("2026-10-20"))
        self.assertTrue(l["competencia"].startswith("2026-09-01"))


if __name__ == "__main__":
    unittest.main()
