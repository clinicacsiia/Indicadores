"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { chamarEdgeFunction } from "@/lib/klingo/chamarEdgeFunction";

// "Atualizar tudo" não monta mais plano no site: a Edge Function sync-relatorios-dw, no modo
// "auto", pergunta ao banco (proximos_trabalhos) o que falta dentro da janela de cada relatório
// ativo (dim_relatorio.janela_dias, até 90 dias) e busca só isso. O mesmo trabalho roda sozinho
// pelo pg_cron (o dia de hoje é refeito a cada 5 h); o botão manual refaz o que tiver mais de 10 min. Quem conduz é o cliente
// (atualizar-tudo-form.tsx), que chama um lote por vez até não restar nada e mostra o progresso.
// Qualquer usuário logado pode disparar — a Edge Function também aceita qualquer JWT autenticado.
const LOTE = 30;

export type ResultadoLote = {
  ok: boolean;
  processados: number;
  restantes: number;
  linhas: number;
  falhas: number;
};

export async function coletarLote(): Promise<ResultadoLote> {
  const falha: ResultadoLote = { ok: false, processados: 0, restantes: 0, linhas: 0, falhas: 0 };

  const supabase = await createClient();
  const { data: sessao } = await supabase.auth.getSession();
  if (!sessao.session) return falha;

  try {
    const dw = await chamarEdgeFunction("sync-relatorios-dw", sessao.session.access_token, {
      modo: "auto",
      limite: LOTE,
      frescor_minutos: 10,
    });
    if (!dw.ok) {
      console.error("sync-relatorios-dw falhou:", dw.status, JSON.stringify(dw.payload));
      return falha;
    }
    const processados = Number(dw.payload?.processados ?? 0);
    const restantes = Number(dw.payload?.restantes ?? 0);
    const falhas = Array.isArray(dw.payload?.erros) ? dw.payload.erros.length : 0;
    if (restantes === 0 || processados === 0) {
      revalidatePath("/");
      revalidatePath("/metas");
    }
    return { ok: true, processados, restantes, linhas: Number(dw.payload?.linhas_sincronizadas ?? 0), falhas };
  } catch (err) {
    console.error("Falha ao coletar relatórios:", err instanceof Error ? err.message : err);
    return falha;
  }
}
