import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { admin } from "./supabase/admin";
import { supabaseDoUsuario } from "./supabase/servidor";
import { COOKIE_SESSAO, lerSessaoAssinada, SESSAO_HORAS } from "./seguranca";
import { MENUS, NOME_DO_MENU, type MenuId } from "@/klingo/config";

export interface Sessao {
  userId: string;
  usuario: string;
  admin: boolean;
  relatorios: string[];   // '*' = todos
}

/**
 * Sessão válida = login no Supabase Auth + cookie assinado (8 h) + perfil existente + emitida depois de "sessoes_validas_desde"
 * (trocar ou redefinir a senha derruba as outras sessões daquele usuário).
 */
export const obterSessao = cache(async (): Promise<Sessao | null> => {
  const sup = await supabaseDoUsuario();
  const { data } = await sup.auth.getUser();
  const user = data.user;
  if (!user) return null;
  const jar = await cookies();
  const ass = lerSessaoAssinada(jar.get(COOKIE_SESSAO)?.value);
  if (!ass || ass.userId !== user.id) return null;
  const { data: perfil } = await admin().from("perfis").select("usuario, admin, relatorios, sessoes_validas_desde").eq("id", user.id).maybeSingle();
  if (!perfil) return null;
  if (ass.emitidoEm < Date.parse(perfil.sessoes_validas_desde) - 1000) return null;
  return { userId: user.id, usuario: perfil.usuario, admin: perfil.admin, relatorios: perfil.relatorios ?? [] };
});

export async function exigirSessao(): Promise<Sessao> {
  const s = await obterSessao();
  if (!s) redirect("/login");
  return s;
}

export async function exigirAdmin(): Promise<Sessao> {
  const s = await exigirSessao();
  if (!s.admin) redirect("/");
  return s;
}

export const podeVerMenu = (s: Sessao, menu: string): boolean => s.admin || s.relatorios.includes("*") || s.relatorios.includes(menu);

export interface ItemMenu { id: MenuId; nome: string; descricao: string; visoes_pdf: string[] }

/** Menus ativos que o usuário pode ver, na ordem de modulos.ordem. */
export async function menusDoUsuario(s: Sessao): Promise<ItemMenu[]> {
  const { data } = await admin().from("modulos").select("id, nome, descricao, visoes_pdf").eq("ativo", true).order("ordem");
  return (data ?? [])
    .filter((m) => (MENUS as readonly string[]).includes(m.id) && podeVerMenu(s, m.id))
    .map((m) => ({ id: m.id as MenuId, nome: m.nome || NOME_DO_MENU[m.id as MenuId], descricao: m.descricao ?? "", visoes_pdf: m.visoes_pdf ?? [] }));
}

export const SESSAO_MAX_AGE = SESSAO_HORAS * 3600;
