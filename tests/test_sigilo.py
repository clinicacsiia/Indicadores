"""Dados financeiros: o que um usuario SEM a permissao recebe dos paineis mistos (Atendimento, Cesta, Suprimentos).

Rodar:  python -m unittest discover -s tests -v
As paginas vem de dados inventados (paineis_de_mentira.py), em todos os periodos do filtro. Os testes de navegador abrem a pagina no Chromium (CHROMIUM=/caminho
ou /opt/pw-browsers/chromium); sem ele, sao pulados. SIGILO_RAPIDO=1 pula so a matriz grande de navegador (periodos, meses, pessoas) e deixa uma pagina por painel.
"""
import html as html_lib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
import guia_pendencias as gp  # noqa: E402
import paineis_de_mentira as pm  # noqa: E402
import sigilo  # noqa: E402

DADOS = re.compile(r'<script id="dados" type="application/json">(.*?)</script>', re.S)
REAIS_NAO_ZERO = sigilo.REAIS
PALAVRAS_DE_DINHEIRO = re.compile(r"ticket|receita(?! - Mensal)|R\$\s*(?!0)\d", re.I)   # "Espera e Receita - Mensal" e o nome de um relatorio do Klingo


def dados_da_pagina(html: str) -> dict:
    return json.loads(DADOS.search(html).group(1).replace("<\\/", "</"))


def com_dados(html: str, dados: dict) -> str:
    m = DADOS.search(html)
    return html[:m.start(1)] + json.dumps(dados, ensure_ascii=False).replace("</", "<\\/") + html[m.end(1):]


def chaves(no, achadas=None):
    achadas = set() if achadas is None else achadas
    if isinstance(no, dict):
        for k, v in no.items():
            achadas.add(k)
            chaves(v, achadas)
    elif isinstance(no, list):
        for v in no:
            chaves(v, achadas)
    return achadas


def textos(no):
    if isinstance(no, dict):
        for v in no.values():
            yield from textos(v)
    elif isinstance(no, list):
        for v in no:
            yield from textos(v)
    elif isinstance(no, str):
        yield no


def alertas(no, acc):
    if isinstance(no, dict):
        if "titulo" in no and "nivel" in no:
            acc.append(no)
        for v in no.values():
            alertas(v, acc)
    elif isinstance(no, list):
        for v in no:
            alertas(v, acc)
    return acc


def todas_as_paginas():
    return [(nome, de, ate, gerar(de, ate)) for nome, gerar in pm.PAGINAS.items() for de, ate in pm.PERIODOS]


