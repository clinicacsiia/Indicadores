"use client";
import { useEffect, useRef } from "react";
import { supabaseNoNavegador } from "@/lib/supabase/navegador";
import { DEPENDE_DE, type MenuId } from "@/klingo/config";

/** O painel roda num iframe do próprio site (X-Frame-Options: SAMEORIGIN). Quando uma atualização termina, o Realtime avisa e ele recarrega sozinho. */
export default function PainelFrame({ menu, consulta }: { menu: MenuId; consulta: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const src = `/api/painel/${menu}${consulta ? `?${consulta}` : ""}`;

  useEffect(() => {
    const sb = supabaseNoNavegador();
    const interessa = new Set<string>([menu, ...DEPENDE_DE[menu]]);
    const canal = sb.channel(`versao-${menu}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "dados_versao" }, (p) => {
        const linha = (p.new ?? {}) as { menu?: string };
        if (linha.menu && interessa.has(linha.menu)) ref.current?.contentWindow?.location.reload();
      })
      .subscribe();
    return () => { void sb.removeChannel(canal); };
  }, [menu]);

  // o período escolhido num painel vale para os outros: o painel avisa e o endereço do iframe segue
  useEffect(() => {
    const ouvir = (e: MessageEvent) => { if (e.origin === location.origin && e.data?.tipo === "periodo") sessionStorage.setItem("csi.periodo", JSON.stringify({ de: e.data.de, ate: e.data.ate })); };
    addEventListener("message", ouvir);
    return () => removeEventListener("message", ouvir);
  }, []);

  return <iframe ref={ref} className="painel-frame" src={src} title={`Painel ${menu}`} />;
}
