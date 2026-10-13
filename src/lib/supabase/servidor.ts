import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { ambiente } from "../ambiente";

/** Cliente do usuário logado (chave anon + cookies de sessão), para Server Components, ações e rotas. */
export async function supabaseDoUsuario() {
  const jar = await cookies();
  return createServerClient(ambiente.supabaseUrl, ambiente.anonKey, {
    cookies: {
      getAll: () => jar.getAll(),
      setAll: (lista) => { try { lista.forEach(({ name, value, options }) => jar.set(name, value, options)); } catch { /* Server Component: o proxy renova */ } },
    },
  });
}
