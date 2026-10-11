"use client";

import { useActionState } from "react";
import { atualizarRelatorio } from "./atualizar-actions";

export type RelatorioOpcao = { klingo_id: string; nome: string; ativo: boolean };

export function AtualizarForm({
  relatorios,
  de,
  ate,
  max,
}: {
  relatorios: RelatorioOpcao[];
  de: string;
  ate: string;
  max: string;
}) {
  const [estado, acao, pendente] = useActionState(atualizarRelatorio, null);

  return (
    <form action={acao} className="toolbar" aria-label="Atualizar relatório">
      <div className="field">
        <label className="field-label" htmlFor="atualizar-relatorio">
          Relatório
        </label>
        <select id="atualizar-relatorio" className="select" name="relatorio" defaultValue="13397" disabled={pendente}>
          {relatorios.map((r) => (
            <option key={r.klingo_id} value={r.klingo_id}>
              {r.nome} (#{r.klingo_id}){r.ativo ? "" : " — inativo"}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="atualizar-de">
          De
        </label>
        <input id="atualizar-de" className="input" type="date" name="de" defaultValue={de} max={max} required disabled={pendente} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="atualizar-ate">
          Até
        </label>
        <input id="atualizar-ate" className="input" type="date" name="ate" defaultValue={ate} max={max} required disabled={pendente} />
      </div>
      <button type="submit" className="btn btn-primary" disabled={pendente}>
        {pendente ? "Atualizando…" : "Atualizar"}
      </button>
      <p className="panel-sub" style={{ flexBasis: "100%", margin: 0 }}>
        Busca o relatório no Klingo e grava no banco (máx. 31 dias por vez; pode levar alguns minutos).
      </p>
      {estado && (
        <p
          role={estado.ok ? "status" : "alert"}
          className={estado.ok ? "panel-sub" : "alert"}
          style={{ flexBasis: "100%", margin: 0, ...(estado.ok ? { color: "var(--ok, green)", fontWeight: 600 } : {}) }}
        >
          {estado.mensagem}
        </p>
      )}
    </form>
  );
}
