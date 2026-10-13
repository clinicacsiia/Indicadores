"use client";

import { useActionState } from "react";
import { atualizarTudo } from "./atualizar-tudo-actions";

export function AtualizarTudoForm() {
  const [estado, acao, pendente] = useActionState(atualizarTudo, null);

  return (
    <form action={acao} className="toolbar" aria-label="Atualizar tudo">
      <div>
        <span className="toolbar-label">Sincronização</span>
        <p className="panel-sub" style={{ marginTop: 4 }}>
          Busca no Klingo só o que falta para cada relatório ficar em dia (máx. 31 dias por vez).
        </p>
      </div>
      <button type="submit" className="btn btn-primary" disabled={pendente} style={{ marginLeft: "auto" }}>
        {pendente && <span className="spinner" aria-hidden="true" />}
        {pendente ? "Atualizando…" : "Atualizar tudo"}
      </button>
      {estado && (
        <p
          role={estado.ok ? "status" : "alert"}
          className="panel-sub"
          style={{
            flexBasis: "100%",
            margin: 0,
            fontWeight: 600,
            color: estado.ok ? "var(--ok)" : "var(--danger)",
          }}
        >
          {estado.mensagem}
        </p>
      )}
    </form>
  );
}
