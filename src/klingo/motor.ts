/**
 * Motor de sincronização com o Klingo, em fila (a Vercel limita o tempo de cada função):
 *  - enfileirarAtualizacao: um item por (relatório, mês) + itens "aquecer" (pré-cálculo do cache dos painéis);
 *  - processarFila: pega um item por vez, baixa, confere, grava em transação e segue até acabar o orçamento de tempo.
 * Sequencial de propósito (a cota do Klingo é 1000 pedidos por janela; um ciclo completo faz ~70).
 */
import type { SupabaseClient } from "@supabase/supabase-js";
import { baixarIntervalo, baixarPorCodigo, baixarSemPeriodo, type OpcoesCliente } from "./cliente";
import { ATUALIZA_JUNTO, COLUNAS_METAS_API, DEFINICOES, DEPENDENTES_DE, type MenuId } from "./config";
import { hojeSalvador, mesMais, primeiroDia, ultimoDia } from "./datas";
import { ErroApiKlingo, FalhaDeRede, RelatorioComErro, TokenInvalido } from "./erros";
import { blocosExistentes, gravarBloco, lerBloco } from "./gravar";
import { linhasDeMetas } from "./metas";
import { planejarMenu } from "./planejar";
import type { Relatorio, RespostaValida } from "./tipos";
import { mesclarPorChave, tipar, type Tabela } from "./transformar";

export interface ItemFila {
  id: number;
  lote: string;
  menu: MenuId;
  tipo: "baixar" | "aquecer";
  relatorio_id: number | null;
  aba: string | null;
  mes: string | null;
  tentativas: number;
  usuario: string;
  criado_em: string;
}

export interface Deps {
  sb: SupabaseClient;
  cliente?: OpcoesCliente;
  agora?: () => Date;
  esperar?: (ms: number) => Promise<void>;
  /** Pré-aquece o cache do painel de um menu (chama o cálculo em Python). */
  aquecer?: (menu: MenuId) => Promise<void>;
  /** Substitui o download (testes). */
  baixar?: (item: ItemFila, r: Relatorio) => Promise<RespostaValida>;
}

const dormir = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
export const PAUSA_ENTRE_CHAMADAS_MS = 800;

// ------------------------------------------------------------------ enfileirar
export async function enfileirarAtualizacao(deps: Deps, menus: MenuId[], usuario: string): Promise<{ lote: string; itens: number; menus: MenuId[] }> {
  const { sb } = deps;
  const lote = crypto.randomUUID();
  const hoje = hojeSalvador(deps.agora?.());
  const todos = [...new Set(menus.flatMap((m) => [m, ...(ATUALIZA_JUNTO[m] ?? [])]))] as MenuId[];
  const linhas: Record<string, unknown>[] = [];
  for (const menu of todos) {
    const existentes = await blocosExistentes(sb, menu);
    for (const it of planejarMenu(menu, existentes, { ym: hoje.ym, dia: hoje.dia })) {
      linhas.push({ lote, menu, tipo: "baixar", relatorio_id: it.relatorio.id, aba: it.relatorio.aba, mes: it.mes, usuario });
    }
  }
  const aquecer = [...new Set(todos.flatMap((m) => [m, ...DEPENDENTES_DE(m)]))];
  for (const menu of aquecer) linhas.push({ lote, menu, tipo: "aquecer", usuario });
  for (let i = 0; i < linhas.length; i += 200) {
    const { error } = await sb.from("fila_sincronizacao").insert(linhas.slice(i, i + 200));
    if (error) throw new Error(`enfileirar: ${error.message}`);
  }
  return { lote, itens: linhas.length, menus: todos };
}

// ------------------------------------------------------------------ executar um item
function relatorioDoItem(item: ItemFila): Relatorio {
  const r = DEFINICOES[item.menu]?.relatorios.find((x) => x.id === item.relatorio_id && x.aba === item.aba);
  if (!r) throw new RelatorioComErro(`relatório ${item.relatorio_id} (${item.aba}) não está configurado em ${item.menu}`);
  return r;
}

