"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { hojeEmBrasilia } from "@/lib/avisos";
import {
  CANAIS,
  CONFIRMACOES,
  EXAMES,
  FORMAS_PAGAMENTO,
  MAX_OBS,
  MOTIVOS_FALTA,
  MOTIVOS_OPERACIONAIS,
  MOTIVOS_PERDA,
  PROXIMAS_ACOES,
  SAI_DO_COMPARECIMENTO,
  SITUACOES,
  SITUACOES_PERDA,
  STATUS_AGENDA,
  TIPOS_PACIENTE,
  VAGA_RECUPERADA,
  lerValor,
  type StatusAgenda,
} from "@/lib/crm-rm";

export type CrmState = { ok?: boolean; error?: string };

const DATA_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const HORA_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const texto = (f: FormData, nome: string) => String(f.get(nome) ?? "").trim();
const dataValida = (iso: string) => DATA_RE.test(iso) && new Date(`${iso}T12:00:00Z`).toISOString().slice(0, 10) === iso;
const naLista = (lista: readonly string[], v: string) => lista.includes(v);

function valor(f: FormData, nome: string, rotulo: string): { v: number | null } | { error: string } {
  const n = lerValor(texto(f, nome));
  if (Number.isNaN(n)) return { error: `${rotulo}: use só números, por exemplo 650,00.` };
  if (n !== null && n > 100000) return { error: `${rotulo}: valor alto demais, confira.` };
  return { v: n };
}

function erroDoBanco(error: { code?: string; message: string }, padrao: string) {
  console.error("Falha ao gravar no CRM da RM:", error.code, error.message);
  if (error.code === "42501") return "Você não tem permissão para esta ação.";
  if (error.code === "23514") return "Algum campo não combina com os outros. Confira a situação, o motivo e as datas.";
  return padrao;
}

// Regras que o banco também garante; aqui só para a mensagem sair clara em português.
function conferirContato(situacao: string, motivo: string, retorno: string, dataContato: string): string | null {
  if (!naLista(SITUACOES.map((s) => s.id), situacao)) return "Escolha a situação do contato.";
  const perdeu = (SITUACOES_PERDA as string[]).includes(situacao);
  if (perdeu && !motivo) return `Quando a situação é "${situacao}", informe o motivo.`;
  if (!perdeu && motivo) return `O motivo só vale para "Não agendou" ou "Desistiu". Limpe o motivo ou mude a situação.`;
  if (motivo && !naLista(MOTIVOS_PERDA.map((m) => m.id), motivo)) return "Motivo inválido.";
  if (retorno && (!dataValida(retorno) || retorno < dataContato)) return "A data de retorno não pode ser antes do contato.";
  return null;
}

export async function registrarContato(_prev: CrmState, f: FormData): Promise<CrmState> {
  const data = texto(f, "data_contato");
  const canal = texto(f, "canal");
  const tipo = texto(f, "tipo_paciente");
  const exame = texto(f, "exame");
  const forma = texto(f, "forma_pagamento");
  const convenio = texto(f, "convenio");
  const situacao = texto(f, "situacao") || "Novo contato";
  const motivo = texto(f, "motivo_perda");
  const acao = texto(f, "proxima_acao");
  const retorno = texto(f, "data_retorno");
  const responsavel = texto(f, "responsavel");
  const obs = texto(f, "observacoes");

  if (!dataValida(data)) return { error: "Informe a data do contato." };
  if (data > hojeEmBrasilia()) return { error: "A data do contato não pode estar no futuro." };
  if (data < hojeEmBrasilia(-365)) return { error: "A data do contato não pode ser de mais de um ano atrás." };
  if (!naLista(CANAIS, canal)) return { error: "Escolha por onde o paciente entrou em contato." };
  if (!naLista(TIPOS_PACIENTE, tipo)) return { error: "Informe se é paciente novo ou já atendido." };
  if (!naLista(EXAMES, exame)) return { error: "Escolha o exame solicitado." };
  if (!naLista(FORMAS_PAGAMENTO, forma)) return { error: "Escolha Particular ou Convênio." };
  if (convenio.length > 60) return { error: "O nome do convênio pode ter no máximo 60 caracteres." };
  if (acao && !naLista(PROXIMAS_ACOES, acao)) return { error: "Próxima ação inválida." };
  if (responsavel.length > 60) return { error: "O nome do responsável pode ter no máximo 60 caracteres." };
  if (obs.length > MAX_OBS) return { error: `As observações podem ter no máximo ${MAX_OBS} caracteres.` };
  const problema = conferirContato(situacao, motivo, retorno, data);
  if (problema) return { error: problema };
  const v = valor(f, "valor_informado", "Valor informado");
  if ("error" in v) return v;

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sua sessão expirou. Entre de novo." };

  const { error } = await supabase.from("crm_rm_contato").insert({
    data_contato: data,
    canal,
    tipo_paciente: tipo,
    exame,
    forma_pagamento: forma,
    convenio: forma === "Convênio" ? convenio || null : null,
    valor_informado: v.v,
    situacao,
    motivo_perda: motivo || null,
    data_ultimo_contato: data,
    proxima_acao: acao || null,
    data_retorno: retorno || null,
    responsavel: responsavel || null,
    observacoes: obs || null,
    criado_por: auth.user.id,
  });
  if (error) return { error: erroDoBanco(error, "Não foi possível registrar o contato. Tente de novo.") };

  revalidatePath("/crm-rm");
  return { ok: true };
}

