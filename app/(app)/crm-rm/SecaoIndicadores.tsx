// Aba "Indicadores": operação (funil, perdas, absenteísmo, sala) e marketing (onde investir).
import type { Indicadores, Marketing } from "@/lib/crm-rm";
import { Kpi, Nota, Painel, Tabela, Vazio, brl, horasTxt, num, pct } from "./comuns";

/** Leitura rápida do período: aponta onde está o volume, sem inventar a causa. */
function destaques(i: Indicadores, m: Marketing, cobertura: number | null): string[] {
  const t: string[] = [];
  if (cobertura !== null && cobertura < 70) {
    t.push(
      `O CRM registrou ${pct(cobertura)} dos exames de RM que o Klingo faturou no período. Enquanto a cobertura não subir, os números abaixo falam de uma parte da operação, não do todo.`,
    );
  }
  const topo = i.perdasPorMotivo[0];
  if (topo && i.perdidos >= 3) {
    t.push(
      `Maior motivo de perda: ${topo.motivo} (${topo.n} de ${i.perdidos}, ${pct(topo.pct)}). Gargalo ${
        topo.categoria === "Comercial" ? "comercial" : topo.categoria === "Agenda" ? "de agenda" : topo.categoria === "Convênio" ? "de convênio" : "a investigar"
      }.`,
    );
  }
  const canais = m.porCanal.filter((c) => c.solicitacoes >= 5);
  if (canais.length >= 2) {
    const pior = [...canais].sort((a, b) => (a.conversao ?? 0) - (b.conversao ?? 0))[0];
    const melhor = [...canais].sort((a, b) => (b.conversao ?? 0) - (a.conversao ?? 0))[0];
    t.push(`Melhor canal: ${melhor.canal} (${pct(melhor.conversao)} agendam). Pior: ${pior.canal} (${pct(pior.conversao)}).`);
  }
  const sem = i.faltasPorConfirmacao.filter((c) => c.confirmacao !== "Confirmou" && c.agendados >= 5);
  const conf = i.faltasPorConfirmacao.find((c) => c.confirmacao === "Confirmou");
  if (sem.length && conf && conf.taxa !== null) {
    const pior = [...sem].sort((a, b) => (b.taxa ?? 0) - (a.taxa ?? 0))[0];
    if ((pior.taxa ?? 0) > conf.taxa) {
      t.push(`Quem está “${pior.confirmacao}” falta ${pct(pior.taxa)} das vezes; quem confirmou, ${pct(conf.taxa)}. A confirmação ativa tem espaço.`);
    }
  }
  if (i.vagasElegiveis >= 3 && i.pctRecuperadas !== null) {
    t.push(`${i.vagasElegiveis - i.vagasRecuperadas} de ${i.vagasElegiveis} vagas de faltas e cancelamentos ficaram vazias (${pct(100 - i.pctRecuperadas)}).`);
  }
  if (m.respostaMediaHoras !== null && m.respostaMediaHoras > 2) {
    t.push(`A primeira resposta está levando ${num(m.respostaMediaHoras)} horas em média. “Demora na resposta” é motivo de perda registrado.`);
  }
  if (i.horasParadas > 0 && i.motivosOperacionais[0]) {
    t.push(`Equipamento com ${horasTxt(i.horasParadas)} parado ou em atraso; mais frequente: ${i.motivosOperacionais[0].motivo}.`);
  }
  return t;
}

