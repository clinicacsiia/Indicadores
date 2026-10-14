"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { MAX_JUSTIFICATIVA, MIN_JUSTIFICATIVA } from "@/lib/avisos";

export type AvisoAcaoState = { ok?: boolean; error?: string };

// Erros que fechar_aviso / reabrir_aviso levantam de propósito, já em português para a pessoa:
// 22023 = justificativa inválida, 55000 = aviso em outro estado, 42501 = sem login ou sem acesso ao painel.
const CODIGOS_DO_BANCO = new Set(["22023", "55000", "42501"]);

function mensagemDe(error: { code?: string; message: string }, padrao: string) {
  console.error("Falha ao gravar o aviso:", error.code, error.message);
  return CODIGOS_DO_BANCO.has(error.code ?? "") ? error.message : padrao;
}

function idDoForm(formData: FormData) {
  const id = Number(formData.get("id"));
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

// Fecha um aviso aberto. A justificativa é obrigatória (aqui, no formulário e dentro do banco, que é quem
// realmente garante). O banco também confere se a pessoa pode ver o painel do aviso.
export async function fecharAviso(_prev: AvisoAcaoState, formData: FormData): Promise<AvisoAcaoState> {
  const id = idDoForm(formData);
  const justificativa = String(formData.get("justificativa") ?? "").trim();

  if (!id) return { error: "Aviso inválido." };
  if (justificativa.length < MIN_JUSTIFICATIVA) {
    return { error: `Explique em pelo menos ${MIN_JUSTIFICATIVA} caracteres o que foi feito ou por que o aviso pode ser fechado.` };
  }
  if (justificativa.length > MAX_JUSTIFICATIVA) {
    return { error: `A justificativa pode ter no máximo ${MAX_JUSTIFICATIVA} caracteres.` };
  }

  const supabase = await createClient();
  const { error } = await supabase.rpc("fechar_aviso", { p_aviso: id, p_justificativa: justificativa });
  if (error) return { error: mensagemDe(error, "Não foi possível fechar o aviso. Tente de novo.") };

  revalidatePath("/", "layout"); // a lista e o contador do menu
  return { ok: true };
}

// "Ainda não resolvi": desfaz o fechamento.
export async function reabrirAviso(_prev: AvisoAcaoState, formData: FormData): Promise<AvisoAcaoState> {
  const id = idDoForm(formData);
  if (!id) return { error: "Aviso inválido." };

  const supabase = await createClient();
  const { error } = await supabase.rpc("reabrir_aviso", { p_aviso: id });
  if (error) return { error: mensagemDe(error, "Não foi possível reabrir o aviso. Tente de novo.") };

  revalidatePath("/", "layout");
  return { ok: true };
}