// Depois de cada conversa com o paciente: muda a situação, o motivo, a próxima ação e a data de retorno.
export async function atualizarContato(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = Number(f.get("id"));
  const dataContato = texto(f, "data_contato");
  const situacao = texto(f, "situacao");
  const motivo = texto(f, "motivo_perda");
  const acao = texto(f, "proxima_acao");
  const retorno = texto(f, "data_retorno");
  const responsavel = texto(f, "responsavel");
  const obs = texto(f, "observacoes");

  if (!Number.isSafeInteger(id) || id <= 0 || !dataValida(dataContato)) return { error: "Registro inválido." };
  if (acao && !naLista(PROXIMAS_ACOES, acao)) return { error: "Próxima ação inválida." };
  if (responsavel.length > 60) return { error: "O nome do responsável pode ter no máximo 60 caracteres." };
  if (obs.length > MAX_OBS) return { error: `As observações podem ter no máximo ${MAX_OBS} caracteres.` };
  const problema = conferirContato(situacao, motivo, retorno, dataContato);
  if (problema) return { error: problema };
  const v = valor(f, "valor_informado", "Valor informado");
  if ("error" in v) return v;

  const supabase = await createClient();
  const { data, error } = await supabase
    .from("crm_rm_contato")
    .update({
      situacao,
      motivo_perda: motivo || null,
      valor_informado: v.v,
      data_ultimo_contato: hojeEmBrasilia() < dataContato ? dataContato : hojeEmBrasilia(),
      proxima_acao: acao || null,
      data_retorno: retorno || null,
      responsavel: responsavel || null,
      observacoes: obs || null,
    })
    .eq("id", id)
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar. Tente de novo.") };
  if (!data?.length) return { error: "Você não pode alterar este registro." };

  revalidatePath("/crm-rm");
  return { ok: true };
}

function conferirHorario(status: string, motivoFalta: string, vaga: string, valorRealizado: number | null, motivoOp: string, horas: number | null): string | null {
  if (!STATUS_AGENDA.some((s) => s.id === status)) return "Escolha o status do horário.";
  const saiu = (SAI_DO_COMPARECIMENTO as string[]).includes(status);
  if (motivoFalta && !naLista(MOTIVOS_FALTA, motivoFalta)) return "Motivo da falta ou cancelamento inválido.";
  if (motivoFalta && !saiu) return `O motivo da falta só vale para Faltou, Cancelado ou Reagendado. Limpe o motivo ou mude o status.`;
  if (!naLista(VAGA_RECUPERADA, vaga)) return "Informe se a vaga foi recuperada.";
  if (vaga !== "Não se aplica" && !saiu) return `"Vaga recuperada" só vale para Faltou, Cancelado ou Reagendado.`;
  if (valorRealizado !== null && status !== "Realizado") return "O valor realizado só vale para exame Realizado.";
  if (motivoOp && !naLista(MOTIVOS_OPERACIONAIS, motivoOp)) return "Motivo operacional inválido.";
  if (horas !== null && (horas < 0 || horas > 24)) return "As horas paradas ficam entre 0 e 24.";
  return null;
}

