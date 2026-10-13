import { admin } from "./supabase/admin";

/** Registro de auditoria: quem entrou, quem errou a senha, quem atualizou, quem mexeu em usuário ou pendência. Nunca grava senha nem dado de paciente. */
export async function auditar(acao: string, usuario: string | null, detalhe: Record<string, unknown> = {}, origem: string | null = null): Promise<void> {
  try {
    await admin().from("auditoria").insert({ acao, usuario, detalhe, origem });
  } catch (e) {
    console.error("falha ao auditar", acao, (e as Error).message);   // auditoria nunca derruba a ação
  }
}