export function SecaoIndicadores({
  ind,
  mkt,
  verValores,
  klingoRealizados,
  metaMes,
  rotuloPeriodo,
}: {
  ind: Indicadores;
  mkt: Marketing;
  verValores: boolean;
  klingoRealizados: number | null;
  metaMes: number | null;
  rotuloPeriodo: string;
}) {
  const cobertura = klingoRealizados && klingoRealizados > 0 ? (ind.realizados / klingoRealizados) * 100 : null;
  const avisos = destaques(ind, mkt, cobertura);

  return (
    <>
      {avisos.length > 0 && (
        <Painel id="t-destaques" titulo="O que olhar primeiro" sub={`Resumo automático de ${rotuloPeriodo}.`}>
          <ul className="crm-destaques">
            {avisos.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </Painel>
      )}

      <section aria-label="Resumo do período">
        <div className="kpis">
          <Kpi rotulo="Solicitações recebidas" valor={String(ind.solicitacoes)} meta={`${ind.emAberto} ainda em andamento`} cor="var(--s-realizados)" />
          <Kpi rotulo="Taxa de conversão" valor={pct(ind.conversao)} meta="Solicitações que viraram agendamento" cor="var(--s-realizados)" />
          <Kpi rotulo="Absenteísmo" valor={pct(ind.absenteismo)} meta={`${ind.faltas} faltas em ${ind.realizados + ind.faltas} horários com resultado`} cor="var(--s-agendados)" />
          <Kpi rotulo="Vagas recuperadas" valor={pct(ind.pctRecuperadas)} meta={`${ind.vagasRecuperadas} de ${ind.vagasElegiveis} faltas e cancelamentos`} />
          <Kpi
            rotulo="Cobertura do CRM"
            valor={cobertura === null ? "—" : pct(cobertura)}
            meta={
              klingoRealizados === null
                ? "Sem dado do Klingo no período"
                : `${ind.realizados} registrados aqui de ${klingoRealizados} que o Klingo faturou`
            }
            cor="var(--s-agendados)"
          />
          <Kpi
            rotulo="Tempo até a 1ª resposta"
            valor={mkt.respostaMediaHoras === null ? "—" : `${num(mkt.respostaMediaHoras)} h`}
            meta={mkt.semResposta > 0 ? `${mkt.semResposta} contatos sem resposta marcada` : "Todos têm resposta marcada"}
          />
          {verValores && <Kpi rotulo="Receita realizada" valor={brl(ind.receitaRealizada)} meta={`${ind.realizados} exames feitos`} cor="var(--s-realizados)" />}
          {verValores && <Kpi rotulo="Previsto nas faltas" valor={brl(ind.valorPrevistoFaltas)} meta="Potencial bruto, não perda contábil" cor="var(--s-agendados)" />}
          {verValores && <Kpi rotulo="Orçado e perdido" valor={brl(ind.valorPerdido)} meta={`${ind.perdidos} não agendaram ou desistiram`} cor="var(--s-agendados)" />}
          {verValores && <Kpi rotulo="Orçado em aberto" valor={brl(ind.valorEmAberto)} meta="Ainda dá para recuperar" />}
        </div>
      </section>

      <Painel id="t-funil" titulo="Funil do paciente" sub="Da procura ao exame feito. Passe o mouse em cada etapa para ver o que ela conta.">
        <ol className="crm-funil">
          {ind.funil.map((e, idx) => {
            const base = Math.max(1, ind.funil[0].n);
            const anterior = idx === 0 ? null : ind.funil[idx - 1].n;
            return (
              <li key={e.id} title={e.dica}>
                <span className="crm-funil-nome">{e.rotulo}</span>
                <span className="crm-funil-trilho" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, (e.n / base) * 100)}%` }} />
                </span>
                <span className="crm-funil-valor">
                  {e.n}
                  {anterior !== null && anterior > 0 && <small> {pct((e.n / anterior) * 100)} da etapa anterior</small>}
                </span>
              </li>
            );
          })}
        </ol>
        <Nota>
          As etapas olham períodos diferentes: solicitações e agendamentos contam pela data do contato; exames feitos, pela data do exame.
          {ind.aRealizar > 0 && ` Há ainda ${ind.aRealizar} ${ind.aRealizar === 1 ? "horário marcado" : "horários marcados"} para os próximos dias.`}
          {metaMes !== null && ` A meta da clínica é de ${metaMes} ressonâncias por mês (aba Metas).`}
        </Nota>
      </Painel>

      <div className="crm-duas">
        <Painel id="t-perdas" titulo="Por que perdemos pacientes" sub="Contatos que não agendaram ou desistiram, por motivo.">
          {ind.perdasPorMotivo.length === 0 ? (
            <Vazio>Nenhuma perda registrada no período.</Vazio>
          ) : (
            <Tabela colunas={verValores ? ["Motivo", "Tipo de gargalo", "Contatos", "%", "Orçado"] : ["Motivo", "Tipo de gargalo", "Contatos", "%"]}>
              {ind.perdasPorMotivo.map((m) => (
                <tr key={m.motivo}>
                  <th scope="row">{m.motivo}</th>
                  <td>{m.categoria}</td>
                  <td>{m.n}</td>
                  <td>{pct(m.pct)}</td>
                  {verValores && <td>{m.valor > 0 ? brl(m.valor) : "—"}</td>}
                </tr>
              ))}
            </Tabela>
          )}
        </Painel>

        <Painel id="t-absent" titulo="Faltas e confirmação" sub="Quem faltou, pela resposta antes do exame (só horários com resultado).">
          <Tabela colunas={["Confirmação prévia", "Horários", "Faltas", "Taxa de falta"]}>
            {ind.faltasPorConfirmacao.map((c) => (
              <tr key={c.confirmacao}>
                <th scope="row">{c.confirmacao}</th>
                <td>{c.agendados}</td>
                <td>{c.faltas}</td>
                <td>{pct(c.taxa)}</td>
              </tr>
            ))}
          </Tabela>
          {ind.motivosFalta.length > 0 && <Nota>Motivos das faltas: {ind.motivosFalta.map((m) => `${m.motivo} (${m.n})`).join(" · ")}.</Nota>}
          <Nota>
            Cancelamentos: {ind.cancelamentos} · Reagendados: {ind.reagendados}. Absenteísmo = faltas ÷ (exames feitos + faltas); horários pendentes
            não entram.
          </Nota>
        </Painel>
      </div>

      <div className="crm-duas">
        <Painel id="t-forma" titulo="Por forma de pagamento" sub="Particular, convênio, SUS e Cetrus têm gargalos diferentes.">
          {ind.porForma.length === 0 ? (
            <Vazio>Sem registros no período.</Vazio>
          ) : (
            <Tabela colunas={[" ", "Solicitações", "Conversão", "Exames feitos", "Absenteísmo"]}>
              {ind.porForma.map((f) => (
                <tr key={f.forma}>
                  <th scope="row">{f.forma}</th>
                  <td>{f.solicitacoes}</td>
                  <td>{pct(f.conversao)}</td>
                  <td>{f.realizados}</td>
                  <td>{pct(f.absenteismo)}</td>
                </tr>
              ))}
            </Tabela>
          )}
        </Painel>

        <Painel id="t-op" titulo="Equipamento e sala" sub="Problemas operacionais anotados nos horários.">
          {ind.motivosOperacionais.length === 0 ? (
            <Vazio>Nenhum problema operacional registrado no período.</Vazio>
          ) : (
            <Tabela colunas={["Motivo", "Ocorrências", "Horas paradas"]}>
              {ind.motivosOperacionais.map((m) => (
                <tr key={m.motivo}>
                  <th scope="row">{m.motivo}</th>
                  <td>{m.n}</td>
                  <td>{m.horas > 0 ? horasTxt(m.horas) : "—"}</td>
                </tr>
              ))}
            </Tabela>
          )}
          <Nota>Total no período: {horasTxt(ind.horasParadas)} de equipamento parado ou em atraso.</Nota>
        </Painel>
      </div>

      <h2 className="crm-secao">Marketing e captação</h2>
      <p className="crm-secao-sub">Onde investir, o que anunciar e o que está travando a captação.</p>

      <section aria-label="Resumo de marketing">
        <div className="kpis">
          <Kpi
            rotulo="Pacientes novos"
            valor={pct(mkt.pctNovos)}
            meta={`${mkt.novos} novos e ${mkt.recorrentes} que já tinham vindo`}
            cor="var(--s-realizados)"
          />
          <Kpi
            rotulo="Perdas por preço"
            valor={pct(mkt.pctPerdaPorPreco)}
            meta={
              mkt.precoPerdeu !== null && mkt.precoGanhou !== null
                ? `Perdeu com ${brl(mkt.precoPerdeu)} em média; fechou com ${brl(mkt.precoGanhou)}`
                : "Sem valores suficientes para comparar"
            }
            cor="var(--s-agendados)"
          />
          <Kpi
            rotulo="Antecedência média"
            valor={mkt.antecedenciaMedia === null ? "—" : `${num(mkt.antecedenciaMedia)} dias`}
            meta="Do contato até a data do exame"
          />
          <Kpi
            rotulo="Demanda sem vaga"
            valor={String(mkt.demandaReprimida.reduce((a, b) => a + b.perdas, 0))}
            meta="Pacientes perdidos por falta de horário"
            cor="var(--s-agendados)"
          />
        </div>
      </section>

      <Painel id="t-canal" titulo="Canal de entrada" sub="Quanto cada canal traz, quanto converte e quanto vale. É daqui que sai onde investir.">
        {mkt.porCanal.length === 0 ? (
          <Vazio>Sem contatos no período.</Vazio>
        ) : (
          <Tabela
            colunas={
              verValores
                ? ["Canal", "Solicitações", "Agendaram", "Conversão", "Novos", "Ticket médio", "Valor agendado"]
                : ["Canal", "Solicitações", "Agendaram", "Conversão", "Novos"]
            }
          >
            {mkt.porCanal.map((c) => (
              <tr key={c.canal}>
                <th scope="row">{c.canal}</th>
                <td>{c.solicitacoes}</td>
                <td>{c.agendadas}</td>
                <td>{pct(c.conversao)}</td>
                <td>{c.novos}</td>
                {verValores && <td>{c.ticket === null ? "—" : brl(c.ticket)}</td>}
                {verValores && <td>{c.receitaAgendada > 0 ? brl(c.receitaAgendada) : "—"}</td>}
              </tr>
            ))}
          </Tabela>
        )}
        <Nota>
          Ticket médio e valor agendado usam só Particular e Convênio (SUS e Cetrus têm regra própria). Canal com muita solicitação e pouca
          conversão é problema de atendimento, não de anúncio.
        </Nota>
      </Painel>

      <div className="crm-duas">
        <Painel id="t-resposta" titulo="Tempo de resposta por canal" sub="Da entrada do contato até a primeira resposta. O mais lento perde mais.">
          {mkt.respostaPorCanal.length === 0 ? (
            <Vazio>Ninguém marcou a primeira resposta ainda. Use o botão “Respondi agora” na aba Meu dia.</Vazio>
          ) : (
            <Tabela colunas={["Canal", "Horas até responder", "Contatos medidos"]}>
              {mkt.respostaPorCanal.map((c) => (
                <tr key={c.canal}>
                  <th scope="row">{c.canal}</th>
                  <td>{c.horas === null ? "—" : `${num(c.horas)} h`}</td>
                  <td>{c.medidos}</td>
                </tr>
              ))}
            </Tabela>
          )}
          <Nota>A conta começa às 9h do dia do contato, porque a hora exata da entrada não é registrada.</Nota>
        </Painel>

        <Painel id="t-demanda" titulo="Demanda que a agenda não absorveu" sub="Exames perdidos por falta de horário: onde abrir mais agenda rende mais.">
          {mkt.demandaReprimida.length === 0 ? (
            <Vazio>Ninguém foi perdido por falta de vaga no período.</Vazio>
          ) : (
            <Tabela colunas={verValores ? ["Grupo de exame", "Perdidos", "Orçado perdido"] : ["Grupo de exame", "Perdidos"]}>
              {mkt.demandaReprimida.map((d) => (
                <tr key={d.exame}>
                  <th scope="row">{d.exame}</th>
                  <td>{d.perdas}</td>
                  {verValores && <td>{d.valor > 0 ? brl(d.valor) : "—"}</td>}
                </tr>
              ))}
            </Tabela>
          )}
        </Painel>
      </div>

      <div className="crm-duas">
        <Painel id="t-procurados" titulo="Exames mais procurados" sub="O que as pessoas pedem e quanto disso vira exame feito. Serve para escolher o que anunciar.">
          {mkt.topProcurados.length === 0 ? (
            <Vazio>Sem contatos no período.</Vazio>
          ) : (
            <Tabela colunas={["Grupo de exame", "Procurado", "Feito", "Conversão"]}>
              {mkt.topProcurados.map((e) => (
                <tr key={e.exame}>
                  <th scope="row">{e.exame}</th>
                  <td>{e.procurado}</td>
                  <td>{e.realizado}</td>
                  <td>{pct(e.conversao)}</td>
                </tr>
              ))}
            </Tabela>
          )}
          <Nota>Procurado conta pela data do contato e feito pela data do exame, então um exame marcado para depois ainda não aparece como feito.</Nota>
        </Painel>

        <Painel id="t-convenios" titulo="Convênios que pedimos e não atendemos" sub="Cada linha é demanda real que foi embora. Vira pedido de credenciamento.">
          {mkt.conveniosNaoAtendidos.length === 0 ? (
            <Vazio>Ninguém foi perdido por convênio não atendido.</Vazio>
          ) : (
            <Tabela colunas={["Convênio pedido", "Pacientes perdidos"]}>
              {mkt.conveniosNaoAtendidos.map((c) => (
                <tr key={c.convenio}>
                  <th scope="row">{c.convenio}</th>
                  <td>{c.pedidos}</td>
                </tr>
              ))}
            </Tabela>
          )}
          <Nota>Para esta lista servir, anote o nome do convênio nas observações quando ele não estiver na lista.</Nota>
        </Painel>
      </div>

      <Painel id="t-dia" titulo="Quando as pessoas procuram" sub="Dia da semana em que os contatos chegam: ajuda a escalar a equipe e a programar campanha.">
        {mkt.porDiaSemana.length === 0 ? (
          <Vazio>Sem contatos no período.</Vazio>
        ) : (
          <ul className="crm-barras">
            {mkt.porDiaSemana.map((d) => {
              const max = Math.max(...mkt.porDiaSemana.map((x) => x.n), 1);
              return (
                <li key={d.dia}>
                  <span className="crm-barras-nome">{d.dia}</span>
                  <span className="crm-barras-trilho" aria-hidden="true">
                    <span style={{ width: `${(d.n / max) * 100}%` }} />
                  </span>
                  <span className="crm-barras-valor">{d.n}</span>
                </li>
              );
            })}
          </ul>
        )}
      </Painel>
    </>
  );
}
