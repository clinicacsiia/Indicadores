// Aba "CRM Ressonância": o funil da Ressonância Magnética lançado à mão (solicitação -> orçamento/autorização -> agendamento -> realização)
// para achar onde se perdem pacientes e faturamento. Nunca registrar nome, CPF ou dado clínico: cada registro tem só um código (RM-0001).
//
// Duas permissões em profiles.permissions, as duas desligadas até o administrador marcar em Configurações:
//   crm_rm_preencher = registra e atualiza o que ela mesma registrou
//   crm_rm           = vê tudo (indicadores e listas) e atualiza qualquer registro
// Administrador tem as duas sempre. O banco (RLS das tabelas crm_rm_*) aplica a mesma regra.
export const PERMISSAO_CRM_RM_VER = "crm_rm";
export const PERMISSAO_CRM_RM_PREENCHER = "crm_rm_preencher";

type Perfil = { role: string; permissions: Record<string, boolean | string> } | null;

export const podeVerCrmRm = (p: Perfil) => !!p && (p.role === "admin" || p.permissions?.[PERMISSAO_CRM_RM_VER] === true);
export const podePreencherCrmRm = (p: Perfil) => !!p && (p.role === "admin" || p.permissions?.[PERMISSAO_CRM_RM_PREENCHER] === true);

// ───────── Termos (os mesmos da planilha; cada um com o que significa e o que a equipe faz) ─────────

export const CANAIS = ["WhatsApp", "Telefone", "Site", "Google", "Instagram", "Indicação médica", "Presencial", "Outro"] as const;
export const TIPOS_PACIENTE = ["Novo paciente", "Paciente já atendido"] as const;
export const FORMAS_PAGAMENTO = ["Particular", "Convênio"] as const;
export const EXAMES = [
  "Crânio / encéfalo",
  "Coluna cervical",
  "Coluna torácica",
  "Coluna lombar",
  "Joelho",
  "Ombro",
  "Quadril / bacia",
  "Pé / tornozelo",
  "Mão / punho",
  "Abdome",
  "Pelve",
  "Mama",
  "Angiorressonância",
  "Outro",
] as const;

export type Situacao = "Novo contato" | "Orçamento enviado" | "Aguardando resposta" | "Aguardando autorização" | "Agendado" | "Não agendou" | "Desistiu";

export const SITUACOES: { id: Situacao; significado: string; acao: string }[] = [
  { id: "Novo contato", significado: "Paciente pediu informação ou exame, ainda sem orçamento", acao: "Responder e verificar disponibilidade" },
  { id: "Orçamento enviado", significado: "Valor e condições foram informados", acao: "Programar retorno" },
  { id: "Aguardando resposta", significado: "Paciente recebeu as informações e ainda não decidiu", acao: "Retomar contato" },
  { id: "Aguardando autorização", significado: "O convênio ainda não autorizou o exame", acao: "Acompanhar a pendência" },
  { id: "Agendado", significado: "Paciente já tem horário reservado", acao: "Registrar o horário na aba Agenda" },
  { id: "Não agendou", significado: "Atendimento terminou sem reserva de horário", acao: "Informar o motivo da perda" },
  { id: "Desistiu", significado: "Paciente avisou que não fará o exame", acao: "Informar o motivo" },
];
export const SITUACOES_PERDA: Situacao[] = ["Não agendou", "Desistiu"];
export const SITUACOES_ABERTAS: Situacao[] = ["Novo contato", "Orçamento enviado", "Aguardando resposta", "Aguardando autorização"];

