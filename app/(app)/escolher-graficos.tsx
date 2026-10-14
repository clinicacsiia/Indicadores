"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import type { Painel } from "@/lib/paineis";
import type { FavoritoItem } from "@/lib/favoritos";
import { alternarFavorito } from "./favoritos-actions";
import { renovarPainel, urlDoPainel, type JanelaDoPainel } from "./favoritos-quadro";

type ItemDoPainel = { aba: string; titulo: string; chave: string };

type Catalogo = { fase: "carregando" | "atualizando" } | { fase: "pronto"; itens: ItemDoPainel[] } | { fase: "falhou" };

const chaveDe = (painelId: string, aba: string, chave: string) => `${painelId}\u0001${aba}\u0001${chave}`;

// Pergunta ao painel quais gráficos ele tem: carrega a página dele num quadro escondido (do mesmo site) e ela responde, depois de montada,
// com a lista de títulos agrupados por aba (itensDaPagina em painel_base.js). Só é chamado quando a pessoa abre o painel na lista.
function useCatalogo(painelId: string) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [catalogo, setCatalogo] = useState<Catalogo>({ fase: "carregando" });

  useEffect(() => {
    const quadro = ref.current;
    if (!quadro) return;
    let recebido = false;
    let renovou = false;
    let encerrado = false;
    const controle = new AbortController();

    const aoReceber = (e: MessageEvent) => {
      if (e.origin !== window.location.origin || e.source !== quadro.contentWindow) return;
      const d = e.data as { tipo?: string; itens?: ItemDoPainel[] } | null;
      if (d?.tipo !== "itens" || !Array.isArray(d.itens)) return;
      recebido = true;
      setCatalogo({ fase: "pronto", itens: d.itens });
    };

    // página guardada antiga (dados vencidos ou layout novo): ainda não tem a lista; renova em segundo plano e recarrega
    const aoCarregar = () => {
      setTimeout(() => {
        if (encerrado || recebido || renovou) return;
        const janela = quadro.contentWindow as JanelaDoPainel | null;
        if (!janela?.PAINEL_VENCIDO) return;
        renovou = true;
        setCatalogo({ fase: "atualizando" });
        void renovarPainel(painelId, controle.signal).then((ok) => {
          if (encerrado) return;
          if (ok) quadro.contentWindow?.location.reload();
          else setCatalogo({ fase: "falhou" });
        });
      }, 400);
    };

    window.addEventListener("message", aoReceber);
    quadro.addEventListener("load", aoCarregar);
    const limite = setTimeout(() => {
      if (!recebido) setCatalogo({ fase: "falhou" });
    }, 120_000);
    return () => {
      encerrado = true;
      controle.abort();
      clearTimeout(limite);
      window.removeEventListener("message", aoReceber);
      quadro.removeEventListener("load", aoCarregar);
    };
  }, [painelId]);

  return { ref, catalogo };
}

