"use client";

import { useEffect, useRef, useState } from "react";

type Item = { id: string; nome: string; src: string; pagina: boolean };

const ESPERA_GRAFICOS_MS = 1500; // os gráficos dos painéis são desenhados por script logo depois do carregamento

// Cada relatório vira um quadro do tamanho do próprio conteúdo, um por folha; quando todos carregam, abre a impressão do navegador
// (destino "Salvar como PDF"). Usa a última página guardada de cada painel: não pede atualização nem consulta o Klingo.
export function Impressao({ paineis }: { paineis: Item[] }) {
  const quadros = useRef<Map<string, HTMLIFrameElement>>(new Map());
  const [prontos, setProntos] = useState<Set<string>>(new Set());
  const impresso = useRef(false);

  const ajustar = (id: string) => {
    const q = quadros.current.get(id);
    const corpo = q?.contentDocument?.body;
    if (q && corpo) q.style.height = `${Math.ceil(corpo.getBoundingClientRect().height)}px`;
  };

  // Páginas do site (Metas, Avisos) vêm com o menu lateral: esconde para sobrar só o conteúdo.
  const limparPagina = (id: string) => {
    const doc = quadros.current.get(id)?.contentDocument;
    if (!doc) return;
    const estilo = doc.createElement("style");
    estilo.textContent = ".sidebar, .skip-link { display: none !important; } .shell { display: block !important; } .main { margin: 0 !important; padding: 0 !important; }";
    doc.head.appendChild(estilo);
  };

  const aoCarregar = (id: string, pagina: boolean) => {
    if (pagina) limparPagina(id);
    ajustar(id);
    setProntos((atual) => new Set(atual).add(id));
  };

  const todos = prontos.size === paineis.length;
  useEffect(() => {
    if (!todos || impresso.current) return;
    const t = setTimeout(() => {
      paineis.forEach((p) => ajustar(p.id));
      impresso.current = true;
      window.print();
    }, ESPERA_GRAFICOS_MS);
    return () => clearTimeout(t);
  }, [todos, paineis]);

  return (
    <main className="extrair-pagina">
      <div className="extrair-barra">
        <strong>
          {todos ? "Pronto. Na janela de impressão, escolha “Salvar como PDF”." : `Preparando ${paineis.length === 1 ? "o relatório" : "os relatórios"}… (${prontos.size}/${paineis.length})`}
        </strong>
        <button type="button" className="btn btn-primary" disabled={!todos} onClick={() => window.print()}>
          Imprimir / salvar em PDF
        </button>
      </div>
      {paineis.map((p) => (
        <section key={p.id} className="extrair-folha">
          <iframe
            ref={(el) => {
              if (el) quadros.current.set(p.id, el);
              else quadros.current.delete(p.id);
            }}
            title={p.nome}
            src={p.src}
            referrerPolicy="same-origin"
            onLoad={() => aoCarregar(p.id, p.pagina)}
          />
        </section>
      ))}
    </main>
  );
}