// Quem separa os gargalos: comercial (atendimento), agenda/acesso (vaga), convênio (autorização) e clínico.
export type CategoriaPerda = "Comercial" | "Agenda" | "Convênio" | "Clínico" | "Outro";
export const MOTIVOS_PERDA: { id: string; categoria: CategoriaPerda; significado: string; acao: string }[] = [
  { id: "Preço", categoria: "Comercial", significado: "Paciente achou o valor impeditivo", acao: "Registrar sem alterar preço por conta própria" },
  { id: "Demora na resposta", categoria: "Comercial", significado: "A resposta lenta fez o paciente seguir para outro lugar", acao: "Avaliar o tempo de resposta" },
  { id: "Preferiu outra clínica", categoria: "Comercial", significado: "Paciente informou que fará o exame em outro serviço", acao: "Anotar o motivo nas observações" },
  { id: "Não respondeu", categoria: "Comercial", significado: "Paciente não respondeu às tentativas do protocolo", acao: "Encerrar depois do protocolo de contato" },
  { id: "Sem vaga na data desejada", categoria: "Agenda", significado: "A agenda não tinha horário compatível", acao: "Avaliar encaixe e lista de espera" },
  { id: "Convênio não atendido", categoria: "Convênio", significado: "A clínica não atende o convênio do paciente", acao: "Oferecer a opção particular, se fizer sentido" },
  { id: "Autorização negada", categoria: "Convênio", significado: "O convênio negou ou não liberou o exame", acao: "Orientar o paciente sobre o recurso" },
  { id: "Preparo / contraindicação", categoria: "Clínico", significado: "Preparo ou contraindicação impediu o exame", acao: "Encaminhar à equipe técnica" },
  { id: "Outro", categoria: "Outro", significado: "Motivo que não está na lista", acao: "Descrever nas observações" },
];
export const categoriaDoMotivo = (m: string | null): CategoriaPerda | null => MOTIVOS_PERDA.find((x) => x.id === m)?.categoria ?? null;

export const PROXIMAS_ACOES = ["Ligar", "Enviar WhatsApp", "Reenviar orçamento", "Verificar vaga", "Acompanhar autorização", "Sem ação"] as const;

export type StatusAgenda = "Agendado" | "Realizado" | "Faltou" | "Cancelado" | "Reagendado";
export const STATUS_AGENDA: { id: StatusAgenda; significado: string; acao: string }[] = [
  { id: "Agendado", significado: "Horário reservado, o exame ainda não aconteceu", acao: "Confirmar com o paciente" },
  { id: "Realizado", significado: "O exame foi feito", acao: "Preencher o valor realizado" },
  { id: "Faltou", significado: "Paciente não compareceu e não fez o exame", acao: "Registrar o motivo e oferecer novo horário" },
  { id: "Cancelado", significado: "Paciente cancelou antes do exame", acao: "Oferecer a vaga à lista de espera" },
  { id: "Reagendado", significado: "O exame foi passado para outra data (a nova data é outro horário na Agenda)", acao: "Registrar o novo horário sem criar contato novo" },
];
export const SAI_DO_COMPARECIMENTO: StatusAgenda[] = ["Faltou", "Cancelado", "Reagendado"]; // status que aceitam motivo e "vaga recuperada"

export const CONFIRMACOES = ["Confirmou", "Não respondeu", "Solicitou reagendamento", "Não contatado"] as const;
export const MOTIVOS_FALTA = ["Esqueceu", "Problema de transporte", "Preparo inadequado", "Autorização pendente", "Doença / imprevisto", "Outro"] as const;
export const VAGA_RECUPERADA = ["Sim", "Não", "Não se aplica"] as const;
export const MOTIVOS_OPERACIONAIS = ["Equipamento parado", "Bobina indisponível", "Manutenção", "Falta de profissional", "Atraso no preparo", "Outro"] as const;

export const MAX_OBS = 500;

export const codigoContato = (id: number) => `RM-${String(id).padStart(4, "0")}`;

// ───────── Registros ─────────

export const CAMPOS_CONTATO =
  "id, data_contato, canal, tipo_paciente, exame, forma_pagamento, convenio, valor_informado, situacao, motivo_perda, data_ultimo_contato, proxima_acao, data_retorno, responsavel, observacoes, exemplo";
export const CAMPOS_AGENDA =
  "id, contato_id, data_exame, horario, forma_pagamento, exame, status, confirmacao, motivo_falta, vaga_recuperada, valor_previsto, valor_realizado, horas_paradas, motivo_operacional, exemplo";

export type Contato = {
  id: number;
  data_contato: string; // AAAA-MM-DD
  canal: string;
  tipo_paciente: string;
  exame: string;
  forma_pagamento: "Particular" | "Convênio";
  convenio: string | null;
  valor_informado: number | null;
  situacao: Situacao;
  motivo_perda: string | null;
  data_ultimo_contato: string | null;
  proxima_acao: string | null;
  data_retorno: string | null;
  responsavel: string | null;
  observacoes: string | null;
  exemplo: boolean;
};

export type Horario = {
  id: number;
  contato_id: number | null;
  data_exame: string;
  horario: string | null; // HH:MM:SS
  forma_pagamento: "Particular" | "Convênio";
  exame: string;
  status: StatusAgenda;
  confirmacao: string;
  motivo_falta: string | null;
  vaga_recuperada: string;
  valor_previsto: number | null;
  valor_realizado: number | null;
  horas_paradas: number | null;
  motivo_operacional: string | null;
  exemplo: boolean;
};

