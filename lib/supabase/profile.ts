import { cache } from "react";
import { createClient } from "./server";

export type Profile = {
  id: string;
  email: string | null;
  role: "admin" | "viewer";
  permissions: Record<string, boolean>;
};

// RLS garante que isso só retorna o perfil do próprio usuário logado.
// `cache` (React) guarda o resultado durante UM pedido: o layout e a página chamam isto na mesma navegação, e sem isso cada uma
// refazia a conferência do login (ida ao Supabase Auth) e a leitura do perfil.
export const getCurrentProfile = cache(async function getCurrentProfile(): Promise<Profile | null> {
  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return null;

  const { data, error } = await supabase
    .from("profiles")
    .select("id, email, role, permissions")
    .eq("id", auth.user.id)
    .single();

  if (error) {
    console.error("Falha ao carregar perfil:", error.message);
    return null;
  }

  return data as Profile;
});
