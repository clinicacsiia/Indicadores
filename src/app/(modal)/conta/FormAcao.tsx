"use client";
import { useActionState } from "react";
import type { Estado } from "./acoes";

type Acao = (prev: Estado, f: FormData) => Promise<Estado>;

/** Formulário ligado a uma ação do servidor, com a mensagem de erro/sucesso ao lado do botão. */
export default function FormAcao({ acao, rotulo, perigo, confirmar, children, className = "linha-form" }: {
  acao: Acao; rotulo: string; perigo?: boolean; confirmar?: string; children?: React.ReactNode; className?: string;
}) {
  const [estado, enviar, pendente] = useActionState(acao, {} as Estado);
  return (
    <form action={enviar} className={className} onSubmit={(e) => { if (confirmar && !window.confirm(confirmar)) e.preventDefault(); }}>
      {children}
      <button className={perigo ? "btn perigo pq" : "btn pq"} disabled={pendente}>{rotulo}</button>
      {estado.erro && <span className="erro" role="alert">{estado.erro}</span>}
      {estado.ok && <span className="ok">{estado.ok}</span>}
    </form>
  );
}
