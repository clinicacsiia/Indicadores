"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { salvarUsuario, type SalvarUsuarioState } from "./actions";

type Props = {
  id: string;
  email: string;
  role: "admin" | "viewer";
  veRelatorios: boolean;
  ehVoce: boolean;
};

const inicial: SalvarUsuarioState = {};

function BotaoSalvar() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Salvando" : "Salvar"}
    </button>
  );
}

export function UsuarioForm({ id, email, role, veRelatorios, ehVoce }: Props) {
  const [state, action] = useActionState(salvarUsuario, inicial);
  const [papel, setPapel] = useState(role);

  const nome = email.endsWith("@csi.local") ? email.replace("@csi.local", "") : email;

  return (
    <li>
      <form action={action} className="user-form" aria-label={`Permissões de ${nome}`}>
        <div className="user-row">
          <input type="hidden" name="userId" value={id} />

          <div className="user-id">
            <span className="avatar" aria-hidden="true">
              {nome.charAt(0) || "?"}
            </span>
            <span className="user-email" title={email}>
              {nome}
              {ehVoce && <span className="badge">Você</span>}
            </span>
          </div>

          <div className="field">
            <label className="field-label" htmlFor={`role-${id}`}>
              Permissão
            </label>
            <select
              id={`role-${id}`}
              name={ehVoce ? undefined : "role"}
              className="select"
              value={papel}
              onChange={(e) => setPapel(e.target.value as "admin" | "viewer")}
              disabled={ehVoce}
              aria-describedby={ehVoce ? `role-hint-${id}` : undefined}
            >
              <option value="admin">Administrador</option>
              <option value="viewer">Visualizador</option>
            </select>
            {ehVoce && (
              <span id={`role-hint-${id}`} className="sr-only">
                Você não pode remover o seu próprio acesso de administrador.
              </span>
            )}
          </div>

          <label className="switch">
            <input type="checkbox" name="relatorios" defaultChecked={veRelatorios} />
            <span className="switch-track" aria-hidden="true" />
            <span className="switch-text">
              Pode ver Relatórios
              {papel === "admin" && <span className="switch-hint">Administradores sempre têm acesso</span>}
            </span>
          </label>

          <div className="user-actions">
            <span
              className="save-status"
              data-kind={state.error ? "error" : state.ok ? "ok" : undefined}
              role="status"
            >
              {state.error ?? (state.ok ? "Salvo" : "")}
            </span>
            <BotaoSalvar />
          </div>
        </div>
      </form>
    </li>
  );
}
