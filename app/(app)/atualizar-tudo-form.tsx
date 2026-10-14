"use client";

import { useEffect, useRef, useState } from "react";
import { coletarLote } from "./atualizar-tudo-actions";

type Estado = {
  fase: "ocioso" | "rodando" | "concluido";
  feitos: number;
  total: number;
  linhas: number;
  falhas: number;
  interrompido: boolean;
  mensagem: string | null;
  erro: boolean;
};

const OCIOSO: Estado = {
  fase: "ocioso",
  feitos: 0,
  total: 0,
  linhas: 0,
  falhas: 0,
  interrompido: false,
  mensagem: null,
  erro: false,
};

const inteiro = new Intl.NumberFormat("pt-BR");

export function AtualizarTudoForm() {
  const [estado, setEstado] = useState<Estado>(OCIOSO);
  const parar = useRef(false);
  const ocupado = estado.fase === "rodando";

  // Fechar a aba no meio interrompe o lote atual; avisa antes.
  useEffect(() => {
    if (!ocupado) return;
    const avisar = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [ocupado]);

  // Pede ao banco o que falta, um lote por vez, até não sobrar nada. A mesma coleta roda sozinha
  // no servidor (a cada 5 h): o botão só antecipa, e fechar a aba não perde nada.
  async function iniciar(e: React.FormEvent) {
    e.preventDefault();
    if (ocupado) return;
    parar.current = false;
    setEstado({ ...OCIOSO, fase: "rodando" });

    let feitos = 0;
    let total = 0;
    let linhas = 0;
    let falhas = 0;
    let restantes = 0;
    let erroGeral = false;

    while (!parar.current) {
      let lote;
      try {
        lote = await coletarLote();
      } catch {
        lote = { ok: false, processados: 0, restantes: 0, linhas: 0, falhas: 0 };
      }
      if (!lote.ok) {
        erroGeral = true;
        break;
      }
      feitos += lote.processados;
      linhas += lote.linhas;
      falhas += lote.falhas;
      restantes = lote.restantes;
      total = feitos + restantes;
      setEstado({ ...OCIOSO, fase: "rodando", feitos, total, linhas, falhas });
      // Nada mais a buscar (ou o lote não avançou): para, para não martelar o Klingo.
      if (lote.processados === 0 || restantes === 0) break;
    }

    const interrompido = parar.current;
    const nada = feitos === 0 && !erroGeral && !interrompido;
    setEstado({
      ...OCIOSO,
      fase: "concluido",
      feitos,
      total,
      linhas,
      falhas,
      interrompido,
      erro: erroGeral || interrompido || falhas > 0,
      mensagem: erroGeral
        ? "Não foi possível atualizar agora. O que já foi baixado foi mantido; tente de novo em instantes."
        : interrompido
          ? "Atualização interrompida. O que já foi baixado foi mantido; o servidor continua o resto sozinho."
          : nada
            ? "Tudo já estava em dia."
            : falhas > 0
              ? `Concluído com ${falhas} falha(s). Veja os alertas de sincronização; relatórios que falham várias vezes são pausados sozinhos.`
              : `Tudo atualizado (${inteiro.format(linhas)} linhas lidas em ${inteiro.format(feitos)} consultas).`,
    });
  }

  const pct = estado.total > 0 ? Math.round((100 * estado.feitos) / estado.total) : 0;

  return (
    <form onSubmit={iniciar} className="toolbar" aria-label="Atualizar tudo">
      <div>
        <span className="toolbar-label">Sincronização</span>
        <p className="panel-sub" style={{ marginTop: 4 }}>
          Busca no Klingo só o que falta nos relatórios ativos (até 90 dias cada). O servidor também atualiza sozinho a cada 5 horas; qualquer pessoa pode atualizar na hora.
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

      {estado.fase === "rodando" && (
        <div className="sync-progress">
          <div className="sync-progress-linha">
            <span className="sync-progress-nome">
              <span className="spinner" aria-hidden="true" />
              <span>
                {estado.total > 0
                  ? `Buscando no Klingo · ${inteiro.format(estado.feitos)} de ${inteiro.format(estado.total)}`
                  : "Verificando o que falta…"}
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
            {estado.falhas > 0 && ` · ${estado.falhas} com falha`}
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
