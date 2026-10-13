import { createClient, type SupabaseClient } from "jsr:@supabase/supabase-js@2";

// Sync genérico "data warehouse": varre os relatórios ativos em
// `dim_relatorio`, busca cada um no Klingo (um dia por vez) e grava as linhas
// cruas em `fact_relatorio_linha`, deduplicadas por hash de conteúdo.
//
// Princípios:
// - Nada é apagado. Linha igual à já gravada só atualiza last_seen_at; linha
//   com conteúdo novo vira um registro novo. Linhas idênticas dentro do mesmo
//   relatório/dia ficam num registro só, com a contagem em `repeticoes`.
// - Nada é "consertado" ou escondido sozinho. Tudo que merece olho humano
//   (erro de sync, coluna nova/ausente, linhas repetidas, dados que já existem
//   em outro relatório, nome de relatório repetido) vira um alerta em
//   `etl_alertas` (consulta: view v_etl_pendencias). Um alerta aberto não
//   para o sync — quem decide o que fazer é uma pessoa.
// - Um relatório falhando não derruba os outros: cada relatório/dia tem seu
//   próprio try/catch e sua linha em `sync_relatorio_runs`.
// - Sem martelar o Klingo: requisições sequenciais, com pausa entre elas, 1
//   retry em falha transitória e só relatórios com ativo=true. A função nunca
//   descobre relatórios testando IDs; novos relatórios entram pelo cadastro
//   manual em dim_relatorio.
// - Quem dispara: o botão "Atualizar" do site (admin logado, com `klingo_ids`) ou SQL com
//   service_role. Não há mais agendamento automático.
// - Relatórios com `supersedido_por` preenchido (decisão humana) são pulados.
//
// ATENÇÃO LGPD: ao contrário de sync-indicadores, esta função NÃO agrega nem
// filtra campos — grava a linha como o Klingo devolveu. Mantenha o relatório
// inativo até confirmar o que ele expõe.

const KLINGO_URL = "https://api-externa.klingo.app/api/info/relatorio";
const MAX_BACKFILL_DAYS = 31;
const UPSERT_CHUNK_SIZE = 500;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const FETCH_RETRIES = 1;
const RETRY_DELAY_MS = 1_000;
const REQUEST_DELAY_MS = 500;

type Row = Record<string, unknown>;
type Grupo = { linha: unknown; repeticoes: number };

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

// Quem pode chamar: service_role (SQL Editor / carga histórica) ou um admin logado
// no site (botão "Atualizar"). A anon key pública NÃO passa: ela não tem usuário.
// O admin é validado aqui com o JWT dele (nunca com service_role), via is_admin().
async function isAuthorizedCaller(req: Request): Promise<boolean> {
  if (isServiceRoleCaller(req)) return true;
  const authorization = req.headers.get("Authorization");
  if (!authorization) return false;
  const userClient = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_ANON_KEY")!,
    { global: { headers: { Authorization: authorization } }, auth: { persistSession: false } },
  );
  const { data: auth } = await userClient.auth.getUser();
  if (!auth.user) return false;
  const { data: isAdmin } = await userClient.rpc("is_admin");
  return isAdmin === true;
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

function resolveDays(body: Record<string, unknown>): string[] | null {
  const from = body.from;
  const to = body.to;
  if (from === undefined && to === undefined) return [todaySaoPaulo()];
  if (!DATE_RE.test(String(from)) || !DATE_RE.test(String(to))) return null;
  const days = daysBetween(String(from), String(to));
  if (days.length === 0 || days.length > MAX_BACKFILL_DAYS) return null;
  return days;
}

