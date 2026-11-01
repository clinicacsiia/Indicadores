"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { rotuloVencimento, type TarefaJornada } from "@/lib/jornada";

// Tarefas e checklist do cartão. As automáticas (checklist da coluna, confirmar presença, nova data) nascem sozinhas; a equipe marca como feita ou cria as suas.
// `versaoTarefas` muda quando o quadro percebe uma tarefa nova ou feita (o aviso do tempo real traz o cartão de novo), e a lista é relida.
export function Tarefas({ cardId, versaoTarefas }: { cardId: number; versaoTarefas: string }) {
  const [tarefas, setTarefas] = useState<TarefaJornada[] | null>(null);
  const [novo, setNovo] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const ler = useCallback(async () => {
    const { data, error } = await createClient()
      .from("jornada_tarefa")
      .select("id, card_id, titulo, origem, vence_em, feita_em")
      .eq("card_id", cardId)
      .order("feita_em", { ascending: false, nullsFirst: true })
      .order("vence_em", { ascending: true, nullsFirst: false })
      .order("id")
      .limit(100);
    if (!error) setTarefas((data ?? []) as TarefaJornada[]);
  }, [cardId]);

  useEffect(() => {
    setTarefas(null);
    setErro(null);
    void ler();
  }, [ler, versaoTarefas]);

  const marcar = async (t: TarefaJornada, feita: boolean) => {
    setErro(null);
    const antes = tarefas;
    setTarefas((atual) => (atual ?? []).map((x) => (x.id === t.id ? { ...x, feita_em: feita ? new Date().toISOString() : null } : x)));
    const { error } = await createClient().rpc("jornada_marcar_tarefa", { p_tarefa: t.id, p_feita: feita });
    if (error) {
      setTarefas(antes);
      setErro(error.message || "Não foi possível atualizar a tarefa.");
    }
  };

  const criar = async () => {
    const titulo = novo.trim();
    if (titulo.length < 3 || enviando) return;
    setEnviando(true);
    setErro(null);
    const { error } = await createClient().rpc("jornada_criar_tarefa", { p_card: cardId, p_titulo: titulo });
    setEnviando(false);
    if (error) {
      setErro(error.message || "Não foi possível criar a tarefa.");
      return;
    }
    setNovo("");
    await ler();
  };

  const abertas = (tarefas ?? []).filter((t) => !t.feita_em).length;

  return (
    <section className="jornada-tarefas" aria-label="Tarefas do cartão">
      <h3>
        Tarefas {tarefas !== null && <small className="jornada-sub">({abertas} {abertas === 1 ? "aberta" : "abertas"})</small>}
      </h3>
      {tarefas === null ? (
        <p className="panel-sub">Carregando…</p>
      ) : tarefas.length === 0 ? (
        <p className="panel-sub">Nenhuma tarefa. As tarefas automáticas aparecem aqui sozinhas.</p>
      ) : (
        <ul className="jornada-tarefas-lista">
          {tarefas.map((t) => {
            const v = t.feita_em ? { texto: "", vencida: false } : rotuloVencimento(t.vence_em);
            return (
              <li key={t.id} data-feita={t.feita_em ? "true" : undefined} data-vencida={v.vencida ? "true" : undefined}>
                <label className="jornada-tarefa">
                  <input type="checkbox" checked={!!t.feita_em} onChange={(e) => void marcar(t, e.target.checked)} />
                  <span className="jornada-tarefa-titulo">{t.titulo}</span>
                  {t.origem === "sistema" && <span className="jornada-tarefa-auto" title="Criada sozinha pelo sistema">auto</span>}
                  {v.texto && <span className="jornada-tarefa-vence">{v.texto}</span>}
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <form
        className="jornada-chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          void criar();
        }}
      >
        <input className="input" type="text" maxLength={200} placeholder="Nova tarefa para este cartão" value={novo} onChange={(e) => setNovo(e.target.value)} aria-label="Nova tarefa" />
        <button type="submit" className="btn" disabled={enviando || novo.trim().length < 3}>
          Adicionar
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
