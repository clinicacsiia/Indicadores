import type { Painel } from "@/lib/paineis";

// "tudo" = todos os relatórios, na ordem do menu; um id = só aquele relatório; qualquer outra coisa não gera nada.
export const EXTRAIR_TUDO = "tudo";

export function paineisParaExtrair(escolha: string | undefined, lista: Painel[]): Painel[] {
  if (escolha === EXTRAIR_TUDO) return lista;
  return lista.filter((p) => p.id === escolha);
}
