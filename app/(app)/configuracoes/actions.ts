"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS, PERMISSAO_FINANCEIRA } from "@/lib/paineis";
import { BLOQUEIO_PENDENTE, DOMINIO_INTERNO } from "@/lib/acesso";
import { metasConfig, mesesParaMudarMeta, SERVICOS_METAS } from "@/lib/metas/config";
import { agoraSaoPaulo, agruparAlteracoes, metaDoMes } from "@/lib/metas/calculo";

// RLS (policy "profiles_update_admin") é quem realmente garante que só admin
// grava aqui, mesmo que estas actions sejam chamadas diretamente.
export async function updateProfileRole(userId: string, role: string) {
  if (role !== "admin" && role !== "viewer") {
    return { error: "Permissão inválida." };
  }

  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();

  // Evita que o único admin se tranque para fora da tela de Configurações.
  if (auth.user?.id === userId && role !== "admin") {
    return { error: "Você não pode remover o seu próprio acesso de admin." };
  }

  const { error } = await supabase.from("profiles").update({ role }).eq("id", userId);

  if (error) {
    console.error("Falha ao atualizar role do perfil:", error.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  revalidatePath("/", "layout");
  return {};
}

export type SalvarUsuarioState = { ok?: boolean; error?: string };

// Salva permissão e acesso às telas de uma vez, com retorno para a tela.
// Se o campo "role" não vier (select desabilitado para o próprio usuário),
// só o acesso às telas é atualizado.
export async function salvarUsuario(
  _prev: SalvarUsuarioState,
  formData: FormData
): Promise<SalvarUsuarioState> {
  const userId = String(formData.get("userId") ?? "");
  const role = formData.get("role");
  const acesso: Record<string, boolean> = {
    metas: formData.get("metas") === "on",
    [PERMISSAO_FINANCEIRA]: formData.get(PERMISSAO_FINANCEIRA) === "on",
    // Painéis em Python: cada um é uma chave em profiles.permissions (o id do painel).
    ...Object.fromEntries(PAINEIS.map((p) => [p.id, formData.get(`painel_${p.id}`) === "on"])),
  };

  if (!userId) return { error: "Usuário inválido." };

  if (typeof role === "string") {
    const result = await updateProfileRole(userId, role);
    if (result.error) return { error: result.error };
  }

  const result = await updateProfileAccess(userId, acesso);
  if (result.error) return { error: result.error };

  return { ok: true };
}

export async function updateProfileAccess(userId: string, acesso: Record<string, boolean>) {
  const supabase = await createClient();
  const { data: current, error: fetchError } = await supabase
    .from("profiles")
    .select("permissions")
    .eq("id", userId)
    .single();

  if (fetchError) {
    console.error("Falha ao ler permissões do perfil:", fetchError.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  const permissions = { ...(current?.permissions ?? {}), ...acesso };

  const { error } = await supabase.from("profiles").update({ permissions }).eq("id", userId);

  if (error) {
    console.error("Falha ao atualizar permissões do perfil:", error.message);
    return { error: "Não foi possível atualizar a permissão." };
  }

  revalidatePath("/", "layout");
  return {};
}

// ───────── Criar usuário e redefinir senha ─────────
// Usam a service role (ignora RLS), então SEMPRE conferem antes se quem chama é admin.

const SENHA_MINIMA = 6;

export type UsuarioAdminState = { ok?: boolean; error?: string; mensagem?: string };

async function exigirAdmin() {
  const perfil = await getCurrentProfile();
  if (perfil?.role !== "admin") return { error: "Apenas administradores podem fazer isso." } as const;
  const admin = createAdminClient();
  if (!admin) return { error: "Falta a variável SUPABASE_SERVICE_ROLE_KEY neste ambiente." } as const;
  return { admin } as const;
}

export async function criarUsuario(
  _prev: UsuarioAdminState,
  formData: FormData
): Promise<UsuarioAdminState> {
  const usuario = String(formData.get("usuario") ?? "").trim().toLowerCase();
  const senha = String(formData.get("senha") ?? "");
  const role = formData.get("role") === "admin" ? "admin" : "viewer";

  if (!usuario) return { error: "Informe o nome de usuário." };
  if (!usuario.includes("@") && !/^[a-z0-9._-]+$/.test(usuario)) {
    return { error: "Use só letras, números, ponto, hífen ou underline no usuário." };
  }
  if (senha.length < SENHA_MINIMA) return { error: `A senha precisa ter ao menos ${SENHA_MINIMA} caracteres.` };

  const acesso = await exigirAdmin();
  if ("error" in acesso) return { error: acesso.error };

  const email = usuario.includes("@") ? usuario : `${usuario}@${DOMINIO_INTERNO}`;
  const { data, error } = await acesso.admin.auth.admin.createUser({
    email,
    password: senha,
    email_confirm: true,
  });

  if (error || !data.user) {
    console.error("Falha ao criar usuário:", error?.message);
    const jaExiste = /already|registered|exists/i.test(error?.message ?? "");
    return { error: jaExiste ? "Já existe um usuário com esse nome." : "Não foi possível criar o usuário." };
  }

  // O perfil nasce por trigger como viewer; aqui só ajusta o papel escolhido.
  if (role === "admin") {
    const { error: roleError } = await acesso.admin.from("profiles").update({ role }).eq("id", data.user.id);
    if (roleError) console.error("Falha ao definir admin:", roleError.message);
  }

  revalidatePath("/configuracoes");
  return { ok: true, mensagem: `Usuário "${usuario}" criado. Agora libere as telas dele abaixo.` };
}

export async function redefinirSenha(
  _prev: UsuarioAdminState,
  formData: FormData
): Promise<UsuarioAdminState> {
  const userId = String(formData.get("userId") ?? "");
  const senha = String(formData.get("senha") ?? "");

  if (!userId) return { error: "Usuário inválido." };
  if (senha.length < SENHA_MINIMA) return { error: `A senha precisa ter ao menos ${SENHA_MINIMA} caracteres.` };

  const acesso = await exigirAdmin();
  if ("error" in acesso) return { error: acesso.error };

  const { error } = await acesso.admin.auth.admin.updateUserById(userId, { password: senha });
  if (error) {
    console.error("Falha ao redefinir senha:", error.message);
    return { error: "Não foi possível redefinir a senha." };
  }

  return { ok: true, mensagem: "Senha redefinida." };
}

// ───────── Excluir usuário e pedidos de acesso ─────────

// Apaga o login no Supabase Auth; o perfil e os favoritos somem junto (on delete cascade).
export async function excluirUsuario(
  _prev: UsuarioAdminState,
  formData: FormData
): Promise<UsuarioAdminState> {
  const userId = String(formData.get("userId") ?? "");
  if (!userId) return { error: "Usuário inválido." };

  const acesso = await exigirAdmin();
  if ("error" in acesso) return { error: acesso.error };

  // Evita que o administrador apague o próprio acesso (e a tela de Configurações junto).
  const perfil = await getCurrentProfile();
  if (perfil?.id === userId) return { error: "Você não pode excluir o seu próprio usuário." };

  const { error } = await acesso.admin.auth.admin.deleteUser(userId);
  if (error) {
    console.error("Falha ao excluir usuário:", error.message);
    return { error: "Não foi possível excluir o usuário." };
  }

  revalidatePath("/configuracoes");
  return { ok: true, mensagem: "Usuário excluído." };
}

// Só recusa quem ainda está pendente; para apagar quem já tem acesso existe excluirUsuario.
export async function recusarSolicitacao(
  _prev: UsuarioAdminState,
  formData: FormData
): Promise<UsuarioAdminState> {
  const userId = String(formData.get("userId") ?? "");
  if (!userId) return { error: "Pedido inválido." };

  const acesso = await exigirAdmin();
  if ("error" in acesso) return { error: acesso.error };

  const { data: alvo } = await acesso.admin.from("profiles").select("status").eq("id", userId).single();
  if (alvo?.status !== "pendente") return { error: "Este pedido não está mais pendente." };

  const { error } = await acesso.admin.auth.admin.deleteUser(userId);
  if (error) {
    console.error("Falha ao recusar pedido de acesso:", error.message);
    return { error: "Não foi possível recusar o pedido." };
  }

  revalidatePath("/configuracoes");
  return { ok: true, mensagem: "Pedido recusado." };
}

// Aprova o pedido: desbloqueia o login e já grava a permissão e as telas escolhidas pelo administrador.
export async function aprovarSolicitacao(
  _prev: UsuarioAdminState,
  formData: FormData
): Promise<UsuarioAdminState> {
  const userId = String(formData.get("userId") ?? "");
  const role = formData.get("role") === "admin" ? "admin" : "viewer";
  if (!userId) return { error: "Pedido inválido." };

  const acesso = await exigirAdmin();
  if ("error" in acesso) return { error: acesso.error };

  const { data: alvo } = await acesso.admin.from("profiles").select("status").eq("id", userId).single();
  if (alvo?.status !== "pendente") return { error: "Este pedido não está mais pendente." };

  const permissions: Record<string, boolean> = {
    metas: formData.get("metas") === "on",
    [PERMISSAO_FINANCEIRA]: formData.get(PERMISSAO_FINANCEIRA) === "on",
    ...Object.fromEntries(PAINEIS.map((p) => [p.id, formData.get(`painel_${p.id}`) === "on"])),
  };

  const { error: desbloqueioError } = await acesso.admin.auth.admin.updateUserById(userId, { ban_duration: "none" });
  if (desbloqueioError) {
    console.error("Falha ao desbloquear usuário:", desbloqueioError.message);
    return { error: "Não foi possível aprovar o pedido." };
  }

  const { error } = await acesso.admin.from("profiles").update({ status: "ativo", role, permissions }).eq("id", userId);
  if (error) {
    console.error("Falha ao ativar perfil:", error.message);
    // Volta ao estado anterior para o pedido não ficar "pendente" com o login já liberado.
    await acesso.admin.auth.admin.updateUserById(userId, { ban_duration: BLOQUEIO_PENDENTE });
    return { error: "Não foi possível aprovar o pedido." };
  }

  revalidatePath("/configuracoes");
  return { ok: true, mensagem: "Acesso aprovado." };
}

// ───────── Metas ─────────
// A mudança vale do mês escolhido em diante, até a próxima mudança do mesmo serviço. Quem realmente garante que só admin grava é a RLS
// (policies metas_valor_*); a conferência aqui é só para dar a mensagem certa.

async function lerMudancasMetas() {
  const supabase = await createClient();
  const { data, error } = await supabase.from("metas_valor").select("servico, a_partir_de, meta");
  if (error) console.error("Falha ao ler as mudanças de meta:", error.message);
  return { supabase, error, linhas: data ?? [] };
}

export async function salvarMetas(_prev: UsuarioAdminState, formData: FormData): Promise<UsuarioAdminState> {
  const perfil = await getCurrentProfile();
  if (perfil?.role !== "admin") return { error: "Apenas administradores podem fazer isso." };

  const mes = String(formData.get("mes") ?? "");
  if (!mesesParaMudarMeta(agoraSaoPaulo().hoje.slice(0, 7)).includes(mes)) return { error: "Escolha um mês da lista." };

  const novos = new Map<string, number>();
  for (const s of SERVICOS_METAS) {
    const texto = String(formData.get(`meta_${s.chave}`) ?? "").trim();
    if (!/^\d{1,6}$/.test(texto)) return { error: `A meta de ${s.nome} (${s.grupo}) precisa ser um número inteiro, de 0 a 999999.` };
    novos.set(s.chave, Number(texto));
  }

  const { supabase, error, linhas } = await lerMudancasMetas();
  if (error) return { error: "Não foi possível ler as metas agora. Tente novamente em instantes." };

  const dia = `${mes}-01`;
  const atual = { ...metasConfig, alteracoes: agruparAlteracoes(linhas) };
  // Sem a linha deste mês, o serviço valeria o que vinha dos meses anteriores (ou do metas.json): voltar a esse valor apaga a linha.
  const semEsteMes = { ...metasConfig, alteracoes: agruparAlteracoes(linhas.filter((l) => String(l.a_partir_de).slice(0, 7) !== mes)) };

  const gravar: { servico: string; a_partir_de: string; meta: number }[] = [];
  const apagar: string[] = [];
  for (const s of SERVICOS_METAS) {
    const novo = novos.get(s.chave) as number;
    if (novo === metaDoMes(atual, s.chave, s.padrao, mes)) continue; // não mudou
    if (novo === metaDoMes(semEsteMes, s.chave, s.padrao, mes)) apagar.push(s.chave);
    else gravar.push({ servico: s.chave, a_partir_de: dia, meta: novo });
  }
  if (gravar.length + apagar.length === 0) return { mensagem: "Nenhuma meta foi alterada." };

  if (gravar.length) {
    const { error: e } = await supabase.from("metas_valor").upsert(gravar, { onConflict: "servico,a_partir_de" });
    if (e) {
      console.error("Falha ao gravar metas:", e.message);
      return { error: "Não foi possível salvar as metas." };
    }
  }
  if (apagar.length) {
    const { error: e } = await supabase.from("metas_valor").delete().eq("a_partir_de", dia).in("servico", apagar);
    if (e) {
      console.error("Falha ao apagar metas:", e.message);
      return { error: "Não foi possível salvar as metas." };
    }
  }

  revalidatePath("/metas");
  revalidatePath("/configuracoes");
  const n = gravar.length + apagar.length;
  return { ok: true, mensagem: `${n} ${n === 1 ? "meta alterada" : "metas alteradas"}. Valem a partir do mês escolhido e seguem nos meses seguintes.` };
}

/** Desfaz uma mudança de meta: o serviço volta a valer o que vinha antes dela. */
export async function removerMudancaMeta(formData: FormData): Promise<void> {
  const perfil = await getCurrentProfile();
  if (perfil?.role !== "admin") return;
  const servico = String(formData.get("servico") ?? "");
  const mes = String(formData.get("mes") ?? "");
  if (!SERVICOS_METAS.some((s) => s.chave === servico) || !/^\d{4}-(0[1-9]|1[0-2])$/.test(mes)) return;

  const supabase = await createClient();
  const { error } = await supabase.from("metas_valor").delete().eq("servico", servico).eq("a_partir_de", `${mes}-01`);
  if (error) console.error("Falha ao desfazer a mudança de meta:", error.message);
  revalidatePath("/metas");
  revalidatePath("/configuracoes");
}
