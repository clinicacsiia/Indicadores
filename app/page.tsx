import { createClient } from "@/lib/supabase/server";
import { signOut } from "./actions";

export default async function Home() {
  const supabase = await createClient();

  // RLS garante que isso só retorna dados para quem está autenticado;
  // o middleware já bloqueia a rota antes mesmo de chegar aqui.
  const { data: indicadores, error } = await supabase
    .from("indicadores")
    .select("codigo, nome, valor, unidade, periodo")
    .order("periodo", { ascending: false })
    .limit(50);

  // Nunca mostrar error.message na tela: pode conter detalhes internos do Postgres.
  if (error) {
    console.error("Falha ao carregar indicadores:", error.message);
  }

  return (
    <main style={{ padding: 32, fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Indicadores</h1>
        <form action={signOut}>
          <button type="submit">Sair</button>
        </form>
      </div>

      {error && <p style={{ color: "crimson" }}>Não foi possível carregar os indicadores agora.</p>}

      {!error && (!indicadores || indicadores.length === 0) && (
        <p>Nenhum indicador sincronizado ainda.</p>
      )}

      {indicadores && indicadores.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Código</th>
              <th align="left">Nome</th>
              <th align="right">Valor</th>
              <th align="left">Unidade</th>
              <th align="left">Período</th>
            </tr>
          </thead>
          <tbody>
            {indicadores.map((item) => (
              <tr key={`${item.codigo}-${item.periodo}`}>
                <td>{item.codigo}</td>
                <td>{item.nome}</td>
                <td align="right">{item.valor}</td>
                <td>{item.unidade}</td>
                <td>{item.periodo}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
