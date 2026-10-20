"""Aba Planilha e bloco Comparar do painel de Despesas (Despesas/dashboard_modelo.html), com dados inventados, no Chromium.

Monta uma página só com o pedaço "PLANILHA + COMPARAR" do modelo (o resto do painel precisa dos relatórios do Klingo) e o painel_base.js/css de verdade,
clica nos botões e confere o que a tela desenhou. Rodar:  python -m unittest tests.test_comparar_despesas -v
"""
import html as html_lib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "Despesas"))
sys.path.insert(0, str(RAIZ / "Acompanhamento de META"))
import planilha_despesas as pl  # noqa: E402


def _chromium():
    return os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)


CENARIO = r"""
const saida = {};
const ok = (nome, cond) => { saida[nome] = !!cond; };
try {
  render();
  ok('matriz_com_meses_descendo', !!document.querySelector('#plan-corpo table.plan-lin'));
  const mes1 = document.querySelector('#plan-corpo table.plan-lin tbody tr td').textContent;
  ok('mais_recente_primeiro', mes1.startsWith('Outubro/2026'));
  ok('comparar_comeca_em_linhas', document.querySelectorAll('#cmp-saida svg.cmp-svg polyline').length > 0);
  document.querySelector('[data-cmp-visao="comp"]').click();
  const svg = document.querySelector('#cmp-saida svg.cmp-svg');
  ok('composicao_vira_empilhada', /barras empilhadas/.test(document.querySelector('#cmp-saida .cmp-tit').textContent) && svg.querySelectorAll('rect[stroke]').length > 20);
  document.querySelector('[data-cmp-visao="seis"]').click();
  ok('poucos_meses_viram_barras_agrupadas', /barras agrupadas/.test(document.querySelector('#cmp-saida .cmp-tit').textContent) && document.querySelectorAll('#cmp-saida svg.cmp-svg path').length > 10);
  ok('seis_meses', CMP.ate - CMP.de + 1 === 6);
  const sel = document.querySelector('[data-cmp="medida"]'); sel.value = 'var'; sel.dispatchEvent(new Event('change', { bubbles: true }));
  ok('variacao_nao_tem_primeiro_mes', valoresMedida(PS.S.T, 0, PS.n - 1, 'var')[0] === null && valoresMedida(PS.S.T, 0, PS.n - 1, 'var')[PS.n - 1] === null);
  document.querySelector('[data-cmp-visao="exec"]').click();
  ok('total_igual_a_soma_dos_grupos', Math.abs(PS.S.T.total - PS.grupos.reduce((s, g) => s + PS.S[g].total, 0)) < 0.05);
  const antes = CMP.sel.length; adicionar(PS.itens[0]); ok('adicionar_item', CMP.sel.length === antes + 1);
  for (let i = 0; i < 20; i++) adicionar(PS.itens[i]);
  ok('limite_de_8', CMP.sel.length === 8 && !!CMP.aviso);
  definirSel(['T', 'G1']); CMP.grafico = 'empilhada'; CMP.medida = 'valor';
  ok('nao_empilha_total_com_grupo', graficoEfetivo().g === 'agrupada' || graficoEfetivo().g === 'linha');
  document.querySelector('[data-plan-orient="colunas"]').click();
  ok('meses_nas_colunas', !!document.querySelector('#plan-corpo table.plan-col'));
  planGrafico('G1');
  ok('clique_abre_grafico', document.getElementById('modal-painel').open && !!document.querySelector('#modal-painel svg.cmp-svg'));
  ok('nomes', bonito('PIS E COFINS - UNIFICADO') === 'PIS e COFINS - Unificado' && bonito('FOLHA SALARIAL') === 'Folha Salarial' && bonito('1ª PARCELA DÉCIMO TERCEIRO') === '1ª Parcela Décimo Terceiro');
  document.querySelector('#modal-painel [data-cmp-add]').click();
  ok('adicionar_pelo_modal_fecha_o_modal', !document.getElementById('modal-painel').open && CMP.sel.includes('G1'));
  ok('sem_nan', !/NaN|undefined/.test(document.getElementById('conteudo').textContent));
} catch (e) { saida.erro = String(e && e.stack || e); }
document.getElementById('saida').textContent = JSON.stringify(saida);
"""


def _pagina(tmp: Path) -> Path:
    base = pl._base_do_arquivo()
    random.seed(3)
    linhas, n = [], 1
    for ym in ("2026-09", "2026-10"):
        for cat in list(base["de_para"])[:40]:
            linhas.append({"Despesa": cat, "_ym": ym, "Bruto": round(random.uniform(500, 90000), 2), "Fornecedor": "F", "ID": n})
            n += 1
    matriz = pl.montar_matriz(pd.DataFrame(linhas), base, "2026-09", "2026-10")
    dados = {"planilha": {"matriz": matriz, "fornecedores": {"ok": False, "motivo": "teste"}}, "hoje": "2026-10-20"}
    modelo = (RAIZ / "Despesas/dashboard_modelo.html").read_text(encoding="utf-8")
    secao = modelo[modelo.index("// ====================== PLANILHA"):modelo.index("function planilhaFornecedores()")]
    estilo = re.search(r"<style>\n__CSS__\n(.*?)</style>", modelo, re.S).group(1)
    css = (RAIZ / "painel_base.css").read_text(encoding="utf-8")
    js = (RAIZ / "painel_base.js").read_text(encoding="utf-8").replace("</", "<\\/")
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>{css}\n{estilo}</style></head><body><div class="wrap"><main id="conteudo"></main></div><pre id="saida"></pre>
<script id="dados" type="application/json">{json.dumps(dados)}</script><script>{js}</script>
<script>
const D = JSON.parse($('dados').textContent);
const curto = (rotulo, ym) => `${{rotulo.split('/')[0].slice(0, 3)}}/${{ym.slice(2, 4)}}`;
const estreito = () => false;
const VAZIO = '—';
{secao}
function render() {{ $('conteudo').innerHTML = tier('Planilha', 'x', planilhaMatriz()) + tier('Comparar', 'y', comparar()); }}
{CENARIO}
</script></body></html>"""
    arq = tmp / "comparar.html"
    arq.write_text(pagina, encoding="utf-8")
    return arq


@unittest.skipUnless(_chromium(), "sem Chromium")
class CompararDespesasTest(unittest.TestCase):
    def test_planilha_e_comparar_no_navegador(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq = _pagina(Path(tmp))
            out = subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=8000", "--enable-logging=stderr", "--v=0", "--dump-dom", arq.as_uri()],
                                 capture_output=True, text=True, timeout=180)
        erros = [linha for linha in out.stderr.splitlines() if "CONSOLE" in linha and "rror" in linha]
        self.assertFalse(erros, erros[:2])
        saida = json.loads(html_lib.unescape(re.search(r'<pre id="saida">(.*?)</pre>', out.stdout, re.S).group(1)))
        self.assertNotIn("erro", saida, saida.get("erro"))
        falhas = [k for k, v in saida.items() if v is not True]
        self.assertFalse(falhas, falhas)


if __name__ == "__main__":
    unittest.main()
