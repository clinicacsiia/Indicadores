import { mesesDisponiveis, type MetasConfig } from "./calculo";
import { primeiroMesValido } from "../inicio-klingo";
// Única fonte das metas e das regras: o mesmo arquivo do painel local ("Acompanhamento de META").
// A meta de base é a deste arquivo; mudanças feitas em Configurações (tabela metas_valor) valem do mês escolhido em diante e vencem o arquivo.
import metas from "../../Acompanhamento de META/metas.json";

export const metasConfig = metas as unknown as MetasConfig;

/** Código do relatório do Klingo que alimenta as metas. */
export const RELATORIO_METAS = "13339";

/** Os serviços com meta, na ordem da tela. `chave` é "grupo/item" (a mesma do metas.json e da tabela metas_valor). */
export const SERVICOS_METAS = metasConfig.grupos.flatMap((g) =>
  g.itens.map((i) => ({ chave: `${g.id}/${i.id}`, grupo: g.nome, nome: i.nome, padrao: i.meta }))
);

const MESES_A_FRENTE = 12;

/** Meses em que dá para começar uma mudança de meta: do primeiro mês das Metas até 12 meses depois do atual (mais antigo primeiro). */
export function mesesParaMudarMeta(mesAtual: string): string[] {
  const [a, m] = mesAtual.split("-").map(Number);
  const fim = new Date(Date.UTC(a, m - 1 + MESES_A_FRENTE, 1)).toISOString().slice(0, 7);
  return mesesDisponiveis(primeiroMesValido(metasConfig.primeiro_mes), fim).reverse();
}
