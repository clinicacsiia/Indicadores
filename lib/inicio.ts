// Tela Início: como cada relatório ativo aparece (cartões) e o que está sendo coletado agora.
// As linhas vêm de status_coleta_relatorios() (supabase/migrations/20261014230000_inicio_status_coleta.sql), que conta na
// unidade certa de cada relatório: dias (diários), meses (coleta mensal) ou 1/0 (pontuais).

export type Unidade = "dia" | "mes" | "unico";

export type StatusRelatorio = {
  klingo_id: string;
  nome: string;
  categoria: string | null;
  unidade: Unidade;
  ultimo_periodo: string | null;
  ultimo_sync: string | null;
  sincronizados: number;
  esperados: number;
  pct: number;
  pausado_ate: string | null;
  falhas_seguidas: number;
  erros_24h: number;
  ultimo_erro: string | null;
};

export type PainelRenovando = { painel: string; decorrido_s: number; previsto_s: number };

export type Situacao = "batida" | "ritmo" | "atencao" | "atrasado";

// Quantas tentativas com erro em 24 h já merecem aviso no cartão (1 ou 2 são comuns: Klingo oscila, um dia ou outro falha).
export const ERROS_PARA_AVISAR = 3;

const FUSO = "America/Sao_Paulo";
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export function temProblema(r: StatusRelatorio): boolean {
  return Boolean(r.pausado_ate) || r.falhas_seguidas > 0 || r.erros_24h >= ERROS_PARA_AVISAR;
}

// Pausado é o pior caso; falha/erro rebaixa um relatório que parecia em dia; o resto segue a % coletada.
export function situacaoDe(r: StatusRelatorio): Situacao {
  if (r.pausado_ate) return "atrasado";
  const base: Situacao = r.pct >= 100 ? "batida" : r.pct >= 75 ? "ritmo" : r.pct >= 50 ? "atencao" : "atrasado";
  if (temProblema(r) && (base === "batida" || base === "ritmo")) return "atencao";
  return base;
}

export function completo(r: StatusRelatorio): boolean {
  return r.sincronizados >= r.esperados;
}

const dm = (iso: string) => {
  const [, mes, dia] = iso.slice(0, 10).split("-");
  return `${dia}/${mes}`;
};

export function rotuloMes(iso: string): string {
  const [ano, mes] = iso.slice(0, 7).split("-");
  return `${MESES[Number(mes) - 1]}/${ano}`;
}

function plural(n: number, um: string, varios: string) {
  return `${n} ${n === 1 ? um : varios}`;
}

// A linha de baixo do cartão, na unidade do relatório.
export function descricaoDoCartao(r: StatusRelatorio): string {
  const faltam = Math.max(r.esperados - r.sincronizados, 0);
  if (r.unidade === "unico") {
    return r.ultimo_sync ? `Coletado em ${dm(dataLocal(r.ultimo_sync))}` : "Nunca sincronizado";
  }
  if (r.unidade === "mes") {
    const base = `${r.sincronizados} de ${r.esperados} ${r.esperados === 1 ? "mês coletado" : "meses coletados"}`;
    const ate = r.ultimo_periodo ? ` · último: ${rotuloMes(r.ultimo_periodo)}` : "";
    return `${base}${ate}${faltam > 0 ? ` · ${faltam === 1 ? "falta 1 mês" : `faltam ${faltam} meses`}` : ""}`;
  }
  if (!r.ultimo_periodo) return "Nunca sincronizado";
  return `Atualizado até ${dm(r.ultimo_periodo)}${faltam > 0 ? ` · ${faltam === 1 ? "falta 1 dia" : `faltam ${faltam} dias`}` : ""}`;
}

export type Alerta = { texto: string; tipo: "erro" | "aviso" };

export function alertasDoCartao(r: StatusRelatorio): Alerta[] {
  const out: Alerta[] = [];
  if (r.pausado_ate) out.push({ texto: `Pausado até ${horaLocal(r.pausado_ate)}`, tipo: "erro" });
  if (r.falhas_seguidas > 0 && !r.pausado_ate) {
    out.push({ texto: plural(r.falhas_seguidas, "falha seguida", "falhas seguidas"), tipo: "aviso" });
  }
  if (r.erros_24h >= ERROS_PARA_AVISAR) {
    out.push({ texto: `${plural(r.erros_24h, "tentativa", "tentativas")} com erro nas últimas 24 h`, tipo: "aviso" });
  }
  return out;
}

// "2026-10-13T23:30:00+00:00" -> dia/hora de Brasília, para qualquer pessoa ver o mesmo horário.
export function dataLocal(iso: string): string {
  const partes = new Intl.DateTimeFormat("en-CA", { timeZone: FUSO, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  return partes; // AAAA-MM-DD
}

export function horaLocal(iso: string): string {
  const d = new Date(iso);
  const dia = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, day: "2-digit", month: "2-digit" }).format(d);
  const hora = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
  return `${dia} ${hora}`;
}

// "há 3 min", "há 2 h", "há 1 dia"
export function haQuanto(iso: string, agora = Date.now()): string {
  const min = Math.max(Math.round((agora - new Date(iso).getTime()) / 60000), 0);
  if (min < 1) return "agora há pouco";
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  return `há ${plural(Math.floor(h / 24), "dia", "dias")}`;
}

// Quando o último relatório foi coletado: se passou de 30 min, a coleta automática (a cada 5 min) pode estar parada.
export function resumoDaColeta(rels: StatusRelatorio[], agora = Date.now()) {
  const ultimos = rels.map((r) => r.ultimo_sync).filter((s): s is string => Boolean(s));
  const ultimo = ultimos.length ? ultimos.reduce((a, b) => (new Date(a) > new Date(b) ? a : b)) : null;
  const parada = ultimo ? agora - new Date(ultimo).getTime() > 30 * 60000 : true;
  return {
    ultimo,
    parada,
    completos: rels.filter(completo).length,
    incompletos: rels.filter((r) => !completo(r)).length,
    problemas: rels.filter(temProblema).length,
    total: rels.length,
  };
}
