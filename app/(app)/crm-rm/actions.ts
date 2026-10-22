"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { hojeEmBrasilia } from "@/lib/avisos";
import {
  CANAIS,
  CONFIRMACOES,
  FORMAS_PAGAMENTO,
  MAX_OBS,
  MOTIVOS_FALTA,
  MOTIVOS_OPERACIONAIS,
  MOTIVOS_PERDA,
  ORIGENS_REGISTRO,
  PROXIMAS_ACOES,
  SAI_DO_COMPARECIMENTO,
  SITUACOES,
  SITUACOES_PERDA,
  STATUS_AGENDA,
  TIPOS_PACIENTE,
  UNIDADE_RM,
  VAGA_RECUPERADA,
  lerValor,
  soDigitos,
  type StatusAgenda,
} from "@/lib/crm-rm";

export type CrmState = { ok?: boolean; error?: string };

const DATA_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const HORA_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const texto = (f: FormData, nome: string) => String(f.get(nome) ?? "").trim();
const dataValida = (iso: string) => DATA_RE.test(iso) && new Date(`${iso}T12:00:00Z`).toISOString().slice(0, 10) === iso;
const naLista = (lista: readonly string[], v: string) => lista.includes(v);
const inteiro = (v: FormDataEntryValue | null) => {
  const n = Number(v);
  return Number.isSafeInteger(n) && n > 0 ? n : null;
};

function valor(f: FormData, nome: string, rotulo: string): { v: number | null } | { error: string } {
  const n = lerValor(texto(f, nome));
  if (Number.isNaN(n)) return { error: `${rotulo}: use só números, por exemplo 650,00.` };
  if (n !== null && n > 100000) return { error: `${rotulo}: valor alto demais, confira.` };
  return { v: n };
}

// 42501 = o banco recusou (sem permissão); 23514 = violou uma regra da tabela.
function erroDoBanco(error: { code?: string; message: string }, padrao: string) {
  console.error("Falha ao gravar no CRM da RM:", error.code, error.message);
  if (error.code === "42501") return "Você não tem permissão para esta ação.";
  if (error.code === "23514") return "Algum campo não combina com os outros. Confira a situação, o motivo e as datas.";
  return padrao;
}

/** Exame e convênio têm de existir no catálogo: é o nome exato que o Klingo usa. */
async function conferirCatalogo(
  supabase: Awaited<ReturnType<typeof createClient>>,
  exame: string,
  convenio: string,
): Promise<string | null> {
  const { data, error } = await supabase.from("crm_rm_exame").select("nome").eq("nome", exame).eq("ativo", true).maybeSingle();
  if (error) {
    console.error("Falha ao conferir o exame no catálogo:", error.message);
    return "Não foi possível conferir o exame. Tente de novo.";
  }
  if (!data) return "Escolha um exame da lista.";
  if (convenio) {
    const { data: cv, error: e2 } = await supabase.from("crm_rm_convenio").select("nome").eq("nome", convenio).eq("ativo", true).maybeSingle();
    if (e2) {
      console.error("Falha ao conferir o convênio no catálogo:", e2.message);
      return "Não foi possível conferir o convênio. Tente de novo.";
    }
    if (!cv) return "Escolha um convênio da lista.";
  }
  return null;
}

/** Regras que o banco também garante; aqui só para a mensagem sair em português. */
function conferirContato(situacao: string, motivo: string, retorno: string, dataContato: string): string | null {
  if (!naLista(SITUACOES.map((s) => s.id), situacao)) return "Escolha a situação do contato.";
  const perdeu = (SITUACOES_PERDA as string[]).includes(situacao);
  if (perdeu && !motivo) return `Quando a situação é "${situacao}", informe o motivo.`;
  if (!perdeu && motivo) return 'O motivo só vale para "Não agendou" ou "Desistiu". Limpe o motivo ou mude a situação.';
  if (motivo && !naLista(MOTIVOS_PERDA.map((m) => m.id), motivo)) return "Motivo inválido.";
  if (retorno && (!dataValida(retorno) || retorno < dataContato)) return "A data de retorno não pode ser antes do contato.";
  return null;
}

function conferirIdentificacao(codigo: string, telefone: string): string | null {
  if (codigo && !/^[A-Za-z0-9.\-/ ]{1,30}$/.test(codigo)) return "Código do Klingo: use só números, letras, ponto, hífen ou barra.";
  if (telefone && (telefone.length < 10 || telefone.length > 13)) return "Telefone: informe DDD e número, por exemplo (71) 99999-8888.";
  return null;
}

