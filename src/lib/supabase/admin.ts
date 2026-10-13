import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { ambiente } from "../ambiente";

let cliente: SupabaseClient | null = null;

/** Cliente com a chave de serviço (ignora RLS): SÓ nas rotas do servidor, depois de checar sessão e permissão. */
export function admin(): SupabaseClient {
  cliente ??= createClient(ambiente.supabaseUrl, ambiente.serviceRoleKey, { auth: { persistSession: false, autoRefreshToken: false } });
  return cliente;
}
