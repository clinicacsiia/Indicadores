import type { Metadata } from "next";
import Link from "next/link";
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

type Props = { searchParams: Promise<{ aba?: string }> };

type Aba = "pedidos" | "usuarios" | "novo";
const ehAba = (a: string | undefined): a is Aba => a === "pedidos" || a === "usuarios" || a === "novo";
const hrefAba = (aba: Aba) => `/configuracoes?aba=${aba}`;

export default async function ConfiguracoesPage({ searchParams }: Props) {
  const { aba: abaParam } = await searchParams;
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

  // Com pedido esperando, abre direto neles; sem pedido, na lista de usuários.
  const aba: Aba = ehAba(abaParam) && (abaParam !== "pedidos" || pendentes.length > 0)
    ? abaParam
    : pendentes.length > 0
      ? "pedidos"
      : "usuarios";

  const abas: { id: Aba; rotulo: string; n?: number; alerta?: boolean }[] = [
    { id: "pedidos", rotulo: "Pedidos de acesso", n: pendentes.length, alerta: pendentes.length > 0 },
    { id: "usuarios", rotulo: "Usuários", n: usuarios.length },
    { id: "novo", rotulo: "Novo usuário" },
  ];

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Configurações</h1>
          <p className="page-lede">
            Gerencie quem acessa o portal: aprove pedidos, crie usuários e escolha as telas e os dados que cada um pode ver.
          </p>
        </div>
        <form action={signOut} className="config-sessao">
          <span className="config-sessao-texto">
            Você está como <strong>{nomeDe(profile.email) || "usuário"}</strong>
          </span>
          <button type="submit" className="btn">
            <IconSair size={16} />
            Sair ou trocar de usuário
          </button>
        </form>
      </header>

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar os usuários agora. Tente novamente em instantes.
        </div>
      )}

      {pendentes.length > 0 && aba !== "pedidos" && (
        <Link href={hrefAba("pedidos")} className="config-alerta" role="status">
          <IconAlerta />
          <span>
            <strong>
              {pendentes.length} {pendentes.length === 1 ? "pedido de acesso aguardando" : "pedidos de acesso aguardando"} aprovação.
            </strong>{" "}
            Clique para revisar.
          </span>
        </Link>
      )}

      <nav className="config-abas" aria-label="Seções de Configurações">
        {abas.map((a) => (
          <Link
            key={a.id}
            href={hrefAba(a.id)}
            className="config-aba"
            aria-current={aba === a.id ? "page" : undefined}
            data-alerta={a.alerta ? "true" : undefined}
          >
            {a.rotulo}
            {a.n !== undefined && (a.n > 0 || a.id === "usuarios") && <span className="config-aba-n">{a.n}</span>}
          </Link>
        ))}
      </nav>

      {aba === "pedidos" && (
        <section className="panel" aria-labelledby="titulo-pedidos">
          <div className="panel-head" style={{ paddingBottom: 12 }}>
            <div>
              <h2 className="panel-title" id="titulo-pedidos">
                Pedidos de acesso
              </h2>
              <p className="panel-sub">
                {pendentes.length === 0
                  ? "Nenhum pedido aguardando aprovação."
                  : `${pendentes.length} ${pendentes.length === 1 ? "pessoa aguardando" : "pessoas aguardando"} aprovação. Escolha a permissão e as telas e aprove, ou recuse o pedido.`}
              </p>
            </div>
          </div>
          {pendentes.length > 0 && (
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
          )}
        </section>
      )}

      {aba === "usuarios" && (
        <section className="panel" aria-labelledby="titulo-usuarios">
          <div className="panel-head" style={{ paddingBottom: 12 }}>
            <div>
              <h2 className="panel-title" id="titulo-usuarios">
                Usuários
              </h2>
              <p className="panel-sub">
                {usuarios.length} {usuarios.length === 1 ? "usuário" : "usuários"}. Abra um usuário para ajustar permissão, telas, dados financeiros e senha. Administradores sempre têm acesso a tudo.
              </p>
            </div>
          </div>
          {usuarios.length > 0 && (
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
          )}
        </section>
      )}

      {aba === "novo" && (
        <section className="panel" aria-labelledby="titulo-novo">
          <div className="panel-head" style={{ paddingBottom: 12 }}>
            <div>
              <h2 className="panel-title" id="titulo-novo">Novo usuário</h2>
              <p className="panel-sub">Cria o acesso com uma senha inicial. Depois libere as telas na aba Usuários.</p>
            </div>
          </div>
          <NovoUsuarioForm />
        </section>
      )}
    </>
  );
}
