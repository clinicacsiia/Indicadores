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
    <form
      action={acao}
      style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", margin: "16px 0", padding: 16, border: "1px solid #ddd", borderRadius: 8 }}
    >
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        Relatório
        <select name="relatorio" defaultValue="13397" disabled={pendente}>
          {relatorios.map((r) => (
            <option key={r.klingo_id} value={r.klingo_id}>
              {r.nome} (#{r.klingo_id}){r.ativo ? "" : " — inativo"}
            </option>
          ))}
        </select>
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        De
        <input type="date" name="de" defaultValue={de} max={max} required disabled={pendente} />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        Até
        <input type="date" name="ate" defaultValue={ate} max={max} required disabled={pendente} />
      </label>
      <button type="submit" disabled={pendente}>
        {pendente ? "Atualizando…" : "Atualizar"}
      </button>
      <span style={{ color: "#666", fontSize: 13, flexBasis: "100%" }}>
        Busca o relatório no Klingo e grava no banco (máx. 31 dias por vez; pode levar alguns minutos).
      </span>
      {estado && (
        <span role="status" style={{ color: estado.ok ? "green" : "crimson", flexBasis: "100%" }}>
          {estado.mensagem}
        </span>
      )}
    </form>
  );
}