function CatalogoDoPainel({
  painel,
  marcados,
  aoAlternar,
}: {
  painel: Painel;
  marcados: Set<string>;
  aoAlternar: (item: FavoritoItem) => void;
}) {
  const { ref, catalogo } = useCatalogo(painel.id);

  const abas =
    catalogo.fase === "pronto"
      ? catalogo.itens.reduce<{ aba: string; itens: ItemDoPainel[] }[]>((grupos, item) => {
          const grupo = grupos.find((g) => g.aba === item.aba);
          if (grupo) grupo.itens.push(item);
          else grupos.push({ aba: item.aba, itens: [item] });
          return grupos;
        }, [])
      : [];

  return (
    <div className="favoritos-catalogo">
      <iframe ref={ref} hidden tabIndex={-1} aria-hidden="true" title={`Lista de gráficos de ${painel.nome}`} src={urlDoPainel(painel.id)} referrerPolicy="same-origin" />

      {(catalogo.fase === "carregando" || catalogo.fase === "atualizando") && (
        <p className="panel-sub" role="status">
          <span className="spinner" aria-hidden="true" />{" "}
          {catalogo.fase === "atualizando" ? "Atualizando os dados do painel para listar os gráficos…" : "Carregando os gráficos do painel…"}
        </p>
      )}
      {catalogo.fase === "falhou" && (
        <p className="favorito-erro" role="alert">
          Não consegui listar os gráficos deste painel agora. Feche e abra de novo em instantes.
        </p>
      )}
      {catalogo.fase === "pronto" && abas.length === 0 && <p className="panel-sub">Este painel ainda não tem gráficos para escolher (sem dados).</p>}

      {abas.map((grupo) => (
        <fieldset className="favoritos-aba" key={grupo.aba}>
          <legend className="favoritos-aba-nome">{grupo.aba}</legend>
          <ul className="favoritos-lista">
            {grupo.itens.map((item) => {
              const marcado = marcados.has(chaveDe(painel.id, item.aba, item.chave));
              return (
                <li key={item.chave}>
                  <label className="favoritos-opcao">
                    <input
                      type="checkbox"
                      checked={marcado}
                      onChange={() => aoAlternar({ painel_id: painel.id, aba: item.aba, chave: item.chave, titulo: item.titulo })}
                    />
                    <span>{item.titulo}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
      ))}
    </div>
  );
}

export function EscolherGraficos({ paineis, favoritos }: { paineis: Painel[]; favoritos: FavoritoItem[] }) {
  const [marcados, setMarcados] = useState(() => new Set(favoritos.map((f) => chaveDe(f.painel_id, f.aba, f.chave))));
  const [abertos, setAbertos] = useState<Set<string>>(() => new Set());
  const [erro, setErro] = useState<string | null>(null);
  const [, startTransition] = useTransition();
  // aberta só na primeira visita (nenhum gráfico escolhido); fixo para a lista não fechar na cara de quem está marcando
  const [abertaNoInicio] = useState(() => favoritos.length === 0);

  const trocarMarca = (item: FavoritoItem, ligado: boolean) =>
    setMarcados((atual) => {
      const novo = new Set(atual);
      const k = chaveDe(item.painel_id, item.aba, item.chave);
      if (ligado) novo.add(k);
      else novo.delete(k);
      return novo;
    });

  const alternar = (item: FavoritoItem) => {
    const k = chaveDe(item.painel_id, item.aba, item.chave);
    const estavaMarcado = marcados.has(k);
    trocarMarca(item, !estavaMarcado); // aparece marcado na hora; volta atrás se o servidor recusar
    setErro(null);
    startTransition(async () => {
      const resultado = await alternarFavorito({ painelId: item.painel_id, aba: item.aba, chave: item.chave, titulo: item.titulo });
      if (resultado?.error) {
        trocarMarca(item, estavaMarcado);
        setErro(resultado.error);
      }
    });
  };

  return (
    <details className="favoritos-escolher" open={abertaNoInicio}>
      <summary>Escolher gráficos</summary>
      <p className="panel-sub">
        Abra um painel, veja os títulos dos gráficos de cada aba e marque os que você quer ver aqui no Início. Só o gráfico escolhido aparece, não a página toda.
      </p>
      {erro && (
        <p role="alert" className="favorito-erro">
          {erro}
        </p>
      )}
      <ul className="favoritos-paineis">
        {paineis.map((p) => (
          <li key={p.id}>
            <details
              className="favoritos-painel"
              onToggle={(e) => {
                if (e.currentTarget.open) setAbertos((atual) => (atual.has(p.id) ? atual : new Set(atual).add(p.id)));
              }}
            >
              <summary>{p.nome}</summary>
              {abertos.has(p.id) && <CatalogoDoPainel painel={p} marcados={marcados} aoAlternar={alternar} />}
            </details>
          </li>
        ))}
      </ul>
    </details>
  );
}
