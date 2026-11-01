"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Mantém o Início em dia sem a pessoa recarregar: refaz a tela do servidor de tempos em tempos (mais rápido enquanto algum painel está sendo
// atualizado) e só enquanto a aba está visível. O estado dos botões e da barra de "Atualizar tudo" continua como está.
export function AtualizarSozinho({ rapido }: { rapido: boolean }) {
  const router = useRouter();
  useEffect(() => {
    const intervalo = (rapido ? 10 : 60) * 1000;
    const t = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, intervalo);
    return () => clearInterval(t);
  }, [rapido, router]);
  return null;
}
