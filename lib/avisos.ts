// Aba Avisos: as pendências de todos os painéis. As linhas vêm das tabelas `aviso` e `aviso_evento`
// (supabase/migrations/20261014210000_avisos.sql), que o servidor Python preenche a cada atualização dos
// painéis. RLS entrega ao administrador tudo e aos demais só os painéis liberados em Configurações.
//
// "Informação": um aviso fechado com justificativa (status "justificado") aparece como informação, com o que a pessoa explicou e, se houver, a data
// prevista. Se ele volta depois de resolvido e a justificativa ainda valia, também fica como informação (não conta como recorrência); a recorrência
// só conta quando alguém diz "Ainda não resolvi" ou "Não explica o problema", quando a data prevista passa ou quando o problema piora
// (migration 20261017110000_aviso_informacao_e_previsao.sql).

export type NivelAviso = "critico" | "atencao" | "info";
export type StatusAviso = "aberto" | "justificado" | "resolvido";
export type TipoEvento =
  | "detectado"
  | "sumiu"
  | "justificado"
  | "confirmado"
  | "reapareceu"
  | "nao_corrigido"
  | "piorou"
  | "reaberto"
  | "informado"
  | "prazo_vencido"
  | "atualizacao"
  | "correcao";

export type GuiaAviso = {
  relatorios?: { id: number; nome: string; url: string; menu?: string }[];
  passos?: string[];
  resolve?: string;
  dica?: string;
  atualizacao?: { em: string; texto: string };
};

export type ItensAviso = {
  colunas: string[];
  linhas: string[][];
  total: number;
  numericas?: number[];
};

export type Aviso = {
  id: number;
  painel: string;
  chave: string;
  tipo: string;
  escopo: string;
  titulo: string;
  texto: string;
  nivel: NivelAviso;
  persistente: boolean;
  guia: GuiaAviso;
  itens: ItensAviso | null;
  itens_total: number | null;
  status: StatusAviso;
  primeira_deteccao: string;
  ultima_deteccao: string;
  ultima_conferencia: string;
  resolvido_em: string | null;
  recorrencias: number;
  reaberturas: number;
  ultima_recorrencia: string | null;
  justificativa: string | null;
  justificado_por: string | null;
  justificado_em: string | null;
  previsto_para: string | null; // AAAA-MM-DD informado ao justificar
  retornos_informados: number;
  em_informacao: boolean;
};

export type EventoAviso = {
  id: number;
  aviso_id: number;
  quando: string;
  tipo: TipoEvento;
  usuario: string;
  detalhe: string;
};

export const CAMPOS_AVISO =
  "id, painel, chave, tipo, escopo, titulo, texto, nivel, persistente, guia, itens, itens_total, status, " +
  "primeira_deteccao, ultima_deteccao, ultima_conferencia, resolvido_em, recorrencias, reaberturas, " +
  "ultima_recorrencia, justificativa, justificado_por, justificado_em, previsto_para, retornos_informados, em_informacao";

// A mesma regra está em fechar_aviso (banco): o banco é quem manda, aqui só se avisa antes.
export const MIN_JUSTIFICATIVA = 15;
export const MAX_JUSTIFICATIVA = 1000;
export type MotivoReabrir = "nao_resolvi" | "nao_explicou";
// Resolvidos mais antigos que isso saem da lista (continuam no banco com o histórico).
export const DIAS_RESOLVIDOS = 90;

export const ROTULO_NIVEL: Record<NivelAviso, string> = { critico: "Crítico", atencao: "Atenção", info: "Informação" };
export const PESO_NIVEL: Record<NivelAviso, number> = { critico: 3, atencao: 2, info: 1 };

export const ROTULO_EVENTO: Record<TipoEvento, string> = {
  detectado: "Apareceu nos dados",
  sumiu: "Resolvido",
  justificado: "Fechado com justificativa",
  confirmado: "Resolvido e confirmado",
  reapareceu: "Voltou a acontecer",
  nao_corrigido: "Reaberto: continuava nos dados",
  piorou: "Reaberto: piorou",
  reaberto: "Reaberto à mão (conta como recorrência)",
  informado: "Voltou, mantido como informação",
  prazo_vencido: "Reaberto: a data prevista passou",
  atualizacao: "Painel atualizado",
  correcao: "Correção de registro",
};

const MESES = [
  "Janeiro",
  "Fevereiro",
  "Março",
  "Abril",
  "Maio",
  "Junho",
  "Julho",
  "Agosto",
  "Setembro",
  "Outubro",
  "Novembro",
  "Dezembro",
];

// Escopo "" = posição de hoje; "AAAA-MM" = só vale para aquele mês.
export function rotuloEscopo(escopo: string): string {
  const m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(escopo);
  return m ? `${MESES[Number(m[2]) - 1]}/${m[1]}` : "Posição de hoje";
}

export const voltou = (a: Aviso) => a.status === "aberto" && (a.recorrencias > 0 || a.reaberturas > 0);

// Fechado com justificativa = informação: o que a pessoa explicou fica à mostra no lugar do problema.
export const emInformacao = (a: Aviso) => a.status === "justificado";

// "AAAA-MM-DD" (coluna date, sem fuso) -> "dd/mm/aaaa"
export function dataDia(iso: string | null): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

// Hoje (ou hoje + N dias) em Brasília, como AAAA-MM-DD: mínimo e máximo do campo "data prevista" (o banco confere de novo).
export function hojeEmBrasilia(maisDias = 0): string {
  const d = new Date(Date.now() + maisDias * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit" }).format(d); // en-CA já vem AAAA-MM-DD
}

export function nomeDoUsuario(email: string | null): string {
  if (!email) return "alguém";
  return email.endsWith("@csi.local") ? email.replace("@csi.local", "") : email;
}

const fmtDataHora = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const fmtData = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

export function dataHora(iso: string | null): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? fmtDataHora.format(d) : "";
}

export function dataCurta(iso: string | null): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? fmtData.format(d) : "";
}

// Só links para o Klingo da clínica saem da página (o guia vem do servidor, mas o link é sempre conferido).
export const urlKlingoValida = (url: string) => url.startsWith("https://clinicacsi.klingo.app/");
