import type { Painel } from "@/lib/paineis";

// "tudo" = todos os relatórios, na ordem do menu; um id = só aquele relatório; qualquer outra coisa não gera nada.
export const EXTRAIR_TUDO = "tudo";

// O que pode virar PDF: cada painel em HTML (/api/painel) e também as páginas do site, Metas e Avisos (esconde o menu ao imprimir).
export type ItemExtrair = { id: string; nome: string; descricao: string; src: string; pagina: boolean };

export function itensParaExtrair(paineis: Painel[]): ItemExtrair[] {
  return [
    { id: "metas", nome: "Metas", descricao: "Metas mensais e comparação", src: "/metas", pagina: true },
    ...paineis.map((p) => ({
      id: p.id,
      nome: p.nome,
      descricao: p.descricao,
      src: `/api/painel?id=${encodeURIComponent(p.id)}`,
      pagina: false,
    })),
    { id: "avisos", nome: "Avisos", descricao: "Avisos abertos dos painéis", src: "/avisos", pagina: true },
  ];
}

export function paineisParaExtrair(escolha: string | undefined, lista: ItemExtrair[]): ItemExtrair[] {
  if (escolha === EXTRAIR_TUDO) return lista;
  return lista.filter((p) => p.id === escolha);
}
