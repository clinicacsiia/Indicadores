export default function Home() {
  return (
    <main style={{ padding: 32, fontFamily: "sans-serif" }}>
      <h1>Indicadores</h1>
      <p>Projeto Next.js conectado ao Supabase.</p>
      <p>
        Use <code>lib/supabase/client.ts</code> em componentes client e{" "}
        <code>lib/supabase/server.ts</code> em Server Components/rotas.
      </p>
    </main>
  );
}
