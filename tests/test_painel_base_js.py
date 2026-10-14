"""painel_base.js e o que todos os 7 paineis usam (tabela, kpi, acordeao, fin(), data-fin, lista de graficos do Inicio). Roda no Chromium; sem ele, e pulado.

Alem disso confere que o JavaScript de cada modelo (dashboard_modelo.html) e sintaticamente valido, com `node --check`.
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


def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


PAGINA = """<!doctype html><html><head><meta charset="utf-8"><script>%(marca)s</script><style>%(css)s</style></head><body><div class="wrap">
<header class="page-head"><h1>Titulo</h1></header><section class="toolbar"></section><div id="aviso" hidden></div><main id="conteudo"></main>
<details class="ajuda"><summary>Ajuda</summary><ul><li id="ajuda-fin" data-fin>so com dinheiro</li><li id="ajuda-normal">sempre</li></ul></details></div>
<script>%(base)s</script><script>%(corpo)s</script></body></html>"""


@unittest.skipUnless(_chromium(), "sem Chromium")
class PainelBaseJsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pasta = Path(tempfile.mkdtemp())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.porta = s.getsockname()[1]
        cls.srv = subprocess.Popen([sys.executable, "-m", "http.server", str(cls.porta), "-d", str(cls.pasta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        cls.base = (RAIZ / "painel_base.js").read_text(encoding="utf-8").replace("</", "<\\/")
        cls.css = (RAIZ / "painel_base.css").read_text(encoding="utf-8")
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait()
        shutil.rmtree(cls.pasta, ignore_errors=True)

    def rodar(self, corpo: str, sem_fin: bool, query: str = "", nome: str = "alvo") -> dict:
        """Monta uma pagina com o painel_base.js de verdade e o `corpo` (JS), abre no Chromium e devolve o objeto `saida` que o corpo preencheu."""
        type(self).n += 1
        marca = f"window.PAINEL_SEM_FIN={'true' if sem_fin else 'false'};window.PAINEL_ID='teste';"
        arq = f"{nome}{self.n}.html"
        (self.pasta / arq).write_text(PAGINA % {"marca": marca, "css": self.css, "base": self.base,
                                               "corpo": "const saida = {};\n" + corpo + "\nsetTimeout(() => { const pre = document.createElement('pre'); pre.id = 'saida'; pre.textContent = JSON.stringify(saida); document.body.appendChild(pre); }, 200);"},
                                      encoding="utf-8")
        out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=5000", "--enable-logging=stderr", "--v=0", "--dump-dom",
                              f"http://127.0.0.1:{self.porta}/{arq}{query}"], capture_output=True, text=True, timeout=120)
        erros = [l for l in out.stderr.splitlines() if "CONSOLE" in l and "rror" in l]
        self.assertFalse(erros, erros[:2])
        m = re.search(r'<pre id="saida">(.*?)</pre>', out.stdout, re.S)
        self.assertIsNotNone(m, out.stdout[-300:])
        return json.loads(html_lib.unescape(m.group(1)))

    def test_tabela_kpi_acordeao_sem_a_permissao_e_com_ela(self):
        corpo = """
        const cols = [{ t: 'Nome', txt: 1 }, { t: 'Qtd', n: 1 }, { t: 'Receita', n: 1, fin: 1 }, { t: 'Ticket', n: 1, fin: 1 }, { t: 'Fim' }];
        const dados = [['A', '1', 'R$ 10', 'R$ 5', 'x'], ['B', '2', 'R$ 20', 'R$ 6', 'y']];
        const rod = ['Total', '3', 'R$ 30', 'R$ 11', ''];
        saida.tabela = tabela(cols, dados, rod);
        saida.semRodape = tabela(cols.slice(0, 2), [['A', '1']]);
        saida.kpiFin = kpi('Receita', 'R$ 9', { fin: 1 });
        saida.kpiNormal = kpi('Atendimentos', '9', { sub: 'x' });
        saida.acordeaoFin = acordeao('Receita', '<p>R$ 1</p>', { fin: 1 });
        saida.acordeaoNormal = acordeao('Pedidos', '<p>9</p>', { dica: '2 itens' });
        saida.fin = fin('dinheiro'); saida.SEM_FIN = SEM_FIN;
        """
        com = self.rodar(corpo, sem_fin=False)
        sem = self.rodar(corpo, sem_fin=True)
        # quem pode ver: tudo como sempre
        self.assertFalse(com["SEM_FIN"])
        self.assertEqual(com["fin"], "dinheiro")
        self.assertEqual(len(re.findall(r"<th[ >]", com["tabela"])), 5)
        self.assertEqual(len(re.findall(r"<td[ >]", com["tabela"])), 15)   # 2 linhas x 5 + rodape (5)
        self.assertIn("R$ 30", com["tabela"])
        self.assertIn("Receita", com["kpiFin"])
        self.assertIn("<details", com["acordeaoFin"])
        # quem nao pode: some a coluna inteira (cabecalho, linhas e rodape) e o cartao e a sanfona de dinheiro
        self.assertTrue(sem["SEM_FIN"])
        self.assertEqual(sem["fin"], "")
        self.assertEqual(len(re.findall(r"<th[ >]", sem["tabela"])), 3)
        self.assertEqual(len(re.findall(r"<td[ >]", sem["tabela"])), 9)
        self.assertNotIn("R$", sem["tabela"])
        self.assertNotIn("Receita", sem["tabela"])
        self.assertIn("Fim", sem["tabela"])
        self.assertEqual(sem["kpiFin"], "")
        self.assertEqual(sem["acordeaoFin"], "")
        # o que nao e de dinheiro e igual para os dois
        for chave in ("semRodape", "kpiNormal", "acordeaoNormal"):
            self.assertEqual(com[chave], sem[chave], chave)
            self.assertNotEqual(com[chave], "")

    def test_elementos_data_fin_saem_para_quem_nao_pode(self):
        corpo = """
        $('conteudo').innerHTML = '<div class="tier"><div class="tier-h"><b>Resumo</b></div><section><h2>Normal</h2><p id="n">ok</p></section><section data-fin id="sf"><h2>Dinheiro</h2></section></div>';
        setTimeout(() => { saida.ajudaFin = !!document.getElementById('ajuda-fin'); saida.ajudaNormal = !!document.getElementById('ajuda-normal');
          saida.modeloFin = !!document.getElementById('sf'); saida.modeloNormal = !!document.getElementById('n'); }, 50);
        """
        com, sem = self.rodar(corpo, sem_fin=False), self.rodar(corpo, sem_fin=True)
        self.assertEqual([com[k] for k in ("ajudaFin", "ajudaNormal", "modeloFin", "modeloNormal")], [True, True, True, True])   # quem pode ver: tudo
        self.assertEqual([sem[k] for k in ("ajudaFin", "ajudaNormal", "modeloFin", "modeloNormal")], [False, True, False, True])   # some o que ja vinha no HTML e o que o modelo escreveu

    def test_lista_de_graficos_e_um_grafico_so(self):
        montar = """
        const g = () => barras([{ rotulo: 'A', valor: 3, texto: '3' }, { rotulo: 'B', valor: 5, texto: '5' }], '', '30%');
        $('conteudo').innerHTML =
          tier('Resumo', 'x', '<div class="kpis">' + kpi('Atendimentos', '9', {}) + '</div>' + `<section><h2>Ritmo dos dias em Outubro/2026</h2><p class="nota">n</p>${g()}</section>`) +
          tier('Análise', 'y', `<section><div><h2>Do produzido à fatura</h2>${g()}</div></section>` +
            `<section><div class="grid2"><div><h2>Faturas em aberto, por vencimento</h2>${g()}</div><div><h2>Faturas a enviar</h2>${g()}</div></div></section>` +
            `<section><h2>Os 12 exames que mais faturam</h2>${g()}<h2>Segundo solto</h2><p>texto do segundo</p></section>` +
            `<section><h2>Dup</h2></section><section><h2>Dup</h2><p>segunda</p></section>`) +
          tier('Detalhes', 'z', '<section>' + acordeao('Procedimentos', '<p>TABELA</p>', { dica: '5 itens' }) + acordeao('Outra', '<h2>interno</h2><p>OUTRA</p>') + '</section>');
        """
        # a lista (mensagem "itens" para o site, que carrega a pagina num quadro)
        host = """<!doctype html><html><head><meta charset="utf-8"></head><body><pre id="saida"></pre><iframe id="f" style="width:800px;height:600px"></iframe><script>
        const esperar = ms => new Promise(r => setTimeout(r, ms)); let ultimo = null;
        addEventListener('message', e => { if (e.data && e.data.tipo === 'itens') ultimo = e.data; });
        async function abrir(url) { ultimo = null; await new Promise(r => { f.onload = r; f.src = url; }); await esperar(300); }
        (async () => {
          const alvo = new URLSearchParams(location.search).get('p'), s = { lista: null, itens: {} };
          await abrir(alvo); s.lista = ultimo && ultimo.itens;
          const pedir = async (aba, item) => { await abrir(alvo + '?aba=' + encodeURIComponent(aba) + '&item=' + encodeURIComponent(item));
            const d = f.contentDocument; return [...d.body.querySelectorAll('h2,p,summary,.kpi,.barras,.item-ausente')].filter(x => x.offsetParent !== null).map(x => x.tagName + ':' + x.textContent.slice(0, 24)); };
          s.itens.ritmo = await pedir('Resumo', 'ritmo dos dias em');
          s.itens.funil = await pedir('Análise', 'do produzido a fatura');
          s.itens.irmao = await pedir('Análise', 'faturas a enviar');
          s.itens.tabela = await pedir('Detalhes', 'procedimentos');
          s.itens.solto = await pedir('Análise', 'segundo solto');
          s.itens.kpis = await pedir('Resumo', 'numeros principais');
          s.itens.nenhum = await pedir('Resumo', 'nao existe');
          document.getElementById('saida').textContent = JSON.stringify(s);
        })();
        </script></body></html>"""
        type(self).n += 1
        alvo = f"lista{self.n}.html"
        (self.pasta / alvo).write_text(PAGINA % {"marca": "window.PAINEL_ID='teste';", "css": self.css, "base": self.base, "corpo": montar}, encoding="utf-8")
        (self.pasta / f"host{self.n}.html").write_text(host, encoding="utf-8")
        out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=30000", "--dump-dom", f"http://127.0.0.1:{self.porta}/host{self.n}.html?p={alvo}"],
                             capture_output=True, text=True, timeout=180)
        saida = json.loads(html_lib.unescape(re.search(r'<pre id="saida">(.*?)</pre>', out.stdout, re.S).group(1)))
        lista = [(i["aba"], i["titulo"]) for i in saida["lista"]]
        self.assertEqual(lista, [("Resumo", "Números principais"), ("Resumo", "Ritmo dos dias em Outubro/2026"), ("Análise", "Do produzido à fatura"),
                                 ("Análise", "Faturas em aberto, por vencimento"), ("Análise", "Faturas a enviar"), ("Análise", "Os 12 exames que mais faturam"),
                                 ("Análise", "Segundo solto"), ("Análise", "Dup"), ("Detalhes", "Procedimentos"), ("Detalhes", "Outra")])
        # a chave ignora mes/ano e numeros: o favorito continua valendo quando o mes muda
        chaves = {i["titulo"]: i["chave"] for i in saida["lista"]}
        self.assertEqual(chaves["Ritmo dos dias em Outubro/2026"], "ritmo dos dias em")
        self.assertEqual(chaves["Os 12 exames que mais faturam"], "os # exames que mais faturam")
        it = saida["itens"]
        self.assertEqual(it["ritmo"], ["P:n", "DIV:A3B5"])                  # so o bloco (o titulo fica a cargo do cartao do site)
        self.assertEqual(it["irmao"], ["DIV:A3B5"])                         # um dos dois lado a lado, sem o outro
        self.assertEqual(it["tabela"], ["P:TABELA"])                        # sanfona aberta, so o corpo
        self.assertEqual(it["solto"], ["P:texto do segundo"])
        self.assertTrue(it["kpis"] and it["kpis"][0].startswith("DIV") or it["kpis"][0].startswith(".kpi") or "Atendimentos" in " ".join(it["kpis"]))
        self.assertEqual(len(it["nenhum"]), 1)                              # bloco que nao existe: aviso, nao a pagina toda
        self.assertTrue(it["nenhum"][0].startswith("P:Este bloco"))

    def test_javascript_dos_modelos_e_valido(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("sem Node")
        base = (RAIZ / "painel_base.js").read_text(encoding="utf-8")
        for modelo in sorted(RAIZ.glob("*/dashboard_modelo.html")):
            with self.subTest(modelo=modelo.parent.name):
                texto = modelo.read_text(encoding="utf-8")
                scripts = re.findall(r"<script>(.*?)</script>", texto, re.S)
                corpo = next(s for s in scripts if "const D = JSON.parse" in s)
                pasta = Path(tempfile.mkdtemp())
                try:
                    (pasta / "m.mjs").write_text(base + "\n" + corpo, encoding="utf-8")
                    r = subprocess.run([node, "--check", str(pasta / "m.mjs")], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr[:400])
                finally:
                    shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
