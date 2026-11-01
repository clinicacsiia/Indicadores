"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  agruparExames,
  cartaoMovido,
  compararCartoes,
  destinosPermitidos,
  diaCurto,
  erroDeMover,
  filtrarCards,
  FILTROS_PADRAO,
  horaCurta,
  iniciais,
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
import { Detalhe } from "./Detalhe";

const POR_COLUNA = 40; // cartões desenhados por coluna antes de "mostrar mais"
const ESPERA_AVISOS_MS = 800; // junta vários avisos do tempo real numa leitura só

export function Quadro({ dados }: { dados: DadosQuadro }) {
  const [f, setF] = useState<Filtros>(FILTROS_PADRAO);
  const [aberto, setAberto] = useState<number | null>(null);
  const [limites, setLimites] = useState<Record<string, number>>({});
  const [cards, setCards] = useState<CardJornada[]>(dados.cards);
  const [exames, setExames] = useState<ExameJornada[]>(dados.exames);
  const [arrastando, setArrastando] = useState<number | null>(null);
  const [alvoSobre, setAlvoSobre] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [tempoReal, setTempoReal] = useState(false);
  const [perdendo, setPerdendo] = useState<{ card: CardJornada; nota: string } | null>(null);

  // a tela do servidor se refaz sozinha a cada 30 s: o que ela traz vale como o estado novo
  useEffect(() => {
    setCards(dados.cards);
    setExames(dados.exames);
  }, [dados.cards, dados.exames]);

  const nomeEquipe = useMemo(() => new Map(dados.equipe.map((m) => [m.id, m.nome])), [dados.equipe]);
  const examesPorCard = useMemo(() => agruparExames(exames), [exames]);
  const nomeColuna = useMemo(() => new Map(dados.colunas.map((c) => [c.id, c.nome])), [dados.colunas]);
  const coluna = useCallback((id: string) => dados.colunas.find((c) => c.id === id), [dados.colunas]);

  const unidades = useMemo(() => [...new Set(cards.map((c) => c.unidade).filter(Boolean))].sort(), [cards]);
  const operadoras = useMemo(() => [...new Set(exames.map((e) => e.operadora).filter((o): o is string => !!o))].sort((a, b) => a.localeCompare(b, "pt-BR")), [exames]);

  const filtrados = useMemo(() => filtrarCards(cards, examesPorCard, f, dados.hoje, dados.usuarioId), [cards, examesPorCard, f, dados.hoje, dados.usuarioId]);
  const ocultos = useMemo(() => cards.filter((c) => c.vazio).length, [cards]);

  const porColuna = useMemo(() => {
    const mapa = new Map<string, CardJornada[]>();
    for (const c of filtrados) {
      const l = mapa.get(c.coluna);
      if (l) l.push(c);
      else mapa.set(c.coluna, [c]);
    }
    for (const l of mapa.values()) l.sort((a, b) => compararCartoes(a, b, horaPrimeiro(a, examesPorCard), horaPrimeiro(b, examesPorCard)));
    return mapa;
  }, [filtrados, examesPorCard]);

  // enquanto arrasta, as colunas de destino aparecem mesmo vazias
  const cardArrastado = arrastando !== null ? (cards.find((c) => c.id === arrastando) ?? null) : null;
  const destinosDoArrastado = useMemo(
    () => new Set(cardArrastado ? destinosPermitidos(cardArrastado.coluna, dados.transicoes, dados.colunas).map((c) => c.id) : []),
    [cardArrastado, dados.transicoes, dados.colunas],
  );
  const colunasVisiveis = dados.colunas.filter((c) => porColuna.has(c.id) || destinosDoArrastado.has(c.id));
  const atrasados = filtrados.filter((c) => c.atrasado).length;
  const selecionado = aberto !== null ? (cards.find((c) => c.id === aberto) ?? null) : null;

  // ------------------------------------------------------------ tempo real: relê só os cartões avisados
  const pendentes = useRef(new Set<number>());
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reler = useCallback(async () => {
    const ids = [...pendentes.current];
    pendentes.current.clear();
    if (ids.length === 0) return;
    const supabase = createClient();
    const [c, e] = await Promise.all([
      supabase.from("v_jornada_quadro").select("*").in("id", ids),
      supabase.from("jornada_exame").select("card_id, marcacao_id, atendimento_id, procedimento, operadora, agendado_para, status, confirm_status, cancelamento_motivo").in("card_id", ids),
    ]);
    if (c.error || e.error) return; // a tela do servidor ainda se refaz em até 30 s
    const novos = new Map((c.data as CardJornada[]).map((x) => [x.id, x]));
    const idsSet = new Set(ids);
    setCards((atual) => {
      const resto = atual.filter((x) => !idsSet.has(x.id));
      return [...resto, ...novos.values()].sort((a, b) => a.id - b.id);
    });
    setExames((atual) => [...atual.filter((x) => !idsSet.has(x.card_id)), ...(e.data as ExameJornada[])]);
  }, []);

  useEffect(() => {
    const supabase = createClient();
    let ativo = true;
    let canal: ReturnType<typeof supabase.channel> | null = null;
    void (async () => {
      await supabase.realtime.setAuth();
      if (!ativo) return;
      canal = supabase
        .channel("jornada:quadro", { config: { private: true } })
        .on("broadcast", { event: "card" }, ({ payload }) => {
          const id = Number((payload as { card_id?: number }).card_id);
          if (!Number.isFinite(id)) return;
          pendentes.current.add(id);
          if (temporizador.current) clearTimeout(temporizador.current);
          temporizador.current = setTimeout(() => void reler(), ESPERA_AVISOS_MS);
        })
        .subscribe((status) => ativo && setTempoReal(status === "SUBSCRIBED"));
    })();
    return () => {
      ativo = false;
      if (temporizador.current) clearTimeout(temporizador.current);
      if (canal) void supabase.removeChannel(canal);
    };
  }, [reler]);

  useEffect(() => {
    if (aberto === null) return;
    const aoTeclar = (e: KeyboardEvent) => e.key === "Escape" && setAberto(null);
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aberto]);

  // ------------------------------------------------------------ mover e atribuir
  const mover = useCallback(
    async (card: CardJornada, paraId: string, nota?: string) => {
      const destino = coluna(paraId);
      if (!destino || destino.id === card.coluna) return;
      if (paraId === "perdido" && !nota) {
        setPerdendo({ card, nota: "" });
        return;
      }
      setAviso(null);
      const antes = cards;
      setCards((atual) => atual.map((c) => (c.id === card.id ? cartaoMovido(c, destino) : c)));
      const { error } = await createClient().rpc("jornada_mover_card", { p_card: card.id, p_para: paraId, p_versao: card.versao, p_nota: nota ?? null });
      if (error) {
        const { texto, conflito } = erroDeMover(error.message);
        setCards(antes);
        setAviso(texto);
        if (conflito) {
          pendentes.current.add(card.id);
          void reler();
        }
      }
    },
    [cards, coluna, reler],
  );

  const atribuir = useCallback(
    async (card: CardJornada, responsavel: string | null) => {
      setAviso(null);
      const antes = cards;
      setCards((atual) => atual.map((c) => (c.id === card.id ? { ...c, responsavel, versao: c.versao + 1 } : c)));
      const { error } = await createClient().rpc("jornada_atribuir_card", { p_card: card.id, p_responsavel: responsavel, p_versao: card.versao });
      if (error) {
        const { texto, conflito } = erroDeMover(error.message);
        setCards(antes);
        setAviso(texto);
        if (conflito) {
          pendentes.current.add(card.id);
          void reler();
        }
      }
    },
    [cards, reler],
  );

  const soltar = (paraId: string) => {
    setAlvoSobre(null);
    const card = cardArrastado;
    setArrastando(null);
    if (card && destinosDoArrastado.has(paraId)) void mover(card, paraId);
  };

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
          <label className="field">
            <span className="field-label">Responsável</span>
            <select className="select" value={f.responsavel} onChange={(e) => mudar("responsavel", e.target.value)}>
              <option value="">Todos</option>
              <option value="meus">Só os meus</option>
              <option value="sem">Sem responsável</option>
              {dados.equipe.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="jornada-opcoes">
          <label className="switch">
            <input type="checkbox" checked={f.soComTarefa} onChange={(e) => mudar("soComTarefa", e.target.checked)} />
            <span className="switch-track" aria-hidden="true" />
            <span className="switch-text">Só com tarefa pendente</span>
          </label>
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
              <span className="jornada-atraso-txt">
                {atrasados} atrasado{atrasados === 1 ? "" : "s"}
              </span>
            </>
          )}
          {dados.sync?.ultima_execucao && <> · cartões do Klingo atualizados às {horaBrasilia(dados.sync.ultima_execucao)}</>}
          {" · "}
          <span className="jornada-tempo-real" data-ligado={tempoReal ? "true" : undefined} title={tempoReal ? "As mudanças da equipe aparecem na hora" : "Sem tempo real: a tela se atualiza a cada 30 s"}>
            {tempoReal ? "● tempo real" : "○ atualiza a cada 30 s"}
          </span>
        </p>
        {aviso && (
          <p className="jornada-erro" role="alert">
            {aviso}{" "}
            <button type="button" className="jornada-link" onClick={() => setAviso(null)}>
              Fechar
            </button>
          </p>
        )}
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
            const alvo = destinosDoArrastado.has(col.id);
            return (
              <section
                key={col.id}
                className="jornada-coluna"
                data-etapa={col.etapa}
                data-alvo={arrastando !== null ? (alvo ? (alvoSobre === col.id ? "sobre" : "sim") : "nao") : undefined}
                aria-label={`${col.nome}: ${lista.length}`}
                onDragOver={(e) => {
                  if (alvo) {
                    e.preventDefault();
                    setAlvoSobre(col.id);
                  }
                }}
                onDragLeave={() => setAlvoSobre((a) => (a === col.id ? null : a))}
                onDrop={(e) => {
                  e.preventDefault();
                  soltar(col.id);
                }}
              >
                <header className="jornada-coluna-cabeca">
                  <h2>{col.nome}</h2>
                  <span className="jornada-coluna-n">{lista.length}</span>
                  <span className="jornada-coluna-origem" title={col.origem === "klingo" ? "Anda sozinha, pelo Klingo" : "Movida pela equipe"}>
                    {col.origem === "klingo" ? "Klingo" : "Equipe"}
                  </span>
                </header>
                {lista.length === 0 && alvo && <p className="jornada-solte">Solte aqui</p>}
                <ul className="jornada-lista">
                  {lista.slice(0, limite).map((c) => (
                    <li key={c.id}>
                      <Cartao
                        card={c}
                        exames={examesPorCard.get(c.id) ?? []}
                        responsavel={c.responsavel ? (nomeEquipe.get(c.responsavel) ?? "?") : null}
                        mostrarDia={f.periodo !== "hoje" && f.periodo !== "amanha" && f.periodo !== "ontem"}
                        arrastavel={destinosPermitidos(c.coluna, dados.transicoes, dados.colunas).length > 0}
                        aoAbrir={() => setAberto(c.id)}
                        aoArrastar={(inicio) => setArrastando(inicio ? c.id : null)}
                      />
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

      {selecionado && (
        <Detalhe
          card={selecionado}
          exames={examesPorCard.get(selecionado.id) ?? []}
          nomeColuna={nomeColuna}
          destinos={destinosPermitidos(selecionado.coluna, dados.transicoes, dados.colunas)}
          equipe={dados.equipe}
          usuarioId={dados.usuarioId}
          aoMover={(para) => void mover(selecionado, para)}
          aoAtribuir={(quem) => void atribuir(selecionado, quem)}
          aoFechar={() => setAberto(null)}
        />
      )}

      {perdendo && (
        <div className="jornada-fundo" role="presentation">
          <form
            className="jornada-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Motivo de perder o contato"
            onSubmit={(e) => {
              e.preventDefault();
              const nota = perdendo.nota.trim();
              if (nota.length < 3) return;
              const card = perdendo.card;
              setPerdendo(null);
              void mover(card, "perdido", nota);
            }}
          >
            <h2>Por que o contato foi perdido?</h2>
            <p>{perdendo.card.paciente_nome ?? `Prontuário ${perdendo.card.paciente_chave}`}</p>
            <textarea
              className="input"
              rows={3}
              maxLength={500}
              autoFocus
              required
              minLength={3}
              placeholder="Ex.: achou caro, foi para outra clínica, não respondeu"
              value={perdendo.nota}
              onChange={(e) => setPerdendo({ ...perdendo, nota: e.target.value })}
            />
            <div className="jornada-modal-acoes">
              <button type="button" className="btn" onClick={() => setPerdendo(null)}>
                Cancelar
              </button>
              <button type="submit" className="btn btn-primary" disabled={perdendo.nota.trim().length < 3}>
                Marcar como perdido
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}

function horaPrimeiro(c: CardJornada, mapa: Map<number, ExameJornada[]>): string {
  return c.data_ref + (mapa.get(c.id)?.[0]?.agendado_para ?? "z");
}

function Cartao({
  card,
  exames,
  responsavel,
  mostrarDia,
  arrastavel,
  aoAbrir,
  aoArrastar,
}: {
  card: CardJornada;
  exames: ExameJornada[];
  responsavel: string | null;
  mostrarDia: boolean;
  arrastavel: boolean;
  aoAbrir: () => void;
  aoArrastar: (inicio: boolean) => void;
}) {
  const ativos = exames.filter((e) => e.status !== "cancelado" && e.status !== "remarcado");
  const lista = ativos.length > 0 ? ativos : exames;
  const mostrados = lista.slice(0, 2);
  const resto = lista.length - mostrados.length;
  const hora = horaCurta(exames[0]?.agendado_para ?? null);
  return (
    <button
      type="button"
      className="jornada-cartao"
      data-atrasado={card.atrasado ? "true" : undefined}
      data-vazio={card.vazio ? "true" : undefined}
      data-prioridade={card.prioridade >= 2 ? String(card.prioridade) : undefined}
      draggable={arrastavel}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(card.id));
        aoArrastar(true);
      }}
      onDragEnd={() => aoArrastar(false)}
      onClick={aoAbrir}
    >
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
        {responsavel && (
          <span className="jornada-resp" title={`Responsável: ${responsavel}`}>
            {iniciais(responsavel)}
          </span>
        )}
        {card.n_tarefas_abertas > 0 && (
          <span className="jornada-tarefas-n" data-vencida={card.n_tarefas_vencidas > 0 ? "true" : undefined} title={`${card.n_tarefas_abertas} tarefa(s) aberta(s)${card.n_tarefas_vencidas > 0 ? `, ${card.n_tarefas_vencidas} vencida(s)` : ""}`}>
            ☑ {card.n_tarefas_abertas}
          </span>
        )}
        {card.n_mensagens > 0 && <span title="Mensagens da equipe">💬 {card.n_mensagens}</span>}
        <span className="jornada-tempo" data-atrasado={card.atrasado ? "true" : undefined} title="Tempo nesta coluna">
          {card.atrasado ? "⏱ " : ""}
          {tempoNaColuna(card.minutos_na_coluna)}
        </span>
      </span>
    </button>
  );
}
