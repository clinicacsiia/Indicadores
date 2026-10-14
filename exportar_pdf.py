"""Exporta todos os paineis do portal (Metas, Faturamento, Financeiro...) para UM unico PDF.

Cada painel e aberto no Chrome ou no Edge instalado (sem janela; e o unico uso de navegador do portal), impresso em A4 paisagem e os PDFs sao
juntados em ordem do menu, com um marcador (indice lateral do leitor de PDF) para cada relatorio. Mostra o mes que o painel
abre por padrao (o mais recente) e os dados que ja estao na planilha: nao consulta o Klingo.
"""
import io
from datetime import datetime

from pypdf import PdfReader, PdfWriter

LARGURA_FOLHA_PX = 1123      # A4 paisagem a 96 dpi
ESCALA = 1.0                 # sem encolher: 12 pt no papel = 16 px na pagina. Tabela larga quebra linha nas celulas em vez de ser cortada
LARGURA_UTIL_PX = 1062       # A4 paisagem (297 mm) menos margens de 8 mm de cada lado, a 96 dpi
FONTE_MIN_PX = 16           # 12 pt (Times New Roman): menor letra permitida em qualquer parte do PDF

# Ajustes so para impressao, injetados em cada painel (os paineis em si nao mudam).
CSS_IMPRESSAO = """
@page { size: A4 landscape; }
html, body { background: #fff !important; }
* { font-family: "Times New Roman", Times, serif !important; }
html, body { overflow: visible !important; max-width: 100% !important; }
table { width: 100% !important; max-width: 100% !important; table-layout: auto !important; }
th, td { white-space: normal !important; overflow-wrap: anywhere !important; word-break: normal; min-width: 0 !important; max-width: none !important; }
.kpi, .alerta, .bloco, .barra, .donut, section, div { min-width: 0; }
img, svg, canvas { max-width: 100% !important; height: auto; }
header .acoes, .toolbar, .mes-pick, .periodo-pick, .filtros, .filtro, #btn-atualizar, .btn, .aviso, #tip, details.ajuda { display: none !important; }
.periodo-ativo { font-size: 15px !important; margin-top: 8px !important; }
.wrap { max-width: none !important; padding: 0 !important; width: 100% !important; }
.tab-wrap { overflow: visible !important; }
.kpi, .alerta, .barra, .bloco, tr { break-inside: avoid; }   /* secoes e cartoes grandes podem quebrar: senao sobra pagina em branco */
thead { display: table-header-group; }
h1, h2, h3 { break-after: avoid; }
* { animation: none !important; transition: none !important; }
"""


# Sobe toda letra menor que 12 pt para 12 pt (texto HTML e texto dentro dos graficos SVG, que encolhem junto com o desenho),
# esconde o que nao e visivel e devolve quantos elementos ainda passam da largura da folha (= conteudo que seria cortado).
JS_AJUSTAR = """
(minPx) => {
  const alvo = document.documentElement.clientWidth;
  for (const el of document.querySelectorAll('body *')) {
    const nome = el.tagName.toLowerCase();
    if (['script','style','link','meta','head','title','defs','path','rect','circle','line','polyline','polygon','g','svg'].includes(nome)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    let tem = false;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { tem = true; break; }
    if (!tem) continue;
    let px = parseFloat(cs.fontSize), fator = 1;
    if (el instanceof SVGElement) {
      const m = el.getScreenCTM ? el.getScreenCTM() : null;
      fator = m ? Math.abs(m.a) || 1 : 1;
    }
    if (px * fator < minPx - 0.01) el.style.setProperty('font-size', (minPx / fator) + 'px', 'important');
  }
  // rotulo de grafico que, ja com a letra maior, passou da borda direita (do desenho ou da folha): empurra para dentro
  for (const t of document.querySelectorAll('svg text')) {
    const svg = t.ownerSVGElement; if (!svg) continue;
    const limite = Math.min(svg.getBoundingClientRect().right, alvo) - 1;
    const r = t.getBoundingClientRect(); if (!r.width || r.right <= limite) continue;
    const m = t.getScreenCTM(); const fator = m ? Math.abs(m.a) || 1 : 1;
    t.setAttribute('transform', (t.getAttribute('transform') || '') + ' translate(' + (-(r.right - limite) / fator) + ',0)');
  }
  const passam = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width && r.right > alvo + 2 && getComputedStyle(el).display !== 'none') passam.push(el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''));
  }
  return [...new Set(passam)].slice(0, 8);
}
"""


def _rodape(titulo: str, nome: str, quando: str, periodo: str = "") -> str:
    texto_periodo = f" · Período: {periodo}" if periodo else ""
    return ('<div style="width:100%;padding:0 8mm;font:12pt \'Times New Roman\',Times,serif;color:#444;'
            'display:flex;justify-content:space-between;-webkit-print-color-adjust:exact">'
            f'<span>{titulo} · {nome}{texto_periodo} · gerado em {quando}</span>'
            '<span>Página <span class="pageNumber"></span> de <span class="totalPages"></span></span></div>')


def _abrir_chrome(p):
    erros = []
    for canal in ("chrome", "msedge", None):
        try:
            if canal:
                return p.chromium.launch(channel=canal, headless=True)
            else:
                return p.chromium.launch(headless=True)
        except Exception as e:
            erros.append(f"{canal or 'chromium'}: {str(e).splitlines()[0]}")
    raise RuntimeError("Não consegui abrir o Chrome (nem o Edge) para gerar o PDF. " + " | ".join(erros))


