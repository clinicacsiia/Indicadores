import { createClient } from "jsr:@supabase/supabase-js@2";

// Sync genérico "data warehouse": varre todos os relatórios cadastrados e
// ativos em `dim_relatorio`, busca cada um no Klingo (um dia por vez, igual
// ao sync-indicadores original) e grava as linhas cruas em
// `fact_relatorio_linha`, deduplicadas por hash de conteúdo.
//
// Diferente de sync-indicadores (que sempre recalcula e sobrescreve 4
// agregados por dia), aqui nada é apagado: uma linha igual à já gravada vira
// um no-op (só atualiza last_seen_at); uma linha com conteúdo novo vira um
// registro novo. Isso cobre o pedido de "ir atualizando só o que mudou" sem
// truncar e recarregar tudo a cada execução.
//
// Um relatório falhando (ex.: não aceita o parâmetro de período, token sem
// permissão) não derruba os outros: cada relatório/dia tem seu próprio
// try/catch e sua própria linha em `sync_relatorio_runs`.
//
// ATENÇÃO LGPD: ao contrário de sync-indicadores, esta função NÃO agrega nem
// filtra campos — grava a linha como o Klingo devolveu. Só relatórios com
// `ativo = true` em `dim_relatorio` rodam; mantenha inativo até confirmar o
// que cada relatório expõe.

const KLINGO_URL = "https://api-externa.klingo.app/api/info/relatorio";
const MAX_BACKFILL_DAYS = 31;
const UPSERT_CHUNK_SIZE = 500;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Row = Record<string, unknown>;

function isServiceRoleCaller(req: Request): boolean {
  const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer /i, "");
  const payloadSegment = token.split(".")[1];
  if (!payloadSegment) return false;
  try {
    const base64 = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64)).role === "service_role";
  } catch {
    return false;
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function todaySaoPaulo(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

function daysBetween(from: string, to: string): string[] {
  const days: string[] = [];
  const end = new Date(`${to}T00:00:00Z`);
  for (let d = new Date(`${from}T00:00:00Z`); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

async function resolveDays(req: Request): Promise<string[] | null> {
  const body = await req.json().catch(() => ({}));
  const from = body?.from;
  const to = body?.to;
  if (from === undefined && to === undefined) return [todaySaoPaulo()];
  if (!DATE_RE.test(String(from)) || !DATE_RE.test(String(to))) return null;
  const days = daysBetween(from, to);
  if (days.length === 0 || days.length > MAX_BACKFILL_DAYS) return null;
  return days;
}

async function fetchReport(klingoId: string, day: string, token: string): Promise<Row[]> {
  const params = new URLSearchParams({
    id: klingoId,
    ":periodo0": "l",
    ":periodo0-from": day,
    ":periodo0-to": day,
  });
  const res = await fetch(`${KLINGO_URL}?${params}`, {
    headers: { "X-APP-TOKEN": token },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`Klingo retornou HTTP ${res.status}`);

  const payload = await res.json();
  if (payload?.error) throw new Error("Klingo retornou erro no relatório");
  const data = payload?.result?.data;
  if (!Array.isArray(data)) throw new Error("Formato inesperado na resposta do Klingo");
  return data as Row[];
}

// Stringify com chaves ordenadas, pra duas linhas com o mesmo conteúdo (em
// ordens de chave diferentes) gerarem sempre o mesmo hash.
function canonicalStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalStringify).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    const entries = keys.map((k) => `${JSON.stringify(k)}:${canonicalStringify((value as Record<string, unknown>)[k])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}

async function hashLinha(row: Row): Promise<string> {
  const data = new TextEncoder().encode(canonicalStringify(row));
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!isServiceRoleCaller(req)) return json({ error: "Forbidden" }, 403);

  const token = Deno.env.get("KLINGO_APP_TOKEN");
  if (!token) return json({ error: "KLINGO_APP_TOKEN não configurado nos secrets da função" }, 500);

  const days = await resolveDays(req);
  if (!days) {
    return json({ error: `Informe {from,to} em AAAA-MM-DD, no máximo ${MAX_BACKFILL_DAYS} dias` }, 400);
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data: relatorios, error: relatoriosError } = await supabase
    .from("dim_relatorio")
    .select("id, klingo_id, nome")
    .eq("ativo", true);
  if (relatoriosError) return json({ error: `Falha ao ler dim_relatorio: ${relatoriosError.message}` }, 500);
  if (!relatorios || relatorios.length === 0) {
    return json({ error: "Nenhum relatório ativo em dim_relatorio" }, 400);
  }

  let totalLinhas = 0;
  const erros: Array<{ relatorio: string; periodo: string; mensagem: string }> = [];

  for (const relatorio of relatorios) {
    for (const periodo of days) {
      const { data: run } = await supabase
        .from("sync_relatorio_runs")
        .insert({ relatorio_id: relatorio.id, periodo, status: "running" })
        .select()
        .single();

      try {
        const data = await fetchReport(relatorio.klingo_id, periodo, token);
        const linhas = await Promise.all(
          data.map(async (linha) => ({
            relatorio_id: relatorio.id,
            periodo,
            linha,
            linha_hash: await hashLinha(linha),
            last_seen_at: new Date().toISOString(),
          })),
        );

        for (const batch of chunk(linhas, UPSERT_CHUNK_SIZE)) {
          const { error } = await supabase
            .from("fact_relatorio_linha")
            .upsert(batch, { onConflict: "relatorio_id,periodo,linha_hash" });
          if (error) throw new Error(`Falha ao gravar fact_relatorio_linha: ${error.message}`);
        }

        totalLinhas += linhas.length;
        if (run) {
          await supabase
            .from("sync_relatorio_runs")
            .update({ status: "success", finished_at: new Date().toISOString(), linhas_sincronizadas: linhas.length })
            .eq("id", run.id);
        }
      } catch (error) {
        const mensagem = error instanceof Error ? error.message : "Erro desconhecido";
        erros.push({ relatorio: `${relatorio.nome} (#${relatorio.klingo_id})`, periodo, mensagem });
        if (run) {
          await supabase
            .from("sync_relatorio_runs")
            .update({ status: "error", finished_at: new Date().toISOString(), error_message: mensagem })
            .eq("id", run.id);
        }
      }
    }
  }

  return json({
    relatorios_processados: relatorios.length,
    dias: days.length,
    linhas_sincronizadas: totalLinhas,
    erros,
  });
});
