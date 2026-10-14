"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { excluirUsuario, recusarSolicitacao, type UsuarioAdminState } from "./actions";

const inicial: UsuarioAdminState = {};

function Confirmar({ rotulo }: { rotulo: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-danger" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Excluindo" : rotulo}
    </button>
  );
}

// Dois passos (botão → confirmação) para ninguém apagar um acesso sem querer.
// `pedido` troca o texto e a action: recusar um pedido de acesso em vez de excluir um usuário que já existe.
export function ExcluirUsuario({ id, nome, pedido = false }: { id: string; nome: string; pedido?: boolean }) {
  const [state, action] = useActionState(pedido ? recusarSolicitacao : excluirUsuario, inicial);
  const [confirmando, setConfirmando] = useState(false);

  if (!confirmando) {
    return (
      <button type="button" className="btn btn-danger" onClick={() => setConfirmando(true)}>
        {pedido ? "Recusar" : "Excluir usuário"}
      </button>
    );
  }

  return (
    <form action={action} className="reset-senha">
      <input type="hidden" name="userId" value={id} />
      <span className="save-status" data-kind="error" role="alert">
        {pedido ? `Recusar o pedido de ${nome}?` : `Excluir ${nome} de vez? Não dá para desfazer.`}
      </span>
      <Confirmar rotulo={pedido ? "Sim, recusar" : "Sim, excluir"} />
      <button type="button" className="btn" onClick={() => setConfirmando(false)}>
        Cancelar
      </button>
      {state.error && (
        <span className="save-status" data-kind="error" role="status">
          {state.error}
        </span>
      )}
    </form>
  );
}
