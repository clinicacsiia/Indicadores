"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";

interface Item { id: string; nome: string; visoes: string[] }

export default function Topo({ menus, usuario, admin }: { menus: Item[]; usuario: string; admin: boolean }) {
  const caminho = usePathname();
  const conta = useRef<HTMLDialogElement>(null);
  const exportar = useRef<HTMLDialogElement>(null);
  const [contaAberta, setContaAberta] = useState(false);
  const [exportarAberto, setExportarAberto] = useState(false);
  void admin;
  return (
    <header className="topo">
      <Link href="/" className="marca"><b>Clínica CSI</b><span>Indicadores</span></Link>
      <nav aria-label="Painéis">
        {menus.map((m) => (
          <Link key={m.id} href={`/painel/${m.id}`} className={caminho === `/painel/${m.id}` ? "ativo" : ""}>{m.nome}</Link>
        ))}
      </nav>
      <div className="direita">
        <button type="button" className="btn sec" onClick={() => { setExportarAberto(true); exportar.current?.showModal(); }}>Exportar / Imprimir</button>
        <button type="button" className="btn sec" onClick={() => { setContaAberta(true); conta.current?.showModal(); }}>{usuario}</button>
        <a className="btn sec" href="/sair">Sair</a>
      </div>
      <dialog ref={conta} className="modal" onClose={() => setContaAberta(false)} onClick={(e) => { if (e.target === conta.current) conta.current?.close(); }}>
        <div className="modal-topo"><b>Conta</b><button type="button" className="link" onClick={() => conta.current?.close()}>Fechar</button></div>
        {contaAberta && <iframe title="Conta" src="/conta" />}
      </dialog>
      <dialog ref={exportar} className="modal" onClose={() => setExportarAberto(false)} onClick={(e) => { if (e.target === exportar.current) exportar.current?.close(); }}>
        <div className="modal-topo"><b>Exportar / Imprimir</b><button type="button" className="link" onClick={() => exportar.current?.close()}>Fechar</button></div>
        {exportarAberto && <iframe title="Exportar" src="/exportar" />}
      </dialog>
    </header>
  );
}
