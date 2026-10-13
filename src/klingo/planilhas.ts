/**
 * Leitura das planilhas do legado (Excel era só armazenamento) para carregar a história no site: uma planilha por menu, uma aba por relatório,
 * com as colunas do Klingo + "Mês (filtro)" + "Atualizado em". Devolve os blocos (aba × mês) prontos para gravar.
 */
import ExcelJS from "exceljs";
import { DEFINICOES, type MenuId } from "./config";
import type { Celula, Relatorio } from "./tipos";
import { paraData, paraNumero, type Tabela } from "./transformar";

export const COL_MES = "Mês (filtro)";
export const COL_EM = "Atualizado em";

export interface BlocoLido { aba: string; mes: string; tabela: Tabela; apagarOutros: boolean }

const p2 = (n: number) => String(n).padStart(2, "0");
function dataExcel(d: Date): string {
  const dia = `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}`;
  const h = d.getUTCHours(), m = d.getUTCMinutes(), s = d.getUTCSeconds();
  return h || m || s ? `${dia} ${p2(h)}:${p2(m)}:${p2(s)}` : dia;   // o Excel guarda a data sem fuso: lemos em UTC para não deslocar
}

function celula(v: ExcelJS.CellValue): Celula {
  if (v === null || v === undefined) return null;
  if (v instanceof Date) return dataExcel(v);
  if (typeof v === "number" || typeof v === "boolean") return v;
  if (typeof v === "string") return v.trim() === "" ? null : v;
  if (typeof v === "object") {
    if ("result" in v) return celula((v as { result: ExcelJS.CellValue }).result);
    if ("text" in v) return String((v as { text: unknown }).text);
    if ("richText" in v) return (v as { richText: { text: string }[] }).richText.map((t) => t.text).join("");
  }
  return String(v);
}

function lerAba(ws: ExcelJS.Worksheet): { cab: string[]; linhas: Celula[][] } {
  const cab: string[] = [];
  ws.getRow(1).eachCell({ includeEmpty: false }, (c, i) => { cab[i - 1] = String(c.value ?? "").trim(); });
  const linhas: Celula[][] = [];
  ws.eachRow({ includeEmpty: false }, (row, n) => {
    if (n === 1) return;
    const l = cab.map((_, i) => celula(row.getCell(i + 1).value));
    if (l.some((c) => c !== null)) linhas.push(l);
  });
  return { cab, linhas };
}

/** Aplica numeros/datas do relatorios.json (a planilha pode ter números como texto e datas como texto). */
function tiparLinhas(cab: string[], linhas: Celula[][], r: Pick<Relatorio, "numeros" | "datas">): Celula[][] {
  const num = new Set(r.numeros ?? []), dat = new Set(Object.keys(r.datas ?? {}));
  return linhas.map((l) => l.map((v, i) => {
    if (v === null) return null;
    if (num.has(cab[i])) return typeof v === "number" ? v : paraNumero(v);
    if (dat.has(cab[i])) return paraData(v as string);
    return v;
  }));
}

export async function lerPlanilhaMenu(caminho: string, menu: MenuId): Promise<BlocoLido[]> {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.readFile(caminho);
  const blocos: BlocoLido[] = [];
  for (const r of DEFINICOES[menu].relatorios) {
    const ws = wb.getWorksheet(r.aba);
    if (!ws) continue;
    const { cab, linhas } = lerAba(ws);
    const iMes = cab.indexOf(menu === "metas" ? "Mês" : COL_MES);
    const manter = cab.map((c, i) => (c === COL_MES || c === COL_EM || c === "" ? -1 : i)).filter((i) => i >= 0);
    const colunas = manter.map((i) => cab[i]);
    const tipadas = tiparLinhas(cab, linhas, r);
    const porMes = new Map<string, Celula[][]>();
    for (const l of tipadas) {
      let mes = iMes >= 0 ? String(l[iMes] ?? "") : "";
      if (!/^\d{4}-\d{2}$/.test(mes)) { const d = paraData(l[cab.indexOf(Object.keys(r.datas ?? {})[0])] as string); mes = d ? d.slice(0, 7) : ""; }
      if (!mes) continue;
      porMes.set(mes, [...(porMes.get(mes) ?? []), manter.map((i) => l[i])]);
    }
    if (r.sem_periodo) {   // baixa inteiro e substitui a aba: um bloco só, no mês mais recente
      const mes = [...porMes.keys()].sort().at(-1);
      if (mes) blocos.push({ aba: r.aba, mes, tabela: { colunas, linhas: [...porMes.values()].flat(), avisos: [] }, apagarOutros: true });
      continue;
    }
    for (const [mes, ls] of porMes) blocos.push({ aba: r.aba, mes, tabela: { colunas, linhas: ls, avisos: [] }, apagarOutros: false });
  }
  return blocos;
}

export interface CustoLido { item: string; grupo: string | null; unidade: string | null; embalagem: string | null; fator: number | null; custo_klingo: number | null; custo: number | null; observacao: string | null }

/** "Custos dos Itens.xlsx": o admin digitava o custo na coluna G ("Custo informado"). */
export async function lerCustos(caminho: string): Promise<CustoLido[]> {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.readFile(caminho);
  const ws = wb.getWorksheet("Custos");
  if (!ws) return [];
  const { cab, linhas } = lerAba(ws);
  const col = (n: string) => cab.findIndex((c) => c.startsWith(n));
  const g = (l: Celula[], n: string) => { const i = col(n); return i >= 0 ? l[i] : null; };
  const txt = (v: Celula) => (v === null ? null : String(v));
  const numero = (v: Celula) => (v === null ? null : paraNumero(v));
  return linhas.filter((l) => g(l, "Item")).map((l) => ({
    item: String(g(l, "Item")), grupo: txt(g(l, "Grupo")), unidade: txt(g(l, "Unidade")), embalagem: txt(g(l, "Embalagem")),
    fator: numero(g(l, "Unidades por")), custo_klingo: numero(g(l, "Custo no Klingo")), custo: numero(g(l, "Custo informado")), observacao: txt(g(l, "Observação")),
  }));
}
