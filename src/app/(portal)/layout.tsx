import { exigirSessao, menusDoUsuario } from "@/lib/sessao";
import Topo from "./Topo";

export const dynamic = "force-dynamic";

export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  const sessao = await exigirSessao();
  const menus = await menusDoUsuario(sessao);
  return (
    <div className="portal">
      <Topo menus={menus.map((m) => ({ id: m.id, nome: m.nome, visoes: m.visoes_pdf }))} usuario={sessao.usuario} admin={sessao.admin} />
      <div className="conteudo">{children}</div>
    </div>
  );
}
