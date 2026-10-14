"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useTransition } from "react";
import { IconEstrela } from "@/app/components/icons";
import type { FavoritoItem } from "@/lib/favoritos";
import { alternarFavorito } from "./favoritos-actions";
import { renovarPainel, urlDoItem, type JanelaDoPainel } from "./favoritos-quadro";

type Fase = "carregando" | "atualizando" | "pronto" | "falhou";

// O bloco escolhido (um gráfico, os números principais, uma tabela) de um painel, sem o resto da página. O quadro cresce até a altura
// do conteúdo, como na tela do painel inteiro.
function QuadroDoItem({ item, nomePainel }: { item: FavoritoItem; nomePainel: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [fase, setFase] = useState<Fase>("carregando");

  useEffect(() => {
    const quadro = ref.current;
    if (!quadro) return;
    let observador: ResizeObserver | null = null;
    let renovou = false;
    let encerrado = false;
    const controle = new AbortController();

    const ajustar = () => {
      const corpo = quadro.contentDocument?.body;
      if (corpo) quadro.style.height = `${Math.max(Math.ceil(corpo.getBoundingClientRect().height), 40)}px`;
    };

    const aoCarregar = () => {
      const doc = quadro.contentDocument;
      if (!doc?.body) return;
      ajustar();
      observador?.disconnect();
      observador = new ResizeObserver(ajustar);
      observador.observe(doc.body);

      const janela = quadro.contentWindow as JanelaDoPainel | null;
      if (janela?.PAINEL_VENCIDO && !renovou) {
        renovou = true;
        setFase("atualizando");
        void renovarPainel(item.painel_id, controle.signal).then((ok) => {
          if (encerrado) return;
          if (ok) quadro.contentWindow?.location.reload();
          else setFase("pronto"); // fica com os dados da última atualização
        });
        return;
      }
      setFase("pronto");
    };

    quadro.addEventListener("load", aoCarregar);
    if (quadro.contentDocument?.readyState === "complete") aoCarregar();
    const limite = setTimeout(() => setFase((f) => (f === "carregando" ? "falhou" : f)), 90_000);
    return () => {
      encerrado = true;
      controle.abort();
      clearTimeout(limite);
      quadro.removeEventListener("load", aoCarregar);
      observador?.disconnect();
    };
  }, [item.painel_id]);

  return (
    <>
      {fase === "atualizando" && (
        <p className="panel-sub" role="status">
          <span className="spinner" aria-hidden="true" /> Atualizando os dados de {nomePainel}…
        </p>
      )}
      {fase === "falhou" && (
        <p className="favorito-erro" role="alert">
          Não consegui carregar este gráfico agora. Use “Abrir painel” para ver o painel completo.
        </p>
      )}
      <iframe
        ref={ref}
        className="favorito-frame"
        title={item.titulo}
        src={urlDoItem(item)}
        referrerPolicy="same-origin"
      />
    </>
  );
}

function RemoverFavorito({ item }: { item: FavoritoItem }) {
  const [pendente, startTransition] = useTransition();
  const [erro, setErro] = useState<string | null>(null);

  return (
    <span className="favorito-estrela-wrap">
      <button
        type="button"
        className="favorito-estrela"
        data-ativo
        aria-label={`Remover “${item.titulo}” dos favoritos do Início`}
        title="Remover dos favoritos"
        disabled={pendente}
        onClick={() =>
          startTransition(async () => {
            const resultado = await alternarFavorito({
              painelId: item.painel_id,
              aba: item.aba,
              chave: item.chave,
              titulo: item.titulo,
            });
            setErro(resultado?.error ?? null);
          })
        }
      >
        <IconEstrela size={18} preenchida />
      </button>
      {erro && (
        <span role="alert" className="favorito-erro">
          {erro}
        </span>
      )}
    </span>
  );
}

export function FavoritoCartao({ item, nomePainel }: { item: FavoritoItem; nomePainel: string }) {
  return (
    <article className="favorito-card" aria-label={item.titulo}>
      <div className="favorito-card-head">
        <div>
          <h3 className="favorito-card-titulo">{item.titulo}</h3>
          <p className="panel-sub">
            {nomePainel} · {item.aba}
          </p>
        </div>
        <div className="favorito-card-acoes">
          <Link href={`/painel/${item.painel_id}`} className="favorito-abrir">
            Abrir painel
          </Link>
          <RemoverFavorito item={item} />
        </div>
      </div>
      <QuadroDoItem item={item} nomePainel={nomePainel} />
    </article>
  );
}
