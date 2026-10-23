"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { hojeEmBrasilia } from "@/lib/avisos";
import {
  CANAIS,
  FORMAS_PAGAMENTO,
  MAX_OBS,
  MOTIVOS_PERDA,
  ORIGENS_REGISTRO,
  PROXIMAS_ACOES,
  SITUACOES,
  SITUACOES_PERDA,
  TIPOS_PACIENTE,
  UNIDADE_RM,
  lerValor,
  soDigitos,
} from "@/lib/crm-rm";

export type CrmState = { ok?: boolean; error?: string };

const DATA_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
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

function conferirIdentificacao(codigo: string, telefone: string, situacao?: string): string | null {
  if (situacao === "Agendado" && !codigo) return "Agendado: informe o código da marcação do Klingo. A marcação tem de ser feita lá; este site não agenda.";
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

  const ident = conferirIdentificacao(codigo, telefone, situacao);
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
  const ident = conferirIdentificacao(codigo, telefone, situacao);
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
