import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { signOut } from "@/app/actions";
import { Brand } from "@/app/components/Brand";
import { NavLinks } from "@/app/components/NavLinks";
import { IconSair } from "@/app/components/icons";
import { PAINEIS, podeVerPainel } from "@/lib/paineis";
import { APP_VERSION } from "@/lib/version";

// RLS (can_view_painel) já limita aos painéis que a pessoa pode ver; o administrador conta todos.
async function contarAvisosAbertos() {
  const supabase = await createClient();
  const { data, error } = await supabase.from("aviso").select("nivel").eq("status", "aberto");
  if (error) {
    console.error("Falha ao contar avisos abertos:", error.message);
    return { abertos: 0, criticos: 0 };
  }
  return { abertos: data.length, criticos: data.filter((a) => a.nivel === "critico").length };
}

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await getCurrentProfile();
  const avisos = await contarAvisosAbertos();
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
        <div className="brand-block">
          <Brand href="/" />
          <span className="version-tag">v{APP_VERSION}</span>
        </div>

        <NavLinks isAdmin={isAdmin} paineis={paineis} avisos={avisos} />

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
