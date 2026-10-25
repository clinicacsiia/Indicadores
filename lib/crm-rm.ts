// Aba "CRM Ressonância": o caminho do paciente na RM (procura -> orçamento/autorização ->
// agendamento -> comparecimento -> realização). A procura é registrada pela equipe de atendimento;
// a AGENDA vem sozinha do Klingo (relatório #13825, pela função `crm_rm_agenda_klingo`): quem marcou,
// confirmação, atendido, cancelado. Ninguém digita horário.
//
// Nomenclatura: exames e convênios vêm do CATÁLOGO (`crm_rm_exame` / `crm_rm_convenio`), semeado
// com o nome EXATO que o Klingo usa. O que a atendente escolhe aqui é o mesmo que ela marca lá;
// sem isso nenhum número cruza com o sistema. Formas de pagamento seguem o resto do sistema
// (Cetrus = antigo "SUS CURSO"; "pagante" = Particular + Convênio).
//
// Permissões em profiles.permissions, as duas desligadas até o administrador marcar:
//   crm_rm_preencher = registra e atualiza o que ela mesma registrou
//   crm_rm           = vê os indicadores e todas as listas, atualiza qualquer registro
// Administrador tem as duas. O banco (RLS) aplica a mesma regra. Quem tem qualquer uma das duas vê a agenda do Klingo.
export const PERMISSAO_CRM_RM_VER = "crm_rm";
export const PERMISSAO_CRM_RM_PREENCHER = "crm_rm_preencher";

type Perfil = { role: string; permissions: Record<string, boolean | string> } | null;

export const podeVerCrmRm = (p: Perfil) => !!p && (p.role === "admin" || p.permissions?.[PERMISSAO_CRM_RM_VER] === true);
export const podePreencherCrmRm = (p: Perfil) => !!p && (p.role === "admin" || p.permissions?.[PERMISSAO_CRM_RM_PREENCHER] === true);

// A RM fica toda nesta unidade (= grupo "CSI 2" do metas.json).
export const UNIDADE_RM = "CLÍNICA DE SAÚDE E IMAGEM - RM/TC";
/** Meta mensal de ressonâncias (metas.json, grupo csi2/ressonancias). */
export const CHAVE_META_RM = "csi2/ressonancias";

// ───────── Listas fixas ─────────

/** Por onde o PACIENTE chegou (marketing). Não confundir com `origem_registro`, que é quem digitou. */
export const CANAIS = [
  "WhatsApp",
  "Telefone",
  "Site",
  "Google",
  "Instagram",
  "Indicação médica",
  "Presencial",
  "Convênio / operadora",
  "Retorno de paciente",
  "Outro",
] as const;

/** Quem registrou, com os mesmos nomes do campo "Origem" do Klingo (relatório 7). */
export const ORIGENS_REGISTRO = ["TELEOPERADOR", "RECEPCIONISTA", "SAC/TEXTO", "ENFERMEIRA", "ADMINISTRATIVO"] as const;

export const TIPOS_PACIENTE = ["Novo paciente", "Paciente já atendido"] as const;

/** Mesmas categorias do resto do sistema. Cetrus é o antigo "SUS CURSO". */
export const FORMAS_PAGAMENTO = ["Particular", "Convênio", "SUS", "Cetrus"] as const;
export type FormaPagamento = (typeof FORMAS_PAGAMENTO)[number];
/** Quem gera receita direta (o SUS e o Cetrus têm regra própria e não entram no ticket). */
export const FORMAS_PAGANTES: FormaPagamento[] = ["Particular", "Convênio"];

export type Situacao =
  | "Novo contato"
  | "Orçamento enviado"
  | "Aguardando resposta"
  | "Aguardando autorização"
  | "Agendado"
  | "Não agendou"
  | "Desistiu";

export const SITUACOES: { id: Situacao; significado: string; acao: string }[] = [
  { id: "Novo contato", significado: "Pediu informação ou exame, ainda sem orçamento", acao: "Responder e verificar disponibilidade" },
  { id: "Orçamento enviado", significado: "Valor e condições já foram informados", acao: "Marcar a data do retorno" },
  { id: "Aguardando resposta", significado: "Recebeu as informações e ainda não decidiu", acao: "Retomar no dia combinado" },
  { id: "Aguardando autorização", significado: "O convênio ainda não liberou o exame", acao: "Acompanhar a guia e avisar o paciente" },
  { id: "Agendado", significado: "Já tem horário reservado", acao: "A marcação aparece sozinha na aba Agenda, vinda do Klingo" },
  { id: "Não agendou", significado: "O atendimento terminou sem reserva de horário", acao: "Informar o motivo da perda" },
  { id: "Desistiu", significado: "Avisou que não vai fazer o exame", acao: "Informar o motivo" },
];
export const SITUACOES_PERDA: Situacao[] = ["Não agendou", "Desistiu"];
export const SITUACOES_ABERTAS: Situacao[] = ["Novo contato", "Orçamento enviado", "Aguardando resposta", "Aguardando autorização"];

