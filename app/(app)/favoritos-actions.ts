"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { podeVerPainel } from "@/lib/paineis";

// Liga/desliga um painel nos favoritos do usuário logado (tela de Início).
// RLS (painel_favoritos_*_own) também garante que só dá para alterar a
// própria lista; a checagem de permissão aqui só evita favoritar um painel
// que o usuário não pode nem abrir.
export async function alternarFavorito(painelId: string) {
  const profile = await getCurrentProfile();
  if (!profile || !podeVerPainel(profile, painelId)) {
    return { error: "Sem acesso a este painel." };
  }

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sessão expirada. Atualize a página." };

  const { data: existente, error: leituraError } = await supabase
    .from("painel_favoritos")
    .select("painel_id")
    .eq("user_id", auth.user.id)
    .eq("painel_id", painelId)
    .maybeSingle();

  if (leituraError) {
    console.error("Falha ao ler favorito:", leituraError.message);
    return { error: "Não foi possível atualizar o favorito." };
  }

  const { error } = existente
    ? await supabase.from("painel_favoritos").delete().eq("user_id", auth.user.id).eq("painel_id", painelId)
    : await supabase.from("painel_favoritos").insert({ user_id: auth.user.id, painel_id: painelId });

  if (error) {
    console.error("Falha ao salvar favorito:", error.message);
    return { error: "Não foi possível atualizar o favorito." };
  }

  revalidatePath("/");
  return { ok: true };
}
