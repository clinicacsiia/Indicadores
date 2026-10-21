"""Testes do portal na nuvem (api/*.py + portal_nuvem.py + armazenamento.py) contra um Supabase e um Klingo simulados.

Rodar:  python -m unittest discover -s tests -v
"""
import base64
import gzip
import importlib.util
import json
import os
import re
import sys
import time
import unittest
from datetime import timedelta
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
    # Estes testes cobrem o caminho antigo (consulta direta ao Klingo, PAINEL_FONTE=klingo); o caminho pelo banco e testado em test_fonte_banco.py
    os.environ.update(SUPABASE_URL=url, SUPABASE_SERVICE_ROLE_KEY="svc", NEXT_PUBLIC_SUPABASE_ANON_KEY="anon", KLINGO_APP_TOKEN="token-de-teste",
                      PAINEL_FONTE="klingo")
    import portal_nuvem  # noqa: F401  (poe as pastas dos paineis no sys.path)
    import extrair_laudo as ex
    ex.API_EXTERNA = kurl + "/api/info/relatorio"
    BANCO.novo_usuario("tok-admin", "csiadmin@csi.local", "admin")
    BANCO.novo_usuario("tok-viewer", "ana@csi.local", "viewer", {"despesas": True, "faturamento": False, "dados_financeiros": True})
    BANCO.novo_usuario("tok-sem-fin", "caio@csi.local", "viewer", {"despesas": True, "faturamento": True, "atendimento": True, "dados_financeiros": False})   # tem os paineis, mas nao os dados financeiros
    BANCO.novo_usuario("tok-sem", "bia@csi.local", "viewer", {})
    todos = {p: True for p in ("faturamento", "financeiro", "despesas", "indicadores", "cesta", "suprimentos", "atendimento", "tempo", "nps")}
    BANCO.novo_usuario("tok-todos-fin", "gil@csi.local", "viewer", {**todos, "dados_financeiros": True})
    BANCO.novo_usuario("tok-todos-sem-fin", "ivo@csi.local", "viewer", {**todos, "dados_financeiros": False})
    BANCO.novo_usuario("tok-so-fin", "lia@csi.local", "viewer", {"dados_financeiros": True})   # tem os dados financeiros, mas nenhum painel liberado
    BANCO.novo_usuario("tok-fin-texto", "mel@csi.local", "viewer", {**todos, "dados_financeiros": "true"})   # texto, nao boolean: nao vale
    for nome in ("painel", "atualizar", "estado", "pendencias", "renovar"):   # as funcoes da Vercel, carregadas do jeito que a Vercel as carrega
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

    def test_painel_so_de_dinheiro_exige_dados_financeiros(self):
        # tem a permissao do painel, mas nao "Dados financeiros": Faturamento/Financeiro/Despesas/Indicadores nem abrem (pagina, estado, avisos, renovacao)
        for painel in ("despesas", "faturamento"):
            self.assertEqual(chamar("painel", f"/api/painel?id={painel}", token="tok-sem-fin")[0], 403)
            self.assertEqual(chamar("estado", f"/api/estado?id={painel}", token="tok-sem-fin")[0], 403)
            self.assertEqual(chamar("pendencias", f"/api/pendencias?id={painel}", token="tok-sem-fin")[0], 403)
            self.assertEqual(chamar("renovar", f"/api/renovar?id={painel}", token="tok-sem-fin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 403)
        self.assertIn("Dados financeiros", chamar("painel", "/api/painel?id=despesas", token="tok-sem-fin")[1])
        # o admin sempre ve
        self.assertEqual(chamar("painel", "/api/painel?id=despesas", token="tok-admin")[0], 200)

    def test_matriz_de_acesso_todos_os_paineis_e_rotas(self):
        """Todo painel x todo tipo de usuario x cada rota. Regra: sem o painel liberado = 403; painel so de dinheiro sem "Dados financeiros" = 403; admin sempre passa."""
        import portal_nuvem as pn
        paineis = pn.modulos()
        usuarios = {   # token: (admin, ve o painel?, tem Dados financeiros?)
            "tok-admin": (True, lambda p: True, True),
            "tok-todos-fin": (False, lambda p: True, True),
            "tok-todos-sem-fin": (False, lambda p: True, False),
            "tok-so-fin": (False, lambda p: False, True),
            "tok-sem": (False, lambda p: False, False),
            "tok-fin-texto": (False, lambda p: True, False),   # "true" em texto nao conta como permissao
        }
        for painel in paineis:
            total = pn.modo_financeiro(painel) == "total"
            for token, (admin, tem_painel, tem_fin) in usuarios.items():
                deveria_passar = admin or (tem_painel(painel) and (tem_fin or not total))
                for rota, caminho in (("painel", "painel"), ("estado", "estado"), ("pendencias", "pendencias")):
                    with self.subTest(painel=painel, usuario=token, rota=rota):
                        status, corpo = chamar(rota, f"/api/{caminho}?id={painel}", token=token)
                        if deveria_passar:
                            self.assertNotIn(status, (401, 403), corpo[:200])
                        else:
                            self.assertEqual(status, 403, corpo[:200])
                            self.assertNotIn('id="dados"', corpo)
                if not deveria_passar:   # renovar e atualizar mexem no painel: tambem fechados
                    for rota in ("renovar", "atualizar"):
                        with self.subTest(painel=painel, usuario=token, rota=rota):
                            self.assertEqual(chamar(rota, f"/api/{rota}?id={painel}", token=token, metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 403)
                if not admin:   # atualizar (consulta o Klingo) e so do administrador, mesmo com tudo liberado
                    with self.subTest(painel=painel, usuario=token, rota="atualizar-admin"):
                        self.assertEqual(chamar("atualizar", f"/api/atualizar?id={painel}", token=token, metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 403)

    def test_sem_login_nenhuma_rota_abre(self):
        import portal_nuvem as pn
        for painel in pn.modulos():
            for rota in ("painel", "estado", "pendencias"):
                with self.subTest(painel=painel, rota=rota):
                    self.assertEqual(chamar(rota, f"/api/{rota}?id={painel}")[0], 401)
                    self.assertEqual(chamar(rota, f"/api/{rota}?id={painel}", token="invalido")[0], 401)

    def test_paineis_mistos_entregam_a_versao_certa_para_cada_usuario(self):
        """Com dados de verdade: quem tem "Dados financeiros" recebe o dinheiro; quem nao tem recebe a pagina limpa. Em todos os periodos do filtro."""
        import paineis_de_mentira as pm
        import portal_nuvem as pn
        original = pn.pagina_para_abrir
        try:
            for painel, gerar in pm.PAGINAS.items():
                for de, ate in pm.PERIODOS:
                    pn.pagina_para_abrir = lambda p, periodo, g=gerar, d=de, a=ate: (g(d, a), False, 0)
                    consulta = f"&de={de}&ate={ate}" if de else ""
                    for token, esperado_sem_fin in (("tok-admin", False), ("tok-todos-fin", False), ("tok-todos-sem-fin", True), ("tok-fin-texto", True)):
                        with self.subTest(painel=painel, periodo=(de, ate), usuario=token):
                            status, html = chamar("painel", f"/api/painel?id={painel}{consulta}", token=token)
                            self.assertEqual(status, 200)
                            self.assertIn(f"window.PAINEL_SEM_FIN={'true' if esperado_sem_fin else 'false'}", html)
                            tem_dinheiro = bool(re.search(r'"(receita|ticket|valor|custo_unit)"', html))
                            self.assertEqual(tem_dinheiro, not esperado_sem_fin, "o JSON da pagina tem (ou nao tem) o dinheiro que deveria")
        finally:
            pn.pagina_para_abrir = original

    def test_pendencias_esconde_avisos_de_dinheiro_de_quem_nao_tem_dados_financeiros(self):
        def aviso(i, painel, chave, sensivel):
            return {"id": i, "painel": painel, "chave": chave, "titulo": chave, "status": "justificado", "recorrencias": 0, "reaberturas": 0, "sensivel": sensivel,
                    "justificativa": "x" * 20, "justificado_por": "a", "justificado_em": None, "resolvido_em": None}
        BANCO.avisos[:] = [aviso(1, "atendimento", "|ate_espera", False), aviso(2, "atendimento", "|ate_x", True), aviso(3, "cesta", "|cesta_menor_fat", True)]
        try:
            def chaves(token, painel):
                status, corpo = chamar("pendencias", f"/api/pendencias?id={painel}", token=token)
                self.assertEqual(status, 200, corpo)
                return [a["chave"] for a in json.loads(corpo)["avisos"]]
            self.assertEqual(chaves("tok-todos-fin", "atendimento"), ["|ate_espera", "|ate_x"])
            self.assertEqual(chaves("tok-admin", "cesta"), ["|cesta_menor_fat"])
            self.assertEqual(chaves("tok-todos-sem-fin", "atendimento"), ["|ate_espera"])   # o de dinheiro nao aparece
            self.assertEqual(chaves("tok-todos-sem-fin", "cesta"), [])
        finally:
            BANCO.avisos[:] = []

    def test_painel_misto_sem_dados_financeiros_vem_sem_os_valores(self):
        import json as _json
        import re as _re
        dados = {"meses": {"2026-10": {"kpis": {"n": 3, "receita": 1234.5, "ticket": 411.5},
                                      "profissionais": [{"nome": "A", "n": 2, "receita": 1000.0}],
                                      "alertas": [{"titulo": "Receita concentrada em um profissional: R$ 12.000", "nivel": "atencao", "id": "ate_receita_x"},
                                                  {"titulo": "Atendimentos sem Check-In", "nivel": "atencao", "id": "ate_sem_checkin"}]}}}
        html = ("<!doctype html><html><head><title>t</title></head><body><script id=\"dados\" type=\"application/json\">"
                + _json.dumps(dados) + "</script></body></html>")
        import portal_nuvem as pn
        original = pn.pagina_para_abrir
        pn.pagina_para_abrir = lambda painel, periodo: (html, False, 0)
        try:
            _, com = chamar("painel", "/api/painel?id=atendimento", token="tok-admin")
            _, sem = chamar("painel", "/api/painel?id=atendimento", token="tok-sem-fin")
        finally:
            pn.pagina_para_abrir = original
        self.assertIn("window.PAINEL_SEM_FIN=false", com)
        self.assertIn("1234.5", com)
        self.assertIn("window.PAINEL_SEM_FIN=true", sem)
        for proibido in ("1234.5", "411.5", "1000.0", "receita", "ticket", "Receita concentrada", "12.000"):
            self.assertNotIn(proibido, sem)
        corpo = _json.loads(_re.search(r'<script id="dados" type="application/json">(.*?)</script>', sem, _re.S).group(1))
        self.assertEqual([a["id"] for a in corpo["meses"]["2026-10"]["alertas"]], ["ate_sem_checkin"])   # o alerta de dinheiro sumiu, o outro ficou
        self.assertEqual(corpo["meses"]["2026-10"]["kpis"], {"n": 3})

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

        # 6. dado novo deixa a pagina guardada VENCIDA (a versao tem resolucao de 1 s): ela sai na hora, sem recalcular, marcada como vencida;
        #    quem a refaz e a renovacao pedida pela tela do site
        time.sleep(1.1)
        arm.gravar_mes("despesas", pn.codigo_do("despesas").k.ler_definicao(RAIZ / "Despesas")["relatorios"][0]["aba"], "2026-10", [], exclusivo=False)
        arm._CACHE_VERSAO.clear()
        pn.montar_pagina = lambda *a, **k: chamadas.append(a) or original(*a, **k)
        try:
            _, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(len(chamadas), 1, "abrir o painel nao pode esperar a conta")
            self.assertIn("window.PAINEL_VENCIDO=true", html)
            status, corpo = chamar("renovar", "/api/renovar?id=despesas", token="tok-viewer", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(corpo)["ok"])
            self.assertEqual(len(chamadas), 2)
            _, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(len(chamadas), 2)
            self.assertIn("window.PAINEL_VENCIDO=false", html)
            self.assertEqual(BANCO.renovacoes, {}, "a trava ficou presa")
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
            self.assertEqual(chamadas, [], "o layout antigo sai na hora; refazer e com a renovacao")
            self.assertIn("layout:antigo", html)
            self.assertIn("window.PAINEL_VENCIDO=true", html)
            chamar("renovar", "/api/renovar?id=despesas", token="tok-viewer", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
            self.assertEqual(len(chamadas), 1)
            self.assertIn(pn._marca_layout(), BANCO.paginas[("despesas", "padrao")]["html"])
            _, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertIn(pn._marca_layout(), html)
            self.assertIn("window.PAINEL_VENCIDO=false", html)
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

    def test_pendencias_lista_os_avisos_do_painel(self):
        BANCO.avisos[:] = [
            {"id": 1, "painel": "despesas", "chave": "2026-10|des_zero", "titulo": "Despesas zeradas", "status": "justificado", "recorrencias": 0, "reaberturas": 0,
             "justificativa": "Corrigido no Klingo", "justificado_por": "ana@csi.local", "justificado_em": "2026-10-14T10:00:00+00:00", "resolvido_em": None},
            {"id": 2, "painel": "despesas", "chave": "|des_repetidas", "titulo": "Repetidas", "status": "aberto", "recorrencias": 2, "reaberturas": 0,
             "justificativa": None, "justificado_por": None, "justificado_em": None, "resolvido_em": None},
            {"id": 3, "painel": "despesas", "chave": "|des_sem_fornecedor", "titulo": "Sem fornecedor", "status": "aberto", "recorrencias": 0, "reaberturas": 0,
             "justificativa": None, "justificado_por": None, "justificado_em": None, "resolvido_em": None},
            {"id": 4, "painel": "faturamento", "chave": "|fat_glosa", "titulo": "Glosa", "status": "justificado", "recorrencias": 0, "reaberturas": 0,
             "justificativa": "x", "justificado_por": "y", "justificado_em": None, "resolvido_em": None},
        ]
        try:
            status, corpo = chamar("pendencias", "/api/pendencias?id=despesas", token="tok-viewer")
            self.assertEqual(status, 200)
            avisos = json.loads(corpo)["avisos"]
            # so o que ja tem desfecho ou historico (um aviso aberto e nunca visto de novo nao precisa de nota na pagina) e so do painel pedido
            self.assertEqual([a["chave"] for a in avisos], ["2026-10|des_zero", "|des_repetidas"])
            self.assertEqual(avisos[0]["justificativa"], "Corrigido no Klingo")
            self.assertEqual(chamar("pendencias", "/api/pendencias?id=despesas", token="tok-sem")[0], 403)
            # fechar nao e mais feito aqui: precisa da justificativa da aba Avisos
            r = chamar("pendencias", "/api/pendencias?id=despesas&acao=resolver", token="tok-viewer", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={"chave": "a|b"})
            self.assertEqual(r[0], 405)
            self.assertIn("Avisos", json.loads(r[1])["mensagem"])
        finally:
            BANCO.avisos[:] = []

    def _refazer_pagina(self, falha=None):
        """Atualiza o painel, apaga a pagina pronta e abre de novo (e ai que os avisos sao conferidos). Devolve (status, html, chamadas de avisos.sincronizar)."""
        import avisos
        chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        BANCO.paginas.clear()
        chamadas, original = [], avisos.sincronizar

        def espiao(painel, payload, versao):
            chamadas.append((painel, payload, versao))
            if falha:
                raise falha
        avisos.sincronizar = espiao
        try:
            status, html = chamar("painel", "/api/painel?id=despesas", token="tok-admin")
        finally:
            avisos.sincronizar = original
        return status, html, chamadas

    def test_pagina_do_painel_registra_os_avisos(self):
        status, _, chamadas = self._refazer_pagina()
        self.assertEqual(status, 200)
        self.assertEqual(len(chamadas), 1)
        painel, payload, versao = chamadas[0]
        self.assertEqual(painel, "despesas")
        self.assertIn("meses", payload)
        self.assertGreater(versao, 0)                          # versao dos dados que gerou a lista

    def test_pagina_abre_mesmo_se_os_avisos_falharem(self):
        status, html, chamadas = self._refazer_pagina(falha=RuntimeError("banco fora do ar"))
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(status, 200)
        self.assertIn("window.PAINEL_NUVEM=true", html)

    def test_sincronizacao_chega_ao_banco(self):
        import armazenamento as arm
        BANCO.avisos_sync.clear()
        r = arm.sincronizar_avisos("despesas", ["", "2026-10"], 123, [{"chave": "|x", "tipo": "x"}])
        self.assertEqual(BANCO.avisos_sync, [("despesas", ["", "2026-10"], 123, [{"chave": "|x", "tipo": "x"}])])
        self.assertEqual(r["total"], 1)
        BANCO.falhar_avisos = True
        try:
            with self.assertRaises(arm.ErroArmazenamento):
                arm.sincronizar_avisos("despesas", [""], 1, [])
        finally:
            BANCO.falhar_avisos = False

    def test_periodo_escolhido_nao_mexe_nos_avisos(self):
        import avisos
        chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        BANCO.paginas.clear()
        chamadas, original = [], avisos.sincronizar
        avisos.sincronizar = lambda *a: chamadas.append(a)
        try:
            status, _ = chamar("painel", "/api/painel?id=despesas&de=2026-08&ate=2026-09", token="tok-admin")   # varios meses = pagina de periodo, nao a de hoje
        finally:
            avisos.sincronizar = original
        self.assertEqual(status, 200)
        self.assertEqual(chamadas, [])


class RenovacaoTest(unittest.TestCase):
    """Abrir o painel nunca espera a atualizacao: a pagina velha sai na hora e a tela do site pede a renovacao (com trava e andamento)."""

    def setUp(self):
        BANCO.renovacoes.clear()
        chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        BANCO.renovacoes.clear()

    def renovar(self, token="tok-viewer", painel="despesas"):
        status, corpo = chamar("renovar", f"/api/renovar?id={painel}", token=token, metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
        return status, json.loads(corpo)

    def test_renovar_exige_cabecalho_login_e_permissao(self):
        self.assertEqual(chamar("renovar", "/api/renovar?id=despesas", token="tok-viewer", metodo="POST", corpo={})[0], 403)           # sem X-Painel
        self.assertEqual(chamar("renovar", "/api/renovar?id=despesas", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 401)  # sem login
        self.assertEqual(chamar("renovar", "/api/renovar?id=despesas", token="tok-sem", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 403)
        self.assertEqual(chamar("renovar", "/api/renovar?id=faturamento", token="tok-viewer", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})[0], 403)

    def test_pagina_em_dia_nao_esta_vencida(self):
        _, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
        self.assertIn("window.PAINEL_VENCIDO=false", html)

    def test_dia_novo_deixa_a_pagina_vencida_e_a_renovacao_refaz(self):
        import portal_nuvem as pn
        BANCO.paginas[("despesas", "padrao")]["dia"] = "2020-01-01"
        chamadas = []
        original = pn.montar_pagina
        pn.montar_pagina = lambda *a, **k: chamadas.append(a) or original(*a, **k)
        try:
            _, html = chamar("painel", "/api/painel?id=despesas", token="tok-viewer")
            self.assertEqual(chamadas, [])
            self.assertIn("window.PAINEL_VENCIDO=true", html)
            self.assertRegex(html, r"window.PAINEL_PREVISTO_S=\d+;")
            status, r = self.renovar()
            self.assertEqual((status, r["ok"], r["ocupado"], r["falhou"]), (200, True, False, False))
            self.assertEqual(len(chamadas), 1)
            self.assertEqual(BANCO.paginas[("despesas", "padrao")]["dia"], pn.date.today().isoformat())
            self.assertEqual(BANCO.atualizacoes[-1]["status"], "pagina")   # fica no historico, sem contar como copia dos dados
            self.assertEqual(BANCO.renovacoes, {})
        finally:
            pn.montar_pagina = original

    def test_outra_renovacao_em_andamento_devolve_o_andamento_e_nao_roda_junto(self):
        import portal_nuvem as pn
        BANCO.paginas[("despesas", "padrao")]["dia"] = "2020-01-01"
        agora = pn.datetime.now(pn.timezone.utc)
        BANCO.renovacoes["despesas"] = {"painel": "despesas", "usuario": "ana@csi.local", "previsto_s": 45,
                                        "iniciado_em": (agora - timedelta(seconds=10)).isoformat(timespec="seconds")}
        chamadas = []
        original = pn.montar_pagina
        pn.montar_pagina = lambda *a, **k: chamadas.append(a) or original(*a, **k)
        try:
            _, r = self.renovar()
            self.assertTrue(r["ok"] and r["ocupado"], r)
            self.assertEqual(r["andamento"]["previsto_s"], 45)
            self.assertGreaterEqual(r["andamento"]["decorrido_s"], 9)
            self.assertEqual(chamadas, [], "rodou junto com a outra")
            _, est = chamar("estado", "/api/estado?id=despesas", token="tok-viewer")
            est = json.loads(est)
            self.assertTrue(est["atualizando"])
            self.assertEqual(est["andamento"]["previsto_s"], 45)
            # o botao Atualizar agora do admin tambem respeita a trava e explica
            _, corpo = chamar("atualizar", "/api/atualizar?id=despesas", token="tok-admin", metodo="POST", cabecalhos={"X-Painel": "1"}, corpo={})
            resp = json.loads(corpo)
            self.assertTrue(resp["ok"] and resp["atualizou"] is False and "já está sendo atualizado" in resp["mensagem"], resp)
            self.assertIn("despesas", BANCO.renovacoes, "o botao nao pode soltar a trava dos outros")
        finally:
            pn.montar_pagina = original

    def test_trava_de_execucao_que_morreu_vence_sozinha(self):
        import portal_nuvem as pn
        BANCO.renovacoes["despesas"] = {"painel": "despesas", "usuario": "ana@csi.local", "previsto_s": 45,
                                        "iniciado_em": (pn.datetime.now(pn.timezone.utc) - timedelta(minutes=7)).isoformat(timespec="seconds")}
        _, est = chamar("estado", "/api/estado?id=despesas", token="tok-viewer")
        self.assertFalse(json.loads(est)["atualizando"])
        _, r = self.renovar()
        self.assertTrue(r["ok"] and not r["ocupado"], r)
        self.assertEqual(BANCO.renovacoes, {})

    def test_falha_ao_renovar_solta_a_trava(self):
        import portal_nuvem as pn
        BANCO.paginas[("despesas", "padrao")]["dia"] = "2020-01-01"
        original = pn.montar_pagina

        def quebra(*a, **k):
            raise RuntimeError("falhou de mentira")
        pn.montar_pagina = quebra
        try:
            _, r = self.renovar()
            self.assertFalse(r["ok"])
            self.assertEqual(BANCO.renovacoes, {})
        finally:
            pn.montar_pagina = original

    def test_login_em_paralelo_confere_o_token_no_supabase(self):
        """Token com cara de JWT: o perfil e buscado junto, mas so vale se o Supabase confirmar o token E o mesmo id."""
        def jwt(sub):
            corpo = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
            return f"cabecalho.{corpo}.assinatura"
        uid = BANCO.novo_usuario(jwt("uid-do-token-admin"), "ana2@csi.local", "viewer", {"despesas": True, "dados_financeiros": True})
        BANCO.usuarios[jwt("uid-do-token-admin")]["id"] = "uid-do-token-admin"   # o id do JWT bate com o do Supabase
        BANCO.perfis["uid-do-token-admin"] = BANCO.perfis[uid]
        status, _ = chamar("estado", "/api/estado?id=despesas", token=jwt("uid-do-token-admin"))
        self.assertEqual(status, 200)
        # JWT que diz ser outra pessoa (admin) mas o Supabase diz que o dono e um viewer sem permissao: vale o que o Supabase diz
        BANCO.novo_usuario(jwt("uid-1"), "bia2@csi.local", "viewer", {})
        self.assertEqual(chamar("estado", "/api/estado?id=despesas", token=jwt("uid-1"))[0], 403)
        self.assertEqual(chamar("estado", "/api/estado?id=despesas", token=jwt("qualquer"))[0], 401)


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
