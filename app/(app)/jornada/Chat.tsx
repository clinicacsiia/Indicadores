"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { MensagemJornada } from "@/lib/jornada";

const COLUNAS = "id, card_id, autor, autor_nome, autor_tipo, texto, criado_em";

// Chat interno do cartão (só da equipe). Cada cartão tem o seu canal privado "jornada:card:<id>": o aviso traz só o número da mensagem e o texto é lido de novo
// pelas regras de acesso de sempre. Sem o tempo real, a conversa continua funcionando: quem envia vê a própria mensagem na hora e as dos outros chegam a cada 15 s.
export function Chat({ cardId, usuarioId }: { cardId: number; usuarioId: string }) {
  const [mensagens, setMensagens] = useState<MensagemJornada[] | null>(null);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const fim = useRef<HTMLDivElement | null>(null);
  const ultimo = useRef(0);

  // lê o que ainda não chegou (depois da última mensagem conhecida)
  const buscar = useCallback(async () => {
    const supabase = createClient();
    const { data, error } = await supabase.from("jornada_mensagem").select(COLUNAS).eq("card_id", cardId).gt("id", ultimo.current).order("id").limit(200);
    if (error || !data) return;
    const novas = data as MensagemJornada[];
    if (novas.length === 0) return;
    ultimo.current = novas[novas.length - 1].id;
    setMensagens((atual) => {
      const ids = new Set((atual ?? []).map((m) => m.id));
      return [...(atual ?? []), ...novas.filter((m) => !ids.has(m.id))];
    });
  }, [cardId]);

  useEffect(() => {
    let ativo = true;
    ultimo.current = 0;
    setMensagens(null);
    setErro(null);
    setTexto("");
    const supabase = createClient();
    let canal: ReturnType<typeof supabase.channel> | null = null;
    void (async () => {
      await buscar();
      if (!ativo) return;
      setMensagens((m) => m ?? []);
      await supabase.realtime.setAuth();
      if (!ativo) return;
      canal = supabase
        .channel(`jornada:card:${cardId}`, { config: { private: true } })
        .on("broadcast", { event: "mensagem" }, () => void buscar())
        .subscribe();
    })();
    const reserva = setInterval(() => {
      if (document.visibilityState === "visible") void buscar();
    }, 15_000);
    return () => {
      ativo = false;
      clearInterval(reserva);
      if (canal) void supabase.removeChannel(canal);
    };
  }, [cardId, buscar]);

  useEffect(() => {
    fim.current?.scrollIntoView({ block: "end" });
  }, [mensagens?.length]);

  const enviar = async () => {
    const t = texto.trim();
    if (!t || enviando) return;
    setEnviando(true);
    setErro(null);
    const { error } = await createClient().rpc("jornada_enviar_mensagem", { p_card: cardId, p_texto: t });
    setEnviando(false);
    if (error) {
      setErro(error.message || "Não foi possível enviar.");
      return;
    }
    setTexto("");
    await buscar();
  };

  return (
    <section className="jornada-chat" aria-label="Conversa da equipe">
      <h3>Conversa da equipe</h3>
      <p className="jornada-chat-aviso">Só a equipe vê esta conversa. Não escreva diagnóstico nem resultado de exame.</p>
      <div className="jornada-chat-lista" role="log" aria-live="polite">
        {mensagens === null ? (
          <p className="panel-sub">Carregando…</p>
        ) : mensagens.length === 0 ? (
          <p className="panel-sub">Ninguém escreveu ainda.</p>
        ) : (
          mensagens.map((m) => (
            <div key={m.id} className="jornada-msg" data-minha={m.autor === usuarioId ? "true" : undefined}>
              <span className="jornada-msg-topo">
                <strong>{m.autor === usuarioId ? "Você" : (m.autor_nome ?? "Equipe")}</strong>
                <time dateTime={m.criado_em}>
                  {new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(m.criado_em))}
                </time>
              </span>
              <span className="jornada-msg-texto">{m.texto}</span>
            </div>
          ))
        )}
        <div ref={fim} />
      </div>
      <form
        className="jornada-chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void enviar();
        }}
      >
        <textarea
          className="input"
          rows={2}
          maxLength={2000}
          placeholder="Escreva para a equipe (Enter envia, Shift+Enter pula linha)"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void enviar();
            }
          }}
          aria-label="Mensagem"
        />
        <button type="submit" className="btn btn-primary" disabled={enviando || texto.trim().length === 0}>
          {enviando ? "Enviando" : "Enviar"}
        </button>
      </form>
      {erro && (
        <p className="jornada-erro" role="alert">
          {erro}
        </p>
      )}
    </section>
  );
}
