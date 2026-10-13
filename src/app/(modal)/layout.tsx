import { exigirSessao } from "@/lib/sessao";

export const dynamic = "force-dynamic";

/** Páginas que abrem dentro do modal do portal (iframe): exigem sessão, mas sem o topo. */
export default async function ModalLayout({ children }: { children: React.ReactNode }) {
  await exigirSessao();
  return <div className="modal-pagina">{children}</div>;
}
