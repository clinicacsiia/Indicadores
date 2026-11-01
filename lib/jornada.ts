// Quadro da Jornada do paciente (supabase/migrations/20261101140000_jornada_modelo.sql e 20261101160000_jornada_sincronizar.sql).
// Aqui: o tipo de cada linha, a permissão, o que o servidor lê e as contas dos filtros (sem React, para a tela e os testes usarem o mesmo código).
import type { SupabaseClient } from "@supabase/supabase-js";

// Chave em profiles.permissions. Quem tem vê TUDO do quadro (o administrador sempre).
export const PERMISSAO_JORNADA = "jornada";

type PerfilComPermissoes = { role: string; permissions: Record<string, boolean | string> } | null;
export function podeVerJornada(perfil: PerfilComPermissoes): boolean {
  if (!perfil) return false;
  return perfil.role === "admin" || perfil.permissions?.[PERMISSAO_JORNADA] === true;
}

export type ColunaJornada = {
  id: string;
  nome: string;
  ordem: number;
  etapa: "antes" | "agendamento" | "depois" | "pos" | "excecao";
  origem: "klingo" | "manual";
  sla_min: number | null;
};

export type CardJornada = {
  id: number;
  paciente_chave: string;
  paciente_nome: string | null;
  data_ref: string; // AAAA-MM-DD
  unidade: string;
  coluna: string;
  coluna_nome: string;
  etapa: ColunaJornada["etapa"];
  origem: ColunaJornada["origem"];
  ordem: number;
  coluna_desde: string;
  responsavel: string | null;
  prioridade: number;
  versao: number;
  n_exames: number;
  n_ativos: number;
  n_mensagens: number;
  vazio: boolean;
  atrasado: boolean;
  minutos_na_coluna: number;
};

export type StatusExame = "agendado" | "confirmado" | "atendido" | "cancelado" | "remarcado" | "faltou";

export type ExameJornada = {
  card_id: number;
  marcacao_id: string;
  atendimento_id: string | null;
  procedimento: string;
  operadora: string | null;
  agendado_para: string | null;
  status: StatusExame;
  confirm_status: string | null;
  cancelamento_motivo: string | null;
};

export type TransicaoJornada = { de: string; para: string };
export type MembroEquipe = { id: string; nome: string };
export type MensagemJornada = { id: number; card_id: number; autor: string | null; autor_nome: string | null; autor_tipo: "equipe" | "paciente" | "sistema"; texto: string; criado_em: string };

export type SyncJornada = { ultima_execucao: string | null; ultimo_resultado: Record<string, number> | null };

export type DadosQuadro = {
  colunas: ColunaJornada[];
  transicoes: TransicaoJornada[];
  equipe: MembroEquipe[];
  usuarioId: string;
  cards: CardJornada[];
  exames: ExameJornada[];
  sync: SyncJornada | null;
  hoje: string;
};

const PAGINA = 1000; // o Supabase devolve no máximo 1000 linhas por pedido