function numeroHoras(f: FormData): number | null | { error: string } {
  const t = texto(f, "horas_paradas").replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? Math.round(n * 10) / 10 : { error: "Horas paradas: use só números, por exemplo 1,5." };
}

export async function registrarHorario(_prev: CrmState, f: FormData): Promise<CrmState> {
  const contato = texto(f, "contato_id");
  const dataExame = texto(f, "data_exame");
  const hora = texto(f, "horario");
  const exame = texto(f, "exame");
  const forma = texto(f, "forma_pagamento");
  const status = texto(f, "status") || "Agendado";
  const conf = texto(f, "confirmacao") || "Não contatado";
  const motivoFalta = texto(f, "motivo_falta");
  const vaga = texto(f, "vaga_recuperada") || "Não se aplica";
  const motivoOp = texto(f, "motivo_operacional");

  const contatoId = contato ? Number(contato) : null;
  if (contatoId !== null && (!Number.isSafeInteger(contatoId) || contatoId <= 0)) return { error: "Contato inválido." };
  if (!dataValida(dataExame)) return { error: "Informe a data do exame." };
  if (dataExame > hojeEmBrasilia(120) || dataExame < hojeEmBrasilia(-365)) return { error: "A data do exame precisa estar entre o último ano e os próximos 4 meses." };
  if (hora && !HORA_RE.test(hora)) return { error: "Horário inválido." };
  if (!naLista(EXAMES, exame)) return { error: "Escolha o exame." };
  if (!naLista(FORMAS_PAGAMENTO, forma)) return { error: "Escolha Particular ou Convênio." };
  if (!naLista(CONFIRMACOES, conf)) return { error: "Escolha a confirmação prévia." };
  const prev = valor(f, "valor_previsto", "Valor previsto");
  if ("error" in prev) return prev;
  const real = valor(f, "valor_realizado", "Valor realizado");
  if ("error" in real) return real;
  const horas = numeroHoras(f);
  if (horas !== null && typeof horas === "object") return horas;
  const problema = conferirHorario(status, motivoFalta, vaga, real.v, motivoOp, horas as number | null);
  if (problema) return { error: problema };

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sua sessão expirou. Entre de novo." };

  const { error } = await supabase.from("crm_rm_agenda").insert({
    contato_id: contatoId,
    data_exame: dataExame,
    horario: hora || null,
    forma_pagamento: forma,
    exame,
    status: status as StatusAgenda,
    confirmacao: conf,
    motivo_falta: motivoFalta || null,
    vaga_recuperada: vaga,
    valor_previsto: prev.v,
    valor_realizado: real.v,
    horas_paradas: horas as number | null,
    motivo_operacional: motivoOp || null,
    criado_por: auth.user.id,
  });
  if (error) return { error: erroDoBanco(error, "Não foi possível registrar o horário. Tente de novo.") };

  revalidatePath("/crm-rm");
  return { ok: true };
}

// Depois da data do exame: realizado, faltou, cancelado ou reagendado (e o que aconteceu).
export async function atualizarHorario(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = Number(f.get("id"));
  const status = texto(f, "status");
  const conf = texto(f, "confirmacao");
  const motivoFalta = texto(f, "motivo_falta");
  const vaga = texto(f, "vaga_recuperada") || "Não se aplica";
  const motivoOp = texto(f, "motivo_operacional");
  if (!Number.isSafeInteger(id) || id <= 0) return { error: "Registro inválido." };
  if (!naLista(CONFIRMACOES, conf)) return { error: "Escolha a confirmação prévia." };
  const real = valor(f, "valor_realizado", "Valor realizado");
  if ("error" in real) return real;
  const horas = numeroHoras(f);
  if (horas !== null && typeof horas === "object") return horas;
  const problema = conferirHorario(status, motivoFalta, vaga, real.v, motivoOp, horas as number | null);
  if (problema) return { error: problema };

  const supabase = await createClient();
  const { data, error } = await supabase
    .from("crm_rm_agenda")
    .update({
      status: status as StatusAgenda,
      confirmacao: conf,
      motivo_falta: motivoFalta || null,
      vaga_recuperada: vaga,
      valor_realizado: real.v,
      horas_paradas: horas as number | null,
      motivo_operacional: motivoOp || null,
    })
    .eq("id", id)
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar. Tente de novo.") };
  if (!data?.length) return { error: "Você não pode alterar este registro." };

  revalidatePath("/crm-rm");
  return { ok: true };
}
