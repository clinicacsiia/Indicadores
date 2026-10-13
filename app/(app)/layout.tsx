import { getCurrentProfile } from "@/lib/supabase/profile";
import { signOut } from "@/app/actions";
import { Brand } from "@/app/components/Brand";
import { NavLinks } from "@/app/components/NavLinks";
import { IconSair } from "@/app/components/icons";
import { PAINEIS, podeVerPainel } from "@/lib/paineis";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await getCurrentProfile();
  const isAdmin = profile?.role === "admin";
  const paineis = PAINEIS.filter((p) => podeVerPainel(profile, p.id));
  const email = profile?.email ?? "";
  // "csiadmin@csi.local" é exibido como "csiadmin".
  const nome = email.endsWith("@csi.local") ? email.replace("@csi.local", "") : email;

  return (
    <div className="shell">
      <a href="#conteudo" className="skip-link">
        Ir para o conteúdo
      </a>

      <aside className="sidebar">
        <Brand href="/" />

        <NavLinks isAdmin={isAdmin} paineis={paineis} />

        <div className="sidebar-user">
          <span className="avatar" aria-hidden="true">
            {(nome || "?").charAt(0)}
          </span>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name" title={email}>
              {nome || "Usuário"}
            </div>
            <div className="sidebar-user-role">{isAdmin ? "Administrador" : "Visualizador"}</div>
          </div>
          <form action={signOut}>
            <button type="submit" className="icon-btn" aria-label="Sair" title="Sair">
              <IconSair />
            </button>
          </form>
        </div>
      </aside>

      <main id="conteudo" className="main">
        <div className="main-inner">{children}</div>
      </main>
    </div>
  );
}
