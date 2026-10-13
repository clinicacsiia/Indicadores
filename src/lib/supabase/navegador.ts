"use client";
import { createBrowserClient } from "@supabase/ssr";

/** Só para o Realtime (aviso "atualização terminou"): usa a chave anon pública; as tabelas de dados não são legíveis por ela. */
export function supabaseNoNavegador() {
  return createBrowserClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);
}