async function baixarItem(deps: Deps, item: ItemFila, r: Relatorio): Promise<RespostaValida> {
  if (deps.baixar) return deps.baixar(item, r);
  const op = { ...deps.cliente, esperar: deps.esperar, pausaEntreChamadasMs: PAUSA_ENTRE_CHAMADAS_MS };
  const filtro = r.periodo ?? "periodo0";
  if (r.sem_periodo || item.mes === null) return baixarSemPeriodo(r.id, op);
  if (item.menu === "metas") {   // porte de extrair_laudo.py: mês atual = "m", mês anterior = "ma"; os demais, intervalo livre
    const hoje = hojeSalvador(deps.agora?.());
    const exigidas = COLUNAS_METAS_API;
    if (item.mes === hoje.ym) return baixarPorCodigo(r.id, filtro, "m", { ...op, exigidas });
    if (item.mes === mesMais(hoje.ym, -1)) return baixarPorCodigo(r.id, filtro, "ma", { ...op, exigidas });
    return baixarIntervalo(r.id, filtro, primeiroDia(item.mes), ultimoDia(item.mes), { ...op, exigidas });
  }
  return baixarIntervalo(r.id, filtro, primeiroDia(item.mes), ultimoDia(item.mes), op);
}

/** Baixa, confere e grava um relatório-mês. Devolve avisos (nunca grava se a resposta não passar na conferência). */
export async function executarItem(deps: Deps, item: ItemFila): Promise<string[]> {
  const r = relatorioDoItem(item);
  const resp = await baixarItem(deps, item, r);
  const hoje = hojeSalvador(deps.agora?.());
  const mesGravado = item.mes ?? hoje.ym;   // relatório sem filtro de data: "Mês (filtro)" = mês em que foi baixado

  let tabela: Tabela;
  if (item.menu === "metas") tabela = linhasDeMetas(resp);
  else tabela = tipar(resp, r);

  const avisos = [...tabela.avisos];
  if (r.chave && !r.sem_periodo && resp.linhas.length) {
    const antigo = await lerBloco(deps.sb, item.menu, r.aba, mesGravado);
    const { tabela: mesclada, descartadas } = mesclarPorChave(antigo, tabela, r.chave);
    if (descartadas) avisos.push(`${descartadas} linha(s) de ${r.aba} sem a chave completa foram ignoradas`);
    tabela = mesclada;
  }
  await gravarBloco(deps.sb, item.menu, r.aba, mesGravado, tabela, Boolean(r.sem_periodo));
  return avisos;
}

// ------------------------------------------------------------------ fila
async function marcar(sb: SupabaseClient, id: number, campos: Record<string, unknown>) {
  const { error } = await sb.from("fila_sincronizacao").update(campos).eq("id", id);
  if (error) throw new Error(`atualizar fila: ${error.message}`);
}

async function pendentesDoLote(sb: SupabaseClient, lote: string, tipo?: "baixar" | "aquecer"): Promise<number> {
  let q = sb.from("fila_sincronizacao").select("id", { count: "exact", head: true }).eq("lote", lote).in("estado", ["pendente", "executando"]);
  if (tipo) q = q.eq("tipo", tipo);
  const { count, error } = await q;
  if (error) throw new Error(`contar fila: ${error.message}`);
  return count ?? 0;
}

/** Termina a parte "baixar" do lote: histórico por menu, versão dos dados (muda o cache e avisa os painéis abertos via Realtime). */
export async function concluirBaixas(deps: Deps, lote: string, abortado?: "token_invalido" | "rede"): Promise<void> {
  const { sb } = deps;
  const { data: itens, error } = await sb.from("fila_sincronizacao").select("*").eq("lote", lote).eq("tipo", "baixar");
  if (error) throw new Error(`ler lote: ${error.message}`);
  const porMenu = new Map<string, typeof itens>();
  for (const it of itens ?? []) porMenu.set(it.menu, [...(porMenu.get(it.menu) ?? []), it]);
  for (const [menu, lista] of porMenu) {
    const ok = lista.filter((i) => i.estado === "ok"), erro = lista.filter((i) => i.estado === "erro"), pulado = lista.filter((i) => i.estado === "pulado");
    let status = "ok";
    if (abortado === "token_invalido") status = "token_invalido";
    else if (abortado === "rede" && !ok.length) status = "erro";
    else if (erro.length || pulado.length) status = ok.length ? "aviso" : "erro";
    const inicio = Math.min(...lista.map((i) => Date.parse(i.criado_em))), fim = Math.max(...lista.map((i) => Date.parse(i.finalizado_em ?? i.criado_em)));
    const partes = [`${ok.length} de ${lista.length} relatório(s)/mês(es) atualizados`];
    if (erro.length) partes.push(`com problema: ${[...new Set(erro.map((i) => `${i.aba}${i.mes ? " " + i.mes : ""}: ${i.erro ?? "erro"}`))].slice(0, 3).join(" | ")}`);
    if (pulado.length) partes.push(`${pulado.length} não executado(s)`);
    await sb.from("historico_atualizacoes").insert({
      modulo_id: menu, status, mensagem: partes.join("; ").slice(0, 600), duracao_segundos: Math.max(0, (fim - inicio) / 1000), usuario: lista[0].usuario,
    });
    if (ok.length) {
      const { error: e2 } = await sb.rpc("subir_versao", { p_menu: menu });
      if (e2) throw new Error(`subir versão de ${menu}: ${e2.message}`);
    }
  }
  await sb.rpc("podar_historico");
}