export async function registrarContato(_prev: CrmState, f: FormData): Promise<CrmState> {
  const data = texto(f, "data_contato");
  const canal = texto(f, "canal");
  const origem = texto(f, "origem_registro");
  const tipo = texto(f, "tipo_paciente");
  const exame = texto(f, "exame");
  const convenio = texto(f, "convenio");
  const situacao = texto(f, "situacao") || "Novo contato";
  const motivo = texto(f, "motivo_perda");
  const acao = texto(f, "proxima_acao");
  const retorno = texto(f, "data_retorno");
  const responsavel = texto(f, "responsavel");
  const obs = texto(f, "observacoes");
  const codigo = texto(f, "codigo_klingo");
  const telefone = soDigitos(texto(f, "telefone"));
  const respondeu = f.get("respondeu") === "on";

  if (!dataValida(data)) return { error: "Informe a data do contato." };
  if (data > hojeEmBrasilia()) return { error: "A data do contato não pode estar no futuro." };
  if (data < hojeEmBrasilia(-365)) return { error: "A data do contato não pode ser de mais de um ano atrás." };
  if (!naLista(CANAIS, canal)) return { error: "Escolha por onde o paciente entrou em contato." };
  if (origem && !naLista(ORIGENS_REGISTRO, origem)) return { error: "Origem do registro inválida." };
  if (!naLista(TIPOS_PACIENTE, tipo)) return { error: "Informe se é paciente novo ou já atendido." };
  if (responsavel.length > 60) return { error: "O nome do responsável pode ter no máximo 60 caracteres." };
  if (obs.length > MAX_OBS) return { error: `As observações podem ter no máximo ${MAX_OBS} caracteres.` };
  if (acao && !naLista(PROXIMAS_ACOES, acao)) return { error: "Próxima ação inválida." };

  const ident = conferirIdentificacao(codigo, telefone);
  if (ident) return { error: ident };
  const problema = conferirContato(situacao, motivo, retorno, data);
  if (problema) return { error: problema };
  const v = valor(f, "valor_informado", "Valor informado");
  if ("error" in v) return v;

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sua sessão expirou. Entre de novo." };

  // A forma de pagamento vem do convênio escolhido: a atendente não escolhe duas vezes a mesma coisa.
  let forma = texto(f, "forma_pagamento");
  if (convenio) {
    const { data: cv } = await supabase.from("crm_rm_convenio").select("tipo").eq("nome", convenio).maybeSingle();
    if (cv?.tipo) forma = cv.tipo as string;
  }
  if (!naLista(FORMAS_PAGAMENTO, forma)) return { error: "Escolha o convênio ou Particular." };

  const doCatalogo = await conferirCatalogo(supabase, exame, convenio);
  if (doCatalogo) return { error: doCatalogo };

  const { error } = await supabase.from("crm_rm_contato").insert({
    data_contato: data,
    canal,
    origem_registro: origem || null,
    tipo_paciente: tipo,
    exame,
    forma_pagamento: forma,
    convenio: convenio || null,
    valor_informado: v.v,
    situacao,
    motivo_perda: motivo || null,
    data_ultimo_contato: data,
    primeira_resposta_em: respondeu ? new Date().toISOString() : null,
    proxima_acao: acao || null,
    data_retorno: retorno || null,
    responsavel: responsavel || null,
    observacoes: obs || null,
    codigo_klingo: codigo || null,
    telefone: telefone || null,
    unidade: UNIDADE_RM,
    criado_por: auth.user.id,
  });
  if (error) return { error: erroDoBanco(error, "Não foi possível registrar o contato. Tente de novo.") };

  revalidatePath("/crm-rm");
  return { ok: true };
}


