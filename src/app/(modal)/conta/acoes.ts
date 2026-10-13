"use server";
import { createClient } from "@supabase/supabase-js";
import { cookies, headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { ambiente, emailDoUsuario } from "@/lib/ambiente";
import { auditar } from "@/lib/auditoria";
import { assinarSessao, COOKIE_SESSAO, hashDeOrigem, ipDe, validarNome, validarSenha } from "@/lib/seguranca";
import { exigirAdmin, exigirSessao, SESSAO_MAX_AGE } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";
import { supabaseDoUsuario } from "@/lib/supabase/servidor";
import { MENUS } from "@/klingo/config";

export interface Estado { erro?: string; ok?: string }
const t = (f: FormData, k: string) => String(f.get(k) ?? "");
const menusDe = (f: FormData): string[] => {
  if (f.get("todos") === "on") return ["*"];
  return f.getAll("menus").map(String).filter((m) => (MENUS as readonly string[]).includes(m));
};

// ------------------------------------------------------------------ minha senha
export async function trocarMinhaSenha(_: Estado, f: FormData): Promise<Estado> {
  const s = await exigirSessao();
  const atual = t(f, "atual"), nova = t(f, "nova"), conf = t(f, "confirmar");
  const e = validarSenha(nova, s.usuario) ?? (nova !== conf ? "A confirmação da senha não confere." : null);
  if (e) return { erro: e };
  const teste = createClient(ambiente.supabaseUrl, ambiente.anonKey, { auth: { persistSession: false, autoRefreshToken: false } });
  const { error } = await teste.auth.signInWithPassword({ email: emailDoUsuario(s.usuario), password: atual });
  if (error) return { erro: "A senha atual não confere." };
  const { error: e2 } = await admin().auth.admin.updateUserById(s.userId, { password: nova });
  if (e2) return { erro: "Não foi possível trocar a senha agora." };
  const agora = new Date();
  await admin().from("perfis").update({ sessoes_validas_desde: agora.toISOString() }).eq("id", s.userId);   // derruba as outras sessões
  (await cookies()).set(COOKIE_SESSAO, assinarSessao(s.userId, agora.getTime() + 1000), { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: SESSAO_MAX_AGE });
  try { await (await supabaseDoUsuario()).auth.signOut({ scope: "others" }); } catch { /* o cookie assinado já invalida as outras sessões */ }
  await auditar("senha_trocada", s.usuario, {}, hashDeOrigem(ipDe({ headers: await headers() })));
  return { ok: "Senha trocada. As outras sessões desta conta foram encerradas." };
}

// ------------------------------------------------------------------ usuários (admin)
async function outrosAdmins(excetoId: string): Promise<number> {
  const { count } = await admin().from("perfis").select("id", { count: "exact", head: true }).eq("admin", true).neq("id", excetoId);
  return count ?? 0;
}

export async function criarUsuario(_: Estado, f: FormData): Promise<Estado> {
  const a = await exigirAdmin();
  const usuario = t(f, "usuario").trim(), senha = t(f, "senha");
  const e = validarNome(usuario) ?? validarSenha(senha, usuario);
  if (e) return { erro: e };
  const { data: existe } = await admin().from("perfis").select("id").ilike("usuario", usuario).maybeSingle();
  if (existe) return { erro: "Esse nome de usuário já existe." };
  const { data, error } = await admin().auth.admin.createUser({ email: emailDoUsuario(usuario), password: senha, email_confirm: true });
  if (error || !data.user) return { erro: "Não foi possível criar o usuário (o nome pode estar em uso)." };
  const { error: e2 } = await admin().from("perfis").insert({ id: data.user.id, usuario, admin: f.get("admin") === "on", relatorios: menusDe(f) });
  if (e2) { await admin().auth.admin.deleteUser(data.user.id); return { erro: "Não foi possível criar o usuário." }; }
  await auditar("usuario_criado", a.usuario, { novo: usuario, admin: f.get("admin") === "on", menus: menusDe(f) });
  revalidatePath("/conta");
  return { ok: `Usuário ${usuario} criado.` };
}

export async function editarUsuario(id: string, _: Estado, f: FormData): Promise<Estado> {
  const a = await exigirAdmin();
  const { data: alvo } = await admin().from("perfis").select("usuario, admin").eq("id", id).maybeSingle();
  if (!alvo) return { erro: "Usuário não encontrado." };
  const virouAdmin = f.get("admin") === "on";
  if (alvo.admin && !virouAdmin && (await outrosAdmins(id)) === 0) return { erro: "Não é possível tirar o último administrador." };
  const campos: Record<string, unknown> = { admin: virouAdmin, relatorios: menusDe(f) };
  const nova = t(f, "nova");
  if (nova) {
    const e = validarSenha(nova, alvo.usuario);
    if (e) return { erro: e };
    const { error } = await admin().auth.admin.updateUserById(id, { password: nova });
    if (error) return { erro: "Não foi possível trocar a senha agora." };
    campos.sessoes_validas_desde = new Date().toISOString();   // redefinir a senha derruba as sessões daquele usuário
  }
  const { error } = await admin().from("perfis").update(campos).eq("id", id);
  if (error) return { erro: "Não foi possível salvar." };
  await auditar("usuario_editado", a.usuario, { alvo: alvo.usuario, admin: virouAdmin, menus: campos.relatorios, senha_redefinida: !!nova });
  revalidatePath("/conta");
  return { ok: "Salvo." };
}

export async function removerUsuario(id: string, _: Estado): Promise<Estado> {
  const a = await exigirAdmin();
  if (id === a.userId) return { erro: "Você não pode remover a si mesmo." };
  const { data: alvo } = await admin().from("perfis").select("usuario, admin").eq("id", id).maybeSingle();
  if (!alvo) return { erro: "Usuário não encontrado." };
  if (alvo.admin && (await outrosAdmins(id)) === 0) return { erro: "Não é possível remover o último administrador." };
  const { error } = await admin().auth.admin.deleteUser(id);
  if (error) return { erro: "Não foi possível remover." };
  await auditar("usuario_removido", a.usuario, { alvo: alvo.usuario });
  revalidatePath("/conta");
  return { ok: "Removido." };
}

// ------------------------------------------------------------------ pedidos de cadastro (admin)
export async function aprovarPedido(id: string, _: Estado, f: FormData): Promise<Estado> {
  const a = await exigirAdmin();
  const { data: p } = await admin().from("solicitacoes_cadastro").select("usuario, user_id").eq("id", id).maybeSingle();
  if (!p) return { erro: "Pedido não encontrado." };
  const { error } = await admin().auth.admin.updateUserById(p.user_id, { ban_duration: "none" });
  if (error) return { erro: "Não foi possível liberar o usuário." };
  const { error: e2 } = await admin().from("perfis").insert({ id: p.user_id, usuario: p.usuario, admin: f.get("admin") === "on", relatorios: menusDe(f) });
  if (e2) return { erro: "Não foi possível criar o perfil." };
  await admin().from("solicitacoes_cadastro").delete().eq("id", id);
  await auditar("cadastro_aprovado", a.usuario, { alvo: p.usuario, admin: f.get("admin") === "on", menus: menusDe(f) });
  revalidatePath("/conta");
  return { ok: "Aprovado." };
}

export async function recusarPedido(id: string, _: Estado): Promise<Estado> {
  const a = await exigirAdmin();
  const { data: p } = await admin().from("solicitacoes_cadastro").select("usuario, user_id").eq("id", id).maybeSingle();
  if (!p) return { erro: "Pedido não encontrado." };
  await admin().auth.admin.deleteUser(p.user_id);   // apaga o usuário bloqueado; o pedido sai junto (cascata)
  await auditar("cadastro_recusado", a.usuario, { alvo: p.usuario });
  revalidatePath("/conta");
  return { ok: "Recusado." };
}

// ------------------------------------------------------------------ custos dos itens (admin)
export async function salvarCusto(item: string, _: Estado, f: FormData): Promise<Estado> {
  const a = await exigirAdmin();
  const bruto = t(f, "custo").replace("R$", "").trim();
  let custo: number | null = null;
  if (bruto) {
    const n = Number(bruto.includes(",") ? bruto.replace(/\./g, "").replace(",", ".") : bruto);
    if (!Number.isFinite(n) || n < 0) return { erro: "Custo inválido." };
    custo = n;
  }
  const { error } = await admin().from("custos_itens").update({ custo, observacao: t(f, "observacao").slice(0, 200) || null }).eq("item", item);
  if (error) return { erro: "Não foi possível salvar." };
  await auditar("custo_item", a.usuario, { item, custo });
  return { ok: "Salvo. Vale no painel depois de Atualizar agora." };
}
