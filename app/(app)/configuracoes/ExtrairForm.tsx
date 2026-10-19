"use client";

import { useState } from "react";
import { EXTRAIR_TUDO } from "@/lib/extrair";

type Props = { paineis: { id: string; nome: string; descricao: string }[] };

// Abre a página de impressão (/extrair) numa aba nova; lá o navegador oferece "Salvar como PDF".
export function ExtrairForm({ paineis }: Props) {
  const [modo, setModo] = useState<"tudo" | "um">("tudo");
  const [painel, setPainel] = useState(paineis[0]?.id ?? "");
  const escolha = modo === "tudo" ? EXTRAIR_TUDO : painel;

  return (
    <form action="/extrair" method="get" target="_blank" className="novo-usuario">
      <input type="hidden" name="p" value={escolha} />
      <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="field-label">O que extrair</legend>
        <label style={{ display: "flex", gap: 8, alignItems: "center", minHeight: 36 }}>
          <input type="radio" name="modo" checked={modo === "tudo"} onChange={() => setModo("tudo")} />
          Todos os relatórios, em um único PDF
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center", minHeight: 36 }}>
          <input type="radio" name="modo" checked={modo === "um"} onChange={() => setModo("um")} />
          Só um relatório
        </label>
      </fieldset>
      {modo === "um" && (
        <div className="field">
          <label className="field-label" htmlFor="extrair-painel">Relatório</label>
          <select id="extrair-painel" className="select" value={painel} onChange={(e) => setPainel(e.target.value)}>
            {paineis.map((p) => (
              <option key={p.id} value={p.id}>{p.nome}</option>
            ))}
          </select>
        </div>
      )}
      <div>
        <button type="submit" className="btn btn-primary" disabled={!escolha}>Gerar PDF</button>
      </div>
    </form>
  );
}
