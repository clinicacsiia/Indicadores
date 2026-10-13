import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile, type Profile } from "@/lib/supabase/profile";
import { IconAlerta } from "@/app/components/icons";
import { PAINEIS } from "@/lib/paineis";
import { NovoUsuarioForm } from "./NovoUsuarioForm";
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
    .select("id, email, role, permissions")
    .order("email");

  if (error) {
    console.error("Falha ao carregar perfis:", error.message);
  }

  const usuarios = (perfis ?? []) as Profile[];

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Configurações</h1>
          <p className="page-lede">
            Adicione usuários, redefina senhas e escolha quais telas cada um pode ver (Metas e painéis). Cada usuário é salvo separadamente; os painéis começam bloqueados para quem não é administrador.
          </p>
        </div>
      </header>

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar os usuários agora. Tente novamente em instantes.
        </div>
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
