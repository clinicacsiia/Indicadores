// Aba "CRM Ressonância": o caminho do paciente na RM (procura -> orçamento/autorização ->
// agendamento -> comparecimento -> realização), registrado pela equipe de atendimento.
//
// Nomenclatura: exames e convênios vêm do CATÁLOGO (`crm_rm_exame` / `crm_rm_convenio`), semeado
// com o nome EXATO que o Klingo usa. O que a atendente escolhe aqui é o mesmo que ela marca lá;
// sem isso nenhum número cruza com o sistema. Formas de pagamento seguem o resto do sistema
// (Cetrus = antigo "SUS CURSO"; "pagante" = Particular + Convênio).
//
// Permissões em profiles.permissions, as duas desligadas até o administrador marcar:
//   crm_rm_preencher = registra e atualiza o que ela mesma registrou
//   crm_rm           = vê os indicadores e todas as listas, atualiza qualquer registro
// Administrador tem as duas. O banco (RLS) aplica a mesma regra.
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
  { id: "Agendado", significado: "Já tem horário reservado", acao: "Registrar o horário na aba Agenda" },
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
export const STATUS_AGENDA: { id: StatusAgenda; significado: string; acao: string }[] = [
  { id: "Agendado", significado: "Horário reservado, o exame ainda não aconteceu", acao: "Confirmar com o paciente" },
  { id: "Realizado", significado: "O exame foi feito", acao: "Preencher o valor realizado" },
  { id: "Faltou", significado: "Não compareceu e não fez o exame", acao: "Registrar o motivo e oferecer novo horário" },
  { id: "Cancelado", significado: "Cancelou antes do exame", acao: "Oferecer a vaga a quem está esperando" },
  { id: "Reagendado", significado: "Passou para outra data (a nova data é outro horário na Agenda)", acao: "Registrar o novo horário sem criar contato novo" },
];
export const SAI_DO_COMPARECIMENTO: StatusAgenda[] = ["Faltou", "Cancelado", "Reagendado"];

export const CONFIRMACOES = ["Confirmou", "Não respondeu", "Solicitou reagendamento", "Não contatado"] as const;
export const MOTIVOS_FALTA = ["Esqueceu", "Problema de transporte", "Preparo inadequado", "Autorização pendente", "Doença / imprevisto", "Outro"] as const;
export const VAGA_RECUPERADA = ["Sim", "Não", "Não se aplica"] as const;
export const MOTIVOS_OPERACIONAIS = ["Equipamento parado", "Bobina indisponível", "Manutenção", "Falta de profissional", "Atraso no preparo", "Outro"] as const;

export const MAX_OBS = 500;
export const codigoContato = (id: number) => `RM-${String(id).padStart(4, "0")}`;

// ───────── Registros ─────────

export const CAMPOS_CONTATO =
  "id, data_contato, canal, origem_registro, tipo_paciente, exame, forma_pagamento, convenio, valor_informado, situacao, motivo_perda, data_ultimo_contato, primeira_resposta_em, proxima_acao, data_retorno, responsavel, observacoes, codigo_klingo, telefone, criado_em, exemplo";
export const CAMPOS_AGENDA =
  "id, contato_id, codigo_marcacao, data_exame, horario, forma_pagamento, exame, status, confirmacao, motivo_falta, vaga_recuperada, valor_previsto, valor_realizado, horas_paradas, motivo_operacional, exemplo";

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

export type Horario = {
  id: number;
  contato_id: number | null;
  codigo_marcacao: string | null;
  data_exame: string;
  horario: string | null;
  forma_pagamento: FormaPagamento;
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
  realizados: number;
  faltas: number;
  cancelamentos: number;
  reagendados: number;
  aRealizar: number;
  absenteismo: number | null;
  receitaRealizada: number;
  valorPrevistoFaltas: number;
  vagasElegiveis: number;
  vagasRecuperadas: number;
  pctRecuperadas: number | null;
  faltasPorConfirmacao: { confirmacao: string; agendados: number; faltas: number; taxa: number | null }[];
  motivosFalta: { motivo: string; n: number }[];
  horasParadas: number;
  motivosOperacionais: { motivo: string; n: number; horas: number }[];
  porForma: { forma: string; solicitacoes: number; agendadas: number; conversao: number | null; realizados: number; faltas: number; absenteismo: number | null }[];
};

