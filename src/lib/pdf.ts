import puppeteer, { type Browser, type HTTPRequest } from "puppeteer-core";

/**
 * Renderiza o HTML de um painel em PDF: A4 paisagem, margens de 8 mm, fonte mínima de 12 pt, acordeões abertos e rodapé em todas as folhas
 * (título + nome do painel + data/hora + período). O HTML já vem pronto do cálculo em Python; o navegador não acessa nenhum outro endereço
 * (as chamadas /api do painel são respondidas aqui, sem sessão e sem dados).
 */
const ORIGEM_FALSA = "https://painel.local";

const CSS_PDF = `
@page { size: A4 landscape; margin: 8mm; }
@media print {
  html { font-size: 12pt !important; }
  body *:not(svg):not(svg *) { font-size: max(12pt, 1em) !important; }
  svg text { font-size: 12px !important; }
  .acoes, .btn, #btn-atualizar, .mes-pick, #visao-pick { display: none !important; }
  details.acord > .corpo { display: block !important; }
  .tier, .tier-h { break-inside: auto; }
  section, .kpi, .alerta, .card, table, .rank .lin { break-inside: avoid; }
  .wrap { max-width: none !important; padding: 0 !important; }
}`;

export async function abrirNavegador(): Promise<Browser> {
  const local = process.env.CHROMIUM_PATH;   // desenvolvimento/teste: um Chromium instalado
  if (local) return puppeteer.launch({ executablePath: local, headless: true, args: ["--no-sandbox"] });
  const { default: chromium } = await import("@sparticuz/chromium");
  return puppeteer.launch({ args: chromium.args, executablePath: await chromium.executablePath(), headless: true });
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

export interface OpcoesPdf { titulo: string; painel: string; periodo: string; quando: string }

export async function htmlParaPdf(browser: Browser, html: string, query: string, op: OpcoesPdf): Promise<Uint8Array> {
  const page = await browser.newPage();
  try {
    await page.setViewport({ width: 1280, height: 900 });
    await page.setRequestInterception(true);
    page.on("request", (r: HTTPRequest) => {
      const u = new URL(r.url());
      if (u.origin !== ORIGEM_FALSA) return void r.abort();
      if (u.pathname === "/painel") return void r.respond({ status: 200, contentType: "text/html; charset=utf-8", body: html });
      if (u.pathname.startsWith("/api/pendencias")) return void r.respond({ status: 200, contentType: "application/json", body: '{"itens":[]}' });
      return void r.respond({ status: 204 });
    });
    await page.goto(`${ORIGEM_FALSA}/painel${query ? `?${query}` : ""}`, { waitUntil: "load", timeout: 60_000 });
    await page.addStyleTag({ content: CSS_PDF });
    await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { (d as HTMLDetailsElement).open = true; }));
    await page.emulateMediaType("print");
    const rodape = `<div style="font-size:8pt;width:100%;padding:0 8mm;color:#555;display:flex;justify-content:space-between;font-family:Segoe UI,Arial,sans-serif">
      <span>Clínica CSI · ${esc(op.painel)} · ${esc(op.quando)} · ${esc(op.periodo)}</span><span><span class="pageNumber"></span>/<span class="totalPages"></span></span></div>`;
    const pdf = await page.pdf({
      format: "A4", landscape: true, printBackground: true, preferCSSPageSize: true,
      margin: { top: "8mm", right: "8mm", bottom: "12mm", left: "8mm" },
      displayHeaderFooter: true, headerTemplate: "<span></span>", footerTemplate: rodape,
    });
    return pdf;
  } finally {
    await page.close();
  }
}
