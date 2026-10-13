import { RelatorioComErro, RespostaInvalida } from "./erros";
import type { ColunaApi, RespostaValida } from "./tipos";

const ESCALAR = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);

interface Opcoes {
  /** Confere se o Klingo aplicou mesmo o filtro de período pedido (chave errada NÃO dá erro: ele ignora e devolve "hoje"). */
  periodo?: { chave: string; codigo: string };
  /** Títulos de colunas que o painel precisa; se faltar alguma, a resposta é recusada. */
  exigidas?: string[];
  /** Relatório sem filtro de data: responde só com id; vazio vale como vazio. */
  semPeriodo?: boolean;
}

const resumo = (v: unknown) => String(typeof v === "string" ? v : JSON.stringify(v)).slice(0, 100);

/**
 * Confere a resposta ANTES de chegar ao banco (porte de validar_resposta em extrair_laudo.py).
 * Armadilhas medidas: erro vem com HTTP 200 {"status_code":400,"msg":...}; filtro errado vira "hoje" sem erro; período sem registros
 * vem como result:"" (string); a mesma célula vem ora número, ora texto (tudo é normalizado para texto).
 */
export function validarResposta(payload: unknown, idRelatorio: number, op: Opcoes = {}): RespostaValida {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new RespostaInvalida(`esperava um objeto JSON e veio ${Array.isArray(payload) ? "lista" : typeof payload}`);
  }
  const p = payload as Record<string, unknown>;
  if (!("id" in p) && !("result" in p)) {
    const msg = p.msg ?? p.message ?? p.error;
    throw new RelatorioComErro(msg ? `o Klingo devolveu erro: ${resumo(msg)}` : `a resposta não é um relatório (chaves: ${Object.keys(p).join(", ").slice(0, 100) || "nenhuma"})`);
  }
  if (p.error) throw new RelatorioComErro(`o Klingo devolveu erro para o relatório ${idRelatorio} (erro ${resumo(p.error)}): confira o período e os filtros`);
  const recebido = Number.parseInt(String(p.id), 10);
  if (recebido !== idRelatorio) throw new RespostaInvalida(`pedi o relatório ${idRelatorio} e o Klingo devolveu o ${resumo(p.id)}`);

  const resultado = p.result;
  if (op.periodo) {
    const filtros = (Array.isArray(p.inputs) ? p.inputs : []).filter((i): i is Record<string, unknown> => typeof i === "object" && i !== null);
    const achado = filtros.find((i) => i.id === op.periodo!.chave);
    if (!achado) {
      const dePeriodo = filtros.filter((i) => i.type === "per-date").map((i) => String(i.id));
      // Sem nenhum filtro de data E sem linhas, não há o que separar por período (ex.: relatório de glosas ainda vazio): vale como vazio.
      // Com linhas, ou com filtro de data de outro nome, o dado cairia no período errado ou repetido em cada mês: recusa.
      if (dePeriodo.length || (resultado && resultado !== "")) {
        throw new RespostaInvalida(`o relatório ${idRelatorio} não tem o filtro de período ${JSON.stringify(op.periodo.chave)} (filtros de data dele: ${dePeriodo.join(", ") || "nenhum"}; todos: ${filtros.map((i) => String(i.id)).join(", ") || "nenhum"}); confira "periodo" ou "sem_periodo" na configuração`);
      }
    } else if (achado.value !== op.periodo.codigo) {
      throw new RespostaInvalida(`o Klingo aplicou o período ${resumo(achado.value)} em vez de ${JSON.stringify(op.periodo.codigo)} no relatório ${idRelatorio}`);
    }
  }
  if (op.semPeriodo && resultado && typeof resultado === "object") {
    // sem filtro de data a resposta vem inteira; nada a conferir além da estrutura
  }

  const limit = Boolean(p.limit);
  if (!resultado) return { id: idRelatorio, limit, colunas: [], linhas: [] };   // período sem nenhum registro: "" (ou nada)
  if (typeof resultado !== "object" || Array.isArray(resultado)) throw new RespostaInvalida(`result veio como ${Array.isArray(resultado) ? "lista" : typeof resultado}; esperava um objeto`);
  const r = resultado as Record<string, unknown>;
  const colunas = r.columns, grupos = r.group_cols ?? [], dados = r.data;
  if (!Array.isArray(colunas) || colunas.length === 0) throw new RespostaInvalida("result.columns ausente ou vazio");
  if (!Array.isArray(grupos) || !Array.isArray(dados)) throw new RespostaInvalida("result.group_cols e result.data devem ser listas");

  const titulos = new Map<string, string>();   // name -> title
  for (const c of [...grupos, ...colunas] as ColunaApi[]) {
    if (typeof c !== "object" || c === null || typeof c.name !== "string" || !c.name || typeof c.title !== "string" || !c.title.trim()) {
      throw new RespostaInvalida(`coluna sem name/title: ${resumo(c)}`);
    }
    if (titulos.has(c.name)) throw new RespostaInvalida(`coluna repetida: ${JSON.stringify(c.name)}`);
    if ([...titulos.values()].includes(c.title)) throw new RespostaInvalida(`duas colunas com o mesmo título: ${JSON.stringify(c.title)}`);
    titulos.set(c.name, c.title);
  }
  const linhas: Record<string, string | boolean | null>[] = [];
  dados.forEach((linha, i) => {
    if (typeof linha !== "object" || linha === null || Array.isArray(linha)) throw new RespostaInvalida(`linha ${i + 1} não é um objeto`);
    const saida: Record<string, string | boolean | null> = {};
    for (const [k, v] of Object.entries(linha as Record<string, unknown>)) {
      const titulo = titulos.get(k);
      if (titulo === undefined) throw new RespostaInvalida(`linha ${i + 1} tem a chave ${JSON.stringify(k)}, que não é coluna do relatório`);
      if (!ESCALAR(v)) throw new RespostaInvalida(`linha ${i + 1}, coluna ${JSON.stringify(titulo)}: valor do tipo ${typeof v} (esperava texto, número ou vazio)`);
      // o mesmo pedido devolve o mesmo campo ora número (1) ora texto ("1"): tudo vira texto; bool e vazio não mudam
      saida[titulo] = typeof v === "number" ? String(v) : (v as string | boolean | null);
    }
    linhas.push(saida);
  });
  if (!limit) {   // com "limit" o Klingo avisa que cortou: quem pede decide (dividir o período)
    const anunciadas = Number.parseInt(String(r.rows), 10);
    if (!Number.isFinite(anunciadas)) throw new RespostaInvalida(`result.rows inválido: ${resumo(r.rows)}`);
    if (anunciadas !== dados.length) throw new RespostaInvalida(`o Klingo anunciou ${anunciadas} linhas e mandou ${dados.length} (resposta incompleta)`);
  }
  const todos = [...titulos.values()];
  const faltam = (op.exigidas ?? []).filter((t) => !todos.includes(t));
  if (faltam.length) throw new RespostaInvalida(`o relatório ${idRelatorio} não trouxe a(s) coluna(s) ${faltam.map((t) => JSON.stringify(t)).join(", ")}: o Klingo mudou o relatório?`);
  return { id: idRelatorio, limit, colunas: todos, linhas };
}
