import type { FavoritoItem } from "@/lib/favoritos";

// Peças comuns das telas do Início que mostram um painel Python (api/painel.py) dentro de um iframe do mesmo site,
// como o PainelFrame faz na tela do painel inteiro.

export type JanelaDoPainel = Window & { PAINEL_VENCIDO?: boolean };

const dormir = (ms: number) => new Promise((r) => setTimeout(r, ms));
const ESPERA_MAX_MS = 3 * 60 * 1000;

export function urlDoPainel(painelId: string) {
  return `/api/painel?id=${encodeURIComponent(painelId)}`;
}

// A mesma página do painel, mas só com o bloco escolhido (o painel_base.js esconde o resto: ver ?aba=&item= lá).
export function urlDoItem(item: Pick<FavoritoItem, "painel_id" | "aba" | "chave">) {
  return `${urlDoPainel(item.painel_id)}&aba=${encodeURIComponent(item.aba)}&item=${encodeURIComponent(item.chave)}`;
}

// Quando o painel abre com dados vencidos (ou layout novo), a página guardada ainda não tem o que se pede aqui: pede a renovação
// em segundo plano (só copia do banco e refaz a página, não consulta o Klingo), espera acabar e devolve se deu certo.
export async function renovarPainel(painelId: string, sinal: AbortSignal): Promise<boolean> {
  const id = encodeURIComponent(painelId);
  try {
    const r = await fetch(`/api/renovar?id=${id}`, { method: "POST", headers: { "X-Painel": "1" }, signal: sinal });
    const j = (await r.json()) as { ok?: boolean; ocupado?: boolean; falhou?: boolean };
    if (!j.ok || j.falhou) return false;
    if (!j.ocupado) return true;
    // outra pessoa (ou o botão Atualizar agora) já está renovando este painel: espera ela terminar
    const limite = Date.now() + ESPERA_MAX_MS;
    while (!sinal.aborted && Date.now() < limite) {
      await dormir(3000);
      const e = await fetch(`/api/estado?id=${id}`, { cache: "no-store", signal: sinal });
      const estado = (await e.json()) as { atualizando?: boolean };
      if (!estado.atualizando) return true;
    }
    return false;
  } catch {
    return false;
  }
}
