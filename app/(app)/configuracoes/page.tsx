import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile, type Profile } from "@/lib/supabase/profile";
import { signOut } from "@/app/actions";
import { IconAlerta, IconSair } from "@/app/components/icons";
import { PAINEIS, PERMISSAO_FINANCEIRA } from "@/lib/paineis";
import { NovoUsuarioForm } from "./NovoUsuarioForm";
import { SolicitacaoForm } from "./SolicitacaoForm";
import { UsuarioForm } from "./UsuarioForm";

export const metadata: Metadata = { title: "Configurações" };

export default async function ConfiguracoesPage() {
  const profile = await getCurrentProfile();

  // RLS (policy "profiles_select_admin") também bloqueia a leitura abaixo
  // para quem não é admin; isso aqui só evita renderizar a tela à toa.
  if (profile?.role !== "admin") {
    redirect("/");
  }

  const supabase = await createClient();
  const { data: perfis, error } = await supabase
    .from("profiles")
    .select("id, email, role, permissions, status, nome, email_contato, solicitado_em")
    .order("email");

  if (error) {
    console.error("Falha ao carregar perfis:", error.message);
  }

  const todos = (perfis ?? []) as Profile[];
  const pendentes = todos
    .filter((p) => p.status === "pendente")
    .sort((a, b) => (a.solicitado_em ?? "").localeCompare(b.solicitado_em ?? ""));
  const usuarios = todos.filter((p) => p.status !== "pendente");
  const nomeDe = (email: string | null) => (email ?? "").replace(/@csi\.local$/, "");
  const desde = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" }) : null;

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Configurações</h1>
          <p className="page-lede">
            Aprove pedidos de acesso, adicione ou exclua usuários, redefina senhas e escolha quais telas cada um pode ver (Metas e painéis) e se pode ver dados financeiros (receitas, despesas e valores em R$). Cada usuário é salvo separadamente; os painéis começam bloqueados para quem não é administrador.
          </p>
        </div>
      </header>

      <section className="panel" aria-labelledby="titulo-sessao">
        <div className="panel-head" style={{ paddingBottom: 12 }}>
          <div>
            <h2 className="panel-title" id="titulo-sessao">Sua sessão</h2>
            <p className="panel-sub">
              Você está como <strong>{nomeDe(profile.email) || "usuário"}</strong>. Para sair ou entrar com outro usuário, use o botão abaixo (vai para a tela de login).
            </p>
          </div>
        </div>
        <form action={signOut} className="sessao-acoes">
          <button type="submit" className="btn btn-primary">
            <IconSair size={16} />
            Sair ou trocar de usuário
          </button>
        </form>
      </section>

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar os usuários agora. Tente novamente em instantes.
        </div>
      )}

      {pendentes.length > 0 && (
        <section className="panel" aria-labelledby="titulo-pedidos">
          <div className="panel-head" style={{ paddingBottom: 12 }}>
            <div>
              <h2 className="panel-title" id="titulo-pedidos">
                Pedidos de acesso
              </h2>
              <p className="panel-sub">
                {pendentes.length} {pendentes.length === 1 ? "pessoa aguardando" : "pessoas aguardando"} aprovação. Escolha a permissão e as telas e aprove, ou recuse o pedido.
              </p>
            </div>
          </div>
          <ul className="user-list" style={{ borderTop: "1px solid var(--line)" }}>
            {pendentes.map((pedido) => (
              <SolicitacaoForm
                key={pedido.id}
                id={pedido.id}
                usuario={nomeDe(pedido.email)}
                nome={pedido.nome ?? ""}
                emailContato={pedido.email_contato ?? ""}
                desde={desde(pedido.solicitado_em)}
                paineis={PAINEIS.map((p) => ({ id: p.id, nome: p.nome }))}
              />
            ))}
          </ul>
        </section>
      )}

      <section className="panel" aria-labelledby="titulo-novo">
        <div className="panel-head" style={{ paddingBottom: 12 }}>
          <div>
            <h2 className="panel-title" id="titulo-novo">Novo usuário</h2>
            <p className="panel-sub">Cria o acesso com uma senha inicial. Depois libere as telas na lista abaixo.</p>
          </div>
        </div>
        <NovoUsuarioForm />
      </section>

      {usuarios.length > 0 && (
        <section className="panel" aria-labelledby="titulo-usuarios">
          <div className="panel-head" style={{ paddingBottom: 12 }}>
            <div>
              <h2 className="panel-title" id="titulo-usuarios">
                Usuários
              </h2>
              <p className="panel-sub">
                {usuarios.length} {usuarios.length === 1 ? "usuário" : "usuários"}
              </p>
            </div>
          </div>
          <ul className="user-list" style={{ borderTop: "1px solid var(--line)" }}>
            {usuarios.map((usuario) => (
              <UsuarioForm
                key={usuario.id}
                id={usuario.id}
                email={usuario.email ?? ""}
                role={usuario.role}
                veMetas={usuario.permissions?.metas !== false}
                veFinanceiro={usuario.permissions?.[PERMISSAO_FINANCEIRA] === true}
                paineis={PAINEIS.map((p) => ({ id: p.id, nome: p.nome, liberado: usuario.permissions?.[p.id] === true }))}
                ehVoce={usuario.id === profile.id}
              />
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