/** Separa o gargalo: atendimento (comercial), vaga (agenda), convênio ou clínico. */
export type CategoriaPerda = "Comercial" | "Agenda" | "Convênio" | "Clínico" | "Outro";

export const MOTIVOS_PERDA: { id: string; categoria: CategoriaPerda; significado: string; roteiro: string[] }[] = [
  {
    id: "Preço",
    categoria: "Comercial",
    significado: "Achou o valor impeditivo",
    roteiro: [
      "Confira na aba Guia o preço que a clínica praticou nesse exame.",
      "Pergunte se tem convênio: muitas vezes o exame sai coberto.",
      "Ofereça outra data ou horário com condição melhor, se houver.",
      "Não invente desconto: registre o valor que foi passado e siga.",
    ],
  },
  {
    id: "Convênio não atendido",
    categoria: "Convênio",
    significado: "A clínica não atende o convênio dele",
    roteiro: [
      "Confirme na aba Guia se o convênio realmente não está na lista.",
      "Ofereça o particular e informe o valor praticado.",
      "Registre o nome do convênio nas observações: a lista dos mais pedidos vira pedido de credenciamento.",
    ],
  },
  {
    id: "Sem vaga na data desejada",
    categoria: "Agenda",
    significado: "A agenda não tinha horário compatível",
    roteiro: [
      "Ofereça a primeira vaga livre, mesmo que em outra semana.",
      "Marque a pessoa para a lista de espera: anote em observações e deixe a próxima ação como “Verificar vaga”.",
      "Quando faltar ou cancelar alguém, a aba Meu dia mostra esta pessoa para você chamar.",
    ],
  },
  {
    id: "Demora na resposta",
    categoria: "Comercial",
    significado: "A resposta demorou e ele procurou outro lugar",
    roteiro: [
      "Registre o contato assim que ele chega, antes de resolver.",
      "Use o botão “Respondi agora” para marcar a primeira resposta.",
      "Se não conseguir resolver na hora, diga um prazo e marque a data do retorno.",
    ],
  },
  {
    id: "Autorização negada",
    categoria: "Convênio",
    significado: "O convênio negou ou não liberou",
    roteiro: [
      "Confirme o motivo da negativa com o faturamento.",
      "Oriente a pessoa sobre o recurso ou um novo pedido médico.",
      "Ofereça o particular como alternativa.",
    ],
  },
  {
    id: "Preparo / contraindicação",
    categoria: "Clínico",
    significado: "O preparo ou uma contraindicação impediu",
    roteiro: [
      "Não decida sozinha: encaminhe à equipe técnica ou ao médico da RM.",
      "Marca-passo, implante metálico, claustrofobia e gestação são casos de avaliação.",
      "Se precisar de sedação, veja na aba Guia o exame com sedação e avise o valor diferente.",
    ],
  },
  {
    id: "Preferiu outra clínica",
    categoria: "Comercial",
    significado: "Avisou que vai fazer em outro serviço",
    roteiro: ["Pergunte o porquê e anote em observações.", "Se foi preço ou prazo, registre também isso: muda o indicador."],
  },
  {
    id: "Não respondeu",
    categoria: "Comercial",
    significado: "Não respondeu às tentativas do protocolo",
    roteiro: ["Tente ao menos três vezes, em dias e horários diferentes.", "Só então feche como perdido."],
  },
  { id: "Outro", categoria: "Outro", significado: "Motivo que não está na lista", roteiro: ["Descreva nas observações o que aconteceu."] },
];
export const categoriaDoMotivo = (m: string | null): CategoriaPerda | null => MOTIVOS_PERDA.find((x) => x.id === m)?.categoria ?? null;
export const roteiroDoMotivo = (m: string | null) => MOTIVOS_PERDA.find((x) => x.id === m)?.roteiro ?? [];

export const PROXIMAS_ACOES = ["Ligar", "Enviar WhatsApp", "Reenviar orçamento", "Verificar vaga", "Acompanhar autorização", "Sem ação"] as const;

