import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { PDFDocument, PDFName } from "pdf-lib";
import { abrirNavegador, htmlParaPdf } from "@/lib/pdf";
import { juntarPdfs } from "@/lib/pdf-juntar";

// Integração: precisa de um Chromium (CHROMIUM_PATH) e de uma página de painel (PDF_HTML), por exemplo gerada por painel_py/rodar_local.py.
const html = process.env.PDF_HTML && existsSync(process.env.PDF_HTML) ? readFileSync(process.env.PDF_HTML, "utf-8") : null;
const pronto = !!process.env.CHROMIUM_PATH && !!html;

describe.runIf(pronto)("PDF do painel", () => {
  it("A4 paisagem, várias folhas, junta com um marcador por painel", async () => {
    const nav = await abrirNavegador();
    try {
      const op = { titulo: "Clínica CSI", painel: "Faturamento", periodo: "Período: de 01/10/2026 a 13/10/2026", quando: "13/10/2026 15:04" };
      const a = await htmlParaPdf(nav, html!, "de=2026-10&ate=2026-10", op);
      const b = await htmlParaPdf(nav, html!, "de=2026-10&ate=2026-10", { ...op, painel: "Metas" });
      const da = await PDFDocument.load(a);
      expect(da.getPageCount()).toBeGreaterThan(1);
      const { width, height } = da.getPage(0).getSize();
      expect(Math.round(width)).toBe(842); expect(Math.round(height)).toBe(595);   // A4 paisagem
      const junto = await PDFDocument.load(await juntarPdfs([{ titulo: "Faturamento", bytes: a }, { titulo: "Metas", bytes: b }]));
      expect(junto.getPageCount()).toBe(da.getPageCount() + (await PDFDocument.load(b)).getPageCount());
      expect(junto.catalog.get(PDFName.of("Outlines"))).toBeDefined();
    } finally { await nav.close(); }
  }, 120_000);
});

describe("juntarPdfs (sem navegador)", () => {
  it("cria o índice com um marcador por parte", async () => {
    const um = async (n: number) => { const d = await PDFDocument.create(); for (let i = 0; i < n; i++) d.addPage([842, 595]); return d.save(); };
    const doc = await PDFDocument.load(await juntarPdfs([{ titulo: "A", bytes: await um(2) }, { titulo: "B", bytes: await um(3) }]));
    expect(doc.getPageCount()).toBe(5);
    expect(doc.catalog.get(PDFName.of("Outlines"))).toBeDefined();
  });
});