/** Depois de cada conversa: muda a situação, o motivo, a próxima ação e a data de retorno. */
export async function atualizarContato(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  const dataContato = texto(f, "data_contato");
  const situacao = texto(f, "situacao");
  const motivo = texto(f, "motivo_perda");
  const acao = texto(f, "proxima_acao");
  const retorno = texto(f, "data_retorno");
  const responsavel = texto(f, "responsavel");
  const obs = texto(f, "observacoes");
  const codigo = texto(f, "codigo_klingo");
  const telefone = soDigitos(texto(f, "telefone"));

  if (!id || !dataValida(dataContato)) return { error: "Registro inválido." };
  if (acao && !naLista(PROXIMAS_ACOES, acao)) return { error: "Próxima ação inválida." };
  if (responsavel.length > 60) return { error: "O nome do responsável pode ter no máximo 60 caracteres." };
  if (obs.length > MAX_OBS) return { error: `As observações podem ter no máximo ${MAX_OBS} caracteres.` };
  const ident = conferirIdentificacao(codigo, telefone);
  if (ident) return { error: ident };
  const problema = conferirContato(situacao, motivo, retorno, dataContato);
  if (problema) return { error: problema };
  const v = valor(f, "valor_informado", "Valor informado");
  if ("error" in v) return v;

  const supabase = await createClient();
  const hoje = hojeEmBrasilia();
  const { data, error } = await supabase
    .from("crm_rm_contato")
    .update({
      situacao,
      motivo_perda: motivo || null,
      valor_informado: v.v,
      data_ultimo_contato: hoje < dataContato ? dataContato : hoje,
      proxima_acao: acao || null,
      data_retorno: retorno || null,
      responsavel: responsavel || null,
      observacoes: obs || null,
      codigo_klingo: codigo || null,
      telefone: telefone || null,
    })
    .eq("id", id)
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar. Tente de novo.") };
  if (!data?.length) return { error: "Você não pode alterar este registro." };

  revalidatePath("/crm-rm");
  return { ok: true };
}

// ───────── Botões de um clique da aba "Meu dia" ─────────

/** Carimba a primeira resposta. Só grava se ainda não houver carimbo (o indicador mede a PRIMEIRA). */
export async function responderAgora(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  if (!id) return { error: "Registro inválido." };
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("crm_rm_contato")
    .update({ primeira_resposta_em: new Date().toISOString(), data_ultimo_contato: hojeEmBrasilia() })
    .eq("id", id)
    .is("primeira_resposta_em", null)
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível marcar a resposta.") };
  if (!data?.length) return { error: "Este contato já tinha a primeira resposta marcada." };
  revalidatePath("/crm-rm");
  return { ok: true };
}

/** Empurra o retorno para daqui a N dias (1 ou 3), sem abrir o formulário inteiro. */
export async function adiarRetorno(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  const d = Number(f.get("dias"));
  if (!id || ![1, 3, 7].includes(d)) return { error: "Registro inválido." };
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("crm_rm_contato")
    .update({ data_retorno: hojeEmBrasilia(d), data_ultimo_contato: hojeEmBrasilia() })
    .eq("id", id)
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível adiar o retorno.") };
  if (!data?.length) return { error: "Você não pode alterar este registro." };
  revalidatePath("/crm-rm");
  return { ok: true };
}

/** Registra a resposta da confirmação prévia num clique. */
export async function marcarConfirmacao(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  const conf = texto(f, "confirmacao");
  if (!id || !naLista(CONFIRMACOES, conf)) return { error: "Registro inválido." };
  const supabase = await createClient();
  const { data, error } = await supabase.from("crm_rm_agenda").update({ confirmacao: conf }).eq("id", id).eq("status", "Agendado").select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar a confirmação.") };
  if (!data?.length) return { error: "Este horário não está mais aberto." };
  revalidatePath("/crm-rm");
  return { ok: true };
}

/** Fecha o horário depois do exame: Realizado (com o valor previsto) ou Faltou. */
export async function fecharHorario(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  const status = texto(f, "status");
  if (!id || !["Realizado", "Faltou"].includes(status)) return { error: "Registro inválido." };

  const supabase = await createClient();
  const { data: atual, error: e1 } = await supabase.from("crm_rm_agenda").select("valor_previsto").eq("id", id).eq("status", "Agendado").maybeSingle();
  if (e1) return { error: erroDoBanco(e1, "Não foi possível ler o horário.") };
  if (!atual) return { error: "Este horário não está mais aberto." };

  const { data, error } = await supabase
    .from("crm_rm_agenda")
    .update(
      status === "Realizado"
        ? { status, valor_realizado: atual.valor_previsto }
        : { status, vaga_recuperada: "Não" },
    )
    .eq("id", id)
    .eq("status", "Agendado")
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar.") };
  if (!data?.length) return { error: "Este horário não está mais aberto." };
  revalidatePath("/crm-rm");
  return { ok: true };
}

/** Marca que a vaga de uma falta ou cancelamento foi ocupada por outra pessoa. */
export async function marcarVagaRecuperada(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  if (!id) return { error: "Registro inválido." };
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("crm_rm_agenda")
    .update({ vaga_recuperada: "Sim" })
    .eq("id", id)
    .in("status", ["Faltou", "Cancelado", "Reagendado"])
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar.") };
  if (!data?.length) return { error: "Este horário não aceita essa marcação." };
  revalidatePath("/crm-rm");
  return { ok: true };
}