# ---------------------------------------------------------------------------------------------------------------- o que sai do JSON
class PaginasSemDinheiroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paginas = todas_as_paginas()

    def test_as_paginas_de_mentira_tem_dinheiro_para_quem_pode_ver(self):
        # sem isto os testes abaixo passariam por uma pagina vazia
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                d = dados_da_pagina(html)
                self.assertTrue(d["meses"], "a pagina de mentira saiu sem meses")
                self.assertTrue(any(sigilo.DINHEIRO.search(c) for c in chaves(d)), "esperava campos de dinheiro na pagina completa")

    def test_a_lista_explicita_ja_cobre_tudo_o_que_parece_dinheiro(self):
        """Campo novo com cara de dinheiro (ou texto com R$) obriga a decidir: CHAVES/RAIZ (e esconder no modelo) ou MANTER. Em producao as camadas 2 e 3 pegam o resto."""
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                sobra = sigilo.suspeitos(nome, dados_da_pagina(html))
                self.assertFalse(sobra, f"{nome}: campos/textos que a lista explicita deixa passar: {sobra[:5]}")

    def test_nenhum_campo_de_dinheiro_sobra_no_json_entregue(self):
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                limpo = dados_da_pagina(sigilo.limpar_html(html, nome))
                sobrou = {c for c in chaves(limpo) if sigilo.DINHEIRO.search(c)} - sigilo.MANTER[nome]
                self.assertFalse(sobrou, f"campos de dinheiro que continuam no JSON de {nome}: {sorted(sobrou)}")

    def test_nenhum_valor_em_reais_sobra_nos_textos(self):
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                limpo = dados_da_pagina(sigilo.limpar_html(html, nome))
                achados = [t[:120] for t in textos(limpo) if REAIS_NAO_ZERO.search(t)]
                self.assertFalse(achados, f"textos com valor em R$ em {nome}: {achados[:3]}")

    def test_nenhum_numero_de_dinheiro_na_pagina_toda(self):
        # o que e entregue (HTML inteiro, nao so o JSON) nao pode ter os valores da pagina completa
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                completo = dados_da_pagina(html)
                valores = set()

                def coleta(no, dentro=False):
                    if isinstance(no, dict):
                        for k, v in no.items():
                            if k in sigilo.CHAVES[nome] or (nome in sigilo.RAIZ and k in sigilo.RAIZ[nome]):
                                if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) > 99:
                                    valores.add(repr(round(v, 2)))
                            coleta(v)
                    elif isinstance(no, list):
                        for v in no:
                            coleta(v)
                coleta(completo)
                self.assertTrue(valores, "o teste precisa de valores de dinheiro para procurar")
                entregue = sigilo.limpar_html(html, nome)
                # um numero igual pode existir por outro motivo (uma quantidade de 350 unidades): so vale como vazamento o que nao esta no JSON entregue como numero
                legitimos = set()

                def folhas(no):
                    if isinstance(no, dict):
                        for v in no.values():
                            folhas(v)
                    elif isinstance(no, list):
                        for v in no:
                            folhas(v)
                    elif isinstance(no, (int, float)) and not isinstance(no, bool):
                        legitimos.add(repr(round(no, 2)))
                        legitimos.add(repr(float(round(no, 2))))
                folhas(dados_da_pagina(entregue))
                vazou = [v for v in valores - legitimos if re.search(r"(?<![\d.])" + re.escape(v) + r"(?![\d])", entregue)]
                self.assertFalse(vazou, f"valores de dinheiro que continuam na pagina entregue de {nome}: {vazou[:5]}")

    def test_alertas_de_dinheiro_saem_e_os_demais_ficam(self):
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                antes = alertas(dados_da_pagina(html), [])
                depois = alertas(dados_da_pagina(sigilo.limpar_html(html, nome)), [])
                self.assertFalse([a["titulo"] for a in depois if gp.sensivel(nome, a)], "sobrou alerta sensivel")
                self.assertEqual(len(depois), len([a for a in antes if not gp.sensivel(nome, a)]), "saiu alerta que nao era de dinheiro")

    def test_o_que_nao_e_dinheiro_continua(self):
        # a limpeza nao pode levar junto o que nao e dinheiro (atendimentos, esperas, pedidos...)
        casos = {"atendimento": ("kpis", "n"), "cesta": ("kpi", "atend"), "suprimentos": ("sol", "solicitacoes")}
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                bloco, campo = casos[nome]
                inteiro, limpo = dados_da_pagina(html), dados_da_pagina(sigilo.limpar_html(html, nome))
                ym = inteiro["mes_padrao"]
                self.assertEqual(limpo["meses"][ym][bloco][campo], inteiro["meses"][ym][bloco][campo])
                self.assertEqual(set(limpo["meses"]), set(inteiro["meses"]), "a limpeza nao pode tirar meses")

    def test_atendimento_por_pessoa_tambem_e_limpo(self):
        # "por_visao" repete o painel inteiro para cada responsavel
        for nome, de, ate, html in self.paginas:
            if nome != "atendimento":
                continue
            with self.subTest(periodo=(de, ate)):
                limpo = dados_da_pagina(sigilo.limpar_html(html, nome))
                self.assertTrue(limpo["por_visao"])
                self.assertFalse({c for c in chaves(limpo["por_visao"]) if re.search(r"receita|ticket", c)})

    def test_pagina_inteira_e_diferente_da_limpa_so_no_dinheiro(self):
        # a limpeza e determinista e nao mexe na pagina de quem pode ver (admin recebe o que esta guardado)
        for nome, de, ate, html in self.paginas:
            with self.subTest(painel=nome, periodo=(de, ate)):
                self.assertEqual(sigilo.limpar_html(html, nome), sigilo.limpar_html(html, nome))
                self.assertNotEqual(sigilo.limpar_html(html, nome), html)

    def test_falha_fechada_sem_dados_na_pagina(self):
        with self.assertRaises(RuntimeError):
            sigilo.limpar_html("<html>sem dados</html>", "atendimento")

    def test_camadas_de_seguranca_pegam_o_que_a_lista_nao_previu(self):
        """Um campo novo com cara de dinheiro e um texto com R$ saem mesmo sem estarem em CHAVES (producao)."""
        dados = {"meses": {"2026-10": {"kpis": {"n": 3, "lucro_bruto": 900.5, "margem_pct": 12.0, "faturado_convenio": 5000, "total_glosa": 10,
                                               "nota": "Foram R$ 1.234,56 neste mes e R$ 0,00 no outro", "quantidade": 7}}}}
        limpo = sigilo.limpar_json("cesta", dados)
        k = limpo["meses"]["2026-10"]["kpis"]
        self.assertEqual(set(k), {"n", "nota", "quantidade"})
        self.assertEqual(k["nota"], "Foram R$ ••• neste mes e R$ 0,00 no outro")
        self.assertEqual(len(sigilo.suspeitos("cesta", dados)), 5)   # o teste enxerga os 4 campos e o texto
        # o que esta em MANTER nao e removido
        self.assertEqual(sigilo.limpar_json("suprimentos", {"x": {"compras": [1], "com_saldo": 2, "saldo": 3}}), {"x": {"compras": [1], "com_saldo": 2}})

    def test_mascara_de_reais(self):
        casos = {"R$ 0,00": "R$ 0,00", "R$&nbsp;0,00": "R$&nbsp;0,00", "R$ 0": "R$ 0", "R$ 12,50": "R$ •••", "R$&nbsp;1.234,56": "R$ •••",
                 "R$ 0,5": "R$ •••", "R$ 100": "R$ •••", "sem dinheiro": "sem dinheiro"}
        for entrada, saida in casos.items():
            self.assertEqual(sigilo.REAIS.sub(sigilo.MASCARA, entrada), saida, entrada)


