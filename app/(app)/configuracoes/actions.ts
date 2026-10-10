"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

// RLS (policy "profiles_update_admin") é quem realmente garante que só admin
// grava aqui, mesmo que estas actions sejam chamadas diretamente.
export async function updateProfileRole(userId: string, role: string) {
  if (role !== "admin" && role !== "viewer") {
    return { error: "Permissão inválida." };
  }

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();

  // Evita que o único admin se tranque para fora da tela de Configurações.
  if (auth.user?.id === userId && role !== "admin") {
    return { error: "Você não pode remover o seu próprio acesso de admin." };
  }

  const { error } = await supabase.from("profiles").update({ role }).eq("id", userId);

  if (error) {
    console.error("Falha ao atualizar role do perfil:", error.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  revalidatePath("/", "layout");
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

  revalidatePath("/", "layout");
  return {};
}
