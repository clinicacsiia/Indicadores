"""Testes do portal na nuvem (api/*.py + portal_nuvem.py + armazenamento.py) contra um Supabase e um Klingo simulados.

Rodar:  python -m unittest discover -s tests -v
"""
import base64
import gzip
import importlib.util
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
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
FUNCOES = {}


def setUpModule():
    sup, url = mn.subir(mn.criar_supabase(BANCO))
    kli, kurl = mn.subir(mn.criar_klingo())
    SERVIDORES.extend([sup, kli])
    os.environ.update(SUPABASE_URL=url, SUPABASE_SERVICE_ROLE_KEY="svc", NEXT_PUBLIC_SUPABASE_ANON_KEY="anon", KLINGO_APP_TOKEN="token-de-teste")
    import portal_nuvem  # noqa: F401  (poe as pastas dos paineis no sys.path)
    import extrair_laudo as ex
    ex.API_EXTERNA = kurl + "/api/info/relatorio"
    BANCO.novo_usuario("tok-admin", "csiadmin@csi.local", "admin")
    BANCO.novo_usuario("tok-viewer", "ana@csi.local", "viewer", {"despesas": True, "faturamento": False})
    BANCO.novo_usuario("tok-sem", "bia@csi.local", "viewer", {})
    for nome in ("painel", "atualizar", "estado", "pendencias"):   # as funcoes da Vercel, carregadas do jeito que a Vercel as carrega
        spec = importlib.util.spec_from_file_location(f"api_{nome}", RAIZ / "api" / f"{nome}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        srv, u = mn.subir(mod.handler)
        SERVIDORES.append(srv)
        FUNCOES[nome] = u


def tearDownModule():
    for s in SERVIDORES:
        s.shutdown()


def chamar(funcao, caminho, token=None, metodo="GET", corpo=None, cabecalhos=None, cookie=None):
    h = {"Accept": "text/html,application/json", "Accept-Encoding": "gzip"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if cookie:
        h["Cookie"] = cookie
    h.update(cabecalhos or {})
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(FUNCOES[funcao] + caminho, data=dados, headers=h, method=metodo)
    try:
        r = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        r = e
    bruto = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        bruto = gzip.decompress(bruto)
    return r.status if hasattr(r, "status") else r.code, bruto.decode("utf-8")


class AcessoTest(unittest.TestCase):
    def test_sem_login_nega(self):
        status, corpo = chamar("painel", "/api/painel?id=despesas")
        self.assertEqual(status, 401)
        self.assertIn("Sessão", corpo)

    def test_token_invalido_nega(self):
        self.assertEqual(chamar("painel", "/api/painel?id=despesas", token="falso")[0], 401)

    def test_painel_inexistente(self):
        self.assertEqual(chamar("painel", "/api/painel?id=../../etc", token="tok-admin")[0], 404)
        self.assertEqual(chamar("painel", "/api/painel?id=metas", token="tok-admin")[0], 404)   # Metas tem aba propria no site

    def test_viewer_sem_permissao_nega(self):
        self.assertEqual(chamar("painel", "/api/painel?id=faturamento", token="tok-viewer")[0], 403)   # permissao false
        self.assertEqual(chamar("painel", "/api/painel?id=despesas", token="tok-sem")[0], 403)         # painel novo nasce bloqueado
        self.assertEqual(chamar("estado", "/api/estado?id=despesas", token="tok-sem")[0], 403)
        self.assertEqual(chamar("pendencias", "/api/pendencias?id=despesas", token="tok-sem")[0], 403)

    def test_cookie_do_site_vale_como_login(self):
        sessao = json.dumps({"access_token": "tok-admin", "refresh_token": "x"})
        valor = "base64-" + base64.urlsafe_b64encode(sessao.encode()).decode().rstrip("=")
        self.assertEqual(chamar("estado", "/api/estado?id=despesas", cookie=f"sb-proj-auth-token={valor}")[0], 200)
        meio = len(valor) // 2   # o @supabase/ssr parte cookies grandes em .0, .1...
        self.assertEqual(chamar("estado", "/api/estado?id=despesas", cookie=f"sb-proj-auth-token.1={valor[meio:]}; sb-proj-auth-token.0={valor[:meio]}")[0], 200)

    def test_atualizar_so_admin_e_com_cabecalho(self):
        self.assertEqual(chamar("atualizar", "/api/atualizar?id=despesas", token="tok-viewer", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 403)
        self.assertEqual(chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", corpo={})[0], 403)   # sem X-Painel


class FluxoTest(unittest.TestCase):
    """Atualizar -> dados no Supabase -> pagina pronta guardada -> entregue a quem tem permissao."""

    def test_fluxo_completo(self):
        import armazenamento as arm
        import portal_nuvem as pn
        # 1. antes de atualizar a pagina sai (vazia), sem quebrar
        status, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
        self.assertEqual(status, 200)
        self.assertIn("window.PAINEL_NUVEM=true", html)
        self.assertIn('window.PAINEL_ID="despesas"', html)
        self.assertIn("window.PAINEL_ADMIN=false", html)

        # 2. admin atualiza (Klingo simulado)
        status, corpo = chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        resp = json.loads(corpo)
        self.assertEqual(status, 200)
        self.assertTrue(resp["ok"], resp)
        self.assertTrue(resp["atualizou"], resp)
        self.assertTrue(BANCO.atualizacoes and BANCO.atualizacoes[-1]["painel"] == "despesas" and BANCO.atualizacoes[-1]["usuario"] == "csiadmin@csi.local")
        n_lotes = len(BANCO.dados)
        self.assertGreater(n_lotes, 0)
        self.assertIn(("despesas", "padrao"), BANCO.paginas)   # a pagina ficou pronta

        # 3. atualizar de novo SUBSTITUI o mes (nao soma): mesma quantidade de lotes ativos
        chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        arm._CACHE_VERSAO.clear()
        ativos = {(m["painel"], m["aba"], m["mes"]): m["versao"] for m in BANCO.mes.values()}
        self.assertEqual(len([d for d in BANCO.dados if d["versao"] == ativos[(d["painel"], d["aba"], d["mes"])]]), len(BANCO.dados), "sobrou versao antiga")
        self.assertEqual(len(BANCO.dados), n_lotes)

        # 4. a pagina vem do cache (nao recalcula) e marca admin ou nao conforme quem pede
        chamadas = []
        original = pn.montar_pagina
        pn.montar_pagina = lambda *a, **k: chamadas.append(a) or original(*a, **k)
        try:
            _, html_admin = chamar("painel", "/api/painel?id=despesas", token="tok-admin")
            _, html_viewer = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(chamadas, [])
            self.assertIn("window.PAINEL_ADMIN=true", html_admin)
            self.assertIn("window.PAINEL_ADMIN=false", html_viewer)
            self.assertIn("<title>", html_viewer)

            # 5. periodo de varios meses: calcula na hora e guarda; mes unico usa a pagina de sempre
            chamar("painel", "/api/painel?id=despesas&de=2026-09&ate=2026-10", token="tok-viewer")
            self.assertEqual(len(chamadas), 1)
            self.assertIn(("despesas", "2026-09..2026-10"), BANCO.paginas)
            chamar("painel", "/api/painel?id=despesas&de=2026-10&ate=2026-10", token="tok-viewer")
            self.assertEqual(len(chamadas), 1)
        finally:
            pn.montar_pagina = original

        # 6. dado novo invalida a pagina guardada (a versao tem resolucao de 1 s)
        time.sleep(1.1)
        arm.gravar_mes("despesas", pn.codigo_do("despesas").k.ler_definicao(RAIZ / "Despesas")["relatorios"][0]["aba"], "2026-10", [], exclusivo=False)
        arm._CACHE_VERSAO.clear()
        pn.montar_pagina = lambda *a, **k: chamadas.append(a) or original(*a, **k)
        try:
            chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(len(chamadas), 2)
        finally:
            pn.montar_pagina = original

    def test_layout_novo_refaz_a_pagina_guardada(self):
        """Pagina guardada com um layout antigo (sem a marca do layout atual) e refeita, mesmo com dados e dia iguais."""
        import portal_nuvem as pn
        chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        pronta = BANCO.paginas[("despesas", "padrao")]
        self.assertIn(pn._marca_layout(), pronta["html"])
        pronta["html"] = pronta["html"].replace(pn._marca_layout(), "<!-- layout:antigo -->")   # como a pagina que a producao ainda servia
        chamadas = []
        original = pn.montar_pagina
        pn.montar_pagina = lambda *a, **k: chamadas.append(a) or original(*a, **k)
        try:
            _, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(len(chamadas), 1)
            self.assertIn(pn._marca_layout(), html)
            self.assertIn(pn._marca_layout(), BANCO.paginas[("despesas", "padrao")]["html"])
            chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(len(chamadas), 1)   # refeita uma vez so
        finally:
            pn.montar_pagina = original

    def test_periodo_livre_por_datas(self):
        chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        status, html = chamar("painel", "/api/painel?id=despesas&de=2026-09-10&ate=2026-10-05", token="tok-viewer")
        self.assertEqual(status, 200)
        self.assertIn(("despesas", "2026-09-10..2026-10-05"), BANCO.paginas)   # recorte de dias: calculado e guardado com as datas na chave
        self.assertIn("toolbar", html)                                         # a barra de filtros padrao
        chamar("painel", "/api/painel?id=despesas&de=2026-10-01&ate=2026-10-31", token="tok-viewer")
        self.assertNotIn(("despesas", "2026-10-01..2026-10-31"), BANCO.paginas)   # datas de um mes inteiro: a pagina de sempre
        status, _ = chamar("painel", "/api/painel?id=despesas&de=2026-02-30&ate=2026-03-10", token="tok-viewer")
        self.assertEqual(status, 200)                                          # data que nao existe: ignora o pedido

    def test_estado_bate_com_versao_da_pagina(self):
        import re
        chamar("atualizar", "/api/atualizar?id=suprimentos", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        # suprimentos: o admin ve; o viewer da suite nao tem permissao
        _, html = chamar("painel", "/api/painel?id=suprimentos", token="tok-admin")
        versao_pagina = int(re.search(r'"versao":\s*(\d+)', html).group(1))
        _, est = chamar("estado", "/api/estado?id=suprimentos", token="tok-admin")
        self.assertEqual(json.loads(est)["versao"], versao_pagina)

    def test_pendencias(self):
        r = chamar("pendencias", "/api/pendencias?id=despesas&acao=resolver", token="tok-viewer", metodo="POST",
                   cabecalhos={"X-Painel": "1"}, corpo={"chave": "a|b", "titulo": "Algo", "versao": 7})
        self.assertEqual(r[0], 200)
        lista = json.loads(r[1])["resolvidas"]
        self.assertEqual([(p["chave"], p["usuario"], p["versao"]) for p in lista], [("a|b", "ana@csi.local", 7)])   # quem marcou vem do login, nao do corpo
        self.assertEqual(json.loads(chamar("pendencias", "/api/pendencias?id=despesas", token="tok-admin")[1])["resolvidas"][0]["chave"], "a|b")
        self.assertEqual(chamar("pendencias", "/api/pendencias?id=despesas&acao=resolver", token="tok-viewer", metodo="POST", corpo={"chave": "x"})[0], 403)  # sem X-Painel
        r = chamar("pendencias", "/api/pendencias?id=despesas&acao=reabrir", token="tok-viewer", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={"chave": "a|b"})
        self.assertEqual(json.loads(r[1])["resolvidas"], [])


class DadosTest(unittest.TestCase):
    """O que sai do Supabase tem a mesma cara do que saia do Excel (tipos, duplicados, ordem das colunas)."""

    def test_tipos_duplicados_e_colunas(self):
        import armazenamento as arm
        import klingo_relatorios as k
        chamar("atualizar", "/api/atualizar?id=faturamento", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        arm._CACHE_VERSAO.clear()
        pasta = RAIZ / "Faturamento"
        defn = k.ler_definicao(pasta)
        abas = k.carregar(pasta)
        com_chave = 0
        for rel in defn["relatorios"]:
            df = abas[rel["aba"]]
            self.assertGreater(len(df), 0, rel["aba"])
            for c in rel.get("numeros", []):
                self.assertTrue(str(df[c].dtype).startswith(("int", "float")), f"{rel['aba']}.{c} = {df[c].dtype}")
            for c in rel.get("datas", {}):
                self.assertTrue(str(df[c].dtype).startswith("datetime64"), f"{rel['aba']}.{c} = {df[c].dtype}")
            self.assertEqual(list(df.columns[-2:]), [k.COL_MES, k.COL_EM])   # colunas de controle no fim, como no Excel
            if rel.get("chave"):
                com_chave += 1
                self.assertEqual(int(df.duplicated(subset=rel["chave"]).sum()), 0, f"{rel['aba']} tem registro repetido entre meses")
        self.assertGreater(com_chave, 0)


class ArmazenamentoTest(unittest.TestCase):
    def test_leitura_paginada_e_custos(self):
        import armazenamento as arm
        linhas = [{"n": i, "texto": "x" * 5} for i in range(arm.TAMANHO_LOTE * arm.LOTES_POR_PAGINA)]   # exatamente uma pagina de lotes: a seguinte da 416
        arm.gravar_mes("teste_pag", "Aba", "2026-10", linhas)
        lidas = arm.ler_aba("teste_pag", "Aba")
        self.assertEqual([x["n"] for x in lidas], list(range(len(linhas))))
        BANCO.custos[:] = [{"item": f"item {i}", "custo": 1.5} for i in range(1200)] + [{"item": "zerado", "custo": 0}]
        self.assertEqual(len(arm.custos_informados()), 1200)   # passa das 1000 linhas que o Supabase devolve por pedido
        BANCO.custos.clear()


class AtualizacaoParcialTest(unittest.TestCase):
    def test_corta_por_tempo_e_continua_no_proximo_clique(self):
        import armazenamento as arm
        import klingo_relatorios as k
        pasta = RAIZ / "Suprimentos"
        antes = len(BANCO.mes)
        k.PRAZO_FINAL = 0.001   # prazo ja vencido: nao baixa nada, mas avisa
        try:
            r = k.atualizar_nuvem(pasta, forcar=True)
        finally:
            k.PRAZO_FINAL = None
        self.assertTrue(r["parcial"])
        self.assertIn("próximo clique", r["mensagem"])
        self.assertEqual(len(BANCO.mes), antes)
        arm._CACHE_VERSAO.clear()


class MetasNoAtendimentoTest(unittest.TestCase):
    def test_atendimento_atualiza_e_le_a_base_de_metas(self):
        import armazenamento as arm
        chamar("atualizar", "/api/atualizar?id=atendimento", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        arm._CACHE_VERSAO.clear()
        df = arm.ler_metas_dados()
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 3)
        self.assertIn("Exames Realizados", df.columns)
        import gerar_dashboard as gd
        dados = gd.carregar_dados()   # o mesmo caminho que o Atendimento usa
        self.assertEqual(len(dados), 3)
        self.assertEqual(int(dados["_sus"].sum()), 1)


if __name__ == "__main__":
    unittest.main()
