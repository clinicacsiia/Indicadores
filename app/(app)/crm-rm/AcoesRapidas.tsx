"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { adiarRetorno, responderAgora, type CrmState } from "./actions";

const inicial: CrmState = {};

function Botao({ texto, ocupado, tom }: { texto: string; ocupado: string; tom?: "primario" | "perigo" }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={`btn btn-pequeno${tom === "primario" ? " btn-primary" : ""}`} data-tom={tom} disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? ocupado : texto}
    </button>
  );
}

function Erro({ state }: { state: CrmState }) {
  if (!state.error) return null;
  return (
    <span role="alert" className="crm-retorno" data-erro="true">
      {state.error}
    </span>
  );
}

/** Carimba a primeira resposta ao paciente. */
export function BotaoRespondi({ id }: { id: number }) {
  const [state, action] = useActionState(responderAgora, inicial);
  return (
    <form action={action} className="crm-rapidas">
      <input type="hidden" name="id" value={id} />
      <Botao texto="Respondi agora" ocupado="Salvando" tom="primario" />
      <Erro state={state} />
    </form>
  );
}

/** Empurra o retorno sem abrir o formulário inteiro. */
export function BotoesAdiar({ id }: { id: number }) {
  const [state, action] = useActionState(adiarRetorno, inicial);
  return (
    <form action={action} className="crm-rapidas">
      <input type="hidden" name="id" value={id} />
      <button type="submit" name="dias" value="1" className="btn btn-pequeno">
        Adiar 1 dia
      </button>
      <button type="submit" name="dias" value="3" className="btn btn-pequeno">
        3 dias
      </button>
      <button type="submit" name="dias" value="7" className="btn btn-pequeno">
        1 semana
      </button>
      <Erro state={state} />
    </form>
  );
}