// ───────── Agenda ─────────

function conferirHorario(
  status: string,
  motivoFalta: string,
  vaga: string,
  valorRealizado: number | null,
  motivoOp: string,
  horas: number | null,
): string | null {
  if (!STATUS_AGENDA.some((s) => s.id === status)) return "Escolha o status do horário.";
  const saiu = (SAI_DO_COMPARECIMENTO as string[]).includes(status);
  if (motivoFalta && !naLista(MOTIVOS_FALTA, motivoFalta)) return "Motivo da falta ou cancelamento inválido.";
  if (motivoFalta && !saiu) return "O motivo da falta só vale para Faltou, Cancelado ou Reagendado.";
  if (!naLista(VAGA_RECUPERADA, vaga)) return "Informe se a vaga foi recuperada.";
  if (vaga !== "Não se aplica" && !saiu) return '"Vaga recuperada" só vale para Faltou, Cancelado ou Reagendado.';
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
  const contatoId = texto(f, "contato_id") ? inteiro(f.get("contato_id")) : null;
  const dataExame = texto(f, "data_exame");
  const hora = texto(f, "horario");
  const exame = texto(f, "exame");
  const codigoMarcacao = texto(f, "codigo_marcacao");
  const status = texto(f, "status") || "Agendado";
  const conf = texto(f, "confirmacao") || "Não contatado";

  if (texto(f, "contato_id") && contatoId === null) return { error: "Contato inválido." };
  if (!dataValida(dataExame)) return { error: "Informe a data do exame." };
  if (dataExame > hojeEmBrasilia(120) || dataExame < hojeEmBrasilia(-365)) {
    return { error: "A data do exame precisa estar entre o último ano e os próximos 4 meses." };
  }
  if (hora && !HORA_RE.test(hora)) return { error: "Horário inválido." };
  if (codigoMarcacao && !/^\d{1,12}$/.test(codigoMarcacao)) return { error: "Código da marcação: só números." };
  if (!naLista(CONFIRMACOES, conf)) return { error: "Escolha a confirmação prévia." };
  const prev = valor(f, "valor_previsto", "Valor previsto");
  if ("error" in prev) return prev;
  const problema = conferirHorario(status, "", "Não se aplica", null, "", null);
  if (problema) return { error: problema };

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return { error: "Sua sessão expirou. Entre de novo." };

  let forma = texto(f, "forma_pagamento");
  if (!naLista(FORMAS_PAGAMENTO, forma)) return { error: "Escolha Particular ou o convênio." };

  const doCatalogo = await conferirCatalogo(supabase, exame, "");
  if (doCatalogo) return { error: doCatalogo };

  const { error } = await supabase.from("crm_rm_agenda").insert({
    contato_id: contatoId,
    codigo_marcacao: codigoMarcacao || null,
    data_exame: dataExame,
    horario: hora || null,
    forma_pagamento: forma,
    exame,
    status: status as StatusAgenda,
    confirmacao: conf,
    vaga_recuperada: "Não se aplica",
    valor_previsto: prev.v,
    unidade: UNIDADE_RM,
    criado_por: auth.user.id,
  });
  if (error) return { error: erroDoBanco(error, "Não foi possível registrar o horário. Tente de novo.") };

  revalidatePath("/crm-rm");
  return { ok: true };
}

/** Depois da data do exame: realizado, faltou, cancelado ou reagendado (e o que aconteceu). */
export async function atualizarHorario(_prev: CrmState, f: FormData): Promise<CrmState> {
  const id = inteiro(f.get("id"));
  const status = texto(f, "status");
  const conf = texto(f, "confirmacao");
  const motivoFalta = texto(f, "motivo_falta");
  const vaga = texto(f, "vaga_recuperada") || "Não se aplica";
  const motivoOp = texto(f, "motivo_operacional");
  const codigoMarcacao = texto(f, "codigo_marcacao");

  if (!id) return { error: "Registro inválido." };
  if (!naLista(CONFIRMACOES, conf)) return { error: "Escolha a confirmação prévia." };
  if (codigoMarcacao && !/^\d{1,12}$/.test(codigoMarcacao)) return { error: "Código da marcação: só números." };
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
      codigo_marcacao: codigoMarcacao || null,
    })
    .eq("id", id)
    .select("id");
  if (error) return { error: erroDoBanco(error, "Não foi possível salvar. Tente de novo.") };
  if (!data?.length) return { error: "Você não pode alterar este registro." };

  revalidatePath("/crm-rm");
  return { ok: true };
}
