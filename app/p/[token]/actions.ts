"use server";

import { revalidatePath } from "next/cache";
import { chamarPortal } from "@/lib/portal-servidor";
import { textoDoMotivo, tokenValido } from "@/lib/portal";

export type AcaoPaciente = { ok?: boolean; erro?: string; mensagem?: string };

async function executar(token: string, funcao: "portal_confirmar" | "portal_remarcar" | "portal_enviar_mensagem", args: Record<string, unknown>, sucesso: string): Promise<AcaoPaciente> {
  if (!tokenValido(token)) return { erro: textoDoMotivo("invalido") };
  const r = await chamarPortal(funcao, { p_token: token, ...args });
  if (!r.ok) return { erro: textoDoMotivo(r.motivo) };
  revalidatePath(`/p/${token}`);
  return { ok: true, mensagem: sucesso };
}

export async function confirmarPresenca(token: string): Promise<AcaoPaciente> {
  return executar(token, "portal_confirmar", {}, "Presença confirmada. Obrigado!");
}

export async function pedirRemarcacao(token: string, _prev: AcaoPaciente, formData: FormData): Promise<AcaoPaciente> {
  const nota = String(formData.get("nota") ?? "").slice(0, 500);
  return executar(token, "portal_remarcar", { p_nota: nota }, "Pedido enviado. A equipe vai entrar em contato para combinar a nova data.");
}

export async function enviarMensagem(token: string, _prev: AcaoPaciente, formData: FormData): Promise<AcaoPaciente> {
  const texto = String(formData.get("texto") ?? "").slice(0, 1000);
  if (texto.trim().length === 0) return { erro: "Escreva a mensagem antes de enviar." };
  return executar(token, "portal_enviar_mensagem", { p_texto: texto }, "Mensagem enviada.");
}
