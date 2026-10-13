import { admin } from "./supabase/admin";
import { ambiente } from "./ambiente";
import { processarFila, type ResultadoFila } from "@/klingo/motor";
import type { MenuId } from "@/klingo/config";

/** Segundos (epoch) em que o menu recebeu dados pela última vez; é o mesmo número que o cálculo em Python põe em D.versao. */
export async function versaoDosDados(menu: MenuId): Promise<{ versao: number | null; atualizadoEm: string | null }> {
  const { data } = await admin().from("dados_versao").select("atualizado_em").eq("menu", menu).maybeSingle();
  if (!data) return { versao: null, atualizadoEm: null };
  return { versao: Math.floor(Date.parse(data.atualizado_em) / 1000), atualizadoEm: data.atualizado_em };
}

export interface Trava { em_andamento: boolean; modulo: string | null; usuario: string | null; inicio: string | null; expira_em: string | null }

export async function travaAtiva(): Promise<Trava | null> {
  const { data } = await admin().from("atualizacao_trava").select("*").eq("id", 1).maybeSingle();
  if (!data || !data.em_andamento) return null;
  if (data.expira_em && Date.parse(data.expira_em) < Date.now()) return null;   // trava com prazo: nunca fica presa
  return data as Trava;
}

const dormir = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Pré-aquece o cache do painel (cálculo em Python) depois de uma atualização. */
export async function aquecerPainel(origem: string, menu: MenuId): Promise<void> {
  const url = new URL("/api/py/painel", origem);
  url.searchParams.set("menu", menu);
  url.searchParams.set("aquecer", "1");
  const cab: Record<string, string> = { "x-interno": ambiente.cronSecret };
  if (process.env.VERCEL_AUTOMATION_BYPASS_SECRET) cab["x-vercel-protection-bypass"] = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
  const r = await fetch(url, { headers: cab, signal: AbortSignal.timeout(280_000), cache: "no-store" });
  if (!r.ok) throw new Error(`cálculo do painel ${menu} respondeu ${r.status}`);
}

/** Processa a fila até acabar o orçamento e, se sobrou item, chama a si mesmo (a Vercel limita o tempo de cada função). */
export async function processarEEncadear(origem: string, orcamentoMs = 45_000): Promise<ResultadoFila> {
  const res = await processarFila({ sb: admin(), aquecer: (m) => aquecerPainel(origem, m) }, orcamentoMs);
  if (res.restantes > 0) {
    const chamada = fetch(new URL("/api/cron/processar", origem), { method: "POST", headers: { Authorization: `Bearer ${ambiente.cronSecret}` }, cache: "no-store" }).catch(() => undefined);
    await Promise.race([chamada, dormir(2000)]);   // só precisa sair; o pg_cron a cada minuto também retoma a fila
  }
  return res;
}
