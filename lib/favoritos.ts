import { createClient } from "@/lib/supabase/server";

// RLS (policy "painel_favoritos_select_own") garante que isso só traz os
// favoritos do próprio usuário logado.
export async function listarFavoritos(): Promise<string[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("painel_favoritos")
    .select("painel_id")
    .order("created_at", { ascending: true });

  if (error) {
    console.error("Falha ao carregar favoritos:", error.message);
    return [];
  }

  return (data ?? []).map((r) => r.painel_id as string);
}
