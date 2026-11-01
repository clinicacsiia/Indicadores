import "server-only";
import { createHash } from "node:crypto";
import { headers } from "next/headers";
import { createAdminClient } from "@/lib/supabase/admin";
import type { RespostaPortal } from "@/lib/portal";

// Só o servidor chama as funções portal_* (a chave de serviço nunca vai para o navegador). O IP do paciente vira um hash para o limite de tentativas; o IP em si não é guardado.
export async function origemDoPedido(): Promise<string> {
  const h = await headers();
  const ip = (h.get("x-forwarded-for") ?? "").split(",")[0].trim() || h.get("x-real-ip") || "sem-ip";
  return createHash("sha256").update(`${ip}:${process.env.PORTAL_SAL ?? "clinica-csi"}`).digest("hex").slice(0, 32);
}

export async function chamarPortal(funcao: "portal_ver" | "portal_confirmar" | "portal_remarcar" | "portal_enviar_mensagem", args: Record<string, unknown>): Promise<RespostaPortal> {
  const admin = createAdminClient();
  if (!admin) return { ok: false, motivo: "desligado" };
  const { data, error } = await admin.rpc(funcao, { ...args, p_ip: await origemDoPedido() });
  if (error || !data || typeof data !== "object") {
    console.error(`Falha em ${funcao}:`, error?.message);
    return { ok: false, motivo: "erro" };
  }
  return data as RespostaPortal;
}