/** `contatos` e `horarios` já vêm filtrados pelo período; `futuros` = horários marcados depois de hoje. */
export function calcular(contatos: Contato[], horarios: Horario[], futuros: number): Indicadores {
  const perdidos = contatos.filter((c) => SITUACOES_PERDA.includes(c.situacao));
  const abertos = contatos.filter((c) => SITUACOES_ABERTAS.includes(c.situacao));
  const agendadas = contatos.filter((c) => c.situacao === "Agendado");
  const comOrcamento = contatos.filter(
    (c) => c.valor_informado !== null || ["Orçamento enviado", "Aguardando autorização", "Agendado"].includes(c.situacao),
  );

  const realizados = horarios.filter((h) => h.status === "Realizado");
  const faltas = horarios.filter((h) => h.status === "Faltou");
  const cancelados = horarios.filter((h) => h.status === "Cancelado");
  const elegiveis = horarios.filter((h) => h.status === "Faltou" || h.status === "Cancelado");
  const recuperadas = elegiveis.filter((h) => h.vaga_recuperada === "Sim");

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
      { id: "realizacao", rotulo: "Fizeram o exame", dica: "Horários da Agenda com status Realizado no período", n: realizados.length },
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
    realizados: realizados.length,
    faltas: faltas.length,
    cancelamentos: cancelados.length,
    reagendados: horarios.filter((h) => h.status === "Reagendado").length,
    aRealizar: futuros,
    absenteismo: razao(faltas.length, realizados.length + faltas.length),
    receitaRealizada: soma(realizados.map((h) => h.valor_realizado)),
    valorPrevistoFaltas: soma(faltas.map((h) => h.valor_previsto)),
    vagasElegiveis: elegiveis.length,
    vagasRecuperadas: recuperadas.length,
    pctRecuperadas: razao(recuperadas.length, elegiveis.length),
    faltasPorConfirmacao: CONFIRMACOES.map((conf) => {
      const hs = horarios.filter((h) => h.confirmacao === conf && ["Realizado", "Faltou"].includes(h.status));
      const fa = hs.filter((h) => h.status === "Faltou").length;
      return { confirmacao: conf, agendados: hs.length, faltas: fa, taxa: razao(fa, hs.length) };
    }),
    motivosFalta: contar(faltas, (h) => h.motivo_falta).map(([motivo, n]) => ({ motivo, n })),
    horasParadas: soma(horarios.map((h) => h.horas_paradas)),
    motivosOperacionais: contar(horarios, (h) => h.motivo_operacional).map(([motivo, n]) => ({
      motivo,
      n,
      horas: soma(horarios.filter((h) => h.motivo_operacional === motivo).map((h) => h.horas_paradas)),
    })),
    porForma: FORMAS_PAGAMENTO.map((forma) => {
      const cs = contatos.filter((c) => c.forma_pagamento === forma);
      const hs = horarios.filter((h) => h.forma_pagamento === forma);
      const ag = cs.filter((c) => c.situacao === "Agendado").length;
      const re = hs.filter((h) => h.status === "Realizado").length;
      const fa = hs.filter((h) => h.status === "Faltou").length;
      return { forma, solicitacoes: cs.length, agendadas: ag, conversao: razao(ag, cs.length), realizados: re, faltas: fa, absenteismo: razao(fa, re + fa) };
    }).filter((f) => f.solicitacoes > 0 || f.realizados > 0),
  };
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
  topProcurados: { exame: string; procurado: number; realizado: number; conversao: number | null }[];
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

  const comExame = (nome: string) => grupoDoExame(nome);
  const procurados = contar(contatos, (c) => comExame(c.exame));
  const realizadosPorGrupo = new Map(contar(horarios.filter((h) => h.status === "Realizado"), (h) => comExame(h.exame)));

  const agendadosComExame = horarios.filter((h) => h.contato_id !== null);
  const antecedencias = agendadosComExame
    .map((h) => {
      const c = contatos.find((x) => x.id === h.contato_id);
      return c ? dias(h.data_exame) - dias(c.data_contato) : null;
    })
    .filter((d): d is number => d !== null && d >= 0);

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
    topProcurados: procurados.slice(0, 8).map(([exame, procurado]) => {
      const realizado = realizadosPorGrupo.get(exame) ?? 0;
      return { exame, procurado, realizado, conversao: razao(realizado, procurado) };
    }),
  };
}

// ───────── Fila de trabalho (aba "Meu dia") ─────────

export type Fila = {
  retornos: Contato[];
  semPrimeiraResposta: Contato[];
  parados: Contato[];
  confirmar: Horario[];
  semResultado: Horario[];
  vagasAbertas: Horario[];
  esperandoVaga: Contato[];
};

/** Quantos dias um contato aberto pode ficar sem retorno marcado antes de virar pendência. */
export const DIAS_PARADO = 3;

export function montarFila(contatos: Contato[], horarios: Horario[], hoje: string, emDias: (n: number) => string): Fila {
  const abertos = contatos.filter((c) => SITUACOES_ABERTAS.includes(c.situacao));
  const porData = (a: Contato, b: Contato) => (a.data_retorno ?? "").localeCompare(b.data_retorno ?? "") || a.id - b.id;

  return {
    retornos: abertos.filter((c) => c.data_retorno !== null && c.data_retorno <= hoje).sort(porData),
    semPrimeiraResposta: abertos.filter((c) => c.primeira_resposta_em === null).sort((a, b) => a.data_contato.localeCompare(b.data_contato) || a.id - b.id),
    parados: abertos
      .filter((c) => c.data_retorno === null && (c.data_ultimo_contato ?? c.data_contato) <= emDias(-DIAS_PARADO))
      .sort((a, b) => (a.data_ultimo_contato ?? a.data_contato).localeCompare(b.data_ultimo_contato ?? b.data_contato)),
    confirmar: horarios
      .filter((h) => h.status === "Agendado" && h.data_exame >= hoje && h.data_exame <= emDias(2) && h.confirmacao !== "Confirmou")
      .sort((a, b) => a.data_exame.localeCompare(b.data_exame) || (a.horario ?? "").localeCompare(b.horario ?? "")),
    semResultado: horarios
      .filter((h) => h.status === "Agendado" && h.data_exame < hoje)
      .sort((a, b) => b.data_exame.localeCompare(a.data_exame)),
    vagasAbertas: horarios
      .filter((h) => (h.status === "Faltou" || h.status === "Cancelado") && h.vaga_recuperada === "Não" && h.data_exame >= emDias(-14))
      .sort((a, b) => b.data_exame.localeCompare(a.data_exame)),
    esperandoVaga: contatos
      .filter((c) => c.motivo_perda === "Sem vaga na data desejada" || (SITUACOES_ABERTAS.includes(c.situacao) && c.proxima_acao === "Verificar vaga"))
      .sort((a, b) => b.data_contato.localeCompare(a.data_contato)),
  };
}

export const tamanhoDaFila = (f: Fila) =>
  f.retornos.length + f.semPrimeiraResposta.length + f.parados.length + f.confirmar.length + f.semResultado.length + f.vagasAbertas.length;

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
