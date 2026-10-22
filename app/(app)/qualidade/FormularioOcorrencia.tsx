"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import { GRAVIDADES, MAX_DESCRICAO, SETORES, TIPOS, UNIDADES } from "@/lib/qualidade";
import { registrarOcorrencia, type OcorrenciaState } from "./actions";

const inicial: OcorrenciaState = {};

function BotaoEnviar() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? "Registrando" : "Registrar"}
    </button>
  );
}

export function FormularioOcorrencia({ hoje }: { hoje: string }) {
  const [state, action] = useActionState(registrarOcorrencia, inicial);
  const [tipo, setTipo] = useState("reclamacao");
  const ref = useRef<HTMLFormElement>(null);

  // Registrou: limpa o formulário para o próximo lançamento (a data volta para hoje).
  useEffect(() => {
    if (state.ok) {
      ref.current?.reset();
      setTipo("reclamacao");
    }
  }, [state]);

  return (
    <form ref={ref} action={action} className="qual-form" aria-label="Registrar ocorrência, reclamação ou elogio">
      <div className="field">
        <label className="field-label" htmlFor="q-tipo">
          O que é
        </label>
        <select id="q-tipo" name="tipo" className="select" value={tipo} onChange={(e) => setTipo(e.target.value)} required>
          {TIPOS.map((t) => (
            <option key={t.id} value={t.id}>
              {t.rotulo}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="q-data">
          Data em que aconteceu
        </label>
        <input id="q-data" name="data" type="date" className="input" defaultValue={hoje} max={hoje} required />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="q-unidade">
          Unidade
        </label>
        <select id="q-unidade" name="unidade" className="select" defaultValue="" required>
          <option value="" disabled>
            Escolha
          </option>
          {UNIDADES.map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="q-setor">
          Setor
        </label>
        <select id="q-setor" name="setor" className="select" defaultValue="" required>
          <option value="" disabled>
            Escolha
          </option>
          {SETORES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      {tipo !== "elogio" && (
        <div className="field">
          <label className="field-label" htmlFor="q-gravidade">
            Gravidade
          </label>
          <select id="q-gravidade" name="gravidade" className="select" defaultValue="baixa" required>
            {GRAVIDADES.map((g) => (
              <option key={g.id} value={g.id}>
                {g.rotulo}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="field qual-descricao">
        <label className="field-label" htmlFor="q-descricao">
          O que aconteceu
        </label>
        <textarea
          id="q-descricao"
          name="descricao"
          className="input qual-texto"
          rows={4}
          minLength={10}
          maxLength={MAX_DESCRICAO}
          placeholder="Conte o que aconteceu, sem dados que identifiquem o paciente."
          required
        />
      </div>
      <div className="qual-acoes">
        <BotaoEnviar />
        <span role="status" aria-live="polite" className="qual-retorno" data-erro={state.error ? "true" : undefined}>
          {state.error ?? (state.ok ? "Registrado. Obrigado!" : "")}
        </span>
      </div>
    </form>
  );
}
