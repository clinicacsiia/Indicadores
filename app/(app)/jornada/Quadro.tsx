"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  agruparExames,
  diaCurto,
  filtrarCards,
  FILTROS_PADRAO,
  horaCurta,
  linkWhatsApp,
  PERIODOS,
  ROTULO_STATUS_EXAME,
  tempoNaColuna,
  type CardJornada,
  type DadosQuadro,
  type ExameJornada,
  type Filtros,
  type Periodo,
} from "@/lib/jornada";
import { horaBrasilia } from "@/lib/coleta-ritmo";

const POR_COLUNA = 40; // cartões desenhados por coluna antes de "mostrar mais"

type EventoCard = { quando: string; tipo: string; origem: string; de_coluna: string | null; para_coluna: string | null; detalhe: Record<string, unknown> };

export function Quadro({ dados }: { dados: DadosQuadro }) {
  const [f, setF] = useState<Filtros>(FILTROS_PADRAO);
  const [aberto, setAberto] = useState<number | null>(null);
  const [limites, setLimites] = useState<Record<string, number>>({});

  const examesPorCard = useMemo(() => agruparExames(dados.exames), [dados.exames]);
  const nomeColuna = useMemo(() => new Map(dados.colunas.map((c) => [c.id, c.nome])), [dados.colunas]);

  const unidades = useMemo(() => [...new Set(dados.cards.map((c) => c.unidade).filter(Boolean))].sort(), [dados.cards]);
  const operadoras = useMemo(() => [...new Set(dados.exames.map((e) => e.operadora).filter((o): o is string => !!o))].sort((a, b) => a.localeCompare(b, "pt-BR")), [dados.exames]);

  const filtrados = useMemo(() => filtrarCards(dados.cards, examesPorCard, f, dados.hoje), [dados.cards, examesPorCard, f, dados.hoje]);
  const ocultos = useMemo(() => dados.cards.filter((c) => c.vazio).length, [dados.cards]);

  const porColuna = useMemo(() => {
    const mapa = new Map<string, CardJornada[]>();
    for (const c of filtrados) {
      const l = mapa.get(c.coluna);
      if (l) l.push(c);
      else mapa.set(c.coluna, [c]);
    }
    for (const l of mapa.values()) l.sort((a, b) => horaPrimeiro(a, examesPorCard).localeCompare(horaPrimeiro(b, examesPorCard)) || a.id - b.id);
    return mapa;
  }, [filtrados, examesPorCard]);

  const colunasVisiveis = dados.colunas.filter((c) => porColuna.has(c.id));
  const atrasados = filtrados.filter((c) => c.atrasado).length;
  const selecionado = aberto !== null ? (dados.cards.find((c) => c.id === aberto) ?? null) : null;

  useEffect(() => {
    if (aberto === null) return;
    const aoTeclar = (e: KeyboardEvent) => e.key === "Escape" && setAberto(null);
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aberto]);

  const mudar = <K extends keyof Filtros>(k: K, v: Filtros[K]) => setF((atual) => ({ ...atual, [k]: v }));
  const filtrosMudaram = JSON.stringify(f) !== JSON.stringify(FILTROS_PADRAO);

  return (
    <section className="jornada" aria-label="Quadro da Jornada do paciente">
      <div className="jornada-filtros panel">
        <div className="jornada-periodos" role="group" aria-label="Dia do atendimento">
          {PERIODOS.map((p) => (
            <button key={p.id} type="button" className="jornada-periodo" aria-pressed={f.periodo === p.id} onClick={() => mudar("periodo", p.id as Periodo)}>
              {p.rotulo}
            </button>
          ))}
        </div>
        <div className="jornada-campos">
          <label className="field">
            <span className="field-label">Buscar</span>
            <input className="input" type="search" placeholder="Nome, prontuário, exame ou nº da marcação" value={f.busca} onChange={(e) => mudar("busca", e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Unidade</span>
            <select className="select" value={f.unidade} onChange={(e) => mudar("unidade", e.target.value)}>
              <option value="">Todas</option>
              {unidades.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Convênio</span>
            <select className="select" value={f.operadora} onChange={(e) => mudar("operadora", e.target.value)}>
              <option value="">Todos</option>
              {operadoras.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="jornada-opcoes">
          <label className="switch">
            <input type="checkbox" checked={f.soAtrasados} onChange={(e) => mudar("soAtrasados", e.target.checked)} />
            <span className="switch-track" aria-hidden="true" />
            <span className="switch-text">Só atrasados</span>
          </label>
          <label className="switch">
            <input type="checkbox" checked={f.mostrarVazios} onChange={(e) => mudar("mostrarVazios", e.target.checked)} />
            <span className="switch-track" aria-hidden="true" />
            <span className="switch-text">Mostrar cartões sem nada a fazer ({ocultos})</span>
          </label>
          {filtrosMudaram && (
            <button type="button" className="btn" onClick={() => setF(FILTROS_PADRAO)}>
              Limpar filtros
            </button>
          )}
        </div>
        <p className="jornada-resumo" role="status">
          <strong>{filtrados.length}</strong> {filtrados.length === 1 ? "paciente" : "pacientes"}
          {atrasados > 0 && (
            <>
              {" · "}
              <span className="jornada-atraso-txt">{atrasados} atrasado{atrasados === 1 ? "" : "s"}</span>
            </>
          )}
          {dados.sync?.ultima_execucao && <> · cartões atualizados às {horaBrasilia(dados.sync.ultima_execucao)}</>}
        </p>
      </div>

      {colunasVisiveis.length === 0 ? (
        <div className="panel empty">
          <h2>Nenhum cartão para estes filtros</h2>
          <p>Mude o dia ou limpe os filtros. Cartões sem nada a fazer ficam ocultos por padrão.</p>
        </div>
      ) : (
        <div className="jornada-quadro">
          {colunasVisiveis.map((col) => {
            const lista = porColuna.get(col.id) ?? [];
            const limite = limites[col.id] ?? POR_COLUNA;
            return (
              <section key={col.id} className="jornada-coluna" data-etapa={col.etapa} aria-label={`${col.nome}: ${lista.length}`}>
                <header className="jornada-coluna-cabeca">
                  <h2>{col.nome}</h2>
                  <span className="jornada-coluna-n">{lista.length}</span>
                  <span className="jornada-coluna-origem" title={col.origem === "klingo" ? "Anda sozinha, pelo Klingo" : "Movida pela equipe"}>
                    {col.origem === "klingo" ? "Klingo" : "Equipe"}
                  </span>
                </header>
                <ul className="jornada-lista">
                  {lista.slice(0, limite).map((c) => (
                    <li key={c.id}>
                      <Cartao card={c} exames={examesPorCard.get(c.id) ?? []} mostrarDia={f.periodo !== "hoje" && f.periodo !== "amanha" && f.periodo !== "ontem"} aoAbrir={() => setAberto(c.id)} />
                    </li>
                  ))}
                </ul>
                {lista.length > limite && (
                  <button type="button" className="btn jornada-mais" onClick={() => setLimites((l) => ({ ...l, [col.id]: limite + POR_COLUNA }))}>
                    Mostrar mais ({lista.length - limite})
                  </button>
                )}
              </section>
            );
          })}
        </div>
      )}

      {selecionado && <Detalhe card={selecionado} exames={examesPorCard.get(selecionado.id) ?? []} nomeColuna={nomeColuna} aoFechar={() => setAberto(null)} />}
    </section>
  );
}

function horaPrimeiro(c: CardJornada, mapa: Map<number, ExameJornada[]>): string {
  return c.data_ref + (mapa.get(c.id)?.[0]?.agendado_para ?? "z");
}

function Cartao({ card, exames, mostrarDia, aoAbrir }: { card: CardJornada; exames: ExameJornada[]; mostrarDia: boolean; aoAbrir: () => void }) {
  const ativos = exames.filter((e) => e.status !== "cancelado" && e.status !== "remarcado");
  const mostrados = (ativos.length > 0 ? ativos : exames).slice(0, 2);
  const resto = (ativos.length > 0 ? ativos : exames).length - mostrados.length;
  const hora = horaCurta(exames[0]?.agendado_para ?? null);
  return (
    <button type="button" className="jornada-cartao" data-atrasado={card.atrasado ? "true" : undefined} data-vazio={card.vazio ? "true" : undefined} onClick={aoAbrir}>
      <span className="jornada-cartao-topo">
        <strong className="jornada-cartao-nome">{card.paciente_nome ?? `Prontuário ${card.paciente_chave}`}</strong>
        <span className="jornada-cartao-hora">{mostrarDia ? `${diaCurto(card.data_ref)} ${hora}` : hora}</span>
      </span>
      <span className="jornada-cartao-exames">
        {mostrados.map((e) => (
          <span key={e.marcacao_id} className="jornada-chip" data-status={e.status} title={`${e.procedimento} — ${ROTULO_STATUS_EXAME[e.status]}`}>
            {e.procedimento}
          </span>
        ))}
        {resto > 0 && <span className="jornada-chip jornada-chip-mais">+{resto}</span>}
      </span>
      <span className="jornada-cartao-base">
        <span className="jornada-unidade">{card.unidade || "—"}</span>
        {card.n_mensagens > 0 && <span title="Mensagens da equipe">💬 {card.n_mensagens}</span>}
        <span className="jornada-tempo" data-atrasado={card.atrasado ? "true" : undefined} title="Tempo nesta coluna">
          {card.atrasado ? "⏱ " : ""}
          {tempoNaColuna(card.minutos_na_coluna)}
        </span>
      </span>
    </button>
  );
}

function Detalhe({ card, exames, nomeColuna, aoFechar }: { card: CardJornada; exames: ExameJornada[]; nomeColuna: Map<string, string>; aoFechar: () => void }) {
  const [contato, setContato] = useState<{ celular: string | null; telefone: string | null } | null>(null);
  const [historico, setHistorico] = useState<EventoCard[] | null>(null);

  useEffect(() => {
    let vivo = true;
    setContato(null);
    setHistorico(null);
    const supabase = createClient();
    // quem abriu o cartão fica registrado (LGPD); falhar aqui não impede de ver
    void supabase.rpc("jornada_registrar_acesso", { p_card: card.id });
    void supabase
      .from("jornada_paciente")
      .select("celular, telefone")
      .eq("prontuario", card.paciente_chave)
      .maybeSingle()
      .then(({ data }) => vivo && setContato((data as { celular: string | null; telefone: string | null } | null) ?? { celular: null, telefone: null }));
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
      return `${quem}: responsável alterado.`;
    default:
      return `${quem}: ${h.tipo}.`;
  }
}
