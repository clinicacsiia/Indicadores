/** Datas em AAAA-MM e dd/mm/aaaa; "hoje" é sempre o de Salvador (America/Bahia), não o da Vercel (UTC). */
export const FUSO = "America/Bahia";

export function hojeSalvador(agora: Date = new Date()): { ano: number; mes: number; dia: number; ym: string; iso: string } {
  const [a, m, d] = new Intl.DateTimeFormat("en-CA", { timeZone: FUSO, year: "numeric", month: "2-digit", day: "2-digit" }).format(agora).split("-").map(Number);
  const p2 = (n: number) => String(n).padStart(2, "0");
  return { ano: a, mes: m, dia: d, ym: `${a}-${p2(m)}`, iso: `${a}-${p2(m)}-${p2(d)}` };
}

export function mesMais(ym: string, n: number): string {
  const t = Number(ym.slice(0, 4)) * 12 + Number(ym.slice(5, 7)) - 1 + n;
  return `${String(Math.floor(t / 12)).padStart(4, "0")}-${String((t % 12) + 1).padStart(2, "0")}`;
}

export function mesesEntre(a: string, b: string): string[] {
  const out: string[] = [];
  for (let m = a; m <= b; m = mesMais(m, 1)) out.push(m);
  return out;
}

export function ultimoDiaDoMes(ym: string): number {
  return new Date(Date.UTC(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)), 0)).getUTCDate();
}

export const primeiroDia = (ym: string) => `${ym}-01`;
export const ultimoDia = (ym: string) => `${ym}-${String(ultimoDiaDoMes(ym)).padStart(2, "0")}`;

/** Ponto médio entre duas datas ISO (para dividir um período cortado pelo limite da API). */
export function pontoMedio(de: string, ate: string): string {
  const a = Date.parse(de + "T00:00:00Z"), b = Date.parse(ate + "T00:00:00Z");
  return new Date(Math.floor((a + b) / 2 / 864e5) * 864e5).toISOString().slice(0, 10);
}
export const diaSeguinte = (d: string) => new Date(Date.parse(d + "T00:00:00Z") + 864e5).toISOString().slice(0, 10);

/** "Período: de dd/mm/aaaa a dd/mm/aaaa" (se o último mês ainda não terminou, o fim é o dia de hoje). */
export function textoPeriodo(de: string, ate: string, hojeIso: string): string {
  const f = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
  const fim = ultimoDia(ate) < hojeIso ? ultimoDia(ate) : hojeIso;
  return `Período: de ${f(primeiroDia(de))} a ${f(fim)}`;
}
