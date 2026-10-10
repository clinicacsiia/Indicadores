import { createClient } from "jsr:@supabase/supabase-js@2";

// Sincroniza indicadores a partir do relatório "AGENDADOS X REALIZADOS" do Klingo.
// Só roda via pg_cron / painel do Supabase, nunca pelo navegador. O token do Klingo
// (KLINGO_APP_TOKEN) fica apenas nos secrets desta função.
//
// Minimização de dados (LGPD): o relatório vem por paciente, mas aqui ele é agregado
// em totais por dia. Nome de paciente e demais campos linha-a-linha NUNCA são gravados.

const KLINGO_URL = "https://api-externa.klingo.app/api/info/relatorio";
const KLINGO_REPORT_ID = "13397";
const MAX_BACKFILL_DAYS = 31;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Row = Record<string, unknown>;

// Só aceitamos o service_role: a verificação padrão de JWT também deixa passar a anon key,
// que é pública. Esta função consome a API externa e escreve com privilégio total.
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

async function fetchReport(day: string, token: string): Promise<Row[]> {
  const params = new URLSearchParams({
    id: KLINGO_REPORT_ID,
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

function toIndicadores(data: Row[], day: string) {
  const valorTotal = data.reduce((sum, r) => {
    const n = Number(r.col10);
    return sum + (Number.isFinite(n) ? n : 0);
  }, 0);

  // Agrupamento por plano guarda apenas contagens, sem identificar paciente.
  const porPlano: Record<string, number> = {};
  for (const r of data) {
    const plano = String(r.col3 ?? "N/I");
    porPlano[plano] = (porPlano[plano] ?? 0) + (Number(r.col1) || 0);
  }

  const base = { periodo: day, metadata: {} as Record<string, unknown> };
  return [
    {
      ...base,
      codigo: "agendamentos_total",
      nome: "Total de agendamentos",
      valor: data.reduce((s, r) => s + (Number(r.col1) || 0), 0),
      unidade: "agendamentos",
      metadata: { por_plano: porPlano },
    },
    {
      ...base,
      codigo: "atendimentos_finalizados",
      nome: "Atendimentos finalizados",
      valor: data.filter((r) => r.col9 === "S").length,
      unidade: "atendimentos",
    },
    {
      ...base,
      codigo: "atendimentos_avulsos",
      nome: "Atendimentos avulsos",
      valor: data.filter((r) => r.col8 === "S").length,
      unidade: "atendimentos",
    },
    {
      ...base,
      codigo: "valor_total_procedimentos",
      nome: "Valor total dos procedimentos",
      valor: Math.round(valorTotal * 100) / 100,
      unidade: "BRL",
    },
  ];
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

  // service_role só é usado aqui dentro e ignora RLS de propósito: as tabelas não têm
  // policy de escrita para authenticated/anon.
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data: run, error: runError } = await supabase
    .from("sync_runs")
    .insert({ status: "running" })
    .select()
    .single();
  if (runError || !run) return json({ error: "Falha ao registrar sync_run" }, 500);

  try {
    let synced = 0;
    for (const day of days) {
      const rows = toIndicadores(await fetchReport(day, token), day);
      const { error } = await supabase.from("indicadores").upsert(rows, { onConflict: "codigo,periodo" });
      if (error) throw new Error(`Falha ao gravar indicadores: ${error.message}`);
      synced += rows.length;
    }

    await supabase
      .from("sync_runs")
      .update({ status: "success", finished_at: new Date().toISOString(), records_synced: synced })
      .eq("id", run.id);
    return json({ synced, days: days.length });
  } catch (error) {
    await supabase
      .from("sync_runs")
      .update({
        status: "error",
        finished_at: new Date().toISOString(),
        error_message: error instanceof Error ? error.message : "Erro desconhecido",
      })
      .eq("id", run.id);
    return json({ error: "Falha na sincronização" }, 500);
  }
});
