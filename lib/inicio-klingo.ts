import modulos from "@/modulos.json";

// Mês (AAAA-MM) em que o Klingo passou a ser usado. É o mesmo `inicio_klingo` do modulos.json que os painéis em Python leem:
// o que vem de antes é de teste ou do sistema anterior (Clinical) e não pode entrar em histórico, média, comparação nem previsão.
export const INICIO_KLINGO: string = String((modulos as { inicio_klingo?: string }).inicio_klingo ?? "2026-09").slice(0, 7);

/** O mês (AAAA-MM, ou AAAA-MM-DD) é anterior ao uso do Klingo? */
export function antesDoKlingo(mes: string): boolean {
  return mes.slice(0, 7) < INICIO_KLINGO;
}

/** O primeiro mês que uma tela pode mostrar: o que a tela pede, mas nunca antes do Klingo. */
export function primeiroMesValido(pedido: string): string {
  return pedido < INICIO_KLINGO ? INICIO_KLINGO : pedido;
}
