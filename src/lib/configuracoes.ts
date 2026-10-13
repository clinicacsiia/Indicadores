import { admin } from "./supabase/admin";

export interface Configuracoes {
  intervalo_minimo_minutos: number;                    // se os dados têm menos que isso, a verificação automática não consulta o Klingo
  verificacao_automatica_minutos: number;
  intervalo_minimo_atualizar_agora_minutos: number;    // quem não é admin só atualiza se os dados têm mais que isso
}
const PADRAO: Configuracoes = { intervalo_minimo_minutos: 30, verificacao_automatica_minutos: 30, intervalo_minimo_atualizar_agora_minutos: 5 };

export async function lerConfiguracoes(): Promise<Configuracoes> {
  const { data } = await admin().from("configuracoes").select("chave, valor");
  const c: Configuracoes = { ...PADRAO };
  for (const r of data ?? []) {
    const n = Number(r.valor);
    if (r.chave in c && Number.isFinite(n) && n >= 0) (c as unknown as Record<string, number>)[r.chave] = n;
  }
  return c;
}
