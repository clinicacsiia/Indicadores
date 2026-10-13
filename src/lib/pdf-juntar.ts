import { PDFDict, PDFDocument, PDFHexString, PDFName, PDFNumber, PDFRef } from "pdf-lib";

export interface ParteDoPdf { titulo: string; bytes: Uint8Array }

/** Junta os PDFs (um por painel) em um só, com um marcador (índice lateral) por painel. Equivale ao pypdf do legado. Roda no servidor e no navegador. */
export async function juntarPdfs(partes: ParteDoPdf[]): Promise<Uint8Array> {
  const saida = await PDFDocument.create();
  const marcas: { titulo: string; pagina: PDFRef }[] = [];
  for (const p of partes) {
    const doc = await PDFDocument.load(p.bytes);
    const paginas = await saida.copyPages(doc, doc.getPageIndices());
    paginas.forEach((pg, i) => { saida.addPage(pg); if (i === 0) marcas.push({ titulo: p.titulo, pagina: pg.ref }); });
  }
  if (marcas.length) {
    const ctx = saida.context;
    const raiz = ctx.nextRef();
    const refs = marcas.map(() => ctx.nextRef());
    marcas.forEach((m, i) => {
      const d = ctx.obj({ Title: PDFHexString.fromText(m.titulo), Parent: raiz, Dest: [m.pagina, PDFName.of("XYZ"), null, null, null] }) as PDFDict;
      if (i > 0) d.set(PDFName.of("Prev"), refs[i - 1]);
      if (i < marcas.length - 1) d.set(PDFName.of("Next"), refs[i + 1]);
      ctx.assign(refs[i], d);
    });
    ctx.assign(raiz, ctx.obj({ Type: "Outlines", First: refs[0], Last: refs[refs.length - 1], Count: PDFNumber.of(marcas.length) }));
    saida.catalog.set(PDFName.of("Outlines"), raiz);
    saida.catalog.set(PDFName.of("PageMode"), PDFName.of("UseOutlines"));
  }
  return saida.save();
}
