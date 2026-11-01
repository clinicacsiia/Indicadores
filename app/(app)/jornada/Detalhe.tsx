"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  diaCurto,
  horaCurta,
  linkWhatsApp,
  ROTULO_STATUS_EXAME,
  tempoNaColuna,
  type CardJornada,
  type ColunaJornada,
  type ExameJornada,
  type MembroEquipe,
} from "@/lib/jornada";
import { Chat } from "./Chat";
import { Tarefas } from "./Tarefas";

type EventoCard = { quando: string; tipo: string; origem: string; de_coluna: string | null; para_coluna: string | null; detalhe: Record<string, unknown> };

export function Detalhe({
  card,
  exames,
  nomeColuna,
  destinos,
  equipe,
  usuarioId,
  aoMover,
  aoAtribuir,
  aoFechar,
}: {
  card: CardJornada;
  exames: ExameJornada[];
  nomeColuna: Map<string, string>;
  destinos: ColunaJornada[];
  equipe: MembroEquipe[];
  usuarioId: string;
  aoMover: (para: string) => void;
  aoAtribuir: (quem: string | null) => void;
  aoFechar: () => void;
}) {
  const [contato, setContato] = useState<{ celular: string | null; telefone: string | null } | null>(null);
  const [historico, setHistorico] = useState<EventoCard[] | null>(null);

  // o histórico se refaz quando o cartão muda de coluna (a equipe, o Klingo ou o sistema)
  useEffect(() => {
    let vivo = true;
    const supabase = createClient();
    void supabase
      .from("jornada_evento")
      .select("quando, tipo, origem, de_coluna, para_coluna, detalhe")
      .eq("card_id", card.id)
      .order("quando", { ascending: false })
      .limit(30)
      .then(({ data }) => vivo && setHistorico((data as EventoCard[] | null) ?? []));
    return () => {
      vivo = false;
    };
  }, [card.id, card.coluna, card.versao]);

  useEffect(() => {
    let vivo = true;
    setContato(null);
    const supabase = createClient();
    // quem abriu o cartão fica registrado (LGPD); falhar aqui não impede de ver
    void supabase.rpc("jornada_registrar_acesso", { p_card: card.id });
    void supabase
      .from("jornada_paciente")
      .select("celular, telefone")
      .eq("prontuario", card.paciente_chave)
      .maybeSingle()
      .then(({ data }) => vivo && setContato((data as { celular: string | null; telefone: string | null } | null) ?? { celular: null, telefone: null }));
    return () => {
      vivo = false;
    };
  }, [card.id, card.paciente_chave]);

  const wa = linkWhatsApp(contato?.celular ?? null);

  return (
    <>
      <div className="jornada-fundo" onClick={aoFechar} aria-hidden="true" />
      <aside className="jornada-detalhe" role="dialog" aria-modal="true" aria-label={`Detalhes de ${card.paciente_nome ?? card.paciente_chave}`}>
        <header className="jornada-detalhe-cabeca">
          <div>
            <h2>{card.paciente_nome ?? `Prontuário ${card.paciente_chave}`}</h2>
            <p>
              Prontuário {card.paciente_chave} · {card.unidade || "sem unidade"} · {diaCurto(card.data_ref)}
            </p>
          </div>
          <button type="button" className="icon-btn" onClick={aoFechar} aria-label="Fechar">
            ✕
          </button>
        </header>

        <p className="jornada-detalhe-coluna">
          Coluna: <strong>{card.coluna_nome}</strong> ({card.origem === "klingo" ? "anda sozinha, pelo Klingo" : "movida pela equipe"}) · há {tempoNaColuna(card.minutos_na_coluna)}
          {card.atrasado && <span className="jornada-atraso-txt"> · atrasado</span>}
        </p>

        <section className="jornada-acoes" aria-label="Ações do cartão">
          <div className="jornada-acao">
            <span className="field-label">Mover para</span>
            {destinos.length > 0 ? (
              <div className="jornada-botoes">
                {destinos.map((d) => (
                  <button key={d.id} type="button" className="btn" onClick={() => aoMover(d.id)}>
                    {d.nome}
                  </button>
                ))}
              </div>
            ) : (
              <p className="panel-sub">{card.origem === "klingo" ? "Esta coluna anda sozinha, pelo Klingo." : "Não há para onde mover daqui."}</p>
            )}
          </div>
          <label className="jornada-acao">
            <span className="field-label">Responsável</span>
            <span className="jornada-responsavel">
              <select className="select" value={card.responsavel ?? ""} onChange={(e) => aoAtribuir(e.target.value || null)}>
                <option value="">Sem responsável</option>
                {equipe.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nome}
                    {m.id === usuarioId ? " (você)" : ""}
                  </option>
                ))}
              </select>
              {card.responsavel !== usuarioId && equipe.some((m) => m.id === usuarioId) && (
                <button type="button" className="btn" onClick={() => aoAtribuir(usuarioId)}>
                  Ficar com este
                </button>
              )}
            </span>
          </label>
        </section>

        <section>
          <h3>Contato</h3>
          {contato === null ? (
            <p className="panel-sub">Carregando…</p>
          ) : (
            <p>
              {contato.celular || contato.telefone ? (
                <>
                  {[contato.celular, contato.telefone].filter(Boolean).join(" · ")}
                  {wa && (
                    <>
                      {" · "}
                      <a href={wa} target="_blank" rel="noopener noreferrer">
                        Abrir no WhatsApp
                      </a>
                    </>
                  )}
                </>
              ) : (
                "Sem telefone no Klingo."
              )}
            </p>
          )}
        </section>

        <section>
          <h3>Exames ({exames.length})</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Hora</th>
                  <th>Exame</th>
                  <th>Convênio</th>
                  <th>Situação</th>
                  <th>Confirmação</th>
                </tr>
              </thead>
              <tbody>
                {exames.map((e) => (
                  <tr key={e.marcacao_id}>
                    <td>{horaCurta(e.agendado_para)}</td>
                    <td>
                      {e.procedimento}
                      <small className="jornada-sub"> #{e.marcacao_id}</small>
                    </td>
                    <td>{e.operadora ?? "—"}</td>
                    <td>
                      <span className="jornada-chip" data-status={e.status}>
                        {ROTULO_STATUS_EXAME[e.status]}
                      </span>
                      {e.cancelamento_motivo && <small className="jornada-sub"> {e.cancelamento_motivo}</small>}
                    </td>
                    <td>{e.confirm_status ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <Tarefas cardId={card.id} versaoTarefas={`${card.n_tarefas_abertas}/${card.n_tarefas_vencidas}`} />

        <Chat cardId={card.id} usuarioId={usuarioId} />

        <section>
          <h3>Histórico</h3>
          {historico === null ? (
            <p className="panel-sub">Carregando…</p>
          ) : historico.length === 0 ? (
            <p className="panel-sub">Nada registrado ainda.</p>
          ) : (
            <ul className="jornada-historico">
              {historico.map((h, i) => (
                <li key={i}>
                  <time dateTime={h.quando}>
                    {new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(h.quando))}
                  </time>{" "}
                  {textoEvento(h, nomeColuna)}
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </>
  );
}

function textoEvento(h: EventoCard, nomeColuna: Map<string, string>): string {
  const de = h.de_coluna ? (nomeColuna.get(h.de_coluna) ?? h.de_coluna) : null;
  const para = h.para_coluna ? (nomeColuna.get(h.para_coluna) ?? h.para_coluna) : null;
  const quem = h.origem === "klingo" ? "Klingo" : h.origem === "sistema" ? "Sistema" : "Equipe";
  switch (h.tipo) {
    case "criado":
      return `${quem}: cartão criado em ${para ?? "—"}.`;
    case "movido":
      return `${quem}: ${de ?? "—"} → ${para ?? "—"}${typeof h.detalhe?.motivo === "string" ? ` (${h.detalhe.motivo})` : ""}${typeof h.detalhe?.nota === "string" ? ` — ${h.detalhe.nota}` : ""}.`;
    case "divergencia":
      return `${quem} indica "${para ?? "—"}", mas o cartão está em "${de ?? "—"}" e não foi puxado para trás.`;
    case "atribuido":
      return `${quem}: responsável alterado${typeof h.detalhe?.motivo === "string" ? ` (${h.detalhe.motivo})` : ""}.`;
    case "prioridade":
      return `${quem}: prioridade ${String(h.detalhe?.de ?? "?")} → ${String(h.detalhe?.para ?? "?")}${typeof h.detalhe?.motivo === "string" ? ` (${h.detalhe.motivo})` : ""}.`;
    case "tarefa":
      return `${quem}: tarefa ${h.detalhe?.acao === "feita" ? "feita" : h.detalhe?.acao === "reaberta" ? "reaberta" : "criada"}${typeof h.detalhe?.titulo === "string" ? ` — ${h.detalhe.titulo}` : ""}.`;
    default:
      return `${quem}: ${h.tipo}.`;
  }
}
