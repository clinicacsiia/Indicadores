import { RespostaInvalida } from "./erros";
import type { Celula, Relatorio, RespostaValida } from "./tipos";

/**
 * Número que vem como 1, "1", "1234.5" ou "1.234,56". Com vírgula, o formato é brasileiro (ponto = milhar); sem vírgula, o ponto é decimal
 * (é como o JSON do Klingo escreve números quando o campo vem como texto). Vazio ou não numérico = null.
 */
export function paraNumero(v: Celula): number | null {
  if (v === null || typeof v === "boolean") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  let t = v.trim().replace(/^R\$\s*/i, "").replace(/\s/g, "");
  if (!t || t === "-") return null;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

const p2 = (n: number) => String(n).padStart(2, "0");

/**
 * Datas vêm como texto: "2026-10-07 08:13:26", "2026-10-07T08:13:26", "07/10/2026" ou "07/10/2026 08:13". Devolve "AAAA-MM-DD" (sem hora)
 * ou "AAAA-MM-DD HH:MM:SS". Data impossível (ex.: 31/02) ou texto qualquer = null.
 */
export function paraData(v: Celula): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/);
  let a: number, mes: number, d: number, hh: number | null = null, mm = 0, ss = 0;
  if (m) { a = +m[1]; mes = +m[2]; d = +m[3]; if (m[4] !== undefined) { hh = +m[4]; mm = +m[5]; ss = m[6] ? +m[6] : 0; } }
  else {
    m = t.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
    if (!m) return null;
    d = +m[1]; mes = +m[2]; a = +m[3];
    if (m[4] !== undefined) { hh = +m[4]; mm = +m[5]; ss = m[6] ? +m[6] : 0; }
  }
  const dt = new Date(Date.UTC(a, mes - 1, d));
  if (dt.getUTCFullYear() !== a || dt.getUTCMonth() !== mes - 1 || dt.getUTCDate() !== d) return null;
  if (hh !== null && (hh > 23 || mm > 59 || ss > 59)) return null;
  const dia = `${String(a).padStart(4, "0")}-${p2(mes)}-${p2(d)}`;
  return hh === null ? dia : `${dia} ${p2(hh)}:${p2(mm)}:${p2(ss)}`;
}

export interface Tabela {
  colunas: string[];
  linhas: Celula[][];
  avisos: string[];
}

/** Converte a resposta conferida em linhas tipadas conforme numeros/datas/limpar_apostrofo/chave do relatorios.json. */
export function tipar(resp: RespostaValida, def: Pick<Relatorio, "numeros" | "datas" | "limpar_apostrofo" | "chave" | "aba">): Tabela {
  const colunas = resp.colunas;
  const numeros = new Set((def.numeros ?? []).filter((c) => colunas.includes(c)));
  const datas = new Set(Object.keys(def.datas ?? {}).filter((c) => colunas.includes(c)));
  const apostrofo = new Set(def.limpar_apostrofo ?? []);
  const faltaChave = (def.chave ?? []).filter((c) => resp.linhas.length && !colunas.includes(c));
  if (faltaChave.length) throw new RespostaInvalida(`a chave ${faltaChave.map((c) => JSON.stringify(c)).join(", ")} não existe nas colunas de ${def.aba}`);
  const ruim: Record<string, number> = {};
  const linhas = resp.linhas.map((l) => colunas.map((c) => {
    let v: Celula = l[c] ?? null;
    if (typeof v === "string") { if (apostrofo.has(c) && v.startsWith("'")) v = v.slice(1); if (v.trim() === "") v = null; }
    if (v === null) return null;
    if (numeros.has(c)) { const n = paraNumero(v); if (n === null) ruim[c] = (ruim[c] ?? 0) + 1; return n; }
    if (datas.has(c)) { const d = paraData(v); if (d === null) ruim[c] = (ruim[c] ?? 0) + 1; return d; }
    return v;
  }));
  const avisos = Object.entries(ruim).map(([c, n]) => `${n} valor(es) de "${c}" em ${def.aba} não puderam ser lidos e ficaram vazios`);
  return { colunas, linhas, avisos };
}

/** Junta linhas novas às existentes pela chave (upsert: a linha nova prevalece). Linha sem chave completa é descartada e contada. */
export function mesclarPorChave(antigo: Tabela | null, novo: Tabela, chave: string[]): { tabela: Tabela; descartadas: number } {
  const colunas = [...new Set([...(antigo?.colunas ?? []), ...novo.colunas])];
  const ix = (t: Tabela) => colunas.map((c) => t.colunas.indexOf(c));
  const remap = (t: Tabela) => { const i = ix(t); return t.linhas.map((l) => i.map((k) => (k < 0 ? null : l[k]))); };
  const pos = chave.map((c) => colunas.indexOf(c));
  const mapa = new Map<string, Celula[]>();
  let descartadas = 0;
  const por = (linhas: Celula[][], contar: boolean) => {
    for (const l of linhas) {
      const partes = pos.map((k) => l[k]);
      if (partes.some((p) => p === null)) { if (contar) descartadas++; continue; }
      mapa.set(JSON.stringify(partes), l);
    }
  };
  if (antigo) por(remap(antigo), false);
  por(remap(novo), true);
  return { tabela: { colunas, linhas: [...mapa.values()], avisos: novo.avisos }, descartadas };
}
