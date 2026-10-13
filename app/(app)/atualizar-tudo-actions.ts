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

function diaSaoPaulo(instante: string) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date(instante));
}

// Mesma janela que a tela Início usa para medir "em dia" (status_sincronizacao_relatorios):
// mensal -> do dia 1 do mês até hoje; os demais -> últimos 30 dias.
function inicioDaJanela(periodicidade: string | null, hoje: string) {
  return periodicidade === "mensal" ? `${hoje.slice(0, 8)}01` : somarDias(hoje, -29);
}

// Para cada relatório liberado para visualização, busca só o que falta dentro da
// mesma janela que a tela Início mede (ver inicioDaJanela): do primeiro dia ainda
// sem sync completo até hoje. Um dia só conta como completo se o sync terminou
// depois da meia-noite dele — sincronizar o dia de hoje (ou um dia que foi
// sincronizado antes de acabar) pega só parte dos registros, então ele é buscado
// de novo. A janela tem no máximo 31 dias, o limite da Edge Function por chamada.
// Relatório "pontual" não se repete: só entra se nunca foi sincronizado.
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
    .select("id, klingo_id, periodicidade")
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
  let totalLinhas = 0;
  let comErro = 0;
  let algumExecutado = false;

  for (const relatorio of ativos) {
    const pontual = relatorio.periodicidade === "pontual";
    const inicioJanela = pontual ? somarDias(hoje, -(MAX_DIAS - 1)) : inicioDaJanela(relatorio.periodicidade, hoje);

    const { data: sucessos, error: sucessosError } = await supabase
      .from("sync_relatorio_runs")
      .select("periodo, finished_at")
      .eq("relatorio_id", relatorio.id)
      .eq("status", "success")
      .gte("periodo", pontual ? "0001-01-01" : inicioJanela)
      .lte("periodo", hoje)
      .limit(1000);

    if (sucessosError) {
      comErro++;
      console.error("Falha ao ler histórico de sync:", sucessosError.message);
      continue;
    }

    if (pontual && (sucessos?.length ?? 0) > 0) continue;

    const completos = new Set(
      (sucessos ?? [])
        .filter((s) => s.finished_at && diaSaoPaulo(s.finished_at) > s.periodo)
        .map((s) => s.periodo as string)
    );
    let de = hoje;
    for (let dia = inicioJanela; dia < hoje; dia = somarDias(dia, 1)) {
      if (!completos.has(dia)) {
        de = dia;
        break;
      }
    }

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

  if (!algumExecutado && comErro === 0) return { ok: true, mensagem: "Tudo já estava em dia." };
  if (comErro > 0) {
    return {
      ok: false,
      mensagem: `Atualização concluída com falhas em ${comErro} relatório(s). Veja os alertas de sincronização.`,
    };
  }
  return { ok: true, mensagem: `Tudo atualizado (${totalLinhas} linhas lidas).` };
}