# ---------------------------------------------------------------------------------------------------------------- avisos
class AlertasSensiveisTest(unittest.TestCase):
    def test_painel_so_de_dinheiro_tem_todo_alerta_sensivel(self):
        for painel in ("faturamento", "financeiro", "despesas", "indicadores"):
            self.assertTrue(gp.sensivel(painel, {"id": "qualquer", "titulo": "Sem dinheiro nenhum", "texto": "x", "nivel": "atencao"}), painel)

    def test_painel_misto_so_esconde_o_que_fala_de_dinheiro(self):
        def a(i, titulo, texto="", **extra):
            return {"id": i, "titulo": titulo, "texto": texto, "nivel": "atencao", **extra}
        self.assertTrue(gp.sensivel("cesta", a("cesta_menor_fat", "A receita da Cesta é menor que a do Faturamento")))
        self.assertTrue(gp.sensivel("atendimento", a("ate_x", "Algo", "A receita caiu <b>R$ 1.200,00</b>")))
        self.assertTrue(gp.sensivel("suprimentos", a("sup_sem_custo", "Custo registrado nas movimentações")))
        self.assertTrue(gp.sensivel("atendimento", a("ate_y", "Algo", itens={"colunas": ["Data", "Valor"], "linhas": [], "total": 1})))
        self.assertTrue(gp.sensivel("atendimento", a("ate_z", "Algo", itens={"colunas": ["Data", "Nome"], "linhas": [["01/10", "R$ 150,00"]], "total": 1})))   # R$ numa celula
        self.assertFalse(gp.sensivel("atendimento", a("ate_espera", "Espera acima do aceitável", "Mediana de 36 min")))
        self.assertFalse(gp.sensivel("suprimentos", a("sup_sem_setor", "Pedidos sem centro de custo")))   # centro de custo = setor
        self.assertFalse(gp.sensivel("atendimento", a("ate_valor_zero", "Atendimentos com valor R$ 0,00")))   # problema de cadastro
        self.assertFalse(gp.sensivel("metas", a("x", "Receita")))   # as Metas tem tela propria, sem dinheiro

    def test_todo_alerta_com_regra_de_painel_so_de_dinheiro_e_sensivel(self):
        # as regras de guia_pendencias.py: nenhum alerta de Faturamento/Financeiro/Despesas/Indicadores pode escapar
        for painel, rx, ident, *_ in gp._COMPILADAS:
            if gp.financeiro_do_painel(painel) == "total":
                self.assertTrue(gp.sensivel(painel, {"id": ident, "titulo": "x", "nivel": "atencao"}), f"{painel}/{ident}")

    def test_alertas_de_dinheiro_conhecidos_dos_paineis_mistos(self):
        # as regras que falam de dinheiro no titulo ou no guia nao podem ficar de fora da lista
        for painel, rx, ident, *_ in gp._COMPILADAS:
            if gp.financeiro_do_painel(painel) != "parcial":
                continue
            titulo_de_exemplo = rx.pattern.lstrip("^").replace("\\", "")
            if re.search(r"receita|ticket|custo registrado|valor do estoque|faturamento", titulo_de_exemplo, re.I) and ident != "sup_sem_setor":
                self.assertTrue(gp.sensivel(painel, {"id": ident, "titulo": titulo_de_exemplo, "nivel": "atencao"}), f"{painel}/{ident}: {titulo_de_exemplo}")


