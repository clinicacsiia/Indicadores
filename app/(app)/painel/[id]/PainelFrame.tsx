"use client";

import { useEffect, useRef, useState } from "react";

// O painel (função Python) é uma página completa dentro de um iframe do mesmo site. Aqui o quadro some: sem borda e com a altura do
// conteúdo, para o painel rolar junto com a tela e parecer uma tela como as outras. Também guarda o período escolhido no endereço
// da tela (o painel avisa com postMessage), para recarregar ou compartilhar o link mantendo o filtro.
//
// O painel abre na hora com a última página guardada. Se os dados estão vencidos (dia novo, dado novo ou a cópia do banco com mais de 5 h),
// a página avisa (window.PAINEL_VENCIDO) e esta tela pede a renovação em segundo plano (POST /api/renovar), mostrando "atualizando" com
// quanto falta (estimado pelo tempo das últimas vezes) e recarregando o quadro quando termina.

type JanelaDoPainel = Window & { PAINEL_VENCIDO?: boolean; PAINEL_PREVISTO_S?: number };

type Andamento = { decorrido_s: number; previsto_s: number };

type Fase =
  | { tipo: "ocioso" }
  | { tipo: "renovando"; inicio: number; previsto: number }
  | { tipo: "pronto" }
  | { tipo: "falhou"; mensagem: string };

const MAX_RENOVACOES = 2; // por abertura da tela: se a página continua vencida depois de renovar, não fica em laço
const ESPERA_MAX_MS = 8 * 60 * 1000;
const PREVISTO_PADRAO_S = 30;

const dormir = (ms: number) => new Promise((r) => setTimeout(r, ms));

function formatarSegundos(total: number) {
  const s = Math.max(Math.round(total), 0);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r === 0 ? `${m} min` : `${m} min ${r} s`;
}

// Quanto falta: o previsto vem da mediana das últimas renovações do painel. Nunca promete 100% antes de terminar.
function andamentoDaRenovacao(decorridoMs: number, previstoS: number) {
  const previsto = Math.max(previstoS, 5);
  const decorrido = Math.max(decorridoMs / 1000, 0);
  const pct = Math.min(95, Math.round((decorrido / previsto) * 100));
  const faltam = previsto - decorrido;
  const texto =
    faltam > 3
      ? `Faltam cerca de ${formatarSegundos(faltam)}`
      : decorrido <= previsto * 1.5
        ? "Quase pronto…"
        : "Está demorando mais que o normal, já deve terminar";
  return { pct, texto };
}

