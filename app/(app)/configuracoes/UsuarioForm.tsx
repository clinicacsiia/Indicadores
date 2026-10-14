"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { ExcluirUsuario } from "./ExcluirUsuario";
import { RedefinirSenha } from "./RedefinirSenha";
import { salvarUsuario, type SalvarUsuarioState } from "./actions";

type Props = {
  id: string;
  email: string;
  role: "admin" | "viewer";
  veMetas: boolean;
  veFinanceiro: boolean;
  paineis: { id: string; nome: string; liberado: boolean }[];
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

export function UsuarioForm({ id, email, role, veMetas, veFinanceiro, paineis, ehVoce }: Props) {
  const [state, action] = useActionState(salvarUsuario, inicial);
  const [papel, setPapel] = useState(role);

  const nome = email.endsWith("@csi.local") ? email.replace("@csi.local", "") : email;

  return (
    <li className="user-card">
      <form action={action} className="user-form" aria-label={`Permissões de ${nome}`}>
        <input type="hidden" name="userId" value={id} />

        <div className="user-head">
          <div className="user-id">
            <span className="avatar" aria-hidden="true">
              {nome.charAt(0) || "?"}
            </span>
            <span className="user-email" title={email}>
              {nome}
              {ehVoce && <span className="badge">Você</span>}
            </span>
          </div>

          <div className="field user-role">
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
        </div>

        <div className="user-paineis" role="group" aria-labelledby={`acesso-${id}`}>
          <span className="field-label user-paineis-titulo" id={`acesso-${id}`}>
            Telas liberadas
            {papel === "admin" && <span className="switch-hint"> — administradores sempre têm acesso a tudo</span>}
          </span>
          <div className="user-switches">
            <label className="switch">
              <input type="checkbox" name="metas" defaultChecked={veMetas} />
              <span className="switch-track" aria-hidden="true" />
              <span className="switch-text">Metas</span>
            </label>
            {paineis.map((p) => (
              <label className="switch" key={p.id}>
                <input type="checkbox" name={`painel_${p.id}`} defaultChecked={p.liberado} />
                <span className="switch-track" aria-hidden="true" />
                <span className="switch-text">{p.nome}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="user-paineis" role="group" aria-labelledby={`dados-${id}`}>
          <span className="field-label user-paineis-titulo" id={`dados-${id}`}>
            Dados sensíveis
            {papel === "admin" && <span className="switch-hint"> — administradores sempre veem tudo</span>}
          </span>
          <div className="user-switches">
            <label className="switch">
              <input type="checkbox" name="dados_financeiros" defaultChecked={veFinanceiro} />
              <span className="switch-track" aria-hidden="true" />
              <span className="switch-text">Dados financeiros (receitas, despesas e valores em R$)</span>
            </label>
          </div>
          <span className="switch-hint">
            Desmarcado: Faturamento, Financeiro, Despesas e Indicadores ficam bloqueados, os valores em R$ somem dos outros painéis e os avisos de dinheiro não aparecem.
          </span>
        </div>

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
      </form>

      <div className="user-senha">
        <RedefinirSenha id={id} />
        {!ehVoce && (
          <span className="user-excluir">
            <ExcluirUsuario id={id} nome={nome} />
          </span>
        )}
      </div>
    </li>
  );
}
