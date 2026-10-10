import { createClient } from "jsr:@supabase/supabase-js@2";

// Job de sincronização: busca os indicadores na API externa e grava no Supabase.
// Nunca é chamado pelo navegador — só pelo pg_cron (ver migration schedule_sync_indicadores)
// ou manualmente pelo painel do Supabase. A chave da API externa (EXTERNAL_API_KEY)
// fica só nos secrets da Edge Function, nunca no código ou no front-end.
// A plataforma (verify_jwt) só garante que o Authorization é um JWT válido do projeto —
// a anon key pública também passa nessa checagem. Como essa função faz uma operação
// privilegiada (grava no banco via service_role e consome a API externa), exigimos
// explicitamente que o caller seja o service_role, nunca anon/authenticated.
// Isso bloqueia qualquer chamada feita a partir do site público, mesmo com a anon key.
function isServiceRoleCaller(req: Request): boolean {
  const authHeader = req.headers.get("Authorization") ?? "";
  const token = authHeader.replace(/^Bearer /i, "");
  const payloadSegment = token.split(".")[1];
  if (!payloadSegment) return false;

  try {
    const base64 = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(base64));
    return claims.role === "service_role";
  } catch {
    return false;
  }
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  if (!isServiceRoleCaller(req)) {
    return new Response(JSON.stringify({ error: "Forbidden" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  }

  const apiUrl = Deno.env.get("EXTERNAL_API_URL");
  const apiKey = Deno.env.get("EXTERNAL_API_KEY");
  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

  if (!apiUrl || !apiKey) {
    return new Response(
      JSON.stringify({ error: "EXTERNAL_API_URL/EXTERNAL_API_KEY não configurados nos secrets da função" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  // service_role: só usado aqui dentro, nunca exposto ao cliente. Ignora RLS de propósito
  // para poder escrever em indicadores/sync_runs, que não têm policy de insert para authenticated/anon.
  const supabase = createClient(supabaseUrl, serviceRoleKey);

  const { data: run, error: runError } = await supabase
    .from("sync_runs")
    .insert({ status: "running" })
    .select()
    .single();

  if (runError || !run) {
    return new Response(JSON.stringify({ error: "Falha ao registrar sync_run" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const apiResponse = await fetch(apiUrl, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });

    if (!apiResponse.ok) {
      throw new Error(`API externa retornou ${apiResponse.status}`);
    }

    const payload = await apiResponse.json();
    // TODO: ajustar esse mapeamento para o formato real da API externa assim que ela for definida.
    const registros = Array.isArray(payload) ? payload : payload.data ?? [];

    const rows = registros.map((item: Record<string, unknown>) => ({
      codigo: String(item.codigo),
      nome: String(item.nome),
      valor: Number(item.valor),
      unidade: item.unidade ? String(item.unidade) : null,
      periodo: String(item.periodo),
      metadata: item,
    }));

    if (rows.length > 0) {
      const { error: upsertError } = await supabase
        .from("indicadores")
        .upsert(rows, { onConflict: "codigo,periodo" });

      if (upsertError) throw upsertError;
    }

    await supabase
      .from("sync_runs")
      .update({
        status: "success",
        finished_at: new Date().toISOString(),
        records_synced: rows.length,
      })
      .eq("id", run.id);

    return new Response(JSON.stringify({ synced: rows.length }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    await supabase
      .from("sync_runs")
      .update({
        status: "error",
        finished_at: new Date().toISOString(),
        error_message: error instanceof Error ? error.message : String(error),
      })
      .eq("id", run.id);

    return new Response(JSON.stringify({ error: String(error) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