def plano_completo(modulos: list[dict]) -> list[tuple[dict, str]]:
    """Tudo o que o PDF 'todos os relatorios' leva: cada painel uma vez e, se tiver "visoes_pdf" (modulos.json), mais uma vez por visao
    (ex.: cada responsavel do Atendimento)."""
    plano = []
    for m in modulos:
        visoes = m.get("visoes_pdf") or []
        for visao in ([""] + list(visoes)) if visoes else [""]:
            plano.append((m, visao))
    return plano


def exportar(modulos: list[dict], base: str, token: str, titulo: str, cookie: str,
             itens: list[tuple[dict, str]] | None = None, de: str | None = None, ate: str | None = None) -> tuple[bytes, list[str]]:
    """Devolve (pdf, avisos). 'base' = http://127.0.0.1:porta ; 'token' = sessao interna do portal ; 'cookie' = nome do cookie.
    'itens' (opcional) = so estes paineis, como (modulo, visao); visao "" = painel inteiro (clinica toda). Sem 'itens', sai tudo (plano_completo).
    'de'/'ate' (opcionais, "AAAA-MM") = periodo do relatorio; sem eles cada painel abre no mes mais recente. O periodo que cada painel
    de fato mostrou ("de 01/09/2026 a 30/09/2026") e lido da propria pagina e escrito no rodape de todas as folhas.
    Um painel que falhar fica de fora e entra em 'avisos'; se todos falharem, levanta RuntimeError."""
    from playwright.sync_api import sync_playwright

    quando = datetime.now().strftime("%d/%m/%Y %H:%M")
    consulta = f"de={de}&ate={ate or de}" if de else ""
    plano = itens if itens is not None else plano_completo(modulos)
    pdfs: list[tuple[str, bytes]] = []
    avisos: list[str] = []
    with sync_playwright() as p:
        navegador = _abrir_chrome(p)
        try:
            ctx = navegador.new_context(color_scheme="light", viewport={"width": 1400, "height": 900}, locale="pt-BR")
            if token:
                ctx.add_cookies([{"name": cookie, "value": token, "url": base + "/"}])
            for m, visao in plano:
                visoes = m.get("visoes_pdf") or []   # painel com visoes (ex.: responsaveis do Atendimento): sempre diz qual abrir
                nome = m["nome"]
                pagina = ctx.new_page()
                try:
                    parametros = "&".join(x for x in ((f"visao={visao or 'todos'}" if visoes else ""), consulta) if x)
                    endereco = f"{base}/{m['id']}/" + (f"?{parametros}" if parametros else "")
                    resp = pagina.goto(endereco, wait_until="load", timeout=240_000)   # a Cesta pode levar mais de 1 min na primeira vez
                    if resp is None or resp.status >= 400:
                        raise RuntimeError((resp.text() if resp else "sem resposta")[:200])
                    pagina.wait_for_timeout(1000)   # os graficos sao desenhados por script logo depois do carregamento
                    periodo = pagina.evaluate("window.PERIODO_TXT || ''")   # "de 01/09/2026 a 30/09/2026", como o painel mostra no alto
                    if visao:
                        nome_visao = pagina.evaluate("window.NOME_VISAO || ''")
                        if not nome_visao:
                            raise RuntimeError(f"a visão “{visao}” não existe no painel (confira o responsaveis.json e o visoes_pdf do modulos.json)")
                        nome = f"{m['nome']} · {nome_visao}"
                    pagina.add_style_tag(content=CSS_IMPRESSAO)
                    pagina.evaluate("document.querySelectorAll('details.acord').forEach(d => { d.open = true; })")   # os "Detalhes" ficam recolhidos na tela, mas o PDF leva as tabelas
                    pagina.emulate_media(media="print", color_scheme="light")
                    pagina.set_viewport_size({"width": LARGURA_UTIL_PX, "height": 900})   # largura real da area impressa: o layout ja nasce no tamanho da folha
                    pagina.wait_for_timeout(300)
                    cortados = pagina.evaluate(JS_AJUSTAR, FONTE_MIN_PX)
                    if cortados:
                        avisos.append(f"{nome}: pode haver conteúdo passando da largura da folha ({', '.join(cortados)})")
                    pdfs.append((nome, pagina.pdf(
                        format="A4", landscape=True, print_background=True, scale=ESCALA, prefer_css_page_size=False,
                        margin={"top": "9mm", "bottom": "16mm", "left": "8mm", "right": "8mm"},
                        display_header_footer=True, header_template="<span></span>",
                        footer_template=_rodape(titulo, nome, quando, periodo))))
                except Exception as e:
                    avisos.append(f"{nome}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
                finally:
                    pagina.close()
        finally:
            navegador.close()
    if not pdfs:
        raise RuntimeError("Nenhum painel pôde ser exportado. " + " | ".join(avisos))

    saida = PdfWriter()
    for nome, dados in pdfs:
        saida.append(PdfReader(io.BytesIO(dados)), outline_item=nome)
    saida.add_metadata({"/Title": f"{titulo} - Relatórios" + (f" · {f'{de} a {ate}' if ate and ate != de else de}" if de else "") + f" ({quando})", "/Creator": "Indicadores CSI"})
    buf = io.BytesIO()
    saida.write(buf)
    return buf.getvalue(), avisos
