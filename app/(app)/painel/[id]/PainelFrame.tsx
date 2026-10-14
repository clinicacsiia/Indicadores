"use client";

import { useEffect, useRef } from "react";

// O painel (função Python) é uma página completa dentro de um iframe do mesmo site. Aqui o quadro some: sem borda e com a altura do
// conteúdo, para o painel rolar junto com a tela e parecer uma tela como as outras. Também guarda o período escolhido no endereço
// da tela (o painel avisa com postMessage), para recarregar ou compartilhar o link mantendo o filtro.
export function PainelFrame({ src, titulo }: { src: string; titulo: string }) {
  const ref = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const quadro = ref.current;
    if (!quadro) return;
    let observador: ResizeObserver | null = null;

    const ajustar = () => {
      const corpo = quadro.contentDocument?.body;
      if (!corpo) return;
      // a altura do corpo (e não a do documento, que nunca encolhe abaixo do quadro): assim o quadro também diminui
      quadro.style.height = `${Math.ceil(corpo.getBoundingClientRect().height)}px`;
    };
    const aoCarregar = () => {
      ajustar();
      const doc = quadro.contentDocument;
      if (!doc?.body) return;
      observador?.disconnect();
      observador = new ResizeObserver(ajustar);
      observador.observe(doc.body);
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
      quadro.removeEventListener("load", aoCarregar);
      window.removeEventListener("message", aoReceber);
      observador?.disconnect();
    };
  }, [src]);

  return <iframe ref={ref} className="painel-frame" title={titulo} src={src} referrerPolicy="same-origin" />;
}
