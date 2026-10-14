"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS, podeVerPainel } from "@/lib/paineis";
import { LIMITE_FAVORITOS } from "@/lib/favoritos";

type ItemEscolhido = { painelId: string; aba: string; chave: string; titulo: string };

// Liga/desliga um gráfico nos favoritos do usuário logado (tela de Início).
// RLS (painel_favoritos_itens_*_own) também garante que só dá para alterar a
// própria lista; a checagem de permissão aqui evita favoritar um painel que o
// usuário não pode nem abrir. Os textos vêm do navegador, então são conferidos
// (tipo e tamanho) antes de ir para o banco.
export async function alternarFavorito(item: ItemEscolhido) {
  const { painelId } = item;
  const aba = typeof item.aba === "string" ? item.aba.trim() : "";
  const chave = typeof item.chave === "string" ? item.chave.trim() : "";
  const titulo = typeof item.titulo === "string" ? item.titulo.replace(/\s+/g, " ").trim() : "";

  if (!PAINEIS.some((p) => p.id === painelId)) return { error: "Painel desconhecido." };
  if (!aba || aba.length > 60 || !chave || chave.length > 200 || !titulo || titulo.length > 200) {
    return { error: "Gráfico inválido." };
  }

  const profile = await getCurrentProfile();
  if (!podeVerPainel(profile, painelId)) {
    return { error: "Sem acesso a este painel." };
  }

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sessão expirada. Atualize a página." };

  const { data: existente, error: leituraError } = await supabase
    .from("painel_favoritos_itens")
    .select("id")
    .eq("user_id", auth.user.id)
    .eq("painel_id", painelId)
    .eq("aba", aba)
    .eq("chave", chave)
    .maybeSingle();

  if (leituraError) {
    console.error("Falha ao ler favorito:", leituraError.message);
    return { error: "Não foi possível atualizar o favorito." };
  }

  if (existente) {
    const { error } = await supabase.from("painel_favoritos_itens").delete().eq("id", existente.id);
    if (error) {
      console.error("Falha ao remover favorito:", error.message);
      return { error: "Não foi possível atualizar o favorito." };
    }
  } else {
    const { count, error: contagemError } = await supabase
      .from("painel_favoritos_itens")
      .select("id", { count: "exact", head: true })
      .eq("user_id", auth.user.id);
    if (contagemError) {
      console.error("Falha ao contar favoritos:", contagemError.message);
      return { error: "Não foi possível atualizar o favorito." };
    }
    if ((count ?? 0) >= LIMITE_FAVORITOS) {
      return { error: `Você já tem ${LIMITE_FAVORITOS} gráficos favoritos. Remova algum para adicionar outro.` };
    }

    const { error } = await supabase
      .from("painel_favoritos_itens")
      .insert({ user_id: auth.user.id, painel_id: painelId, aba, chave, titulo });
    if (error) {
      console.error("Falha ao salvar favorito:", error.message);
      return { error: "Não foi possível atualizar o favorito." };
    }
  }

  revalidatePath("/");
  return { ok: true };
}
