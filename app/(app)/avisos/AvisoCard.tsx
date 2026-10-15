import {
  ROTULO_EVENTO,
  ROTULO_NIVEL,
  dataCurta,
  dataDia,
  dataHora,
  emInformacao,
  nomeDoUsuario,
  rotuloEscopo,
  urlKlingoValida,
  voltou,
  type Aviso,
  type EventoAviso,
} from "@/lib/avisos";
import { FecharAviso, ReabrirAviso } from "./AvisoAcoes";

function Historico({ eventos }: { eventos: EventoAviso[] }) {
  if (!eventos.length) return null;
  return (
    <details className="aviso-bloco">
      <summary>Histórico ({eventos.length})</summary>
      <ol className="aviso-historico">
        {eventos.map((e) => (
          <li key={e.id} data-tipo={e.tipo}>
            <span className="aviso-historico-quando">{dataHora(e.quando)}</span>
            <span className="aviso-historico-tipo">{ROTULO_EVENTO[e.tipo] ?? e.tipo}</span>
            {e.usuario && <span className="aviso-historico-quem"> · {nomeDoUsuario(e.usuario)}</span>}
            {e.detalhe && <p>{e.detalhe}</p>}
          </li>
        ))}
      </ol>
    </details>
  );
}

function Guia({ aviso }: { aviso: Aviso }) {
  const { guia, itens } = aviso;
  const relatorios = (guia.relatorios ?? []).filter((r) => urlKlingoValida(r.url));
  const passos = guia.passos ?? [];
  if (!relatorios.length && !passos.length && !itens?.linhas?.length && !guia.dica && !guia.atualizacao) return null;
  const numericas = new Set(itens?.numericas ?? []);
  return (
    <details className="aviso-bloco">
      <summary>Como achar e resolver</summary>
      <div className="aviso-guia">
        {relatorios.length > 0 && (
          <div className="aviso-links">
            {relatorios.map((r) => (
              <a key={r.id} className="btn" href={r.url} target="_blank" rel="noopener noreferrer">
                Abrir no Klingo: {r.nome} ↗
              </a>
            ))}
          </div>
        )}
        {passos.length > 0 && (
          <>
            <h4>Passo a passo</h4>
            <ol>
              {passos.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          </>
        )}
        {guia.dica && (
          <p className="aviso-dica">
            <b>Dica:</b> {guia.dica}
          </p>
        )}
        {guia.atualizacao && (
          <p className="aviso-dica" data-tom="ok">
            <b>Painel atualizado em {dataDia(guia.atualizacao.em)}:</b> {guia.atualizacao.texto}
          </p>
        )}
        {itens && itens.linhas.length > 0 && (
          <>
            <h4>
              Quais são{" "}
              <span className="aviso-conta">
                {itens.linhas.length < itens.total
                  ? `Mostrando ${itens.linhas.length} de ${itens.total}; o resto está no relatório.`
                  : `${itens.total} no total.`}
              </span>
            </h4>
            <div className="table-wrap aviso-tabela">
              <table className="table">
                <thead>
                  <tr>
                    {itens.colunas.map((c, i) => (
                      <th key={i} className={numericas.has(i) ? "num" : undefined}>
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {itens.linhas.map((l, i) => (
                    <tr key={i}>
                      {l.map((v, j) => (
                        <td key={j} className={numericas.has(j) ? "num" : undefined}>
                          {v}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {guia.resolve && (
          <p className="aviso-resolve">
            <b>Quando o painel considera resolvido:</b> {guia.resolve}
          </p>
        )}
      </div>
    </details>
  );
}

export function AvisoCard({ aviso, eventos }: { aviso: Aviso; eventos: EventoAviso[] }) {
  const reincidente = voltou(aviso);
  const informacao = emInformacao(aviso);
  return (
    <article id={`aviso-${aviso.id}`} className="panel aviso" data-nivel={aviso.nivel} data-status={aviso.status}>
      <header className="aviso-topo">
        <div className="aviso-marcas">
          <span className="aviso-nivel" data-nivel={informacao ? "info" : aviso.nivel} title={informacao ? "Fechado com justificativa: fica como informação" : undefined}>
            {informacao ? ROTULO_NIVEL.info : ROTULO_NIVEL[aviso.nivel]}
          </span>
          <span className="aviso-escopo">{rotuloEscopo(aviso.escopo)}</span>
          {aviso.recorrencias > 0 && (
            <span className="aviso-selo" data-tom="alerta" title="Foi resolvido e voltou a aparecer nos dados">
              Voltou a acontecer {aviso.recorrencias}×
            </span>
          )}
          {aviso.reaberturas > 0 && (
            <span
              className="aviso-selo"
              data-tom="alerta"
              title="Contado quando foi fechado com justificativa e alguém disse “Ainda não resolvi” ou “Não explica”, a data prevista passou, ou o problema continuou ou piorou"
            >
              Reaberto {aviso.reaberturas}×
            </span>
          )}
          {aviso.retornos_informados > 0 && (
            <span className="aviso-selo" title="Voltou a aparecer depois de resolvido e foi mantido como informação por já ter justificativa (não conta como recorrência)">
              Voltou {aviso.retornos_informados}× como informação
            </span>
          )}
          {aviso.persistente && (
            <span className="aviso-selo" title="Pode ser aceito com justificativa: só reabre se piorar">
              Pode ser aceito
            </span>
          )}
        </div>
        <h3 className="aviso-titulo">{aviso.titulo}</h3>
        {aviso.texto && <p className="aviso-texto">{aviso.texto}</p>}
        <p className="aviso-meta">
          Detectado em {dataCurta(aviso.primeira_deteccao)} · visto nos dados em {dataHora(aviso.ultima_deteccao)}
          {aviso.itens_total != null && ` · ${aviso.itens_total} ${aviso.itens_total === 1 ? "registro" : "registros"}`}
        </p>
      </header>

      {aviso.status === "justificado" && (
        <div className="aviso-nota" data-tom="ok">
          <p>
            <b>
              Informação de {nomeDoUsuario(aviso.justificado_por)} em {dataHora(aviso.justificado_em)}.
            </b>{" "}
            <span className="aviso-justificativa">“{aviso.justificativa}”</span>
          </p>
          {aviso.previsto_para && (
            <p>
              <b>Previsão informada: {dataDia(aviso.previsto_para)}.</b>
            </p>
          )}
          <p className="aviso-nota-fim">
            {aviso.previsto_para
              ? "Até essa data o aviso fica como informação, mesmo com os dados atualizados; se o problema continuar depois dela, reabre e conta como recorrência. Reabre antes se piorar."
              : aviso.em_informacao
                ? "Voltou a aparecer e foi mantido como informação por já ter justificativa. Reabre se piorar, ou se você disser que ainda não resolveu ou que a justificativa não explica."
                : aviso.persistente
                  ? "Continua como informação enquanto o painel mostrar o mesmo problema; reabre se ele piorar."
                  : "O painel confere na próxima atualização dos dados: se o problema sumiu, fica resolvido; se continuar, o aviso reabre."}
          </p>
          <ReabrirAviso id={aviso.id} />
        </div>
      )}

      {aviso.status === "resolvido" && (
        <div className="aviso-nota" data-tom="ok">
          <p>
            <b>Resolvido: não aparece mais nos dados</b>
            {aviso.resolvido_em && ` (desde ${dataHora(aviso.resolvido_em)})`}. O painel segue conferindo e avisa se ele voltar.
          </p>
          {aviso.justificativa && (
            <p className="aviso-justificativa">
              Última justificativa, de {nomeDoUsuario(aviso.justificado_por)}: “{aviso.justificativa}”
            </p>
          )}
        </div>
      )}

      {reincidente && aviso.justificativa && (
        <div className="aviso-nota" data-tom="alerta">
          <p>
            <b>Já foi explicado antes</b>, por {nomeDoUsuario(aviso.justificado_por)} em {dataHora(aviso.justificado_em)}:{" "}
            <span className="aviso-justificativa">“{aviso.justificativa}”</span>
          </p>
        </div>
      )}

      <Guia aviso={aviso} />
      {aviso.status === "aberto" && <FecharAviso id={aviso.id} persistente={aviso.persistente} />}
      <Historico eventos={eventos} />
    </article>
  );
}
