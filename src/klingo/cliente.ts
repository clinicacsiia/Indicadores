import { FalhaDeRede, RelatorioComErro, RespostaInvalida, TokenInvalido, LimiteAtingido } from "./erros";
import { validarResposta } from "./validar";
import { diaSeguinte, pontoMedio } from "./datas";
import type { FiltroPeriodo, RespostaValida } from "./tipos";

export const API_EXTERNA = "https://api-externa.klingo.app/api/info/relatorio";
/** Códigos de período aceitos pela API: l livre, lh, lm, ld, aa, a, ma, m, h, o, do, t, s, u3, u6, u9. */
export const CODIGOS_PERIODO = ["l", "lh", "lm", "ld", "aa", "a", "ma", "m", "h", "o", "do", "t", "s", "u3", "u6", "u9"];

export interface OpcoesCliente {
  /** Token da API (padrão: KLINGO_APP_TOKEN). Nunca vai para log nem para mensagem. */
  token?: string;
  fetchImpl?: typeof fetch;
  esperar?: (ms: number) => Promise<void>;
  tentativas?: number;            // rede/5xx/429: 3
  timeoutMs?: number;
  pausaEntreChamadasMs?: number;  // cota de 1000 pedidos por janela: varredura SEQUENCIAL com ~0,8 s de pausa
  aoConsultar?: (info: { restante: string | null }) => void;
}

const dormir = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function lerToken(env: Record<string, string | undefined> = process.env): string {
  const token = (env.KLINGO_APP_TOKEN ?? "").trim();
  if (!token) throw new TokenInvalido("Falta o token da API do Klingo (variável KLINGO_APP_TOKEN no servidor).");
  if (!/^[\x21-\x7e]{8,200}$/.test(token)) throw new TokenInvalido("O token da API do Klingo está em formato inválido: deve ser uma linha só, sem espaços.");
  return token;
}

const trecho = (t: string) => t.replace(/\s+/g, " ").trim().slice(0, 160);

/** GET com X-APP-TOKEN e tentativas. 401/403 = TokenInvalido; 429 espera e repete; 5xx e rede repetem; outro 4xx = erro do relatório. */
export async function baixarTexto(url: string, op: OpcoesCliente = {}): Promise<string> {
  const f = op.fetchImpl ?? fetch, esperar = op.esperar ?? dormir, max = op.tentativas ?? 3, token = op.token ?? lerToken();
  let motivo = "";
  for (let n = 1; n <= max; n++) {
    let espera = 2000 * n;
    try {
      const r = await f(url, {
        headers: { "X-APP-TOKEN": token, Accept: "application/json", "Accept-Encoding": "gzip", "User-Agent": "PortalCSI/1.0" },
        signal: AbortSignal.timeout(op.timeoutMs ?? 50_000),
      });
      op.aoConsultar?.({ restante: r.headers.get("X-RateLimit-Remaining") });
      if (r.ok) return await r.text();
      const texto = trecho(await r.text().catch(() => ""));
      if (r.status === 401 || r.status === 403) throw new TokenInvalido(`O Klingo recusou o token da API (HTTP ${r.status}: ${texto || "sem detalhe"}).`);
      if (r.status === 429) {
        const ra = Number.parseInt(r.headers.get("Retry-After") ?? "", 10);
        if (Number.isFinite(ra)) espera = Math.min(Math.max(ra, 1), 60) * 1000;
        motivo = "limite de requisições do Klingo atingido (HTTP 429)";
      } else if (r.status >= 500) motivo = `o servidor do Klingo falhou (HTTP ${r.status})`;
      else throw new RelatorioComErro(`o Klingo recusou o pedido (HTTP ${r.status}: ${texto || "sem detalhe"})`);
    } catch (e) {
      if (e instanceof TokenInvalido || e instanceof RelatorioComErro) throw e;
      motivo = `sem resposta do Klingo (${e instanceof Error ? e.name : "erro"})`;
    }
    if (n < max) await esperar(espera);
  }
  throw new FalhaDeRede(`Não consegui falar com a API do Klingo depois de ${max} tentativas: ${motivo}.`);
}

/** Monta a URL: id + filtros com o ':' que o Klingo usa nos nomes (%3A). */
export function montarUrl(id: number, filtros: Record<string, string> = {}): string {
  const q = new URLSearchParams({ id: String(id) });
  for (const [k, v] of Object.entries(filtros)) q.set(`:${k}`, v);
  return `${API_EXTERNA}?${q.toString()}`;
}

export interface PedidoRelatorio {
  id: number;
  filtros?: Record<string, string>;
  periodo?: FiltroPeriodo;
  exigidas?: string[];
  semPeriodo?: boolean;
}

export async function consultarRelatorio(p: PedidoRelatorio, op: OpcoesCliente = {}): Promise<RespostaValida> {
  const corpo = await baixarTexto(montarUrl(p.id, p.filtros), op);
  let payload: unknown;
  try { payload = JSON.parse(corpo); } catch { throw new RespostaInvalida(`a resposta do Klingo não é um JSON válido (começa com: ${JSON.stringify(trecho(corpo).slice(0, 80))})`); }
  return validarResposta(payload, p.id, { periodo: p.periodo, exigidas: p.exigidas, semPeriodo: p.semPeriodo });
}

/**
 * Baixa [de, ate] (livre: l + from/to). Se o Klingo avisar que cortou (limit: true), divide o período ao meio e junta; se não der para
 * dividir mais (um dia só), é erro: nunca trunca calado.
 */
export async function baixarIntervalo(id: number, filtroId: string, de: string, ate: string, op: OpcoesCliente & { exigidas?: string[] } = {}): Promise<RespostaValida> {
  const esperar = op.esperar ?? dormir;
  const r = await consultarRelatorio({
    id, exigidas: op.exigidas, periodo: { chave: filtroId, codigo: "l" },
    filtros: { [filtroId]: "l", [`${filtroId}-from`]: de, [`${filtroId}-to`]: ate },
  }, op);
  if (!r.limit) return r;
  if (de >= ate) throw new LimiteAtingido(`o Klingo cortou o resultado do relatório ${id} em ${de} e não dá para dividir mais`);
  const meio = pontoMedio(de, ate);
  if (op.pausaEntreChamadasMs) await esperar(op.pausaEntreChamadasMs);
  const a = await baixarIntervalo(id, filtroId, de, meio, op);
  if (op.pausaEntreChamadasMs) await esperar(op.pausaEntreChamadasMs);
  const b = await baixarIntervalo(id, filtroId, diaSeguinte(meio), ate, op);
  const colunas = [...new Set([...a.colunas, ...b.colunas])];
  return { id, limit: false, colunas, linhas: [...a.linhas, ...b.linhas] };
}

/** Relatório com período em código (m, ma, a...) ou sem filtro de data (sem_periodo: responde só com id). */
export async function baixarPorCodigo(id: number, filtroId: string, codigo: string, op: OpcoesCliente & { exigidas?: string[] } = {}): Promise<RespostaValida> {
  return consultarRelatorio({ id, exigidas: op.exigidas, periodo: { chave: filtroId, codigo }, filtros: { [filtroId]: codigo } }, op);
}

export async function baixarSemPeriodo(id: number, op: OpcoesCliente & { exigidas?: string[] } = {}): Promise<RespostaValida> {
  return consultarRelatorio({ id, exigidas: op.exigidas, semPeriodo: true }, op);
}
