"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { chamarEdgeFunction } from "@/lib/klingo/chamarEdgeFunction";

// "Atualizar tudo" percorre só os relatórios liberados no catálogo (dim_relatorio com
// ativo = true, sem supersedido_por): os que o site realmente usa. Relatório que
// ninguém precisa fica inativo e não é buscado no Klingo, o que deixa a
// atualização mais rápida e estável. Quem conduz é o
// cliente (atualizar-tudo-form.tsx): primeiro pede o plano, depois executa um
// passo por vez, e assim consegue mostrar o progresso de verdade. Cada passo é
// um relatório em poucos dias, para caber folgado no tempo de uma chamada.
// Qualquer usuário logado pode disparar (não só admin) — a Edge Function também
// aceita qualquer JWT autenticado, ver sync-relatorios-dw/index.ts.
const MAX_DIAS = 31;
const DIAS_POR_PASSO = 5;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const KLINGO_ID_RE = /^\d{1,10}$/;

export type Passo = { de: string; ate: string };
export type PlanoRelatorio = { klingoId: string; nome: string; passos: Passo[] };
export type Plano = { ok: true; relatorios: PlanoRelatorio[] } | { ok: false; mensagem: string };
export type ResultadoPasso = { ok: boolean; linhas: number; dias: number; falhas: number };

function hojeSaoPaulo() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

function diaSaoPaulo(instante: string) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date(instante));
}

function somarDias(iso: string, dias: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

// Mesma janela que a tela Início usa para medir "em dia" (status_sincronizacao_relatorios):
// mensal -> do dia 1 do mês até hoje; os demais -> últimos 30 dias.
function inicioDaJanela(periodicidade: string | null, hoje: string) {
  return periodicidade === "mensal" ? `${hoje.slice(0, 8)}01` : somarDias(hoje, -29);
}

function dividirEmPassos(de: string, ate: string): Passo[] {
  const passos: Passo[] = [];
  for (let inicio = de; inicio <= ate; inicio = somarDias(inicio, DIAS_POR_PASSO)) {
    const fim = somarDias(inicio, DIAS_POR_PASSO - 1);
    passos.push({ de: inicio, ate: fim < ate ? fim : ate });
  }
  return passos;
}

// Para cada relatório, só o que falta dentro da janela medida no Início: do primeiro
// dia ainda sem sync completo até hoje. Um dia só conta como completo se o sync
// terminou depois da meia-noite dele — sincronizar o dia de hoje (ou um dia
// sincronizado antes de acabar) pega só parte dos registros, então ele é buscado de
// novo. Relatório "pontual" não se repete: só entra se nunca foi sincronizado.
export async function planejarAtualizacao(): Promise<Plano> {
  const supabase = await createClient();
  const { data: sessao } = await supabase.auth.getSession();
  if (!sessao.session) return { ok: false, mensagem: "Sessão expirada. Entre novamente." };

  const { data: catalogo, error } = await supabase
    .from("dim_relatorio")
    .select("id, klingo_id, nome, categoria, periodicidade")
    .eq("ativo", true)
    .is("supersedido_por", null)
    .order("categoria")
    .order("nome");

  if (error) {
    console.error("Falha ao listar relatórios:", error.message);
    return { ok: false, mensagem: "Não foi possível listar os relatórios agora." };
  }
  if (!catalogo || catalogo.length === 0) {
    return { ok: false, mensagem: "Nenhum relatório ativo para atualizar." };
  }

  const hoje = hojeSaoPaulo();

  const planos = await Promise.all(
    catalogo.map(async (relatorio): Promise<PlanoRelatorio | null> => {
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
        // Sem o histórico não dá para saber o que falta: busca a janela inteira.
        console.error("Falha ao ler histórico de sync:", sucessosError.message);
      } else if (pontual && (sucessos?.length ?? 0) > 0) {
        return null;
      }

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

      return { klingoId: relatorio.klingo_id, nome: relatorio.nome, passos: dividirEmPassos(de, hoje) };
    })
  );

  return { ok: true, relatorios: planos.filter((p): p is PlanoRelatorio => p !== null) };
}

// Executa um passo do plano: um relatório num intervalo curto. `fim` = último passo
// do relatório, quando a tela é revalidada para o card dele já aparecer atualizado.
export async function atualizarPasso(klingoId: string, de: string, ate: string, fim: boolean): Promise<ResultadoPasso> {
  const falha: ResultadoPasso = { ok: false, linhas: 0, dias: 0, falhas: 0 };

  if (!KLINGO_ID_RE.test(klingoId) || !DATE_RE.test(de) || !DATE_RE.test(ate) || de > ate) return falha;
  const dias = (Date.parse(`${ate}T00:00:00Z`) - Date.parse(`${de}T00:00:00Z`)) / 86_400_000 + 1;
  if (dias > MAX_DIAS) return falha;

  const supabase = await createClient();
  const { data: sessao } = await supabase.auth.getSession();
  if (!sessao.session) return falha;

  try {
    const dw = await chamarEdgeFunction("sync-relatorios-dw", sessao.session.access_token, {
      from: de,
      to: ate,
      klingo_ids: [klingoId],
    });
    if (!dw.ok) {
      console.error("sync-relatorios-dw falhou:", dw.status, JSON.stringify(dw.payload));
      return { ...falha, dias, falhas: dias };
    }
    const falhas = Array.isArray(dw.payload?.erros) ? dw.payload.erros.length : 0;
    if (fim) {
      revalidatePath("/");
      revalidatePath("/metas");
    }
    return { ok: falhas === 0, linhas: dw.payload?.linhas_sincronizadas ?? 0, dias, falhas };
  } catch (err) {
    console.error("Falha ao atualizar relatório:", err instanceof Error ? err.message : err);
    return { ...falha, dias, falhas: dias };
  }
}