# ---------------------------------------------------------------------------------------------------------------- regras do modulos.json
class ModoFinanceiroTest(unittest.TestCase):
    def test_painel_sem_o_campo_conta_como_so_dinheiro(self):
        import portal_nuvem as pn
        original = pn.modulos
        try:
            pn.modulos = lambda: {"novo": {"id": "novo", "tipo": "relatorios"}, "x": {"id": "x", "financeiro": "nenhum"}, "m": {"id": "m", "financeiro": "parcial"}}
            self.assertEqual(pn.modo_financeiro("novo"), "total")       # esqueceram de preencher: bloqueia
            self.assertIsNone(pn.modo_financeiro("x"))                  # "nenhum" diz que nao tem dinheiro
            self.assertEqual(pn.modo_financeiro("m"), "parcial")
            self.assertIsNone(pn.modo_financeiro("desconhecido"))
        finally:
            pn.modulos = original

    def test_modulos_json_declara_o_modo_de_todos_os_paineis(self):
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        for m in cfg["modulos"]:
            if m["tipo"] == "relatorios":
                self.assertIn(m.get("financeiro"), ("total", "parcial", "nenhum"), f"{m['id']}: falta \"financeiro\" no modulos.json")

    def test_todo_painel_misto_tem_regra_e_pagina_de_teste(self):
        """Painel novo marcado como misto precisa de regra em sigilo.py e de uma pagina COM DADOS em paineis_de_mentira.py: sem isso a protecao nao e testada."""
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        for m in cfg["modulos"]:
            if m.get("financeiro") == "parcial":
                self.assertTrue(sigilo.CHAVES.get(m["id"]), f"{m['id']}: sem campos de dinheiro em sigilo.CHAVES")
                self.assertIn(m["id"], sigilo.MANTER, f"{m['id']}: falta em sigilo.MANTER (pode ser vazio)")
                self.assertIn(m["id"], pm.PAGINAS, f"{m['id']}: falta pagina de teste em tests/paineis_de_mentira.py")
                self.assertIn(m["id"], sigilo.COLUNAS_DE_DINHEIRO, f"{m['id']}: falta em sigilo.COLUNAS_DE_DINHEIRO")
        for nome in pm.PAGINAS:
            self.assertEqual(next(m for m in cfg["modulos"] if m["id"] == nome).get("financeiro"), "parcial", f"{nome} tem pagina de teste mas nao e misto")

    def test_colunas_novas_de_dinheiro_nos_relatorios_dos_paineis_mistos(self):
        """Relatorio novo (ou coluna nova) com cara de dinheiro num painel misto: o teste falha ate alguem decidir o que fazer com ela."""
        cfg = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig"))
        for m in cfg["modulos"]:
            if m.get("financeiro") != "parcial":
                continue
            conhecidas = sigilo.COLUNAS_DE_DINHEIRO[m["id"]]
            rels = json.loads((RAIZ / m["pasta"] / "relatorios.json").read_text(encoding="utf-8"))["relatorios"]
            for rel in rels:
                colunas = {*rel.get("chave", []), *rel.get("numeros", [])}
                novas = {c for c in colunas if re.search(r"valor|pre[cç]o|custo|ticket|receita|total|pago|fatur|glosa|saldo", c, re.I)} - conhecidas - {"Movimentação - Quantidade Consolidada"}
                self.assertFalse(novas, f"{m['id']} / relatorio {rel['id']}: coluna(s) com cara de dinheiro nao declaradas em sigilo.COLUNAS_DE_DINHEIRO: {sorted(novas)}")
            for c in conhecidas:   # e nao pode sobrar nome que nao existe mais
                self.assertTrue(any(c in {*r.get("chave", []), *r.get("numeros", [])} for r in rels), f"{m['id']}: {c!r} nao esta mais em relatorios.json")

    def test_modulos_json_e_lido_igual_pelo_python_e_pelo_site(self):
        import portal_nuvem as pn
        for painel in pn.modulos():
            self.assertEqual(pn.modo_financeiro(painel), gp.financeiro_do_painel(painel), painel)


