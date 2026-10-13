export type Celula = string | number | boolean | null;

/** Uma definição de relatorios.json (campos do legado, todos portados). */
export interface Relatorio {
  id: number;
  aba: string;
  descricao?: string;
  periodo?: string;            // id do filtro de período: periodo0 (padrão), periodo (#26), PERIODO (#798)
  sem_periodo?: boolean;       // relatório sem filtro de data: baixa inteiro e substitui a aba
  primeiro_mes?: string;
  revisar_meses?: number;      // quantos meses recentes rebaixar sempre
  meses_a_frente?: number;     // baixar também meses futuros
  chave?: string[];            // upsert por esta chave
  ordenar?: string[];
  numeros?: string[];
  datas?: Record<string, string>;
  limpar_apostrofo?: string[];
  alerta_datas?: unknown;
  ajustar_ao_faturamento?: boolean;
}

export interface DefinicaoMenu {
  titulo: string;
  primeiro_mes: string;
  relatorios: Relatorio[];
  [k: string]: unknown;
}

export interface ColunaApi { name: string; title: string }

/** Resposta já conferida e normalizada: linhas por TÍTULO de coluna, células em texto (ou vazio). */
export interface RespostaValida {
  id: number;
  limit: boolean;
  colunas: string[];                         // títulos, na ordem
  linhas: Record<string, Celula>[];
}

export interface FiltroPeriodo { chave: string; codigo: string }   // ex.: {chave:"periodo0", codigo:"l"}
