"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { solicitarAcesso, type SolicitarAcessoState } from "./actions";
import { IconAlerta } from "@/app/components/icons";

const inicial: SolicitarAcessoState = {};

function Botao() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary btn-block" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Enviando" : "Enviar pedido"}
    </button>
  );
}

export function SolicitarAcessoForm({ onVoltar }: { onVoltar: () => void }) {
  const [state, action] = useActionState(solicitarAcesso, inicial);

  if (state.ok) {
    return (
      <div className="login-form">
        <div className="alert alert-ok" role="status">
          <span>
            Pedido enviado{state.usuario ? ` para o usuário “${state.usuario}”` : ""}. Assim que um administrador aprovar e liberar as telas, entre com a senha que você escolheu.
          </span>
        </div>
        <button type="button" className="btn btn-block" onClick={onVoltar}>
          Voltar para o login
        </button>
      </div>
    );
  }

  return (
    <form action={action} className="login-form">
      <div className="field">
        <label className="field-label" htmlFor="sol-nome">Seu nome</label>
        <input id="sol-nome" name="nome" className="input" required maxLength={80} autoFocus autoComplete="name" defaultValue={state.nome} />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="sol-email">Seu e-mail</label>
        <input
          id="sol-email"
          name="email"
          type="email"
          className="input"
          required
          maxLength={254}
          autoComplete="email"
          autoCapitalize="none"
          spellCheck={false}
          placeholder="nome@empresa.com"
          defaultValue={state.email}
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="sol-usuario">Usuário desejado</label>
        <input
          id="sol-usuario"
          name="usuario"
          className="input"
          required
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          placeholder="ex.: maria"
          defaultValue={state.usuario}
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="sol-senha">Senha</label>
        <input id="sol-senha" name="senha" className="input" type="password" required minLength={6} autoComplete="new-password" placeholder="mín. 6 caracteres" />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="sol-confirmar">Repita a senha</label>
        <input id="sol-confirmar" name="confirmar" className="input" type="password" required minLength={6} autoComplete="new-password" />
      </div>

      {/* armadilha para robôs: pessoas não veem nem preenchem */}
      <input name="site" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hp-field" />

      {state.error && (
        <div className="alert" role="alert">
          <IconAlerta size={18} />
          <span>{state.error}</span>
        </div>
      )}

      <Botao />
      <button type="button" className="btn btn-block" onClick={onVoltar}>
        Voltar para o login
      </button>
    </form>
  );
}
