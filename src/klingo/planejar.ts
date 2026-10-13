import { DEFINICOES, primeiroMesDo, type MenuId } from "./config";
import { mesMais, mesesEntre } from "./datas";
import type { Relatorio } from "./tipos";

export interface ItemPlanejado {
  relatorio: Relatorio;
  mes: string | null;       // null = relatório sem filtro de data
  motivo: "revisar" | "faltando" | "sempre" | "futuro" | "inteiro";
}

/**
 * Quais (relatório, mês) baixar para atualizar um menu (regras do relatorios.json do legado):
 *  - sem_periodo: baixa inteiro e substitui a aba;
 *  - revisar_meses = N: sempre rebaixa os N meses mais recentes (até o corrente) e baixa os que faltam desde primeiro_mes;
 *  - sem revisar_meses (com ou sem chave): rebaixa TODOS os meses desde primeiro_mes (o status muda com o tempo);
 *  - meses_a_frente = N: baixa também os N meses futuros;
 *  - Metas: o mês corrente, mais o anterior nos primeiros 5 dias (fecha o mês), mais os que faltam desde primeiro_mes.
 * `existentes` = "aba|mes" que já estão no banco.
 */
export function planejarMenu(menu: MenuId, existentes: Set<string>, hoje: { ym: string; dia: number }): ItemPlanejado[] {
  const itens: ItemPlanejado[] = [];
  for (const r of DEFINICOES[menu].relatorios) {
    if (r.sem_periodo) { itens.push({ relatorio: r, mes: null, motivo: "inteiro" }); continue; }
    const primeiro = primeiroMesDo(menu, r);
    const frente = r.meses_a_frente ?? 0;
    const ate = mesMais(hoje.ym, frente);
    const todos = primeiro <= ate ? mesesEntre(primeiro, ate) : [];
    const escolhidos = new Map<string, ItemPlanejado["motivo"]>();
    const rebaixar = (m: string, motivo: ItemPlanejado["motivo"]) => { if (!escolhidos.has(m)) escolhidos.set(m, motivo); };
    if (menu === "metas") {
      rebaixar(hoje.ym, "revisar");
      if (hoje.dia <= 5) rebaixar(mesMais(hoje.ym, -1), "revisar");
    } else if (r.revisar_meses) {
      for (let i = 0; i < r.revisar_meses; i++) rebaixar(mesMais(hoje.ym, -i), "revisar");
    } else {
      for (const m of todos) if (m <= hoje.ym) rebaixar(m, "sempre");
    }
    for (const m of todos) {
      if (m > hoje.ym) rebaixar(m, "futuro");
      else if (!existentes.has(`${r.aba}|${m}`)) rebaixar(m, "faltando");
    }
    for (const [m, motivo] of [...escolhidos].sort(([a], [b]) => (a < b ? -1 : 1))) {
      if (m >= primeiro || motivo === "revisar") itens.push({ relatorio: r, mes: m, motivo });
    }
  }
  return itens;
}