export type StatusAgenda = "Agendado" | "Realizado" | "Faltou" | "Cancelado" | "Reagendado";
/** O status vem do Klingo (relatório #13825), ninguém digita: a regra de cada um está em `statusDoKlingo`. */
export const STATUS_AGENDA: { id: StatusAgenda; significado: string; acao: string }[] = [
  { id: "Agendado", significado: "Marcação aberta, com exame hoje ou depois", acao: "Confirmar com o paciente" },
  { id: "Realizado", significado: "O Klingo registrou o atendimento: o paciente fez o exame", acao: "Nada a fazer" },
  { id: "Faltou", significado: "Marcação aberta, sem atendimento e com a data já passada", acao: "Ligar, entender o motivo e oferecer novo horário" },
  { id: "Cancelado", significado: "Cancelada no Klingo", acao: "Oferecer a vaga a quem está esperando" },
  { id: "Reagendado", significado: "Cancelada com o motivo “Remarcado”: o paciente já tem outra marcação", acao: "Nada a fazer: a nova marcação aparece sozinha" },
];

export type Confirmacao = "Confirmou" | "Não respondeu" | "Solicitou reagendamento" | "Não contatado";
export const CONFIRMACOES: Confirmacao[] = ["Confirmou", "Não respondeu", "Solicitou reagendamento", "Não contatado"];

export const MAX_OBS = 500;
export const codigoContato = (id: number) => `RM-${String(id).padStart(4, "0")}`;

// ───────── Registros ─────────

export const CAMPOS_CONTATO =
  "id, data_contato, canal, origem_registro, tipo_paciente, exame, forma_pagamento, convenio, valor_informado, situacao, motivo_perda, data_ultimo_contato, primeira_resposta_em, proxima_acao, data_retorno, responsavel, observacoes, codigo_klingo, telefone, criado_em, exemplo";

export type Contato = {
  id: number;
  data_contato: string;
  canal: string;
  origem_registro: string | null;
  tipo_paciente: string;
  exame: string;
  forma_pagamento: FormaPagamento;
  convenio: string | null;
  valor_informado: number | null;
  situacao: Situacao;
  motivo_perda: string | null;
  data_ultimo_contato: string | null;
  primeira_resposta_em: string | null;
  proxima_acao: string | null;
  data_retorno: string | null;
  responsavel: string | null;
  observacoes: string | null;
  codigo_klingo: string | null;
  telefone: string | null;
  criado_em: string;
  exemplo: boolean;
};

/** Uma linha de `crm_rm_agenda_klingo()`: uma marcação de RM do Klingo, como o banco entrega. */
export type AgendaKlingo = {
  codigo_marcacao: string;
  id_atendimento: string | null;
  prontuario: string | null;
  agendado_em: string | null;
  data_exame: string;
  horario: string | null;
  exame: string;
  convenio: string | null;
  forma_pagamento: FormaPagamento;
  responsavel: string | null;
  valor: number | null;
  confirm_status: string | null;
  cancelada: boolean;
  atendido: boolean;
  motivo_cancelamento: string | null;
  observacao: string | null;
  paciente: string | null;
  celular: string | null;
  telefone: string | null;
  unidade: string | null;
  atualizado_em: string;
};

/** Uma marcação do Klingo já traduzida para a linguagem do CRM (status e confirmação). */
export type Horario = {
  codigo_marcacao: string;
  id_atendimento: string | null;
  prontuario: string | null;
  /** Quando a marcação foi feita, "AAAA-MM-DDTHH:MM:SS". */
  agendado_em: string | null;
  data_exame: string;
  horario: string | null;
  exame: string;
  convenio: string | null;
  forma_pagamento: FormaPagamento;
  /** Usuário do Klingo que fez a marcação. */
  responsavel: string | null;
  valor: number | null;
  status: StatusAgenda;
  confirmacao: Confirmacao;
  motivo_cancelamento: string | null;
  observacao: string | null;
  paciente: string | null;
  /** Celular; se não houver, o telefone fixo. */
  telefone: string | null;
  atualizado_em: string;
};

/** Atendido = o Klingo abriu o atendimento. Marcação aberta e sem atendimento depois da data do exame = faltou. */
export function statusDoKlingo(a: Pick<AgendaKlingo, "atendido" | "cancelada" | "motivo_cancelamento" | "data_exame">, hoje: string): StatusAgenda {
  if (a.atendido) return "Realizado";
  if (a.cancelada) return /remarc/i.test(a.motivo_cancelamento ?? "") ? "Reagendado" : "Cancelado";
  return a.data_exame < hoje ? "Faltou" : "Agendado";
}

const CONFIRMACAO_DO_KLINGO: Record<string, Confirmacao> = { Confirmado: "Confirmou", "Sem Resposta": "Não respondeu" };

