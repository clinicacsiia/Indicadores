import { createClient } from "@supabase/supabase-js";

// Cliente com a service role: ignora RLS e pode criar usuários / trocar senhas.
// Só pode ser usado em server actions depois de confirmar que quem chama é admin;
// a chave nunca vai para o navegador (não tem prefixo NEXT_PUBLIC_).
export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false } });
}
