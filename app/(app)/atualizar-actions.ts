"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const KLINGO_ID_RE = /^\d{1,10}$/;
const MAX_DIAS = 31;
const RELATORIO_INDICADORES = "13397"; // alimenta a tabela "indicadores" exibida em Relatórios

export type AtualizarEstado = { ok: boolean; mensagem: string } | null;

function diasEntre(de: string, ate: string) {
  return (Date.parse(`${ate}T00:00:00Z`) - Date.parse(`${de}T00:00:00Z`)) / 86_400_000 + 1;
}

async function chamarFuncao(nome: string, accessToken: string, corpo: unknown) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/${nome}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      // JWT do admin logado: a Edge Function valida com is_admin(). Nenhuma chave
      // privilegiada (service_role) existe no site.
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(corpo),
    signal: AbortSignal.timeout(280_000),
  });
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, payload };
}

// Dispara a atualização de UM relatório escolhido, num período. Só admin: a Edge Function
// confere de novo (is_admin) — esta checagem só poupa a viagem e dá mensagem melhor.
export async function atualizarRelatorio(_: AtualizarEstado, formData: FormData): Promise<AtualizarEstado> {
  const klingoId = String(formData.get("relatorio") ?? "");
  const de = String(formData.get("de") ?? "");
  const ate = String(formData.get("ate") ?? "");

  if (!KLINGO_ID_RE.test(klingoId)) return { ok: false, mensagem: "Escolha um relatório." };
  if (!DATE_RE.test(de) || !DATE_RE.test(ate) || de > ate) {
    return { ok: false, mensagem: "Informe um período válido." };
  }
  if (diasEntre(de, ate) > MAX_DIAS) {
    return { ok: false, mensagem: `Escolha no máximo ${MAX_DIAS} dias por atualização.` };
  }

  const profile = await getCurrentProfile();
  if (profile?.role !== "admin") {
    return { ok: false, mensagem: "Somente administradores podem atualizar relatórios." };
  }

  const supabase = await createClient();
  const { data: sessao } = await supabase.auth.getSession();
  if (!sessao.session) return { ok: false, mensagem: "Sessão expirada. Entre novamente." };
  const token = sessao.session.access_token;

  try {
    const dw = await chamarFuncao("sync-relatorios-dw", token, { from: de, to: ate, klingo_ids: [klingoId] });
    if (!dw.ok) {
      console.error("sync-relatorios-dw falhou:", dw.status, JSON.stringify(dw.payload));
      return { ok: false, mensagem: "Não foi possível atualizar o relatório agora. Veja os alertas de sincronização." };
    }
    const erros = Array.isArray(dw.payload?.erros) ? dw.payload.erros.length : 0;

    // O relatório 13397 também alimenta os totais exibidos nesta tela.
    let indicadoresOk = true;
    if (klingoId === RELATORIO_INDICADORES) {
      const ind = await chamarFuncao("sync-indicadores", token, { from: de, to: ate });
      indicadoresOk = ind.ok;
      if (!ind.ok) console.error("sync-indicadores falhou:", ind.status, JSON.stringify(ind.payload));
    }

    revalidatePath("/metas");

    if (erros > 0 || !indicadoresOk) {
      return { ok: false, mensagem: "Atualização concluída com falhas em alguns dias. Tente novamente ou confira os alertas." };
    }
    return { ok: true, mensagem: `Relatório atualizado (${dw.payload?.linhas_sincronizadas ?? 0} linhas lidas).` };
  } catch (error) {
    console.error("Falha ao chamar a atualização:", error instanceof Error ? error.message : error);
    return { ok: false, mensagem: "A atualização demorou demais ou falhou. Tente um período menor." };
  }
}