// ───────── Cálculo dos indicadores ─────────

const soma = (xs: (number | null | undefined)[]) => xs.reduce<number>((a, b) => a + (b ?? 0), 0);
const razao = (a: number, b: number) => (b > 0 ? (a / b) * 100 : null);

export type Etapa = { id: string; rotulo: string; dica: string; n: number };
export type LinhaGrupo = { nome: string; n: number; extra?: string };

export type FormaResumo = {
  forma: string;
  solicitacoes: number;
  agendadas: number;
  conversao: number | null;
  realizados: number;
  faltas: number;
  absenteismo: number | null;
};

export type Indicadores = {
  solicitacoes: number;
  conversao: number | null;
  funil: Etapa[];
  perdidos: number;
  valorPerdido: number; // soma do valor informado dos contatos perdidos (potencial)
  emAberto: number;
  valorEmAberto: number;
  perdasPorMotivo: { motivo: string; categoria: CategoriaPerda | null; n: number; pct: number; valor: number }[];
  perdasPorCategoria: { categoria: string; n: number }[];
  porCanal: { canal: string; solicitacoes: number; agendadas: number; conversao: number | null }[];
  porForma: FormaResumo[];
  // agenda
  realizados: number;
  faltas: number;
  cancelamentos: number;
  reagendados: number;
  aRealizar: number;
  absenteismo: number | null;
  receitaRealizada: number;
  valorPrevistoFaltas: number;
  vagasElegiveis: number; // faltas + cancelamentos
  vagasRecuperadas: number;
  pctRecuperadas: number | null;
  faltasPorConfirmacao: { confirmacao: string; agendados: number; faltas: number; taxa: number | null }[];
  motivosFalta: { motivo: string; n: number }[];
  horasParadas: number;
  motivosOperacionais: { motivo: string; n: number; horas: number }[];
};

function contar<T>(xs: T[], chave: (x: T) => string | null): Map<string, number> {
  const m = new Map<string, number>();
  for (const x of xs) {
    const k = chave(x);
    if (k) m.set(k, (m.get(k) ?? 0) + 1);
  }
  return m;
}

