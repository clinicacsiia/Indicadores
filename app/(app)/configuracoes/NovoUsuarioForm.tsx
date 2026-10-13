"use client";

import { useActionState, useEffect, useRef } from "react";
import { useFormStatus } from "react-dom";
import { criarUsuario, type UsuarioAdminState } from "./actions";

const inicial: UsuarioAdminState = {};

function Botao() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Criando" : "Adicionar usuário"}
    </button>
  );
}

export function NovoUsuarioForm() {
  const [state, action] = useActionState(criarUsuario, inicial);
  const ref = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.ok) ref.current?.reset();
  }, [state]);

  return (
    <form action={action} ref={ref} className="novo-usuario">
      <div className="field">
        <label className="field-label" htmlFor="novo-usuario">Usuário</label>
        <input id="novo-usuario" name="usuario" className="input" required autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="ex.: maria" />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="novo-senha">Senha inicial</label>
        <input id="novo-senha" name="senha" className="input" type="text" required minLength={6} autoComplete="off" placeholder="mín. 6 caracteres" />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="novo-role">Permissão</label>
        <select id="novo-role" name="role" className="select" defaultValue="viewer">
          <option value="viewer">Visualizador</option>
          <option value="admin">Administrador</option>
        </select>
      </div>
      <Botao />
      {(state.error || state.mensagem) && (
        <p className="save-status novo-usuario-msg" data-kind={state.error ? "error" : "ok"} role="status">
          {state.error ?? state.mensagem}
        </p>
      )}
    </form>
  );
}
