// Barra de atualização da coleta adaptativa (supabase/migrations/20261101120000_coleta_ritmo.sql).
// As linhas vêm de status_ritmo_coleta(); aqui ficam só as contas e os textos, sem React, para a tela e os testes usarem o mesmo código.

export type Marcha = "ao_vivo" | "calmo" | "dormindo";

export type RitmoRelatorio = {
  klingo_id: string;
  nome: string;
  marcha: Marcha;
  intervalo_min: number;
  minimo_min: number;
  ultima_leitura_em: string | null;
  proxima_leitura_em: string;
  ultimo_movimento_em: string | null;
  motivo_movimento: string | null;
  erros_seguidos: number;
  em_expediente: boolean;
  agora: string; // relógio do servidor no momento da consulta
};

// ao_vivo = lendo no ritmo normal; calmo/dormindo = fora do expediente e sem movimento; atrasado = passou da hora e não leu; erro = a última leitura falhou
export type EstadoBarra = "ao_vivo" | "calmo" | "dormindo" | "atrasado" | "erro";

// Folga antes de chamar de "atrasado": a leitura de 1 min leva alguns segundos e o cron só roda a cada minuto.
const FOLGA_MIN_S = 150;

export function segundosAte(iso: string | null, agoraMs: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.round((t - agoraMs) / 1000);
}

// 20 -> "20 s"; 200 -> "3 min"; 3900 -> "1 h 05"
export function duracaoCurta(segundos: number): string {
  const s = Math.max(0, Math.round(segundos));
  if (s < 90) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return m === 60 ? `${h + 1} h` : `${h} h ${String(m).padStart(2, "0")}`;
}

// "21:30" no horário de Brasília
export function horaBrasilia(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function estadoDoRelatorio(r: RitmoRelatorio, agoraMs: number): EstadoBarra {
  if (r.erros_seguidos > 0) return "erro";
  const falta = segundosAte(r.proxima_leitura_em, agoraMs) ?? 0;
  if (falta < -Math.max(FOLGA_MIN_S, r.intervalo_min * 60)) return "atrasado";
  return r.marcha;
}

const PESO: Record<EstadoBarra, number> = { erro: 4, atrasado: 3, ao_vivo: 2, calmo: 1, dormindo: 0 };

// O estado da barra é o do relatório que pede mais atenção: erro > atrasado > ao vivo > calmo > dormindo.
export function estadoGeral(rs: RitmoRelatorio[], agoraMs: number): EstadoBarra {
  return rs.reduce<EstadoBarra>((pior, r) => {
    const e = estadoDoRelatorio(r, agoraMs);
    return PESO[e] > PESO[pior] ? e : pior;
  }, "dormindo");
}

export const ROTULO_ESTADO: Record<EstadoBarra, string> = {
  ao_vivo: "Ao vivo",
  calmo: "Calmo",
  dormindo: "Dormindo",
  atrasado: "Atrasado",
  erro: "Falha na leitura",
};

// Quanto do intervalo já passou (0 a 1) para o preenchimento da barra: do relatório que vai ler primeiro.
export function progresso(r: RitmoRelatorio, agoraMs: number): number {
  const prox = Date.parse(r.proxima_leitura_em);
  const intervaloMs = r.intervalo_min * 60_000;
  if (Number.isNaN(prox) || intervaloMs <= 0) return 0;
  return Math.min(1, Math.max(0, 1 - (prox - agoraMs) / intervaloMs));
}

// O relatório que mostra o texto principal: o próximo a ser lido.
export function proximoALer(rs: RitmoRelatorio[]): RitmoRelatorio | null {
  return rs.reduce<RitmoRelatorio | null>((m, r) => (!m || Date.parse(r.proxima_leitura_em) < Date.parse(m.proxima_leitura_em) ? r : m), null);
}
