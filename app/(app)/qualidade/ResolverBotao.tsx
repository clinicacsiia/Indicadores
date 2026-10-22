"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { resolverOcorrencia, type OcorrenciaState } from "./actions";

const inicial: OcorrenciaState = {};

function Botao() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Salvando" : "Marcar como resolvida"}
    </button>
  );
}

export function ResolverBotao({ id }: { id: number }) {
  const [state, action] = useActionState(resolverOcorrencia, inicial);
  return (
    <form action={action} className="qual-resolver">
      <input type="hidden" name="id" value={id} />
      <Botao />
      {state.error && (
        <span role="alert" className="qual-retorno" data-erro="true">
          {state.error}
        </span>
      )}
    </form>
  );
}
