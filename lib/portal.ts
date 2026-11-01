// Portal do paciente (supabase/migrations/20261101190000_jornada_portal_paciente.sql). Contas e textos sem React nem servidor, para a página, a equipe e os testes usarem o mesmo código.

// O código do link tem 64 letras/números hexadecimais (244 bits). Qualquer outra coisa nem chega ao banco.
export const TOKEN_RE = /^[0-9a-f]{64}$/;
export const tokenValido = (t: string) => TOKEN_RE.test(t);

export type SituacaoExame = "agendado" | "confirmado" | "atendido" | "cancelado" | "remarcado" | "faltou";

export type PaginaPaciente = {
  ok: true;
  nome: string;
  data: string; // AAAA-MM-DD
  unidade: string;
  confirmou_em: string | null;
  pode_agir: boolean;
  exames: { hora: string; exame: string; situacao: SituacaoExame }[];
  mensagens: { de: "paciente" | "equipe"; texto: string; quando: string }[];
};

export type RespostaPortal = PaginaPaciente | { ok: false; motivo: "desligado" | "limite" | "invalido" | string };

// O que o paciente lê quando o servidor devolve um motivo.
export function textoDoMotivo(motivo: string): string {
  switch (motivo) {
    case "desligado":
      return "O atendimento online está indisponível no momento. Fale com a clínica pelo telefone ou pelo WhatsApp.";
    case "limite":
      return "Muitas tentativas. Tente de novo mais tarde.";
    case "invalido":
      return "Este link não vale mais. Peça um novo à clínica.";
    case "indisponivel":
      return "Este atendimento não pode mais ser alterado por aqui. Fale com a clínica.";
    case "muitas":
      return "Você enviou muitas mensagens em pouco tempo. Tente de novo daqui a pouco.";
    case "tamanho":
      return "Escreva uma mensagem de até 1000 letras.";
    default:
      return "Não foi possível concluir agora. Tente de novo em instantes.";
  }
}

export const ROTULO_SITUACAO: Record<SituacaoExame, string> = {
  agendado: "Agendado",
  confirmado: "Confirmado",
  atendido: "Atendido",
  cancelado: "Cancelado",
  remarcado: "Remarcado",
  faltou: "Faltou",
};

// "2026-11-04" -> "quarta-feira, 04/11"
export function diaPorExtenso(dia: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dia);
  if (!m) return dia;
  const semana = new Intl.DateTimeFormat("pt-BR", { weekday: "long", timeZone: "UTC" }).format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))));
  return `${semana}, ${m[3]}/${m[2]}`;
}

export function urlDoPortal(origem: string, token: string): string {
  return `${origem.replace(/\/+$/, "")}/p/${token}`;
}

// Texto que a atendente envia pelo WhatsApp (sem dado clínico: só o nome, o dia e o link).
export function mensagemDoLink(nome: string | null | undefined, dia: string, url: string): string {
  const primeiro = (nome ?? "").trim().split(/\s+/)[0];
  const ola = primeiro ? `Olá, ${primeiro.charAt(0).toUpperCase()}${primeiro.slice(1).toLowerCase()}!` : "Olá!";
  const d = /^\d{4}-(\d{2})-(\d{2})/.exec(dia);
  return `${ola} Aqui é a Clínica CSI. Para confirmar seu atendimento${d ? ` de ${d[2]}/${d[1]}` : ""} ou falar com a nossa equipe, acesse: ${url}`;
}

// Link do WhatsApp com a mensagem pronta. Sem telefone válido, devolve null.
export function linkWhatsAppComTexto(telefone: string | null | undefined, texto: string): string | null {
  const d = (telefone ?? "").replace(/\D/g, "");
  const numero = d.length === 10 || d.length === 11 ? `55${d}` : (d.length === 12 || d.length === 13) && d.startsWith("55") ? d : null;
  return numero ? `https://wa.me/${numero}?text=${encodeURIComponent(texto)}` : null;
}