export interface ResultadoFila { processados: number; restantes: number; lotesConcluidos: number }

/**
 * Processa itens até acabar a fila ou o orçamento de tempo. Só um processador por vez (lease). TokenInvalido e queda de rede abortam o lote
 * (status token_invalido/erro no histórico); resposta fora do formato derruba só aquele relatório/mês (vira aviso, o resto segue).
 */
export async function processarFila(deps: Deps, orcamentoMs = 40_000): Promise<ResultadoFila> {
  const { sb } = deps;
  const esperar = deps.esperar ?? dormir;
  const inicio = Date.now();
  const res: ResultadoFila = { processados: 0, restantes: 0, lotesConcluidos: 0 };
  const { data: pegou, error: errLease } = await sb.rpc("pegar_lease", { p_segundos: Math.ceil(orcamentoMs / 1000) + 30 });
  if (errLease) throw new Error(`lease: ${errLease.message}`);
  if (!pegou) { res.restantes = -1; return res; }   // outro processador está rodando
  try {
    while (Date.now() - inicio < orcamentoMs) {
      const { data: reservado, error } = await sb.rpc("reservar_item_fila");
      if (error) throw new Error(`reservar item: ${error.message}`);
      const item = reservado as ItemFila | null;
      if (!item || !item.id) break;
      res.processados++;
      await sb.rpc("estender_trava", { p_minutos: 5 });
      let abortar: "token_invalido" | "rede" | undefined;
      try {
        if (item.tipo === "aquecer") {
          let aviso: string | null = null;
          try { await deps.aquecer?.(item.menu); } catch (e) { aviso = `cache não aquecido: ${(e as Error).message}`.slice(0, 300); }   // o painel se calcula na primeira abertura
          await marcar(sb, item.id, { estado: "ok", erro: aviso, finalizado_em: new Date().toISOString() });
        } else {
          const avisos = await executarItem(deps, item);
          await marcar(sb, item.id, { estado: "ok", erro: avisos.length ? avisos.join("; ").slice(0, 300) : null, finalizado_em: new Date().toISOString() });
          await esperar(PAUSA_ENTRE_CHAMADAS_MS);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (e instanceof TokenInvalido) abortar = "token_invalido";
        else if (e instanceof FalhaDeRede) abortar = "rede";
        if (abortar) {
          await marcar(sb, item.id, { estado: "erro", erro: msg.slice(0, 300), finalizado_em: new Date().toISOString() });
          await sb.from("fila_sincronizacao").update({ estado: "pulado", finalizado_em: new Date().toISOString() }).eq("lote", item.lote).eq("estado", "pendente").eq("tipo", "baixar");
        } else if (e instanceof ErroApiKlingo) {   // este relatório/mês fica como estava e vira aviso; o resto segue
          await marcar(sb, item.id, { estado: "erro", erro: msg.slice(0, 300), finalizado_em: new Date().toISOString() });
        } else {   // erro nosso (banco, rede interna): tenta de novo até 3 vezes
          const tent = item.tentativas + 1;
          await marcar(sb, item.id, tent >= 3 ? { estado: "erro", erro: msg.slice(0, 300), tentativas: tent, finalizado_em: new Date().toISOString() } : { estado: "pendente", erro: msg.slice(0, 300), tentativas: tent });
        }
      }
      if (item.tipo === "baixar" && (abortar || (await pendentesDoLote(sb, item.lote, "baixar")) === 0)) {
        // com abortar, os "aquecer" do lote também não fazem sentido: nada mudou
        if (abortar) await sb.from("fila_sincronizacao").update({ estado: "pulado", finalizado_em: new Date().toISOString() }).eq("lote", item.lote).eq("estado", "pendente");
        await concluirBaixas(deps, item.lote, abortar);
      }
      if ((await pendentesDoLote(sb, item.lote)) === 0) { await sb.rpc("liberar_trava"); res.lotesConcluidos++; }
    }
  } finally {
    await sb.rpc("soltar_lease");
  }
  const { count } = await sb.from("fila_sincronizacao").select("id", { count: "exact", head: true }).eq("estado", "pendente");
  res.restantes = count ?? 0;
  return res;
}