// `klingo_ids` opcional: atualiza só os relatórios escolhidos (botão "Atualizar"). Sem ele,
// varre todos os ativos. Retorna null se vier num formato inválido.
function resolveKlingoIds(body: Record<string, unknown>): string[] | undefined | null {
  const ids = body.klingo_ids;
  if (ids === undefined) return undefined;
  if (!Array.isArray(ids) || ids.length === 0 || ids.length > 20) return null;
  if (!ids.every((id) => typeof id === "string" && /^\d{1,10}$/.test(id))) return null;
  return ids as string[];
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// `titulos`: chave da coluna (col1, col2…) -> título que o Klingo dá a ela. Vazio quando o
// período não tem registros ou o Klingo não informou as colunas.
type Relatorio = { data: unknown[]; titulos: Record<string, string> };

async function fetchReportOnce(klingoId: string, day: string, token: string): Promise<Relatorio> {
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
  // Período sem nenhum registro: o Klingo devolve result = "" (sem erro) em vez de data = [].
  if (payload?.result === "") return { data: [], titulos: {} };
  const data = payload?.result?.data;
  if (!Array.isArray(data)) throw new Error("Formato inesperado na resposta do Klingo");
  return { data, titulos: extrairTitulos(payload.result) };
}

function extrairTitulos(result: unknown): Record<string, string> {
  const titulos: Record<string, string> = {};
  if (!isPlainObject(result)) return titulos;
  const colunas = [
    ...(Array.isArray(result.group_cols) ? result.group_cols : []),
    ...(Array.isArray(result.columns) ? result.columns : []),
  ];
  for (const coluna of colunas) {
    if (isPlainObject(coluna) && typeof coluna.name === "string" && typeof coluna.title === "string" && coluna.title.trim()) {
      titulos[coluna.name] = coluna.title.trim();
    }
  }
  return titulos;
}

async function fetchReport(klingoId: string, day: string, token: string): Promise<Relatorio> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= FETCH_RETRIES; attempt++) {
    try {
      return await fetchReportOnce(klingoId, day, token);
    } catch (error) {
      lastError = error;
      if (attempt < FETCH_RETRIES) await sleep(RETRY_DELAY_MS);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Falha desconhecida ao buscar relatório");
}

function isPlainObject(value: unknown): value is Row {
  return value !== null && typeof value === "object" && !Array.isArray(value);
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

async function hashLinha(row: unknown): Promise<string> {
  const data = new TextEncoder().encode(canonicalStringify(row));
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Agrupa linhas idênticas: o upsert falha se o mesmo lote tiver a mesma chave
// duas vezes, e colapsar sem contar subconta linhas legítimas. Guarda a
// contagem em `repeticoes`.
async function agruparLinhas(data: unknown[]): Promise<Map<string, Grupo>> {
  const hashes = await Promise.all(data.map(hashLinha));
  const grupos = new Map<string, Grupo>();
  data.forEach((linha, i) => {
    const grupo = grupos.get(hashes[i]);
    if (grupo) grupo.repeticoes += 1;
    else grupos.set(hashes[i], { linha, repeticoes: 1 });
  });
  return grupos;
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}

// Só o tipo do valor, nunca o valor: as linhas já vivem em
// fact_relatorio_linha e não faz sentido copiar conteúdo potencialmente
// sensível pro dicionário de colunas.
function tipoDe(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (typeof value === "string") return "string";
  if (Array.isArray(value)) return "array";
  if (typeof value === "object") return "object";
  return "desconhecido";
}

function colunasObservadas(data: unknown[]): Map<string, string> {
  const colunas = new Map<string, string>();
  for (const row of data) {
    if (!isPlainObject(row)) continue;
    for (const [key, value] of Object.entries(row)) {
      if (colunas.has(key) && colunas.get(key) !== "null") continue;
      colunas.set(key, tipoDe(value));
    }
  }
  return colunas;
}

type Alerta = {
  tipo: string;
  severidade: "erro" | "aviso" | "info";
  chave: string;
  mensagem: string;
  relatorioId: string;
  periodo: string;
  detalhes?: Record<string, unknown>;
  reabrir?: boolean;
};

// Alerta nunca derruba o sync: se registrar falhar, só vai pro log da função.
async function registrarAlerta(supabase: SupabaseClient, alerta: Alerta): Promise<void> {
  const { error } = await supabase.rpc("registrar_alerta", {
    p_tipo: alerta.tipo,
    p_severidade: alerta.severidade,
    p_chave: alerta.chave,
    p_mensagem: alerta.mensagem,
    p_relatorio_id: alerta.relatorioId,
    p_periodo: alerta.periodo,
    p_detalhes: alerta.detalhes ?? {},
    p_reabrir: alerta.reabrir ?? false,
  });
  if (error) console.error(`Falha ao registrar alerta ${alerta.tipo}: ${error.message}`);
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!(await isAuthorizedCaller(req))) return json({ error: "Forbidden" }, 403);

  const token = Deno.env.get("KLINGO_APP_TOKEN");
  if (!token) return json({ error: "KLINGO_APP_TOKEN não configurado nos secrets da função" }, 500);

  const body = await req.json().catch(() => ({}));
  const days = resolveDays(isPlainObject(body) ? body : {});
  if (!days) {
    return json({ error: `Informe {from,to} em AAAA-MM-DD, no máximo ${MAX_BACKFILL_DAYS} dias` }, 400);
  }
  const klingoIds = resolveKlingoIds(isPlainObject(body) ? body : {});
  if (klingoIds === null) return json({ error: "klingo_ids deve ser uma lista de 1 a 20 IDs numéricos" }, 400);

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  // Com klingo_ids, quem escolheu foi uma pessoa: vale mesmo que o relatório esteja com
  // ativo=false (a flag só decide quem entra numa varredura geral). Sem klingo_ids, só ativos.
  let consulta = supabase.from("dim_relatorio").select("id, klingo_id, nome, supersedido_por");
  consulta = klingoIds ? consulta.in("klingo_id", klingoIds) : consulta.eq("ativo", true);
  const { data: todosAtivos, error: relatoriosError } = await consulta;
  if (relatoriosError) return json({ error: `Falha ao ler dim_relatorio: ${relatoriosError.message}` }, 500);
  if (!todosAtivos || todosAtivos.length === 0) {
    return json({ error: klingoIds ? "Relatório não encontrado em dim_relatorio" : "Nenhum relatório ativo em dim_relatorio" }, 400);
  }

  // supersedido_por só é preenchido por uma pessoa; se ela marcou, respeita.
  const pulados = todosAtivos.filter((r) => r.supersedido_por);
  const relatorios = todosAtivos.filter((r) => !r.supersedido_por);
  if (relatorios.length === 0) {
    return json({ error: "Todos os relatórios ativos estão marcados como supersedidos" }, 400);
  }

  let totalLinhas = 0;
  let primeiraRequisicao = true;
  const erros: Array<{ relatorio: string; periodo: string; mensagem: string }> = [];

  for (const relatorio of relatorios) {
    const rotulo = `"${relatorio.nome}" (#${relatorio.klingo_id})`;

    for (const periodo of days) {
      const { data: run } = await supabase
        .from("sync_relatorio_runs")
        .insert({ relatorio_id: relatorio.id, periodo, status: "running" })
        .select()
        .single();

      if (!primeiraRequisicao) await sleep(REQUEST_DELAY_MS);
      primeiraRequisicao = false;

      try {
        const { data, titulos } = await fetchReport(relatorio.klingo_id, periodo, token);
        const grupos = await agruparLinhas(data);
        const agora = new Date().toISOString();

        const linhasPayload = Array.from(grupos.entries()).map(([linha_hash, grupo]) => ({
          relatorio_id: relatorio.id,
          periodo,
          linha: grupo.linha,
          linha_hash,
          repeticoes: grupo.repeticoes,
          last_seen_at: agora,
        }));

        for (const batch of chunk(linhasPayload, UPSERT_CHUNK_SIZE)) {
          const { error } = await supabase
            .from("fact_relatorio_linha")
            .upsert(batch, { onConflict: "relatorio_id,periodo,linha_hash" });
          if (error) throw new Error(`Falha ao gravar fact_relatorio_linha: ${error.message}`);
        }

        totalLinhas += data.length;
        if (run) {
          await supabase
            .from("sync_relatorio_runs")
            .update({ status: "success", finished_at: new Date().toISOString(), linhas_sincronizadas: data.length })
            .eq("id", run.id);
        }

        // --- Revisão (nada abaixo apaga ou altera dados já gravados) ---
        if (data.length === 0) continue;

        const invalidas = data.filter((row) => !isPlainObject(row)).length;
        if (invalidas > 0) {
          await registrarAlerta(supabase, {
            tipo: "linha_invalida",
            severidade: "aviso",
            chave: `linha_invalida:${relatorio.id}`,
            mensagem: `${rotulo} devolveu ${invalidas} linha(s) que não são um objeto de colunas em ${periodo}. Foram gravadas como vieram; conferir o relatório no Klingo.`,
            relatorioId: relatorio.id,
            periodo,
            detalhes: { periodo, linhas_invalidas: invalidas },
          });
        }

        const repetidas = Array.from(grupos.values()).filter((g) => g.repeticoes > 1);
        if (repetidas.length > 0) {
          const extras = repetidas.reduce((soma, g) => soma + g.repeticoes - 1, 0);
          await registrarAlerta(supabase, {
            tipo: "linhas_repetidas",
            severidade: "info",
            chave: `linhas_repetidas:${relatorio.id}`,
            mensagem: `${rotulo} tem linhas totalmente idênticas em ${periodo} (${repetidas.length} grupo(s), ${extras} linha(s) a mais). Foram mantidas, com a contagem em repeticoes. Pode ser legítimo (itens iguais) ou erro do relatório — conferir.`,
            relatorioId: relatorio.id,
            periodo,
            detalhes: { periodo, grupos_repetidos: repetidas.length, linhas_extras: extras },
          });
        }

        const observadas = colunasObservadas(data);
        const { data: existentes, error: existentesError } = await supabase
          .from("dim_relatorio_coluna")
          .select("coluna_key")
          .eq("relatorio_id", relatorio.id);
        if (existentesError) {
          console.error(`Falha ao ler dim_relatorio_coluna: ${existentesError.message}`);
        } else if (observadas.size > 0) {
          const jaConhecidas = new Set((existentes ?? []).map((c) => c.coluna_key as string));

          // Só compara layout quando já havia um mapa anterior; no primeiro
          // sync todas as colunas seriam "novas" e isso é só ruído.
          if (jaConhecidas.size > 0) {
            for (const key of observadas.keys()) {
              if (jaConhecidas.has(key)) continue;
              await registrarAlerta(supabase, {
                tipo: "coluna_nova",
                severidade: "aviso",
                chave: `coluna_nova:${relatorio.id}:${key}`,
                mensagem: `${rotulo} passou a trazer a coluna ${key}, que não existia antes. O Klingo pode ter mudado o layout do relatório — conferir o mapeamento (dim_relatorio_coluna.rotulo).`,
                relatorioId: relatorio.id,
                periodo,
                detalhes: { periodo, coluna: key },
              });
            }
            for (const key of jaConhecidas) {
              if (observadas.has(key)) continue;
              await registrarAlerta(supabase, {
                tipo: "coluna_ausente",
                severidade: "info",
                chave: `coluna_ausente:${relatorio.id}:${key}`,
                mensagem: `${rotulo} não trouxe a coluna ${key} em ${periodo}, que já tinha aparecido antes. Pode ser mudança de layout ou só um dia sem esse dado — conferir se persistir.`,
                relatorioId: relatorio.id,
                periodo,
                detalhes: { periodo, coluna: key },
              });
            }
          }

          // Título do Klingo só entra se vier para todas as colunas: num upsert em lote, uma
          // coluna sem título apagaria o que já estava gravado.
          const gravaTitulos = Array.from(observadas.keys()).every((key) => titulos[key]);
          const colunasPayload = Array.from(observadas.entries()).map(([coluna_key, tipo_observado]) => ({
            relatorio_id: relatorio.id,
            coluna_key,
            tipo_observado,
            last_seen_at: agora,
            ...(gravaTitulos ? { titulo_klingo: titulos[coluna_key] } : {}),
          }));
          const { error: colunaError } = await supabase
            .from("dim_relatorio_coluna")
            .upsert(colunasPayload, { onConflict: "relatorio_id,coluna_key" });
          if (colunaError) console.error(`Falha ao atualizar dim_relatorio_coluna: ${colunaError.message}`);
        }

        const { error: sobreposicaoError } = await supabase.rpc("analisar_sobreposicao_dados", {
          p_relatorio_id: relatorio.id,
          p_periodo: periodo,
        });
        if (sobreposicaoError) console.error(`Falha na análise de sobreposição: ${sobreposicaoError.message}`);
      } catch (error) {
        const mensagem = error instanceof Error ? error.message : "Erro desconhecido";
        erros.push({ relatorio: `${relatorio.nome} (#${relatorio.klingo_id})`, periodo, mensagem });
        if (run) {
          await supabase
            .from("sync_relatorio_runs")
            .update({ status: "error", finished_at: new Date().toISOString(), error_message: mensagem })
            .eq("id", run.id);
        }
        await registrarAlerta(supabase, {
          tipo: "sync_erro",
          severidade: "erro",
          chave: `sync_erro:${relatorio.id}:${mensagem}`,
          mensagem: `Falha ao sincronizar ${rotulo} em ${periodo}: ${mensagem}. Nenhum dado já gravado foi alterado.`,
          relatorioId: relatorio.id,
          periodo,
          detalhes: { periodo, erro: mensagem },
          reabrir: true,
        });
      }
    }
  }

  return json({
    relatorios_processados: relatorios.length,
    relatorios_pulados_supersedidos: pulados.map((r) => `${r.nome} (#${r.klingo_id})`),
    dias: days.length,
    linhas_sincronizadas: totalLinhas,
    erros,
    pendencias: "consulte a view v_etl_pendencias para alertas abertos",
  });
});
