"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { salvarMetas, type UsuarioAdminState } from "./actions";

const inicial: UsuarioAdminState = {};

type Servico = { chave: string; grupo: string; nome: string };
type Props = {
  servicos: Servico[];
  meses: { valor: string; rotulo: string }[];
  mesInicial: string;
  /** Meta que vale em cada mês, por serviço (já com as mudanças feitas antes). */
  vigentes: Record<string, Record<string, number>>;
};

function Botao() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Salvando" : "Salvar metas"}
    </button>
  );
}

export function MetasForm({ servicos, meses, mesInicial, vigentes }: Props) {
  const [state, action] = useActionState(salvarMetas, inicial);
  const [mes, setMes] = useState(mesInicial);
  const grupos = [...new Set(servicos.map((s) => s.grupo))];

  return (
    <form action={action} className="metas-config">
      <div className="field">
        <label className="field-label" htmlFor="metas-mes">Valer a partir de</label>
        <select id="metas-mes" name="mes" className="select" value={mes} onChange={(e) => setMes(e.target.value)}>
          {meses.map((m) => (
            <option key={m.valor} value={m.valor}>{m.rotulo}</option>
          ))}
        </select>
      </div>
      {grupos.map((g) => (
        <fieldset key={g} className="metas-config-grupo">
          <legend className="field-label">{g}</legend>
          {servicos
            .filter((s) => s.grupo === g)
            .map((s) => (
              <div className="field metas-config-linha" key={`${mes}-${s.chave}`}>
                <label htmlFor={`meta-${s.chave}`}>{s.nome}</label>
                <input
                  id={`meta-${s.chave}`}
                  name={`meta_${s.chave}`}
                  className="input"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={999999}
                  step={1}
                  required
                  defaultValue={vigentes[mes]?.[s.chave]}
                />
              </div>
            ))}
        </fieldset>
      ))}
      <div>
        <Botao />
      </div>
      {(state.error || state.mensagem) && (
        <p className="save-status" data-kind={state.error ? "error" : "ok"} role="status">
          {state.error ?? state.mensagem}
        </p>
      )}
    </form>
  );
}