# ---------------------------------------------------------------------------------------------------------------- navegador
def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


@unittest.skipUnless(_chromium(), "sem Chromium")
class NoNavegadorTest(unittest.TestCase):
    """Abre a pagina no Chromium como o usuario abriria: sem erro de JavaScript e sem nenhum valor em R$ no que aparece na tela."""

    @classmethod
    def setUpClass(cls):
        import portal_nuvem as pn
        cls.pn = pn
        cls.pasta = Path(tempfile.mkdtemp())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.porta = s.getsockname()[1]
        cls.srv = subprocess.Popen([sys.executable, "-m", "http.server", str(cls.porta), "-d", str(cls.pasta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def abrir(self, html: str, query: str = "", orcamento: int = 8000):
        type(self).n += 1
        arq = f"p{self.n}.html"
        (self.pasta / arq).write_text(html, encoding="utf-8")
        out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", f"--virtual-time-budget={orcamento}", "--enable-logging=stderr", "--v=0",
                              "--dump-dom", f"http://127.0.0.1:{self.porta}/{arq}{query}"], capture_output=True, text=True, timeout=300)
        erros = [l for l in out.stderr.splitlines() if "CONSOLE" in l and "rror" in l]
        return out.stdout, erros

    def conteudo(self, dom: str) -> str:
        m = re.search(r'<main id="conteudo">(.*?)</main>', dom, re.S)
        self.assertIsNotNone(m, "a pagina nao montou o conteudo")
        return m.group(1)

    def confere_sem_dinheiro(self, dom: str, erros: list[str]):
        self.assertFalse(erros, erros[:2])
        corpo = self.conteudo(dom)
        self.assertGreater(len(corpo), 2000, "a pagina saiu vazia")
        texto = re.sub(r"<[^>]+>", " ", corpo)
        self.assertFalse(REAIS_NAO_ZERO.search(corpo), re.findall(r".{40}R\$.{20}", corpo)[:3])
        self.assertIsNone(re.search(r"NaN|undefined|\[object", texto), re.findall(r".{30}(?:NaN|undefined|\[object).{20}", texto)[:3])
        self.assertFalse(PALAVRAS_DE_DINHEIRO.search(texto), PALAVRAS_DE_DINHEIRO.findall(texto)[:3])

    def marcar(self, html: str, admin: bool) -> str:
        return self.pn.com_marcas(html, "x", admin=admin, sem_financeiro=not admin) if False else self.pn.com_marcas(html, self._painel, admin=admin, sem_financeiro=not admin)

    # ---- cada painel x cada periodo do filtro x com e sem a permissao
    @unittest.skipIf(os.environ.get("SIGILO_RAPIDO"), "SIGILO_RAPIDO")
    def test_todos_os_periodos(self):
        for nome, gerar in pm.PAGINAS.items():
            self._painel = nome
            for de, ate in pm.PERIODOS:
                html = gerar(de, ate)
                with self.subTest(painel=nome, periodo=(de, ate)):
                    completo, erros = self.abrir(self.marcar(html, True))
                    self.assertFalse(erros, erros[:2])
                    self.assertRegex(self.conteudo(completo), r"R\$(?:&nbsp;|\s)*[1-9]")   # com permissao o dinheiro aparece (senao o resto nao prova nada)
                    dom, erros = self.abrir(self.marcar(html, False))
                    self.confere_sem_dinheiro(dom, erros)

    # ---- um painel por vez, mes a mes (a tela tem o seletor de mes)
    @unittest.skipIf(os.environ.get("SIGILO_RAPIDO"), "SIGILO_RAPIDO")
    def test_cada_mes_do_seletor(self):
        for nome, gerar in pm.PAGINAS.items():
            self._painel = nome
            html = gerar()
            dados = dados_da_pagina(html)
            for ym in sorted(m for m in dados["meses"] if re.fullmatch(r"\d{4}-\d\d", m)):
                with self.subTest(painel=nome, mes=ym):
                    dom, erros = self.abrir(self.marcar(com_dados(html, {**dados, "mes_padrao": ym}), False))
                    self.confere_sem_dinheiro(dom, erros)

    # ---- Atendimento: "Todos" e a visao de cada responsavel (Juliana, Carla, Luzia)
    @unittest.skipIf(os.environ.get("SIGILO_RAPIDO"), "SIGILO_RAPIDO")
    def test_atendimento_cada_responsavel(self):
        self._painel = "atendimento"
        html = pm.pagina_atendimento()
        visoes = [v["id"] for v in dados_da_pagina(html)["visoes"]]
        self.assertTrue(visoes)
        for v in visoes:
            with self.subTest(visao=v):
                dom, erros = self.abrir(self.marcar(html, False), query=f"?visao={v}")
                self.confere_sem_dinheiro(dom, erros)

    # ---- uma pagina por painel (modo rapido e base de tudo)
    def test_uma_pagina_por_painel(self):
        for nome, gerar in pm.PAGINAS.items():
            self._painel = nome
            html = gerar()
            with self.subTest(painel=nome):
                completo, erros = self.abrir(self.marcar(html, True))
                self.assertFalse(erros, erros[:2])
                self.assertRegex(self.conteudo(completo), r"R\$(?:&nbsp;|\s)*[1-9]")
                dom, erros = self.abrir(self.marcar(html, False))
                self.confere_sem_dinheiro(dom, erros)

    # ---- Inicio: a lista de graficos que a pessoa escolhe e cada grafico sozinho (?aba=&item=)
    def test_lista_de_graficos_e_cada_grafico_do_inicio(self):
        host = """<!doctype html><html><head><meta charset="utf-8"></head><body><pre id="saida"></pre><iframe id="f" style="width:900px;height:700px"></iframe><script>
        const esperar = ms => new Promise(r => setTimeout(r, ms)); let ultimo = null;
        addEventListener('message', e => { if (e.data && e.data.tipo === 'itens') ultimo = e.data; });
        async function abrir(url) { ultimo = null; await new Promise(r => { f.onload = r; f.src = url; }); await esperar(300); }
        (async () => {
          const q = new URLSearchParams(location.search), alvo = q.get('p'), saida = { catalogo: [], itens: [] };
          await abrir(alvo); saida.catalogo = ultimo ? ultimo.itens : null;
          for (const it of (saida.catalogo || [])) {
            await abrir(alvo + '?aba=' + encodeURIComponent(it.aba) + '&item=' + encodeURIComponent(it.chave));
            const d = f.contentDocument, c = d.getElementById('conteudo');
            const visivel = [...d.body.querySelectorAll('*')].filter(x => x.offsetParent !== null && x.children.length === 0).map(x => x.textContent).join(' ');
            saida.itens.push({ aba: it.aba, titulo: it.titulo, ausente: !!d.querySelector('.item-ausente'), html: c ? c.innerHTML : '', texto: visivel });
          }
          document.getElementById('saida').textContent = JSON.stringify(saida);
        })();
        </script></body></html>"""
        for nome, gerar in pm.PAGINAS.items():
            self._painel = nome
            html = gerar()
            catalogos = {}
            for admin in (True, False):
                type(self).n += 1
                alvo = f"alvo{self.n}.html"
                (self.pasta / alvo).write_text(self.marcar(html, admin), encoding="utf-8")
                type(self).n += 1
                arq = f"host{self.n}.html"
                (self.pasta / arq).write_text(host, encoding="utf-8")
                out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=300000", "--enable-logging=stderr", "--v=0",
                                      "--dump-dom", f"http://127.0.0.1:{self.porta}/{arq}?p={alvo}"], capture_output=True, text=True, timeout=600)
                m = re.search(r'<pre id="saida">(.*?)</pre>', out.stdout, re.S)
                self.assertIsNotNone(m, f"{nome}: o teste de navegador nao terminou")
                saida = json.loads(html_lib.unescape(m.group(1)))
                self.assertTrue(saida["catalogo"], f"{nome} ({'admin' if admin else 'sem permissao'}): a pagina nao respondeu a lista de graficos")
                catalogos[admin] = saida
            titulos_admin = {i["titulo"] for i in catalogos[True]["catalogo"]}
            titulos_sem = {i["titulo"] for i in catalogos[False]["catalogo"]}
            with self.subTest(painel=nome, passo="a lista de quem nao ve dinheiro e menor e nao cita dinheiro"):
                self.assertLess(len(titulos_sem), len(titulos_admin), "sem a permissao a lista de graficos deveria ter menos itens")
                citam = [t for t in titulos_sem if re.search(r"receita|ticket|faturam|R\$ ?[1-9]|custo de|valor em|potencial", t, re.I)]
                self.assertFalse(citam, f"titulos de dinheiro na lista de {nome}: {citam}")
            for item in catalogos[False]["itens"]:
                with self.subTest(painel=nome, grafico=item["titulo"]):
                    self.assertFalse(item["ausente"], "o grafico listado nao aparece sozinho")
                    self.assertFalse(REAIS_NAO_ZERO.search(item["html"]), "valor em R$ dentro de um grafico escolhido")
                    self.assertFalse(re.search(r"NaN|undefined", item["texto"]), item["texto"][:80])
            for item in catalogos[True]["itens"]:
                with self.subTest(painel=nome, admin_grafico=item["titulo"]):
                    self.assertFalse(item["ausente"])


if __name__ == "__main__":
    unittest.main()
