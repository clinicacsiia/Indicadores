"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS } from "@/lib/paineis";

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
    relatorios: formData.get("relatorios") === "on",
    metas: formData.get("metas") === "on",
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

const DOMINIO_INTERNO = "csi.local";
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
