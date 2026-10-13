import { redirect } from "next/navigation";
import { exigirSessao, menusDoUsuario } from "@/lib/sessao";

export default async function Inicio() {
  const menus = await menusDoUsuario(await exigirSessao());
  if (menus.length) redirect(`/painel/${menus[0].id}`);
  return (
    <div className="vazio-portal">
      <h1>Sem painéis liberados</h1>
      <p>Sua conta ainda não tem acesso a nenhum painel. Peça a um administrador para liberar.</p>
    </div>
  );
}