export function doKlingo(a: AgendaKlingo, hoje: string): Horario {
  return {
    codigo_marcacao: a.codigo_marcacao,
    id_atendimento: a.id_atendimento,
    prontuario: a.prontuario,
    agendado_em: a.agendado_em,
    data_exame: a.data_exame,
    horario: a.horario,
    exame: a.exame,
    convenio: a.convenio,
    forma_pagamento: a.forma_pagamento,
    responsavel: a.responsavel,
    valor: a.valor,
    status: statusDoKlingo(a, hoje),
    confirmacao: CONFIRMACAO_DO_KLINGO[a.confirm_status ?? ""] ?? "Não contatado",
    motivo_cancelamento: a.motivo_cancelamento,
    observacao: a.observacao,
    paciente: a.paciente,
    telefone: a.celular ?? a.telefone,
    atualizado_em: a.atualizado_em,
  };
}

export type ExameCatalogo = {
  id: number;
  nome: string;
  grupo: string;
  sedacao: boolean;
  contraste: string | null;
  preparo: string | null;
  duracao_min: number | null;
  observacao: string | null;
  atendimentos: number;
};
export const CAMPOS_EXAME = "id, nome, grupo, sedacao, contraste, preparo, duracao_min, observacao, atendimentos";

export type ConvenioCatalogo = {
  id: number;
  nome: string;
  tipo: FormaPagamento;
  exige_autorizacao: boolean | null;
  prazo_autorizacao: number | null;
  observacao: string | null;
  atendimentos: number;
};
export const CAMPOS_CONVENIO = "id, nome, tipo, exige_autorizacao, prazo_autorizacao, observacao, atendimentos";

export type Preco = {
  exame: string;
  particular_min: number | null;
  particular_max: number | null;
  particular_mediana: number | null;
  convenio_medio: number | null;
  atendimentos: number;
};

// ───────── Contas ─────────

const soma = (xs: (number | null | undefined)[]) => xs.reduce<number>((a, b) => a + (b ?? 0), 0);
const razao = (a: number, b: number) => (b > 0 ? (a / b) * 100 : null);
const DIA_MS = 86_400_000;
const dias = (iso: string) => Date.parse(`${iso}T12:00:00Z`) / DIA_MS;
const media = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