async function lerTudo<T>(consulta: (de: number, ate: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>): Promise<T[]> {
  const todas: T[] = [];
  for (let de = 0; ; de += PAGINA) {
    const { data, error } = await consulta(de, de + PAGINA - 1);
    if (error) throw new Error(error.message);
    todas.push(...(data ?? []));
    if (!data || data.length < PAGINA) return todas;
  }
}

// "Hoje" em Brasília (AAAA-MM-DD): o servidor da Vercel roda em UTC e, depois das 21h, o dia certo ainda é o de ontem.
export function hojeBrasilia(agora = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(agora);
}

export async function carregarQuadro(supabase: SupabaseClient, usuarioId: string): Promise<DadosQuadro> {
  const [colunasRes, transicoesRes, equipeRes, cards, exames, syncRes] = await Promise.all([
    supabase.from("jornada_coluna").select("id, nome, ordem, etapa, origem, sla_min").eq("ativa", true).order("ordem"),
    supabase.from("jornada_transicao").select("de, para"),
    supabase.rpc("jornada_equipe"),
    lerTudo<CardJornada>((de, ate) =>
      supabase.from("v_jornada_quadro").select("*").order("id").range(de, ate) as unknown as PromiseLike<{ data: CardJornada[] | null; error: { message: string } | null }>,
    ),
    lerTudo<ExameJornada>((de, ate) =>
      supabase
        .from("jornada_exame")
        .select("card_id, marcacao_id, atendimento_id, procedimento, operadora, agendado_para, status, confirm_status, cancelamento_motivo")
        .order("id")
        .range(de, ate) as unknown as PromiseLike<{ data: ExameJornada[] | null; error: { message: string } | null }>,
    ),
    supabase.from("jornada_sync_estado").select("ultima_execucao, ultimo_resultado").maybeSingle(),
  ]);
  if (colunasRes.error) throw new Error(colunasRes.error.message);
  // sem as transições ou sem a lista da equipe o quadro continua valendo, só sem mover/atribuir
  if (transicoesRes.error) console.error("Falha ao ler as transições da Jornada:", transicoesRes.error.message);
  if (equipeRes.error) console.error("Falha ao ler a equipe da Jornada:", equipeRes.error.message);
  return {
    colunas: (colunasRes.data ?? []) as ColunaJornada[],
    transicoes: (transicoesRes.data ?? []) as TransicaoJornada[],
    equipe: (equipeRes.data ?? []) as MembroEquipe[],
    usuarioId,
    cards,
    exames,
    sync: (syncRes.data as SyncJornada | null) ?? null,
    hoje: hojeBrasilia(),
  };
}

// ---------------------------------------------------------------- filtros (puros)

export type Periodo = "ontem" | "hoje" | "amanha" | "7dias" | "30dias" | "tudo";
export const PERIODOS: { id: Periodo; rotulo: string }[] = [
  { id: "ontem", rotulo: "Ontem" },
  { id: "hoje", rotulo: "Hoje" },
  { id: "amanha", rotulo: "Amanhã" },
  { id: "7dias", rotulo: "7 dias" },
  { id: "30dias", rotulo: "30 dias" },
  { id: "tudo", rotulo: "Tudo" },
];

export type Filtros = {
  periodo: Periodo;
  unidade: string; // "" = todas
  operadora: string; // "" = todas
  busca: string;
  responsavel: string; // "" = todos · "meus" · "sem" (sem responsável) · id de uma pessoa
  soAtrasados: boolean;
  mostrarVazios: boolean;
};

export const FILTROS_PADRAO: Filtros = { periodo: "7dias", unidade: "", operadora: "", busca: "", responsavel: "", soAtrasados: false, mostrarVazios: false };

// AAAA-MM-DD + n dias (sem fuso: só calendário)
export function somarDias(dia: string, n: number): string {
  const [a, m, d] = dia.split("-").map(Number);
  return new Date(Date.UTC(a, m - 1, d + n)).toISOString().slice(0, 10);
}

export function noPeriodo(dataRef: string, periodo: Periodo, hoje: string): boolean {
  switch (periodo) {
    case "ontem":
      return dataRef === somarDias(hoje, -1);
    case "hoje":
      return dataRef === hoje;
    case "amanha":
      return dataRef === somarDias(hoje, 1);
    case "7dias":
      return dataRef >= hoje && dataRef <= somarDias(hoje, 6);
    case "30dias":
      return dataRef >= hoje && dataRef <= somarDias(hoje, 29);
    default:
      return true;
  }
}

// Sem acento e sem maiúscula, para "joao" achar "João".
export const semAcento = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export function filtrarCards(cards: CardJornada[], examesPorCard: Map<number, ExameJornada[]>, f: Filtros, hoje: string, usuarioId = ""): CardJornada[] {
  const busca = semAcento(f.busca.trim());
  const soDigitos = busca.replace(/\D/g, "");
  return cards.filter((c) => {
    if (!noPeriodo(c.data_ref, f.periodo, hoje)) return false;
    if (f.unidade && c.unidade !== f.unidade) return false;
    if (c.vazio && !f.mostrarVazios) return false;
    if (f.soAtrasados && !c.atrasado) return false;
    if (f.responsavel === "meus" && c.responsavel !== usuarioId) return false;
    if (f.responsavel === "sem" && c.responsavel) return false;
    if (f.responsavel && f.responsavel !== "meus" && f.responsavel !== "sem" && c.responsavel !== f.responsavel) return false;
    const exames = examesPorCard.get(c.id) ?? [];
    if (f.operadora && !exames.some((e) => e.operadora === f.operadora)) return false;
    if (busca) {
      const achou =
        semAcento(c.paciente_nome ?? "").includes(busca) ||
        (soDigitos.length >= 3 && c.paciente_chave.includes(soDigitos)) ||
        exames.some((e) => semAcento(e.procedimento).includes(busca) || semAcento(e.marcacao_id) === busca);
      if (!achou) return false;
    }
    return true;
  });
}

export function agruparExames(exames: ExameJornada[]): Map<number, ExameJornada[]> {
  const mapa = new Map<number, ExameJornada[]>();
  for (const e of exames) {
    const lista = mapa.get(e.card_id);
    if (lista) lista.push(e);
    else mapa.set(e.card_id, [e]);
  }
  for (const lista of mapa.values()) lista.sort((a, b) => (a.agendado_para ?? "").localeCompare(b.agendado_para ?? ""));
  return mapa;
}

export const ROTULO_STATUS_EXAME: Record<StatusExame, string> = {
  agendado: "Agendado",
  confirmado: "Confirmado",
  atendido: "Atendido",
  cancelado: "Cancelado",
  remarcado: "Remarcado",
  faltou: "Faltou",
};

export function horaCurta(iso: string | null): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

// "2 h 05", "35 min", "1 d 3 h"
export function tempoNaColuna(min: number): string {
  if (min < 60) return `${Math.max(0, min)} min`;
  if (min < 1440) return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}`;
  return `${Math.floor(min / 1440)} d ${Math.floor((min % 1440) / 60)} h`;
}

// "2026-11-03" -> "03/11"
export function diaCurto(dia: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(dia);
  return m ? `${m[2]}/${m[1]}` : dia;
}

// Só dígitos; com 10 ou 11 vira link do WhatsApp (55 + DDD + número).
export function linkWhatsApp(telefone: string | null): string | null {
  const d = (telefone ?? "").replace(/\D/g, "");
  if (d.length === 10 || d.length === 11) return `https://wa.me/55${d}`;
  if ((d.length === 12 || d.length === 13) && d.startsWith("55")) return `https://wa.me/${d}`;
  return null;
}

