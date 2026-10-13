"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

// Supabase Auth exige email; quem digita só o usuário (ex.: "csiadmin")
// é mapeado para este domínio interno, que nunca recebe email.
const DOMINIO_INTERNO = "csi.local";

export async function signIn(_prevState: unknown, formData: FormData) {
  const usuario = String(formData.get("usuario") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");

  if (!usuario || !password) {
    return { error: "Informe usuário e senha.", usuario };
  }

  const email = usuario.includes("@") ? usuario : `${usuario}@${DOMINIO_INTERNO}`;

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });

  if (error) {
    // Mensagem genérica: nunca revelar se o problema foi o usuário ou a senha.
    return { error: "Credenciais inválidas.", usuario };
  }

  redirect("/metas");
}
