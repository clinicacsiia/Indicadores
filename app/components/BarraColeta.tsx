"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  duracaoCurta,
  estadoDoRelatorio,
  estadoGeral,
  horaBrasilia,
  progresso,
  proximoALer,
  ROTULO_ESTADO,
  segundosAte,
  type RitmoRelatorio,
} from "@/lib/coleta-ritmo";

const CONSULTA_MS = 10_000;

// Barra de atualização da Jornada: mostra se os relatórios do Klingo estão sendo lidos "ao vivo" (a cada 1 min), em ritmo calmo (fora do expediente,
// sem movimento) ou dormindo, quando foi a última leitura e quando será a próxima. Ao abrir (e ao voltar para a aba) ela acorda a coleta que estava
// devagar, no máximo uma vez a cada 20 s (acordar_coleta). Sem dados ou sem permissão, não desenha nada.
export function BarraColeta() {
  const [linhas, setLinhas] = useState<RitmoRelatorio[] | null>(null);
  const [agoraMs, setAgoraMs] = useState(() => Date.now());
  // diferença entre o relógio do servidor e o do navegador, para a contagem não depender da hora do computador
  const desvio = useRef(0);

  const ler = useCallback(async () => {
    const supabase = createClient();
    const { data, error } = await supabase.rpc("status_ritmo_coleta");
    if (error || !data) return;
    const rs = data as RitmoRelatorio[];
    if (rs.length > 0) desvio.current = Date.parse(rs[0].agora) - Date.now();
    setLinhas(rs);
  }, []);

  const acordar = useCallback(async () => {
    const supabase = createClient();
    const { data } = await supabase.rpc("acordar_coleta", { p_motivo: "Alguém abriu o painel" });
    if ((data as { acordou?: number } | null)?.acordou) await ler();
  }, [ler]);

  useEffect(() => {
    void acordar();
    void ler();
    const consulta = setInterval(() => {
      if (document.visibilityState === "visible") void ler();
    }, CONSULTA_MS);
    const relogio = setInterval(() => setAgoraMs(Date.now() + desvio.current), 1000);
    const aoVoltar = () => {
      if (document.visibilityState === "visible") {
        void acordar();
        void ler();
      }
    };
    document.addEventListener("visibilitychange", aoVoltar);
    return () => {
      clearInterval(consulta);
      clearInterval(relogio);
      document.removeEventListener("visibilitychange", aoVoltar);
    };
  }, [acordar, ler]);

  if (!linhas || linhas.length === 0) return null;

  const estado = estadoGeral(linhas, agoraMs);
  const proximo = proximoALer(linhas);
  const ultimaMs = Math.max(...linhas.map((r) => (r.ultima_leitura_em ? Date.parse(r.ultima_leitura_em) : 0)));
  const falta = proximo ? segundosAte(proximo.proxima_leitura_em, agoraMs) : null;

  return (
    <section className="barra-coleta" data-estado={estado} aria-label="Atualização dos relatórios do Klingo" role="status" aria-live="polite">
      <div className="barra-coleta-linha">
        <span className="barra-coleta-nome">
          <span className="barra-coleta-ponto" aria-hidden="true" />
          <strong>{ROTULO_ESTADO[estado]}</strong>
          {estado === "ao_vivo" && <span className="barra-coleta-sub">lendo o Klingo a cada 1 min</span>}
          {(estado === "calmo" || estado === "dormindo") && (
            <span className="barra-coleta-sub">fora do expediente e sem movimento: o ritmo volta a 1 min assim que algo acontecer</span>
          )}
          {estado === "atrasado" && <span className="barra-coleta-sub">passou da hora da leitura e ela ainda não saiu</span>}
          {estado === "erro" && <span className="barra-coleta-sub">o Klingo não respondeu; tentando de novo</span>}
        </span>
        <span className="barra-coleta-texto">
          {ultimaMs > 0 ? `Atualizado há ${duracaoCurta((agoraMs - ultimaMs) / 1000)}` : "Ainda sem leitura"}
          {falta !== null && (falta > 0 ? ` · próxima em ${duracaoCurta(falta)}` : " · lendo agora")}
        </span>
      </div>
      {proximo && (
        <div className="meter" data-status={estado === "erro" || estado === "atrasado" ? "atrasado" : estado === "ao_vivo" ? "rodando" : "atencao"} aria-hidden="true">
          <div className="meter-fill" style={{ width: `${Math.round(progresso(proximo, agoraMs) * 100)}%` }} />
        </div>
      )}
      <details className="barra-coleta-detalhes">
        <summary>Por relatório</summary>
        <ul>
          {linhas.map((r) => {
            const e = estadoDoRelatorio(r, agoraMs);
            const f = segundosAte(r.proxima_leitura_em, agoraMs);
            return (
              <li key={r.klingo_id} data-estado={e}>
                <strong>
                  #{r.klingo_id} {r.nome}
                </strong>
                <span>
                  {ROTULO_ESTADO[e]} · a cada {r.intervalo_min} min
                  {r.ultima_leitura_em && ` · lido às ${horaBrasilia(r.ultima_leitura_em)}`}
                  {f !== null && ` · ${f > 0 ? `próxima em ${duracaoCurta(f)}` : "lendo agora"}`}
                  {r.ultimo_movimento_em && ` · último movimento às ${horaBrasilia(r.ultimo_movimento_em)}${r.motivo_movimento ? ` (${r.motivo_movimento})` : ""}`}
                  {r.minimo_min > 1 && ` · enquanto não existir o relatório por data do exame, o mínimo é ${r.minimo_min} min (ver Avisos)`}
                </span>
              </li>
            );
          })}
        </ul>
      </details>
    </section>
  );
}
