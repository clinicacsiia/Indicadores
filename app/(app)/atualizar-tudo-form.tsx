"use client";

import { useEffect, useRef, useState } from "react";
import { atualizarPasso, planejarAtualizacao } from "./atualizar-tudo-actions";

type Estado = {
  fase: "ocioso" | "planejando" | "rodando" | "concluido";
  feitos: number;
  total: number;
  relatorioIdx: number;
  relatorioTotal: number;
  relatorioNome: string;
  linhas: number;
  falhas: string[];
  interrompido: boolean;
  mensagem: string | null;
  erro: boolean;
};

const OCIOSO: Estado = {
  fase: "ocioso",
  feitos: 0,
  total: 0,
  relatorioIdx: 0,
  relatorioTotal: 0,
  relatorioNome: "",
  linhas: 0,
  falhas: [],
  interrompido: false,
  mensagem: null,
  erro: false,
};

const inteiro = new Intl.NumberFormat("pt-BR");

export function AtualizarTudoForm() {
  const [estado, setEstado] = useState<Estado>(OCIOSO);
  const parar = useRef(false);
  const ocupado = estado.fase === "planejando" || estado.fase === "rodando";

  // Fechar a aba no meio interrompe a atualização; avisa antes.
  useEffect(() => {
    if (!ocupado) return;
    const avisar = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [ocupado]);

  async function iniciar(e: React.FormEvent) {
    e.preventDefault();
    if (ocupado) return;
    parar.current = false;
    setEstado({ ...OCIOSO, fase: "planejando" });

    let plano;
    try {
      plano = await planejarAtualizacao();
    } catch {
      setEstado({ ...OCIOSO, fase: "concluido", erro: true, mensagem: "Não foi possível preparar a atualização agora." });
      return;
    }
    if (!plano.ok) {
      setEstado({ ...OCIOSO, fase: "concluido", erro: true, mensagem: plano.mensagem });
      return;
    }
    if (plano.relatorios.length === 0) {
      setEstado({ ...OCIOSO, fase: "concluido", mensagem: "Tudo já estava em dia." });
      return;
    }

    const relatorios = plano.relatorios;
    const total = relatorios.reduce((soma, r) => soma + r.passos.length, 0);
    let feitos = 0;
    let linhas = 0;
    const falhas: string[] = [];

    for (let i = 0; i < relatorios.length && !parar.current; i++) {
      const relatorio = relatorios[i];
      let falhou = false;

      for (let j = 0; j < relatorio.passos.length && !parar.current; j++) {
        const passo = relatorio.passos[j];
        setEstado({
          ...OCIOSO,
          fase: "rodando",
          feitos,
          total,
          relatorioIdx: i + 1,
          relatorioTotal: relatorios.length,
          relatorioNome: relatorio.nome,
          linhas,
          falhas: [...falhas],
        });

        let resultado;
        try {
          resultado = await atualizarPasso(relatorio.klingoId, passo.de, passo.ate, j === relatorio.passos.length - 1);
        } catch {
          resultado = { ok: false, linhas: 0, dias: 1, falhas: 1 };
        }
        feitos++;
        linhas += resultado.linhas;

        if (!resultado.ok) {
          if (!falhou) falhas.push(relatorio.nome);
          falhou = true;
          // Todos os dias do passo falharam: o relatório está com problema (ou fora do ar);
          // não adianta martelar o Klingo com o resto dele.
          if (resultado.falhas >= resultado.dias) {
            feitos += relatorio.passos.length - j - 1;
            break;
          }
        }
      }
    }

    const interrompido = parar.current;
    setEstado({
      ...OCIOSO,
      fase: "concluido",
      feitos,
      total,
      relatorioTotal: relatorios.length,
      linhas,
      falhas,
      interrompido,
      erro: falhas.length > 0 || interrompido,
      mensagem: interrompido
        ? "Atualização interrompida. O que já foi baixado foi mantido; clique de novo para continuar de onde parou."
        : falhas.length > 0
          ? `Concluído com falha em ${falhas.length} relatório(s): ${falhas.join("; ")}. Veja os alertas de sincronização.`
          : `Tudo atualizado (${inteiro.format(linhas)} linhas lidas em ${relatorios.length} relatórios).`,
    });
  }

  const pct = estado.total > 0 ? Math.round((100 * estado.feitos) / estado.total) : 0;

  return (
    <form onSubmit={iniciar} className="toolbar" aria-label="Atualizar tudo">
      <div>
        <span className="toolbar-label">Sincronização</span>
        <p className="panel-sub" style={{ marginTop: 4 }}>
          Busca no Klingo, para todos os relatórios, só o que falta para ficarem em dia (máx. 31 dias por relatório).
        </p>
      </div>

      {ocupado ? (
        <button type="button" className="btn" style={{ marginLeft: "auto" }} onClick={() => (parar.current = true)}>
          Parar
        </button>
      ) : (
        <button type="submit" className="btn btn-primary" style={{ marginLeft: "auto" }}>
          Atualizar tudo
        </button>
      )}

      {estado.fase === "planejando" && (
        <p className="panel-sub sync-progress-texto" role="status">
          <span className="spinner" aria-hidden="true" /> Verificando o que falta…
        </p>
      )}

      {estado.fase === "rodando" && (
        <div className="sync-progress">
          <div className="sync-progress-linha">
            <span className="sync-progress-nome">
              <span className="spinner" aria-hidden="true" />
              <span>
                Relatório {estado.relatorioIdx} de {estado.relatorioTotal} · {estado.relatorioNome}
              </span>
            </span>
            <strong>{pct}%</strong>
          </div>
          <div
            className="meter"
            data-status="rodando"
            role="progressbar"
            aria-label="Progresso da atualização"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <span className="meter-fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="panel-sub sync-progress-texto">
            {inteiro.format(estado.linhas)} linhas lidas
            {estado.falhas.length > 0 && ` · ${estado.falhas.length} com falha`}
          </p>
        </div>
      )}

      {estado.fase === "concluido" && estado.mensagem && (
        <p
          role={estado.erro ? "alert" : "status"}
          className="panel-sub"
          style={{
            flexBasis: "100%",
            margin: 0,
            fontWeight: 600,
            color: estado.erro ? "var(--danger)" : "var(--ok)",
          }}
        >
          {estado.mensagem}
        </p>
      )}
    </form>
  );
}
