"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

// RLS (policy "profiles_update_admin") é quem realmente garante isso: só um
// usuário com role=admin consegue gravar aqui, mesmo que esta action seja
// chamada diretamente. Isso é defesa em profundidade, não a única barreira.
export async function updateProfileRole(userId: string, role: "admin" | "viewer") {
  const supabase = await createClient();
  const { error } = await supabase.from("profiles").update({ role }).eq("id", userId);

  if (error) {
    console.error("Falha ao atualizar role do perfil:", error.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  revalidatePath("/configuracoes");
  return {};
}

export async function updateProfileRelatoriosAccess(userId: string, canView: boolean) {
  const supabase = await createClient();
  const { data: current, error: fetchError } = await supabase
    .from("profiles")
    .select("permissions")
    .eq("id", userId)
    .single();

  if (fetchError) {
    console.error("Falha ao ler permissões do perfil:", fetchError.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  const permissions = { ...(current?.permissions ?? {}), relatorios: canView };

  const { error } = await supabase.from("profiles").update({ permissions }).eq("id", userId);

  if (error) {
    console.error("Falha ao atualizar permissões do perfil:", error.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  revalidatePath("/configuracoes");
  return {};
}
