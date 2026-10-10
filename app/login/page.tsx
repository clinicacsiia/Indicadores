"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { signIn } from "./actions";

const initialState: { error?: string; usuario?: string } = {};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending}>
      {pending ? "Entrando..." : "Entrar"}
    </button>
  );
}

export default function LoginPage() {
  const [state, formAction] = useActionState(signIn, initialState);

  return (
    <main
      style={{
        fontFamily: "sans-serif",
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: 320,
          padding: 32,
          border: "1px solid #ddd",
          borderRadius: 8,
        }}
      >
        <h1>Indicadores</h1>
        <form action={formAction} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Usuário
            <input name="usuario" type="text" required autoComplete="username" autoCapitalize="none" defaultValue={state?.usuario} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Senha
            <input name="password" type="password" required autoComplete="current-password" />
          </label>
          {state?.error && <p style={{ color: "crimson" }}>{state.error}</p>}
          <SubmitButton />
        </form>
      </div>
    </main>
  );
}
