/**
 * Configuração dos menus e dos relatórios. A fonte única é a pasta painel_py/<Menu>/relatorios.json (a mesma que o cálculo em Python lê),
 * copiada do legado sem alterar: ids, abas, períodos, chave, numeros, datas, revisar_meses, meses_a_frente...
 * Os ids de relatório do Klingo só existem aqui (a API exige); as telas mostram o nome.
 */
import atendimento from "../../painel_py/Atendimento/relatorios.json";
import cesta from "../../painel_py/Cesta/relatorios.json";
import despesas from "../../painel_py/Despesas/relatorios.json";
import faturamento from "../../painel_py/Faturamento/relatorios.json";
import financeiro from "../../painel_py/Financeiro/relatorios.json";
import indicadores from "../../painel_py/Indicadores/relatorios.json";
import suprimentos from "../../painel_py/Suprimentos/relatorios.json";
import metasCfg from "../../painel_py/Acompanhamento de META/metas.json";
import type { DefinicaoMenu, Relatorio } from "./tipos";

export const MENUS = ["metas", "faturamento", "financeiro", "despesas", "indicadores", "cesta", "suprimentos", "atendimento"] as const;
export type MenuId = (typeof MENUS)[number];

export const NOME_DO_MENU: Record<MenuId, string> = {
  metas: "Metas", faturamento: "Faturamento", financeiro: "Financeiro", despesas: "Despesas",
  indicadores: "Indicadores", cesta: "Cesta", suprimentos: "Suprimentos", atendimento: "Atendimento",
};

/** Metas é especial (tipo "metas"): vem do relatório base "Link dos dados das meta relatório" (#13339); "Exames Realizados" é um ID. */
export const RELATORIO_METAS: Relatorio = {
  id: 13339,
  aba: "Dados",
  descricao: "Atendimentos – Acompanhamento de Metas por Unidade e Procedimento – Mensal",
  periodo: "periodo0",
  chave: ["Exames Realizados"],
  numeros: ["Exames Realizados"],
  datas: { "Data do Atendimento": "dd/mm/yyyy hh:mm" },
  ordenar: ["Data do Atendimento", "Exames Realizados"],
};
export const COLUNAS_METAS_API = ["Exames Realizados", "Unidade", "Procedimento - Classes", "Especialidade", "Data do Atendimento", "Procedimento"];

export const DEFINICOES: Record<MenuId, DefinicaoMenu> = {
  metas: { titulo: "Metas", primeiro_mes: (metasCfg as { primeiro_mes: string }).primeiro_mes, relatorios: [RELATORIO_METAS] },
  faturamento: faturamento as unknown as DefinicaoMenu,
  financeiro: financeiro as unknown as DefinicaoMenu,
  despesas: despesas as unknown as DefinicaoMenu,
  indicadores: indicadores as unknown as DefinicaoMenu,
  cesta: cesta as unknown as DefinicaoMenu,
  suprimentos: suprimentos as unknown as DefinicaoMenu,
  atendimento: atendimento as unknown as DefinicaoMenu,
};

/** Quem consome os dados de quem (para pré-aquecer o cache dos painéis dependentes e compor a versão do cache). */
export const DEPENDE_DE: Record<MenuId, MenuId[]> = {
  metas: [], faturamento: [], financeiro: ["faturamento"], despesas: [],
  indicadores: ["faturamento", "financeiro"], cesta: ["faturamento"], suprimentos: ["atendimento"], atendimento: ["metas"],
};
export const DEPENDENTES_DE = (m: MenuId): MenuId[] => MENUS.filter((x) => DEPENDE_DE[x].includes(m));

/** "Atualizar agora" do Indicadores também atualiza Faturamento e Financeiro (os dados dele vêm deles). */
export const ATUALIZA_JUNTO: Partial<Record<MenuId, MenuId[]>> = { indicadores: ["faturamento", "financeiro"] };

export const ehMenu = (v: unknown): v is MenuId => typeof v === "string" && (MENUS as readonly string[]).includes(v);

export function primeiroMesDo(menu: MenuId, r: Relatorio): string {
  return r.primeiro_mes ?? DEFINICOES[menu].primeiro_mes;
}
