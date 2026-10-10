import Link from "next/link";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { signOut } from "@/app/actions";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await getCurrentProfile();
  const isAdmin = profile?.role === "admin";

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "sans-serif" }}>
      <nav
        style={{
          width: 220,
          borderRight: "1px solid #ddd",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <strong style={{ marginBottom: 16 }}>Indicadores</strong>

        <Link href="/" style={{ padding: "8px 12px", borderRadius: 6 }}>
          Relatórios
        </Link>

        {isAdmin && (
          <Link href="/configuracoes" style={{ padding: "8px 12px", borderRadius: 6 }}>
            Configurações
          </Link>
        )}

        <form action={signOut} style={{ marginTop: "auto" }}>
          <button type="submit" style={{ width: "100%" }}>
            Sair
          </button>
        </form>
      </nav>

      <main style={{ flex: 1, padding: 32 }}>{children}</main>
    </div>
  );
}
