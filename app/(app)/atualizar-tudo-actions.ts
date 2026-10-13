"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { chamarEdgeFunction } from "@/lib/klingo/chamarEdgeFunction";

// Qualquer usuário logado pode disparar (não só admin) — a Edge Function
// também aceita qualquer JWT autenticado, ver sync-relatorios-dw/index.ts.
const MAX_DIAS = 31;

export type AtualizarTudoEstado = { ok: boolean; mensagem: string } | null;

function hojeSaoPaulo() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

function somarDias(iso: string, dias: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

// Para cada relatório liberado para visualização, busca só o que falta: do dia
// seguinte ao último sync bem-sucedido até hoje, limitado aos últimos 31 dias
// (o máximo que a Edge Function aceita numa chamada). Relatório sem nenhum
// sync ainda usa esse mesmo limite de 31 dias como ponto de partida.
export async function atualizarTudo(
  _prev: AtualizarTudoEstado,
  _formData: FormData
): Promise<AtualizarTudoEstado> {
  const supabase = await createClient();
  const { data: sessao } = await supabase.auth.getSession();
  if (!sessao.session) return { ok: false, mensagem: "Sessão expirada. Entre novamente." };
  const token = sessao.session.access_token;

  const { data: ativos, error } = await supabase
    .from("dim_relatorio")
    .select("id, klingo_id")
    .eq("ativo", true)
    .is("supersedido_por", null);

  if (error) {
    console.error("Falha ao listar relatórios ativos:", error.message);
    return { ok: false, mensagem: "Não foi possível listar os relatórios agora." };
  }
  if (!ativos || ativos.length === 0) {
    return { ok: false, mensagem: "Nenhum relatório liberado para atualizar." };
  }

  const hoje = hojeSaoPaulo();
  const inicioMaximo = somarDias(hoje, -(MAX_DIAS - 1));
  let totalLinhas = 0;
  let comErro = 0;
  let algumExecutado = false;

  for (const relatorio of ativos) {
    const { data: ultimo } = await supabase
      .from("sync_relatorio_runs")
      .select("periodo")
      .eq("relatorio_id", relatorio.id)
      .eq("status", "success")
      .order("periodo", { ascending: false })
      .limit(1)
      .maybeSingle();

    const de = ultimo?.periodo
      ? (somarDias(ultimo.periodo, 1) > inicioMaximo ? somarDias(ultimo.periodo, 1) : inicioMaximo)
      : inicioMaximo;

    if (de > hoje) continue; // já está em dia

    algumExecutado = true;
    try {
      const dw = await chamarEdgeFunction("sync-relatorios-dw", token, {
        from: de,
        to: hoje,
        klingo_ids: [relatorio.klingo_id],
      });
      if (!dw.ok) {
        comErro++;
        console.error("sync-relatorios-dw falhou:", dw.status, JSON.stringify(dw.payload));
        continue;
      }
      totalLinhas += dw.payload?.linhas_sincronizadas ?? 0;
      if (Array.isArray(dw.payload?.erros) && dw.payload.erros.length > 0) comErro++;
    } catch (err) {
      comErro++;
      console.error("Falha ao atualizar relatório:", err instanceof Error ? err.message : err);
    }
  }

  revalidatePath("/");
  revalidatePath("/metas");

  if (!algumExecutado) return { ok: true, mensagem: "Tudo já estava em dia." };
  if (comErro > 0) {
    return {
      ok: false,
      mensagem: `Atualização concluída com falhas em ${comErro} relatório(s). Veja os alertas de sincronização.`,
    };
  }
  return { ok: true, mensagem: `Tudo atualizado (${totalLinhas} linhas lidas).` };
}
