"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { BLOQUEIO_PENDENTE, DOMINIO_INTERNO } from "@/lib/acesso";

export async function signIn(_prevState: unknown, formData: FormData) {
  const usuario = String(formData.get("usuario") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");

  if (!usuario || !password) {
    return { error: "Informe usuário e senha.", usuario };
  }

  const email = usuario.includes("@") ? usuario : `${usuario}@${DOMINIO_INTERNO}`;

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });

  if (error) {
    // Pedido de acesso ainda não aprovado (o usuário existe, mas está bloqueado no Auth). Só quem acertou a senha chega aqui:
    // o Supabase confere a senha antes de avisar do bloqueio, então isto não revela se um usuário existe.
    if (error.code === "user_banned" || /banned/i.test(error.message)) {
      return { aviso: "Seu pedido de acesso ainda aguarda a aprovação de um administrador.", usuario };
    }
    // Mensagem genérica: nunca revelar se o problema foi o usuário ou a senha.
    return { error: "Credenciais inválidas.", usuario };
  }

  redirect("/");
}

// ───────── Solicitar acesso ─────────
// Cria o usuário já bloqueado (ban) e marca o perfil como pendente; um administrador aprova em Configurações.
// Usa a service role porque quem pede ainda não tem login.

const SENHA_MINIMA = 6;
const LIMITE_PENDENTES = 50; // trava de spam: a tela de login é pública

export type SolicitarAcessoState = { ok?: boolean; error?: string; usuario?: string; nome?: string; email?: string };

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@.]{2,}$/;

export async function solicitarAcesso(
  _prev: SolicitarAcessoState,
  formData: FormData
): Promise<SolicitarAcessoState> {
  // Campo escondido que só robô preenche.
  if (String(formData.get("site") ?? "") !== "") return { ok: true };

  const nome = String(formData.get("nome") ?? "").trim().slice(0, 80);
  const email = String(formData.get("email") ?? "").trim().toLowerCase().slice(0, 254);
  const usuario = String(formData.get("usuario") ?? "").trim().toLowerCase();
  const senha = String(formData.get("senha") ?? "");
  const confirmar = String(formData.get("confirmar") ?? "");
  const devolve = { usuario, nome, email };

  if (!nome) return { error: "Informe o seu nome.", ...devolve };
  if (!email) return { error: "Informe o seu e-mail.", ...devolve };
  if (!EMAIL_RE.test(email)) return { error: "Informe um e-mail válido, como nome@empresa.com.", ...devolve };
  if (!usuario) return { error: "Escolha um nome de usuário.", ...devolve };
  if (!usuario.includes("@") && !/^[a-z0-9._-]+$/.test(usuario)) {
    return { error: "Use só letras, números, ponto, hífen ou underline no usuário.", ...devolve };
  }
  if (senha.length < SENHA_MINIMA) return { error: `A senha precisa ter ao menos ${SENHA_MINIMA} caracteres.`, ...devolve };
  if (senha !== confirmar) return { error: "As senhas não são iguais.", ...devolve };

  const admin = createAdminClient();
  if (!admin) return { error: "Solicitação de acesso indisponível neste ambiente. Peça a um administrador para criar o seu usuário.", ...devolve };

  const { count } = await admin.from("profiles").select("id", { count: "exact", head: true }).eq("status", "pendente");
  if ((count ?? 0) >= LIMITE_PENDENTES) {
    return { error: "Há pedidos demais aguardando. Fale com um administrador.", ...devolve };
  }

  const login = usuario.includes("@") ? usuario : `${usuario}@${DOMINIO_INTERNO}`;
  const { data, error } = await admin.auth.admin.createUser({
    email: login,
    password: senha,
    email_confirm: true,
    ban_duration: BLOQUEIO_PENDENTE,
  });

  if (error || !data.user) {
    console.error("Falha ao solicitar acesso:", error?.message);
    const jaExiste = /already|registered|exists/i.test(error?.message ?? "");
    return { error: jaExiste ? "Já existe um usuário com esse nome. Escolha outro." : "Não foi possível enviar o pedido agora.", ...devolve };
  }

  const { error: perfilError } = await admin
    .from("profiles")
    .update({ status: "pendente", nome, email_contato: email, solicitado_em: new Date().toISOString(), permissions: { metas: false } })
    .eq("id", data.user.id);

  if (perfilError) {
    // Sem o perfil marcado, o administrador não veria o pedido: desfaz tudo para a pessoa poder tentar de novo.
    console.error("Falha ao marcar o pedido como pendente:", perfilError.message);
    await admin.auth.admin.deleteUser(data.user.id);
    return { error: "Não foi possível enviar o pedido agora.", ...devolve };
  }

  return { ok: true, usuario };
}
