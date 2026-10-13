"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import { redefinirSenha, type UsuarioAdminState } from "./actions";

const inicial: UsuarioAdminState = {};

function Botao() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Salvando" : "Definir nova senha"}
    </button>
  );
}

export function RedefinirSenha({ id }: { id: string }) {
  const [state, action] = useActionState(redefinirSenha, inicial);
  const [aberto, setAberto] = useState(false);
  const ref = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.ok) ref.current?.reset();
  }, [state]);

  if (!aberto) {
    return (
      <button type="button" className="btn" onClick={() => setAberto(true)}>
        Redefinir senha
      </button>
    );
  }

  return (
    <form action={action} ref={ref} className="reset-senha">
      <input type="hidden" name="userId" value={id} />
      <input name="senha" className="input" type="text" required minLength={6} autoComplete="off" placeholder="Nova senha (mín. 6)" aria-label="Nova senha" />
      <Botao />
      <button type="button" className="btn" onClick={() => setAberto(false)}>Fechar</button>
      {(state.error || state.mensagem) && (
        <span className="save-status" data-kind={state.error ? "error" : "ok"} role="status">
          {state.error ?? state.mensagem}
        </span>
      )}
    </form>
  );
}
