"use server";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { emailDoUsuario } from "@/lib/ambiente";
import { auditar } from "@/lib/auditoria";
import { estaBloqueado, limparFalhas, registrarFalha } from "@/lib/bloqueio";
import { assinarSessao, COOKIE_SESSAO, hashDeOrigem, ipDe, validarNome, validarSenha } from "@/lib/seguranca";
import { SESSAO_MAX_AGE } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";
import { supabaseDoUsuario } from "@/lib/supabase/servidor";

export interface Estado { erro?: string; ok?: string }

const GENERICO = "Usuário ou senha incorretos.";
const texto = (f: FormData, k: string) => String(f.get(k) ?? "");

async function origemAtual(): Promise<string> {
  return hashDeOrigem(ipDe({ headers: await headers() }));
}

async function abrirSessao(userId: string) {
  (await cookies()).set(COOKIE_SESSAO, assinarSessao(userId), { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: SESSAO_MAX_AGE });
}

export async function entrar(_: Estado, f: FormData): Promise<Estado> {
  const usuario = texto(f, "usuario").trim(), senha = texto(f, "senha");
  const origem = await origemAtual();
  if (!usuario || !senha || usuario.length > 64 || senha.length > 128) return { erro: GENERICO };
  if (await estaBloqueado(usuario, origem)) {
    await auditar("login_bloqueado", usuario, {}, origem);
    return { erro: "Muitas tentativas. Aguarde um pouco e tente de novo." };
  }
  const sup = await supabaseDoUsuario();
  const { data, error } = await sup.auth.signInWithPassword({ email: emailDoUsuario(usuario), password: senha });
  if (error || !data.user) {
    await registrarFalha(usuario, origem);
    await auditar("senha_errada", usuario, {}, origem);
    return { erro: GENERICO };
  }
  const { data: perfil } = await admin().from("perfis").select("usuario").eq("id", data.user.id).maybeSingle();
  if (!perfil) { await sup.auth.signOut(); await registrarFalha(usuario, origem); return { erro: GENERICO }; }
  await limparFalhas(usuario);
  await abrirSessao(data.user.id);
  await auditar("entrou", perfil.usuario, {}, origem);
  redirect("/");
}

/** Só funciona enquanto NÃO existir nenhum usuário: o primeiro vira administrador e define a própria senha (não há senha padrão). */
export async function criarPrimeiroAdmin(_: Estado, f: FormData): Promise<Estado> {
  const usuario = texto(f, "usuario").trim(), senha = texto(f, "senha"), conf = texto(f, "confirmar");
  const origem = await origemAtual();
  const { count } = await admin().from("perfis").select("id", { count: "exact", head: true });
  if ((count ?? 0) > 0) return { erro: "Já existe um usuário. Peça acesso a um administrador." };
  const e = validarNome(usuario) ?? validarSenha(senha, usuario) ?? (senha !== conf ? "A confirmação da senha não confere." : null);
  if (e) return { erro: e };
  const { data, error } = await admin().auth.admin.createUser({ email: emailDoUsuario(usuario), password: senha, email_confirm: true });
  if (error || !data.user) return { erro: "Não foi possível criar o usuário agora." };
  const { error: e2 } = await admin().from("perfis").insert({ id: data.user.id, usuario, admin: true, relatorios: ["*"], fundador: true });
  if (e2) { await admin().auth.admin.deleteUser(data.user.id); return { erro: "Já existe um usuário. Peça acesso a um administrador." }; }
  await auditar("usuario_criado", usuario, { admin: true, fundador: true }, origem);
  const sup = await supabaseDoUsuario();
  const { error: e3 } = await sup.auth.signInWithPassword({ email: emailDoUsuario(usuario), password: senha });
  if (e3) return { ok: "Administrador criado. Entre com a sua senha." };
  await abrirSessao(data.user.id);
  redirect("/");
}

const MAX_PENDENTES = 50, MAX_POR_HORA = 3;

/** Pedido de cadastro: o usuário é criado no Auth já bloqueado (a senha fica só no Auth) e só entra depois que um administrador aprovar. */
export async function solicitarCadastro(_: Estado, f: FormData): Promise<Estado> {
  const usuario = texto(f, "usuario").trim(), senha = texto(f, "senha"), mensagem = texto(f, "mensagem").trim().slice(0, 200);
  const origem = await origemAtual();
  const e = validarNome(usuario) ?? validarSenha(senha, usuario);
  if (e) return { erro: e };
  const db = admin();
  const { count: pend } = await db.from("solicitacoes_cadastro").select("id", { count: "exact", head: true });
  if ((pend ?? 0) >= MAX_PENDENTES) return { erro: "Há pedidos demais aguardando. Tente mais tarde." };
  const { count: porOrigem } = await db.from("solicitacoes_cadastro").select("id", { count: "exact", head: true }).eq("origem", origem).gte("solicitado_em", new Date(Date.now() - 3600_000).toISOString());
  if ((porOrigem ?? 0) >= MAX_POR_HORA) return { erro: "Muitos pedidos deste acesso. Tente de novo em uma hora." };
  const { data: existe } = await db.from("perfis").select("id").ilike("usuario", usuario).maybeSingle();
  const { data: pedido } = await db.from("solicitacoes_cadastro").select("id").ilike("usuario", usuario).maybeSingle();
  if (existe || pedido) return { erro: "Esse nome de usuário não está disponível." };
  const { data, error } = await db.auth.admin.createUser({ email: emailDoUsuario(usuario), password: senha, email_confirm: true, ban_duration: "876000h" });
  if (error || !data.user) return { erro: "Não foi possível registrar o pedido agora." };
  const { error: e2 } = await db.from("solicitacoes_cadastro").insert({ usuario, user_id: data.user.id, mensagem, origem });
  if (e2) { await db.auth.admin.deleteUser(data.user.id); return { erro: "Esse nome de usuário não está disponível." }; }
  await auditar("cadastro_solicitado", usuario, {}, origem);
  return { ok: "Pedido enviado. Um administrador vai analisar; depois disso você poderá entrar com este usuário e senha." };
}

/** Evita expor a configuração do Supabase ao navegador na página de login. */
export async function haUsuarios(): Promise<boolean> {
  const { count } = await admin().from("perfis").select("id", { count: "exact", head: true });
  return (count ?? 0) > 0;
}

