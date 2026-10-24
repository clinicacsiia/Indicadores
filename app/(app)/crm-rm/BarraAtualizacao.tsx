"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

/**
 * Quando o Klingo foi lido pela última vez e um botão para reler a tela.
 * O botão só refaz a leitura do banco: a ida ao Klingo é automática (a agenda é recoletada a cada ~5 h pelo servidor);
 * para forçar na hora, "Atualizar tudo" no Início.
 */
export function BarraAtualizacao({ lidoEm, demora }: { lidoEm: string | null; demora: boolean }) {
  const router = useRouter();
  const [pendente, comecar] = useTransition();

  return (
    <div className="crm-atualizacao">
      <p className="crm-atualizacao-texto" data-demora={demora ? "true" : undefined}>
        {lidoEm ? (
          <>
            Agenda do Klingo lida em <strong>{lidoEm}</strong>
            {demora && " · faz tempo: peça a um administrador para conferir a coleta"}
          </>
        ) : (
          "Ainda não há leitura da agenda do Klingo."
        )}
      </p>
      <button type="button" className="btn btn-pequeno" onClick={() => comecar(() => router.refresh())} disabled={pendente} aria-busy={pendente}>
        {pendente ? "Atualizando…" : "Atualizar tela"}
      </button>
    </div>
  );
}
