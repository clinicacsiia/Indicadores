import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile, type Profile } from "@/lib/supabase/profile";
import { updateProfileRole, updateProfileRelatoriosAccess } from "./actions";

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

  return (
    <>
      <h1>Configurações</h1>
      <p>Controle quem tem acesso de administrador e quem pode ver os Relatórios.</p>

      {error && <p style={{ color: "crimson" }}>Não foi possível carregar os usuários agora.</p>}

      {perfis && perfis.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Usuário</th>
              <th align="left">Permissão</th>
              <th align="left">Vê Relatórios</th>
            </tr>
          </thead>
          <tbody>
            {(perfis as Profile[]).map((usuario) => (
              <tr key={usuario.id}>
                <td>{usuario.email}</td>
                <td>
                  <form
                    action={async (formData) => {
                      "use server";
                      const role = formData.get("role") as "admin" | "viewer";
                      await updateProfileRole(usuario.id, role);
                    }}
                    style={{ display: "flex", gap: 8 }}
                  >
                    <select name="role" defaultValue={usuario.role}>
                      <option value="admin">Admin</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button type="submit">Salvar</button>
                  </form>
                </td>
                <td>
                  <form
                    action={async (formData) => {
                      "use server";
                      const canView = formData.get("relatorios") === "on";
                      await updateProfileRelatoriosAccess(usuario.id, canView);
                    }}
                    style={{ display: "flex", gap: 8, alignItems: "center" }}
                  >
                    <input
                      type="checkbox"
                      name="relatorios"
                      defaultChecked={usuario.permissions?.relatorios !== false}
                    />
                    <button type="submit">Salvar</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