function contar<T>(xs: T[], chave: (x: T) => string | null): [string, number][] {
  const m = new Map<string, number>();
  for (const x of xs) {
    const k = chave(x);
    if (k) m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export type Etapa = { id: string; rotulo: string; dica: string; n: number };

export type Indicadores = {
  solicitacoes: number;
  conversao: number | null;
  funil: Etapa[];
  perdidos: number;
  valorPerdido: number;
  emAberto: number;
  valorEmAberto: number;
  perdasPorMotivo: { motivo: string; categoria: CategoriaPerda | null; n: number; pct: number; valor: number }[];
  /** Marcações de RM feitas no Klingo no período (toda a clínica, não só as que passaram pelo CRM). */
  marcacoesNovas: number;
  /** Contatos que viraram agendamento ÷ marcações novas do Klingo: quanto da operação o CRM enxerga. */
  cobertura: number | null;
  realizados: number;
  faltas: number;
  cancelamentos: number;
  reagendados: number;
  aRealizar: number;
  absenteismo: number | null;
  /** Soma do valor (tabela do Klingo) dos exames realizados. */
  valorRealizado: number;
  valorPrevistoFaltas: number;
  faltasPorConfirmacao: { confirmacao: string; agendados: number; faltas: number; taxa: number | null }[];
  porForma: { forma: string; solicitacoes: number; agendadas: number; conversao: number | null; realizados: number; faltas: number; absenteismo: number | null }[];
};

/**
 * `contatos` vêm filtrados pelo período; `horarios` são as marcações do Klingo com exame de `inicio` em diante.
 * `futuros` = marcações abertas depois de hoje.
 */
export function calcular(contatos: Contato[], horarios: Horario[], futuros: number, marcacoesNovas: number): Indicadores {
  const perdidos = contatos.filter((c) => SITUACOES_PERDA.includes(c.situacao));
  const abertos = contatos.filter((c) => SITUACOES_ABERTAS.includes(c.situacao));
  const agendadas = contatos.filter((c) => c.situacao === "Agendado");
  const comOrcamento = contatos.filter(
    (c) => c.valor_informado !== null || ["Orçamento enviado", "Aguardando autorização", "Agendado"].includes(c.situacao),
  );

  const realizados = horarios.filter((h) => h.status === "Realizado");
  const faltas = horarios.filter((h) => h.status === "Faltou");

  const valorDoMotivo = (m: string) => soma(perdidos.filter((c) => c.motivo_perda === m).map((c) => c.valor_informado));

  return {
    solicitacoes: contatos.length,
    conversao: razao(agendadas.length, contatos.length),
    funil: [
      { id: "procura", rotulo: "Procuraram o exame", dica: "Todas as solicitações registradas no período", n: contatos.length },
      {
        id: "orcamento",
        rotulo: "Chegaram ao orçamento ou à autorização",
        dica: "Têm valor informado ou estão em Orçamento enviado, Aguardando autorização ou Agendado",
        n: comOrcamento.length,
      },
      { id: "agendamento", rotulo: "Agendaram", dica: "Situação do contato = Agendado", n: agendadas.length },
    ],
    perdidos: perdidos.length,
    valorPerdido: soma(perdidos.map((c) => c.valor_informado)),
    emAberto: abertos.length,
    valorEmAberto: soma(abertos.map((c) => c.valor_informado)),
    perdasPorMotivo: contar(perdidos, (c) => c.motivo_perda).map(([motivo, n]) => ({
      motivo,
      categoria: categoriaDoMotivo(motivo),
      n,
      pct: (n / Math.max(1, perdidos.length)) * 100,
      valor: valorDoMotivo(motivo),
    })),
    marcacoesNovas,
    cobertura: razao(agendadas.length, marcacoesNovas),
    realizados: realizados.length,
    faltas: faltas.length,
    cancelamentos: horarios.filter((h) => h.status === "Cancelado").length,
    reagendados: horarios.filter((h) => h.status === "Reagendado").length,
    aRealizar: futuros,
    absenteismo: razao(faltas.length, realizados.length + faltas.length),
    valorRealizado: soma(realizados.map((h) => h.valor)),
    valorPrevistoFaltas: soma(faltas.map((h) => h.valor)),
    faltasPorConfirmacao: CONFIRMACOES.map((conf) => {
      const hs = horarios.filter((h) => h.confirmacao === conf && ["Realizado", "Faltou"].includes(h.status));
      const fa = hs.filter((h) => h.status === "Faltou").length;
      return { confirmacao: conf, agendados: hs.length, faltas: fa, taxa: razao(fa, hs.length) };
    }),
    porForma: FORMAS_PAGAMENTO.map((forma) => {
      const cs = contatos.filter((c) => c.forma_pagamento === forma);
      const hs = horarios.filter((h) => h.forma_pagamento === forma);
      const ag = cs.filter((c) => c.situacao === "Agendado").length;
      const re = hs.filter((h) => h.status === "Realizado").length;
      const fa = hs.filter((h) => h.status === "Faltou").length;
      return { forma, solicitacoes: cs.length, agendadas: ag, conversao: razao(ag, cs.length), realizados: re, faltas: fa, absenteismo: razao(fa, re + fa) };
    }).filter((f) => f.solicitacoes > 0 || f.realizados > 0 || f.faltas > 0),
  };
}

// ───────── Agenda do Klingo ─────────

export type LinhaAgenda = { nome: string; marcacoes: number; feitos: number; faltas: number; cancelados: number; absenteismo: number | null };

export type ResumoAgenda = {
  porConvenio: LinhaAgenda[];
  porGrupo: LinhaAgenda[];
  porResponsavel: { nome: string; marcacoes: number; cancelados: number; pctCancelado: number | null }[];
};

const ABERTO_OU_FEITO: StatusAgenda[] = ["Agendado", "Realizado", "Faltou"];

function linhaDaAgenda(nome: string, hs: Horario[]): LinhaAgenda {
  const feitos = hs.filter((h) => h.status === "Realizado").length;
  const faltas = hs.filter((h) => h.status === "Faltou").length;
  return {
    nome,
    marcacoes: hs.length,
    feitos,
    faltas,
    cancelados: hs.filter((h) => h.status === "Cancelado" || h.status === "Reagendado").length,
    absenteismo: razao(faltas, feitos + faltas),
  };
}

function agruparAgenda(horarios: Horario[], chave: (h: Horario) => string): LinhaAgenda[] {
  const grupos = new Map<string, Horario[]>();
  for (const h of horarios) grupos.set(chave(h), [...(grupos.get(chave(h)) ?? []), h]);
  return [...grupos.entries()].map(([nome, hs]) => linhaDaAgenda(nome, hs)).sort((a, b) => b.marcacoes - a.marcacoes || a.nome.localeCompare(b.nome));
}

/** Quem marca, o que marca e por onde se perde: tudo a partir das marcações do Klingo. */
export function resumirAgenda(horarios: Horario[], grupoDoExame: (nome: string) => string): ResumoAgenda {
  const porResp = new Map<string, Horario[]>();
  for (const h of horarios) porResp.set(h.responsavel ?? "(sem usuário)", [...(porResp.get(h.responsavel ?? "(sem usuário)") ?? []), h]);
  return {
    porConvenio: agruparAgenda(horarios, (h) => h.convenio ?? "(sem convênio)"),
    porGrupo: agruparAgenda(horarios, (h) => grupoDoExame(h.exame)),
    porResponsavel: [...porResp.entries()]
      .map(([nome, hs]) => {
        const cancelados = hs.filter((h) => h.status === "Cancelado" || h.status === "Reagendado").length;
        return { nome, marcacoes: hs.length, cancelados, pctCancelado: razao(cancelados, hs.length) };
      })
      .sort((a, b) => b.marcacoes - a.marcacoes || a.nome.localeCompare(b.nome)),
  };
}

// ───────── Calendário da agenda ─────────

/** Marcações de um dia, por situação: abertas = exame de hoje em diante; canceladas incluem as remarcadas. */
export type ContagemDia = { total: number; abertas: number; feitas: number; faltas: number; canceladas: number };

/** "2026-10" vale se o mês for de 01 a 12; qualquer outra coisa vira o mês de `hoje`. */
export function mesDoCalendario(texto: string | undefined, hoje: string): string {
  return texto && /^\d{4}-(0[1-9]|1[0-2])$/.test(texto) ? texto : hoje.slice(0, 7);
}

/** Anda `n` meses (pode ser negativo): "2026-12" + 1 = "2027-01". */
export function somarMeses(mes: string, n: number): string {
  const [ano, m] = mes.split("-").map(Number);
  const total = ano * 12 + (m - 1) + n;
  return `${String(Math.floor(total / 12)).padStart(4, "0")}-${String((total % 12) + 1).padStart(2, "0")}`;
}

/** O mês em semanas de domingo a sábado: cada célula é o dia "AAAA-MM-DD", ou null fora do mês. */
export function semanasDoMes(mes: string): (string | null)[][] {
  const [ano, m] = mes.split("-").map(Number);
  const antes = new Date(Date.UTC(ano, m - 1, 1)).getUTCDay();
  const dias = new Date(Date.UTC(ano, m, 0)).getUTCDate();
  const celulas: (string | null)[] = [
    ...Array<null>(antes).fill(null),
    ...Array.from({ length: dias }, (_, i) => `${mes}-${String(i + 1).padStart(2, "0")}`),
  ];
  while (celulas.length % 7 !== 0) celulas.push(null);
  return Array.from({ length: celulas.length / 7 }, (_, s) => celulas.slice(s * 7, s * 7 + 7));
}

/** Quantas marcações há em cada dia de exame, separadas por situação. */
export function contarPorDia(horarios: Horario[]): Map<string, ContagemDia> {
  const dias = new Map<string, ContagemDia>();
  for (const h of horarios) {
    const c = dias.get(h.data_exame) ?? { total: 0, abertas: 0, feitas: 0, faltas: 0, canceladas: 0 };
    c.total += 1;
    if (h.status === "Agendado") c.abertas += 1;
    else if (h.status === "Realizado") c.feitas += 1;
    else if (h.status === "Faltou") c.faltas += 1;
    else c.canceladas += 1;
    dias.set(h.data_exame, c);
  }
  return dias;
}

// ───────── Marketing ─────────

export type Marketing = {
  porCanal: { canal: string; solicitacoes: number; agendadas: number; conversao: number | null; ticket: number | null; receitaAgendada: number; novos: number }[];
  demandaReprimida: { exame: string; perdas: number; valor: number }[];
  conveniosNaoAtendidos: { convenio: string; pedidos: number }[];
  precoPerdeu: number | null;
  precoGanhou: number | null;
  pctPerdaPorPreco: number | null;
  novos: number;
  recorrentes: number;
  pctNovos: number | null;
  respostaMediaHoras: number | null;
  respostaPorCanal: { canal: string; horas: number | null; medidos: number }[];
  semResposta: number;
  antecedenciaMedia: number | null;
  porDiaSemana: { dia: string; n: number }[];
  topProcurados: { exame: string; procurado: number; marcado: number; feito: number }[];
};

const DIAS_SEMANA = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];

/** Indicadores pensados para decidir onde investir em captação. `grupoDoExame` junta os nomes do Klingo. */
export function calcularMarketing(contatos: Contato[], horarios: Horario[], grupoDoExame: (nome: string) => string): Marketing {
  const perdidos = contatos.filter((c) => SITUACOES_PERDA.includes(c.situacao));
  const agendados = contatos.filter((c) => c.situacao === "Agendado");
  const pagantes = (c: Contato) => FORMAS_PAGANTES.includes(c.forma_pagamento);

  const horasResposta = (c: Contato) =>
    c.primeira_resposta_em ? (Date.parse(c.primeira_resposta_em) - Date.parse(`${c.data_contato}T09:00:00-03:00`)) / 3_600_000 : null;
  const respostas = contatos.map(horasResposta).filter((h): h is number => h !== null && h >= 0);

  const porCanal = [...new Set(contatos.map((c) => c.canal))]
    .map((canal) => {
      const doCanal = contatos.filter((c) => c.canal === canal);
      const ag = doCanal.filter((c) => c.situacao === "Agendado");
      const valores = ag.filter(pagantes).map((c) => c.valor_informado).filter((v): v is number => v !== null);
      return {
        canal,
        solicitacoes: doCanal.length,
        agendadas: ag.length,
        conversao: razao(ag.length, doCanal.length),
        ticket: media(valores),
        receitaAgendada: soma(valores),
        novos: doCanal.filter((c) => c.tipo_paciente === "Novo paciente").length,
      };
    })
    .sort((a, b) => b.solicitacoes - a.solicitacoes);

  const semVaga = perdidos.filter((c) => c.motivo_perda === "Sem vaga na data desejada");
  const demandaReprimida = contar(semVaga, (c) => grupoDoExame(c.exame)).map(([exame, perdas]) => ({
    exame,
    perdas,
    valor: soma(semVaga.filter((c) => grupoDoExame(c.exame) === exame).map((c) => c.valor_informado)),
  }));

  const naoAtendidos = perdidos.filter((c) => c.motivo_perda === "Convênio não atendido");
  const valoresPerdidosPreco = perdidos.filter((c) => c.motivo_perda === "Preço").map((c) => c.valor_informado).filter((v): v is number => v !== null);
  const valoresGanhos = agendados.filter(pagantes).map((c) => c.valor_informado).filter((v): v is number => v !== null);

  // Antecedência = da marcação (Klingo) até o exame, nas marcações que não foram canceladas.
  const antecedencias = horarios
    .filter((h) => h.agendado_em !== null && ABERTO_OU_FEITO.includes(h.status))
    .map((h) => dias(h.data_exame) - dias((h.agendado_em as string).slice(0, 10)))
    .filter((d) => d >= 0);

  const procurados = new Map(contar(contatos, (c) => grupoDoExame(c.exame)));
  const marcados = new Map(contar(horarios.filter((h) => ABERTO_OU_FEITO.includes(h.status)), (h) => grupoDoExame(h.exame)));
  const feitos = new Map(contar(horarios.filter((h) => h.status === "Realizado"), (h) => grupoDoExame(h.exame)));
  const topProcurados = [...new Set([...procurados.keys(), ...marcados.keys()])]
    .map((exame) => ({ exame, procurado: procurados.get(exame) ?? 0, marcado: marcados.get(exame) ?? 0, feito: feitos.get(exame) ?? 0 }))
    .sort((a, b) => b.marcado - a.marcado || b.procurado - a.procurado || a.exame.localeCompare(b.exame))
    .slice(0, 8);

  return {
    porCanal,
    demandaReprimida,
    conveniosNaoAtendidos: contar(naoAtendidos, (c) => c.convenio ?? "(não anotado)").map(([convenio, pedidos]) => ({ convenio, pedidos })),
    precoPerdeu: media(valoresPerdidosPreco),
    precoGanhou: media(valoresGanhos),
    pctPerdaPorPreco: razao(perdidos.filter((c) => c.motivo_perda === "Preço").length, perdidos.length),
    novos: contatos.filter((c) => c.tipo_paciente === "Novo paciente").length,
    recorrentes: contatos.filter((c) => c.tipo_paciente === "Paciente já atendido").length,
    pctNovos: razao(contatos.filter((c) => c.tipo_paciente === "Novo paciente").length, contatos.length),
    respostaMediaHoras: media(respostas),
    respostaPorCanal: [...new Set(contatos.map((c) => c.canal))]
      .map((canal) => {
        const hs = contatos.filter((c) => c.canal === canal).map(horasResposta).filter((h): h is number => h !== null && h >= 0);
        return { canal, horas: media(hs), medidos: hs.length };
      })
      .filter((x) => x.medidos > 0)
      .sort((a, b) => (b.horas ?? 0) - (a.horas ?? 0)),
    semResposta: contatos.filter((c) => c.primeira_resposta_em === null).length,
    antecedenciaMedia: media(antecedencias),
    porDiaSemana: DIAS_SEMANA.map((dia, i) => ({
      dia,
      n: contatos.filter((c) => new Date(`${c.data_contato}T12:00:00Z`).getUTCDay() === i).length,
    })).filter((d) => d.n > 0),
    topProcurados,
  };
}

// ───────── Fila de trabalho (aba "Meu dia") ─────────

export type Fila = {
  retornos: Contato[];
  semPrimeiraResposta: Contato[];
  parados: Contato[];
  /** Exames de hoje até depois de amanhã que ainda não confirmaram (a confirmação é registrada no Klingo). */
  confirmar: Horario[];
  /** Faltaram nos últimos 7 dias: oferecer novo horário. */
  faltaram: Horario[];
  /** Marcações canceladas ou remarcadas com exame de hoje até daqui a 7 dias: a vaga está livre. */
  vagasAbertas: Horario[];
  esperandoVaga: Contato[];
};

/** Quantos dias um contato aberto pode ficar sem retorno marcado antes de virar pendência. */
export const DIAS_PARADO = 3;

export function montarFila(contatos: Contato[], horarios: Horario[], hoje: string, emDias: (n: number) => string): Fila {
  const abertos = contatos.filter((c) => SITUACOES_ABERTAS.includes(c.situacao));
  const porData = (a: Contato, b: Contato) => (a.data_retorno ?? "").localeCompare(b.data_retorno ?? "") || a.id - b.id;
  const porExame = (a: Horario, b: Horario) =>
    a.data_exame.localeCompare(b.data_exame) || (a.horario ?? "").localeCompare(b.horario ?? "") || a.codigo_marcacao.localeCompare(b.codigo_marcacao);

  return {
    retornos: abertos.filter((c) => c.data_retorno !== null && c.data_retorno <= hoje).sort(porData),
    semPrimeiraResposta: abertos.filter((c) => c.primeira_resposta_em === null).sort((a, b) => a.data_contato.localeCompare(b.data_contato) || a.id - b.id),
    parados: abertos
      .filter((c) => c.data_retorno === null && (c.data_ultimo_contato ?? c.data_contato) <= emDias(-DIAS_PARADO))
      .sort((a, b) => (a.data_ultimo_contato ?? a.data_contato).localeCompare(b.data_ultimo_contato ?? b.data_contato)),
    confirmar: horarios
      .filter((h) => h.status === "Agendado" && h.data_exame >= hoje && h.data_exame <= emDias(2) && h.confirmacao !== "Confirmou")
      .sort(porExame),
    faltaram: horarios.filter((h) => h.status === "Faltou" && h.data_exame >= emDias(-7)).sort((a, b) => porExame(b, a)),
    vagasAbertas: horarios
      .filter((h) => (h.status === "Cancelado" || h.status === "Reagendado") && h.data_exame >= hoje && h.data_exame <= emDias(7))
      .sort(porExame),
    esperandoVaga: contatos
      .filter((c) => c.motivo_perda === "Sem vaga na data desejada" || (SITUACOES_ABERTAS.includes(c.situacao) && c.proxima_acao === "Verificar vaga"))
      .sort((a, b) => b.data_contato.localeCompare(a.data_contato)),
  };
}

/** O que pede ação da atendente. As vagas abertas ficam de fora: são oportunidade, não pendência. */
export const tamanhoDaFila = (f: Fila) =>
  f.retornos.length + f.semPrimeiraResposta.length + f.parados.length + f.confirmar.length + f.faltaram.length;

// ───────── Utilidades ─────────

/** "650,50", "650.50", "1.250,00" -> número; vazio -> null; lixo -> NaN. */
export function lerValor(texto: string): number | null {
  const t = texto.trim().replace(/^R\$\s*/i, "");
  if (!t) return null;
  const normal = t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t;
  return /^\d+(\.\d{1,2})?$/.test(normal) ? Number(normal) : Number.NaN;
}

/** Telefone só com dígitos: "(71) 99999-8888" -> "71999998888". */
export const soDigitos = (t: string) => t.replace(/\D/g, "");

export function telefoneBonito(t: string | null): string {
  if (!t) return "";
  const d = soDigitos(t);
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return d;
}

/** Link de WhatsApp (o Brasil é 55). Só para a atendente abrir a conversa. */
export const linkWhatsApp = (t: string | null) => (t ? `https://wa.me/55${soDigitos(t)}` : null);