export function PainelFrame({ src, titulo, painelId }: { src: string; titulo: string; painelId: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const renovacoes = useRef(0);
  const [fase, setFase] = useState<Fase>({ tipo: "ocioso" });
  const [agora, setAgora] = useState(() => Date.now());

  useEffect(() => {
    const quadro = ref.current;
    if (!quadro) return;
    let observador: ResizeObserver | null = null;
    let encerrado = false;
    let emCurso = false;
    const controle = new AbortController();

    const ajustar = () => {
      const corpo = quadro.contentDocument?.body;
      if (!corpo) return;
      // a altura do corpo (e não a do documento, que nunca encolhe abaixo do quadro): assim o quadro também diminui
      quadro.style.height = `${Math.ceil(corpo.getBoundingClientRect().height)}px`;
    };

    const id = encodeURIComponent(painelId);
    const esperarOutraRenovacao = async (andamento: Andamento | null) => {
      // outra pessoa (ou o botão Atualizar agora) já está renovando este painel: acompanha o andamento dela até acabar
      const limite = Date.now() + ESPERA_MAX_MS;
      let atual = andamento;
      while (!encerrado && Date.now() < limite) {
        if (atual) {
          const inicio = Date.now() - atual.decorrido_s * 1000;
          setFase({ tipo: "renovando", inicio, previsto: atual.previsto_s });
        }
        await dormir(3000);
        if (encerrado) return false;
        const r = await fetch(`/api/estado?id=${id}`, { cache: "no-store", signal: controle.signal });
        const j = (await r.json()) as { atualizando?: boolean; andamento?: Andamento | null };
        if (!j.atualizando) return true;
        atual = j.andamento ?? null;
      }
      return false;
    };

    const renovar = async (previstoS: number) => {
      emCurso = true;
      renovacoes.current += 1;
      setFase({ tipo: "renovando", inicio: Date.now(), previsto: previstoS > 0 ? previstoS : PREVISTO_PADRAO_S });
      setAgora(Date.now());
      let ok = false;
      let mensagem = "Não consegui atualizar agora. Você está vendo os dados da última atualização.";
      try {
        const r = await fetch(`/api/renovar?id=${id}`, { method: "POST", headers: { "X-Painel": "1" }, signal: controle.signal });
        const j = (await r.json()) as { ok?: boolean; ocupado?: boolean; falhou?: boolean; andamento?: Andamento | null };
        if (j.ok && j.ocupado) ok = await esperarOutraRenovacao(j.andamento ?? null);
        else ok = Boolean(j.ok);
        if (j.ok && j.falhou) {
          ok = false;
          mensagem = "Não consegui buscar dados novos agora. Você está vendo os dados da última atualização.";
        }
      } catch {
        ok = false;
      }
      emCurso = false;
      if (encerrado) return;
      if (!ok) {
        setFase({ tipo: "falhou", mensagem });
        return;
      }
      setFase({ tipo: "pronto" });
      quadro.contentWindow?.location.reload();
      setTimeout(() => {
        if (!encerrado) setFase((f) => (f.tipo === "pronto" ? { tipo: "ocioso" } : f));
      }, 5000);
    };

    const aoCarregar = () => {
      ajustar();
      const doc = quadro.contentDocument;
      if (!doc?.body) return;
      observador?.disconnect();
      observador = new ResizeObserver(ajustar);
      observador.observe(doc.body);
      const janela = quadro.contentWindow as JanelaDoPainel | null;
      if (janela?.PAINEL_VENCIDO && !emCurso && renovacoes.current < MAX_RENOVACOES) {
        void renovar(Number(janela.PAINEL_PREVISTO_S) || PREVISTO_PADRAO_S);
      }
    };
    const aoReceber = (e: MessageEvent) => {
      if (e.origin !== window.location.origin || e.source !== quadro.contentWindow) return;
      const d = e.data as { tipo?: string; de?: string; ate?: string } | null;
      if (d?.tipo !== "periodo" || !d.de || !d.ate) return;
      const q = new URLSearchParams(window.location.search);
      q.set("de", d.de);
      q.set("ate", d.ate);
      window.history.replaceState(null, "", `${window.location.pathname}?${q.toString()}`);
    };

    quadro.addEventListener("load", aoCarregar);
    window.addEventListener("message", aoReceber);
    if (quadro.contentDocument?.readyState === "complete") aoCarregar();
    return () => {
      encerrado = true;
      controle.abort();
      quadro.removeEventListener("load", aoCarregar);
      window.removeEventListener("message", aoReceber);
      observador?.disconnect();
    };
  }, [src, painelId]);

  // relógio do aviso: só roda enquanto está atualizando
  const renovando = fase.tipo === "renovando";
  useEffect(() => {
    if (!renovando) return;
    const t = setInterval(() => setAgora(Date.now()), 1000);
    return () => clearInterval(t);
  }, [renovando]);

  return (
    <>
      {fase.tipo === "renovando" && <AvisoAtualizando fase={fase} agora={agora} />}
      {fase.tipo === "pronto" && (
        <div className="painel-aviso" data-tipo="ok" role="status">
          <strong>Dados atualizados.</strong>
        </div>
      )}
      {fase.tipo === "falhou" && (
        <div className="painel-aviso" data-tipo="erro" role="alert">
          <strong>{fase.mensagem}</strong>
        </div>
      )}
      <iframe ref={ref} className="painel-frame" title={titulo} src={src} referrerPolicy="same-origin" />
    </>
  );
}

function AvisoAtualizando({ fase, agora }: { fase: Extract<Fase, { tipo: "renovando" }>; agora: number }) {
  const { pct, texto } = andamentoDaRenovacao(agora - fase.inicio, fase.previsto);
  return (
    <div className="painel-aviso" data-tipo="info" role="status" aria-live="polite">
      <div className="painel-aviso-linha">
        <span className="painel-aviso-nome">
          <span className="spinner" aria-hidden="true" />
          <strong>Atualizando os dados deste painel…</strong>
        </span>
        <span>{texto}</span>
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
      <p className="panel-sub">Você já pode ver os dados da última atualização logo abaixo; a tela recarrega sozinha quando terminar. O tempo é uma estimativa.</p>
    </div>
  );
}
