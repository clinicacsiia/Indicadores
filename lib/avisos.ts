// Aba Avisos: as pendências de todos os painéis. As linhas vêm das tabelas `aviso` e `aviso_evento`
// (supabase/migrations/20261014210000_avisos.sql), que o servidor Python preenche a cada atualização dos
// painéis. RLS entrega ao administrador tudo e aos demais só os painéis liberados em Configurações.

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
  | "reaberto";

export type GuiaAviso = {
  relatorios?: { id: number; nome: string; url: string }[];
  passos?: string[];
  resolve?: string;
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
  "ultima_recorrencia, justificativa, justificado_por, justificado_em";

// A mesma regra está em fechar_aviso (banco): o banco é quem manda, aqui só se avisa antes.
export const MIN_JUSTIFICATIVA = 15;
export const MAX_JUSTIFICATIVA = 1000;
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
  reaberto: "Reaberto à mão",
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
