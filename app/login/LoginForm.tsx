"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { signIn } from "./actions";
import { IconAlerta, IconOlho, IconOlhoFechado } from "@/app/components/icons";

const initialState: { error?: string; usuario?: string } = {};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary btn-block" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Entrando" : "Entrar"}
    </button>
  );
}

export function LoginForm() {
  const [state, formAction] = useActionState(signIn, initialState);
  const [mostrarSenha, setMostrarSenha] = useState(false);

  return (
    <form action={formAction} className="login-form">
      <div className="field">
        <label className="field-label" htmlFor="usuario">
          Usuário
        </label>
        <input
          id="usuario"
          name="usuario"
          className="input"
          type="text"
          required
          autoFocus
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          defaultValue={state?.usuario}
          aria-invalid={state?.error ? true : undefined}
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="password">
          Senha
        </label>
        <div className="input-wrap">
          <input
            id="password"
            name="password"
            className="input"
            type={mostrarSenha ? "text" : "password"}
            required
            autoComplete="current-password"
            aria-invalid={state?.error ? true : undefined}
          />
          <button
            type="button"
            className="input-toggle"
            onClick={() => setMostrarSenha((v) => !v)}
            aria-label={mostrarSenha ? "Ocultar senha" : "Mostrar senha"}
            aria-pressed={mostrarSenha}
          >
            {mostrarSenha ? <IconOlhoFechado /> : <IconOlho />}
          </button>
        </div>
      </div>

      {state?.error && (
        <div className="alert" role="alert">
          <IconAlerta size={18} />
          <span>{state.error} Confira os dados e tente de novo.</span>
        </div>
      )}

      <SubmitButton />
    </form>
  );
}
