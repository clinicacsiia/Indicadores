"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { hojeEmBrasilia } from "@/lib/avisos";
import { MAX_DESCRICAO, MIN_DESCRICAO, GRAVIDADES, SETORES, TIPOS, UNIDADES } from "@/lib/qualidade";

export type OcorrenciaState = { ok?: boolean; error?: string };

const DATA_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const texto = (formData: FormData, nome: string) => String(formData.get(nome) ?? "").trim();

// 42501 = o banco recusou (sem a permissão de preencher); 23514 = violou uma regra da tabela.
export async function registrarOcorrencia(_prev: OcorrenciaState, formData: FormData): Promise<OcorrenciaState> {
  const data = texto(formData, "data");
  const unidade = texto(formData, "unidade");
  const setor = texto(formData, "setor");
  const tipo = texto(formData, "tipo");
  const descricao = texto(formData, "descricao");
  // Elogio não tem gravidade: o banco exige um valor, então vai o mais baixo.
  const gravidade = tipo === "elogio" ? "baixa" : texto(formData, "gravidade");

  if (!DATA_RE.test(data) || new Date(`${data}T12:00:00Z`).toISOString().slice(0, 10) !== data) return { error: "Informe a data em que aconteceu." };
  if (data > hojeEmBrasilia()) return { error: "A data não pode estar no futuro." };
  if (data < hojeEmBrasilia(-365)) return { error: "A data não pode ser de mais de um ano atrás." };
  if (!UNIDADES.some((u) => u === unidade)) return { error: "Escolha a unidade." };
  if (!SETORES.some((s) => s === setor)) return { error: "Escolha o setor." };
  if (!TIPOS.some((t) => t.id === tipo)) return { error: "Escolha se é reclamação, ocorrência ou elogio." };
  if (!GRAVIDADES.some((g) => g.id === gravidade)) return { error: "Escolha a gravidade." };
  if (descricao.length < MIN_DESCRICAO) return { error: `Descreva o que aconteceu em pelo menos ${MIN_DESCRICAO} caracteres.` };
  if (descricao.length > MAX_DESCRICAO) return { error: `A descrição pode ter no máximo ${MAX_DESCRICAO} caracteres.` };

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sua sessão expirou. Entre de novo." };

  const { error } = await supabase
    .from("ocorrencia")
    .insert({ data_ocorrencia: data, unidade, setor, tipo, gravidade, descricao, criado_por: auth.user.id });
  if (error) {
    console.error("Falha ao registrar ocorrência:", error.code, error.message);
    return { error: error.code === "42501" ? "Você não tem permissão para registrar." : "Não foi possível registrar. Tente de novo." };
  }

  revalidatePath("/qualidade");
  return { ok: true };
}

export async function resolverOcorrencia(_prev: OcorrenciaState, formData: FormData): Promise<OcorrenciaState> {
  const id = Number(formData.get("id"));
  if (!Number.isSafeInteger(id) || id <= 0) return { error: "Registro inválido." };

  const supabase = await createClient();
  // Só resolve o que ainda está aberto e nunca antes da data da ocorrência (o banco confere o resto).
  const { data, error } = await supabase
    .from("ocorrencia")
    .update({ status: "resolvida", resolvida_em: hojeEmBrasilia() })
    .eq("id", id)
    .eq("status", "aberta")
    .neq("tipo", "elogio")
    .select("id");
  if (error) {
    console.error("Falha ao resolver ocorrência:", error.code, error.message);
    return { error: "Não foi possível marcar como resolvida." };
  }
  if (!data?.length) return { error: "Este registro não está mais aberto ou você não pode resolvê-lo." };

  revalidatePath("/qualidade");
  return { ok: true };
}
