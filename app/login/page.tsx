"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { signIn } from "./actions";

const initialState: { error?: string } = {};

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
    <main style={{ padding: 32, fontFamily: "sans-serif", maxWidth: 360 }}>
      <h1>Entrar</h1>
      <form action={formAction} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label>
          Email
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <label>
          Senha
          <input name="password" type="password" required autoComplete="current-password" />
        </label>
        {state?.error && <p style={{ color: "crimson" }}>{state.error}</p>}
        <SubmitButton />
      </form>
    </main>
  );
}