const porQuantidade = (m: Map<string, number>) => [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

// `contatos` e `horarios` já vêm filtrados pelo período (contatos pela data do contato; horários pela data do exame, até hoje).
// `futuros` = horários com exame depois de hoje (ainda sem resultado).
export function calcular(contatos: Contato[], horarios: Horario[], futuros: number): Indicadores {
  const perdidos = contatos.filter((c) => SITUACOES_PERDA.includes(c.situacao));
  const abertos = contatos.filter((c) => SITUACOES_ABERTAS.includes(c.situacao));
  const agendadas = contatos.filter((c) => c.situacao === "Agendado");
  // Chegou ao orçamento ou à autorização: tem valor informado ou passou da fase "Novo contato" sem desistir antes.
  const comOrcamento = contatos.filter(
    (c) => c.valor_informado !== null || ["Orçamento enviado", "Aguardando autorização", "Agendado"].includes(c.situacao),
  );

  const realizados = horarios.filter((h) => h.status === "Realizado");
  const faltas = horarios.filter((h) => h.status === "Faltou");
  const cancelados = horarios.filter((h) => h.status === "Cancelado");
  const reagendados = horarios.filter((h) => h.status === "Reagendado");
  const elegiveis = horarios.filter((h) => h.status === "Faltou" || h.status === "Cancelado");
  const recuperadas = elegiveis.filter((h) => h.vaga_recuperada === "Sim");

  const motivos = porQuantidade(contar(perdidos, (c) => c.motivo_perda));
  const valorDoMotivo = (m: string) => soma(perdidos.filter((c) => c.motivo_perda === m).map((c) => c.valor_informado));
  const porCategoria = porQuantidade(contar(perdidos, (c) => categoriaDoMotivo(c.motivo_perda)));

  const canais = [...new Set(contatos.map((c) => c.canal))].map((canal) => {
    const doCanal = contatos.filter((c) => c.canal === canal);
    const ag = doCanal.filter((c) => c.situacao === "Agendado").length;
    return { canal, solicitacoes: doCanal.length, agendadas: ag, conversao: razao(ag, doCanal.length) };
  });

  const formas = FORMAS_PAGAMENTO.map((forma) => {
    const cs = contatos.filter((c) => c.forma_pagamento === forma);
    const hs = horarios.filter((h) => h.forma_pagamento === forma);
    const ag = cs.filter((c) => c.situacao === "Agendado").length;
    const re = hs.filter((h) => h.status === "Realizado").length;
    const fa = hs.filter((h) => h.status === "Faltou").length;
    return { forma, solicitacoes: cs.length, agendadas: ag, conversao: razao(ag, cs.length), realizados: re, faltas: fa, absenteismo: razao(fa, re + fa) };
  });

  const confirmacoes = CONFIRMACOES.map((conf) => {
    const hs = horarios.filter((h) => h.confirmacao === conf && ["Realizado", "Faltou"].includes(h.status));
    const fa = hs.filter((h) => h.status === "Faltou").length;
    return { confirmacao: conf, agendados: hs.length, faltas: fa, taxa: razao(fa, hs.length) };
  });

  const operacionais = porQuantidade(contar(horarios, (h) => h.motivo_operacional)).map(([motivo, n]) => ({
    motivo,
    n,
    horas: soma(horarios.filter((h) => h.motivo_operacional === motivo).map((h) => h.horas_paradas)),
  }));

  return {
    solicitacoes: contatos.length,
    conversao: razao(agendadas.length, contatos.length),
    funil: [
      { id: "procura", rotulo: "Procuraram o exame", dica: "Todas as solicitações registradas no período", n: contatos.length },
      { id: "orcamento", rotulo: "Chegaram ao orçamento ou à autorização", dica: "Têm valor informado ou estão em Orçamento enviado, Aguardando autorização ou Agendado", n: comOrcamento.length },
      { id: "agendamento", rotulo: "Agendaram", dica: "Situação do contato = Agendado", n: agendadas.length },
      { id: "realizacao", rotulo: "Fizeram o exame", dica: "Horários da Agenda com status Realizado no período", n: realizados.length },
    ],
    perdidos: perdidos.length,
    valorPerdido: soma(perdidos.map((c) => c.valor_informado)),
    emAberto: abertos.length,
    valorEmAberto: soma(abertos.map((c) => c.valor_informado)),
    perdasPorMotivo: motivos.map(([motivo, n]) => ({ motivo, categoria: categoriaDoMotivo(motivo), n, pct: (n / Math.max(1, perdidos.length)) * 100, valor: valorDoMotivo(motivo) })),
    perdasPorCategoria: porCategoria.map(([categoria, n]) => ({ categoria, n })),
    porCanal: canais.sort((a, b) => b.solicitacoes - a.solicitacoes),
    porForma: formas,
    realizados: realizados.length,
    faltas: faltas.length,
    cancelamentos: cancelados.length,
    reagendados: reagendados.length,
    aRealizar: futuros,
    absenteismo: razao(faltas.length, realizados.length + faltas.length),
    receitaRealizada: soma(realizados.map((h) => h.valor_realizado)),
    valorPrevistoFaltas: soma(faltas.map((h) => h.valor_previsto)),
    vagasElegiveis: elegiveis.length,
    vagasRecuperadas: recuperadas.length,
    pctRecuperadas: razao(recuperadas.length, elegiveis.length),
    faltasPorConfirmacao: confirmacoes,
    motivosFalta: porQuantidade(contar(faltas, (h) => h.motivo_falta)).map(([motivo, n]) => ({ motivo, n })),
    horasParadas: soma(horarios.map((h) => h.horas_paradas)),
    motivosOperacionais: operacionais,
  };
}

// Contatos que pedem ação hoje: ainda abertos e com retorno marcado para hoje ou antes.
export function paraRetomar(contatos: Contato[], hoje: string): Contato[] {
  return contatos
    .filter((c) => SITUACOES_ABERTAS.includes(c.situacao) && c.data_retorno !== null && c.data_retorno <= hoje)
    .sort((a, b) => (a.data_retorno as string).localeCompare(b.data_retorno as string) || a.id - b.id);
}

// "650,50" ou "650.50" ou "1.250,00" -> número; vazio -> null; lixo -> NaN
export function lerValor(texto: string): number | null {
  const t = texto.trim().replace(/^R\$\s*/i, "");
  if (!t) return null;
  const normal = t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t;
  return /^\d+(\.\d{1,2})?$/.test(normal) ? Number(normal) : Number.NaN;
}
