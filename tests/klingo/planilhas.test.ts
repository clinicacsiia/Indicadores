import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import ExcelJS from "exceljs";
import { describe, expect, it } from "vitest";
import { lerCustos, lerPlanilhaMenu } from "@/klingo/planilhas";

async function planilha(nome: string, abas: Record<string, (string | number | Date | null)[][]>) {
  const wb = new ExcelJS.Workbook();
  for (const [aba, linhas] of Object.entries(abas)) { const ws = wb.addWorksheet(aba); linhas.forEach((l) => ws.addRow(l)); }
  const caminho = join(mkdtempSync(join(tmpdir(), "csi-")), nome);
  await wb.xlsx.writeFile(caminho);
  return caminho;
}

describe("importar planilhas do legado", () => {
  it("agrupa por 'Mês (filtro)', tira as colunas de controle e converte numeros/datas", async () => {
    const f = await planilha("Faturamento.xlsx", {
      "Receita Produzida": [
        ["Data", "Valor", "Operadora", "Mês (filtro)", "Atualizado em"],
        [new Date(Date.UTC(2026, 8, 30, 10, 5, 0)), "1.234,50", "UNIMED", "2026-09", "x"],
        [new Date(Date.UTC(2026, 9, 1)), 10, "GEAP", "2026-10", "x"],
      ],
    });
    const b = await lerPlanilhaMenu(f, "faturamento");
    expect(b.map((x) => [x.aba, x.mes])).toEqual([["Receita Produzida", "2026-09"], ["Receita Produzida", "2026-10"]]);
    expect(b[0].tabela.colunas).toEqual(["Data", "Valor", "Operadora"]);
    expect(b[0].tabela.linhas).toEqual([["2026-09-30 10:05:00", 1234.5, "UNIMED"]]);
    expect(b[1].tabela.linhas[0]).toEqual(["2026-10-01", 10, "GEAP"]);
  });
  it("relatório sem filtro de data vira um bloco só, no mês mais recente, e apaga os outros", async () => {
    const f = await planilha("Indicadores.xlsx", { Baixas: [["Baixa - Id", "Valor Bruto", "Mês (filtro)"], [1, 5, "2026-09"], [2, 7, "2026-10"]] });
    const b = await lerPlanilhaMenu(f, "indicadores");
    expect(b).toHaveLength(1);
    expect(b[0]).toMatchObject({ aba: "Baixas", mes: "2026-10", apagarOutros: true });
    expect(b[0].tabela.linhas).toHaveLength(2);
  });
  it("lê os custos digitados (coluna 'Custo informado')", async () => {
    const f = await planilha("Custos dos Itens.xlsx", { Custos: [
      ["Item", "Grupo", "Unidade no Klingo", "Embalagem", "Unidades por embalagem", "Custo no Klingo (R$ por unidade do estoque)", "Custo informado (R$ por unidade do estoque)", "Observação"],
      ["GRAMPO 26/6 (CX. C/ 5000)", "Papelaria", "CX", "caixa com 5.000 unidades", 5000, null, 18, "preço da caixa"]] });
    expect(await lerCustos(f)).toEqual([{ item: "GRAMPO 26/6 (CX. C/ 5000)", grupo: "Papelaria", unidade: "CX", embalagem: "caixa com 5.000 unidades", fator: 5000, custo_klingo: null, custo: 18, observacao: "preço da caixa" }]);
  });
});
