import { admin } from "./supabase/admin";

/**
 * Bloqueios de login (tabela tentativas_acesso; sem Redis):
 *  - usuário: 5 senhas erradas seguidas => espera 1 min;
 *  - mesma origem (hash do IP): 12 erros em 10 min => 5 min sem tentar.
 */
const USUARIO = { max: 5, espera: 60_000 };
const ORIGEM = { max: 12, janela: 600_000, espera: 300_000 };

async function ultimas(tipo: "usuario" | "ip", chave: string, desdeMs: number, limite: number): Promise<number[]> {
  const { data } = await admin().from("tentativas_acesso").select("quando").eq("tipo", tipo).eq("chave", chave)
    .gte("quando", new Date(Date.now() - desdeMs).toISOString()).order("quando", { ascending: false }).limit(limite);
  return (data ?? []).map((r) => Date.parse(r.quando));
}

export async function estaBloqueado(usuario: string, origem: string): Promise<boolean> {
  const u = await ultimas("usuario", usuario.toLowerCase(), USUARIO.espera, USUARIO.max);
  if (u.length >= USUARIO.max) return true;
  const o = await ultimas("ip", origem, ORIGEM.janela, ORIGEM.max);
  return o.length >= ORIGEM.max && Date.now() - o[0] < ORIGEM.espera;
}

export async function registrarFalha(usuario: string, origem: string): Promise<void> {
  await admin().from("tentativas_acesso").insert([{ tipo: "usuario", chave: usuario.toLowerCase() }, { tipo: "ip", chave: origem }]);
}

export async function limparFalhas(usuario: string): Promise<void> {
  await admin().from("tentativas_acesso").delete().eq("tipo", "usuario").eq("chave", usuario.toLowerCase());
  await admin().from("tentativas_acesso").delete().lt("quando", new Date(Date.now() - 86_400_000).toISOString());   // limpeza do que já não vale
}
