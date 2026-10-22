// Aba "Meu dia": o que a pessoa de atendimento tem para fazer agora, em ordem de urgência.
// Cada item traz como achar o paciente e os botões que resolvem sem abrir formulário.
import { DIAS_PARADO, codigoContato, type Fila } from "@/lib/crm-rm";
import { BotaoRespondi, BotaoVagaRecuperada, BotoesAdiar, BotoesConfirmacao, BotoesResultado } from "./AcoesRapidas";
import { EditarContatoForm } from "./ContatoForm";
import { EditarHorarioForm } from "./HorarioForm";
import { Identificacao, Nota, Painel, ResumoContato, ResumoHorario, Vazio, dataBR } from "./comuns";

export function SecaoMeuDia({ fila, hoje, verValores }: { fila: Fila; hoje: string; verValores: boolean }) {
  const nada =
    !fila.retornos.length && !fila.semPrimeiraResposta.length && !fila.confirmar.length && !fila.semResultado.length && !fila.vagasAbertas.length && !fila.parados.length;

  return (
    <>
      {nada && (
        <section className="panel empty">
          <h2>Nada pendente agora</h2>
          <p>Quando houver retorno marcado, confirmação para fazer ou exame sem resultado, aparece aqui.</p>
        </section>
      )}

      <Painel
        id="t-responder"
        titulo="Responder primeiro"
        contador={fila.semPrimeiraResposta.length}
        sub="Contatos abertos que ainda não receberam a primeira resposta. É a perda mais fácil de evitar."
      >
        {fila.semPrimeiraResposta.length === 0 ? (
          <Vazio>Todo mundo já foi respondido.</Vazio>
        ) : (
          <ul className="crm-lista">
            {fila.semPrimeiraResposta.slice(0, 15).map((c) => (
              <li key={c.id} className="crm-item">
                <ResumoContato c={c} verValores={verValores} />
                <Identificacao c={c} />
                <BotaoRespondi id={c.id} />
              </li>
            ))}
          </ul>
        )}
      </Painel>

      <Painel id="t-retornos" titulo="Retornos de hoje e atrasados" contador={fila.retornos.length} sub="Você marcou de falar com estas pessoas até hoje.">
        {fila.retornos.length === 0 ? (
          <Vazio>Nenhum retorno vencido.</Vazio>
        ) : (
          <ul className="crm-lista">
            {fila.retornos.slice(0, 20).map((c) => (
              <li key={c.id} className="crm-item">
                <ResumoContato c={c} verValores={verValores} />
                <Identificacao c={c} />
                <p className="crm-item-meta">
                  {c.data_retorno && c.data_retorno < hoje ? "Atrasado desde" : "Marcado para"} {dataBR(c.data_retorno as string)}
                  {c.proxima_acao && c.proxima_acao !== "Sem ação" ? ` · ${c.proxima_acao}` : ""}
                  {c.responsavel ? ` · ${c.responsavel}` : ""}
                </p>
                {c.observacoes && <p className="crm-item-texto">{c.observacoes}</p>}
                <BotoesAdiar id={c.id} />
                <details className="crm-detalhes">
                  <summary>Atualizar situação</summary>
                  <EditarContatoForm contato={c} />
                </details>
              </li>
            ))}
          </ul>
        )}
      </Painel>

      <Painel
        id="t-confirmar"
        titulo="Confirmar os próximos exames"
        contador={fila.confirmar.length}
        sub="Exames de hoje até depois de amanhã que ainda não confirmaram. Quem não confirma falta muito mais."
      >
        {fila.confirmar.length === 0 ? (
          <Vazio>Tudo confirmado.</Vazio>
        ) : (
          <ul className="crm-lista">
            {fila.confirmar.slice(0, 20).map((h) => (
              <li key={h.id} className="crm-item">
                <ResumoHorario h={h} verValores={verValores} />
                <p className="crm-item-meta">Confirmação: {h.confirmacao}</p>
                <BotoesConfirmacao id={h.id} />
              </li>
            ))}
          </ul>
        )}
      </Painel>

      <Painel
        id="t-resultado"
        titulo="Exames sem resultado"
        contador={fila.semResultado.length}
        sub="A data já passou e ninguém disse se o exame foi feito. Sem isso o absenteísmo fica errado."
      >
        {fila.semResultado.length === 0 ? (
          <Vazio>Nenhum exame pendente de resultado.</Vazio>
        ) : (
          <ul className="crm-lista">
            {fila.semResultado.slice(0, 20).map((h) => (
              <li key={h.id} className="crm-item">
                <ResumoHorario h={h} verValores={verValores} />
                <BotoesResultado id={h.id} />
                <details className="crm-detalhes">
                  <summary>Cancelou ou remarcou</summary>
                  <EditarHorarioForm horario={h} />
                </details>
              </li>
            ))}
          </ul>
        )}
      </Painel>

      <Painel
        id="t-vagas"
        titulo="Vagas que abriram"
        contador={fila.vagasAbertas.length}
        sub="Faltas e cancelamentos dos últimos 14 dias que ninguém ocupou. Abaixo, quem está esperando vaga."
      >
        {fila.vagasAbertas.length === 0 ? (
          <Vazio>Nenhuma vaga aberta sem destino.</Vazio>
        ) : (
          <ul className="crm-lista">
            {fila.vagasAbertas.slice(0, 15).map((h) => (
              <li key={h.id} className="crm-item">
                <ResumoHorario h={h} verValores={verValores} />
                <p className="crm-item-meta">{h.motivo_falta ? `Motivo: ${h.motivo_falta}` : "Sem motivo registrado"}</p>
                <BotaoVagaRecuperada id={h.id} />
              </li>
            ))}
          </ul>
        )}
        {fila.esperandoVaga.length > 0 && (
          <>
            <Nota>
              Esperando vaga (perderam por falta de horário ou estão com “Verificar vaga”): chame estas pessoas quando abrir um horário do mesmo
              exame.
            </Nota>
            <ul className="crm-lista">
              {fila.esperandoVaga.slice(0, 10).map((c) => (
                <li key={c.id} className="crm-item">
                  <div className="crm-item-topo">
                    <strong>{codigoContato(c.id)}</strong>
                    <span className="crm-item-meta">
                      {c.exame} · {c.convenio ?? c.forma_pagamento} · pediu em {dataBR(c.data_contato)}
                    </span>
                  </div>
                  <Identificacao c={c} />
                </li>
              ))}
            </ul>
          </>
        )}
      </Painel>

      <Painel
        id="t-parados"
        titulo="Parados sem data de retorno"
        contador={fila.parados.length}
        sub={`Contatos abertos sem nenhuma conversa há mais de ${DIAS_PARADO} dias e sem retorno marcado.`}
      >
        {fila.parados.length === 0 ? (
          <Vazio>Nenhum contato esquecido.</Vazio>
        ) : (
          <ul className="crm-lista">
            {fila.parados.slice(0, 15).map((c) => (
              <li key={c.id} className="crm-item">
                <ResumoContato c={c} verValores={verValores} />
                <Identificacao c={c} />
                <p className="crm-item-meta">Última conversa em {dataBR(c.data_ultimo_contato ?? c.data_contato)}</p>
                <BotoesAdiar id={c.id} />
                <details className="crm-detalhes">
                  <summary>Atualizar situação</summary>
                  <EditarContatoForm contato={c} />
                </details>
              </li>
            ))}
          </ul>
        )}
      </Painel>
    </>
  );
}