// ---------------------------------------------------------------- mover à mão

// Colunas para onde a equipe pode levar o cartão (só colunas da equipe, só por transição cadastrada).
export function destinosPermitidos(coluna: string, transicoes: TransicaoJornada[], colunas: ColunaJornada[]): ColunaJornada[] {
  const ids = new Set(transicoes.filter((t) => t.de === coluna).map((t) => t.para));
  return colunas.filter((c) => ids.has(c.id) && c.origem === "manual");
}

// O cartão já na coluna nova, antes de o servidor confirmar (volta atrás se o servidor recusar).
export function cartaoMovido(card: CardJornada, destino: ColunaJornada): CardJornada {
  return { ...card, coluna: destino.id, coluna_nome: destino.nome, etapa: destino.etapa, origem: destino.origem, ordem: destino.ordem, versao: card.versao + 1, minutos_na_coluna: 0, atrasado: false };
}

// Mensagens de erro do servidor em português simples; "CONFLITO" quer dizer que outra pessoa mexeu antes.
export function erroDeMover(mensagem: string): { texto: string; conflito: boolean } {
  if (mensagem.startsWith("CONFLITO")) return { texto: "Outra pessoa mexeu neste cartão antes de você. A tela foi atualizada: confira e tente de novo.", conflito: true };
  return { texto: mensagem || "Não foi possível mover o cartão.", conflito: false };
}

export function iniciais(nome: string | null | undefined): string {
  const partes = (nome ?? "").trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}
