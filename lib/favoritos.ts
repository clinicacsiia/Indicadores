import { createClient } from "@/lib/supabase/server";

// Um gráfico (ou bloco) de um painel que o usuário fixou no Início. `aba` e `chave` acham o bloco dentro do painel
// (ver itensDaPagina em painel_base.js); `titulo` é o texto que ele tinha quando foi escolhido.
export type FavoritoItem = { painel_id: string; aba: string; chave: string; titulo: string };

export const LIMITE_FAVORITOS = 40;

// RLS (policy "painel_favoritos_itens_select_own") garante que isso só traz os
// favoritos do próprio usuário logado.
export async function listarFavoritos(): Promise<FavoritoItem[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("painel_favoritos_itens")
    .select("painel_id, aba, chave, titulo")
    .order("created_at", { ascending: true });

  if (error) {
    console.error("Falha ao carregar favoritos:", error.message);
    return [];
  }

  return (data ?? []) as FavoritoItem[];
}
