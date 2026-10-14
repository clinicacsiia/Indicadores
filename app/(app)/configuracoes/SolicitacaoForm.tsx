"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { ExcluirUsuario } from "./ExcluirUsuario";
import { aprovarSolicitacao, type UsuarioAdminState } from "./actions";

type Props = {
  id: string;
  usuario: string;
  nome: string;
  desde: string | null;
  paineis: { id: string; nome: string }[];
};

const inicial: UsuarioAdminState = {};

function BotaoAprovar() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Aprovando" : "Aprovar acesso"}
    </button>
  );
}

export function SolicitacaoForm({ id, usuario, nome, desde, paineis }: Props) {
  const [state, action] = useActionState(aprovarSolicitacao, inicial);

  return (
    <li className="user-card" data-pendente>
      <form action={action} className="user-form" aria-label={`Pedido de acesso de ${usuario}`}>
        <input type="hidden" name="userId" value={id} />

        <div className="user-head">
          <div className="user-id">
            <span className="avatar" aria-hidden="true">
              {(nome || usuario).charAt(0) || "?"}
            </span>
            <span className="user-email">
              {nome || usuario}
              <span className="user-desde">
                {" "}
                · usuário “{usuario}”{desde ? ` · pediu em ${desde}` : ""}
              </span>
            </span>
          </div>

          <div className="field user-role">
            <label className="field-label" htmlFor={`pedido-role-${id}`}>
              Permissão
            </label>
            <select id={`pedido-role-${id}`} name="role" className="select" defaultValue="viewer">
              <option value="viewer">Visualizador</option>
              <option value="admin">Administrador</option>
            </select>
          </div>
        </div>

        <div className="user-paineis" role="group" aria-labelledby={`pedido-acesso-${id}`}>
          <span className="field-label user-paineis-titulo" id={`pedido-acesso-${id}`}>
            Telas a liberar
            <span className="switch-hint"> — administradores sempre têm acesso a tudo</span>
          </span>
          <div className="user-switches">
            <label className="switch">
              <input type="checkbox" name="metas" />
              <span className="switch-track" aria-hidden="true" />
              <span className="switch-text">Metas</span>
            </label>
            {paineis.map((p) => (
              <label className="switch" key={p.id}>
                <input type="checkbox" name={`painel_${p.id}`} />
                <span className="switch-track" aria-hidden="true" />
                <span className="switch-text">{p.nome}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="user-actions">
          <span className="save-status" data-kind={state.error ? "error" : state.ok ? "ok" : undefined} role="status">
            {state.error ?? (state.ok ? state.mensagem : "")}
          </span>
          <BotaoAprovar />
        </div>
      </form>

      <div className="user-senha">
        <ExcluirUsuario id={id} nome={nome || usuario} pedido />
      </div>
    </li>
  );
}
