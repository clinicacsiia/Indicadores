// Aba "Agenda": as marcações de Ressonância do Klingo (relatório #13825), lidas sem digitação.
// Quem tem acesso ao CRM vê paciente, telefone e confirmação; confirmar ou cancelar continua sendo no Klingo.
// Duas visões: calendário do mês (padrão) e lista corrida por período. Filtro de situação e busca valem nas duas.
import Link from "next/link";
import { contarPorDia, type Horario } from "@/lib/crm-rm";
import { CalendarioAgenda, MESES, dataPorExtenso } from "./CalendarioAgenda";
import { Kpi, Nota, PacienteHorario, Painel, ResumoHorario, Vazio, dataBR, dataHoraBR } from "./comuns";

export type FiltroAgenda = { id: string; rotulo: string; status: readonly string[] | null };
export type VisaoAgenda = "calendario" | "lista";

const NA_LISTA = 40;

type Alvo = { visao: VisaoAgenda; dias: number; busca: string; st: string; mes: string; dia: string | null };

function href(a: Alvo) {
  const q = new URLSearchParams({ aba: "agenda" });
  if (a.visao === "lista") {
    q.set("visao", "lista");
    if (a.dias !== 30) q.set("dias", String(a.dias));
  } else {
    q.set("mes", a.mes);
    if (a.dia) q.set("dia", a.dia);
  }
  if (a.busca) q.set("busca", a.busca);
  if (a.st !== "todas") q.set("st", a.st);
  return `/crm-rm?${q.toString()}`;
}

const contem = (h: Horario, busca: string) => {
  const t = busca.toLowerCase();
  return [h.codigo_marcacao, h.prontuario, h.paciente, h.exame, h.convenio, h.responsavel, h.id_atendimento].some((v) => (v ?? "").toLowerCase().includes(t));
};

/** Uma marcação com paciente, telefone e confirmação, igual na lista e no detalhe do dia. */
function ItemHorario({ h, verValores, semData }: { h: Horario; verValores: boolean; semData?: boolean }) {
  return (
    <li className="crm-item">
      <ResumoHorario h={h} verValores={verValores} semData={semData} />
      <PacienteHorario h={h} />
      <p className="crm-item-meta">
        Confirmação: {h.confirmacao}
        {h.agendado_em ? ` · marcada em ${dataBR(h.agendado_em.slice(0, 10))}` : ""}
        {h.responsavel ? ` por ${h.responsavel}` : ""}
        {h.id_atendimento ? ` · atendimento ${h.id_atendimento}` : ""}
        {h.motivo_cancelamento ? ` · cancelamento: ${h.motivo_cancelamento}` : ""}
      </p>
      {h.observacao && <p className="crm-item-texto">{h.observacao}</p>}
    </li>
  );
}

const porHorario = (a: Horario, b: Horario) => (a.horario ?? "99:99").localeCompare(b.horario ?? "99:99") || a.codigo_marcacao.localeCompare(b.codigo_marcacao);

export function SecaoAgenda({
  horarios,
  hoje,
  visao,
  mes,
  dia,
  dias,
  busca,
  filtros,
  filtro,
  verValores,
  atualizadoEm,
  cortada,
}: {
  /** Calendário: as marcações do mês. Lista: as do período escolhido (exame de `inicio` em diante, inclusive as futuras). */
  horarios: Horario[];
  hoje: string;
  visao: VisaoAgenda;
  /** Mês do calendário, "AAAA-MM". */
  mes: string;
  /** Dia pedido na URL, "AAAA-MM-DD", já conferido contra o mês. */
  dia: string | null;
  dias: number;
  busca: string;
  filtros: readonly FiltroAgenda[];
  filtro: FiltroAgenda;
  verValores: boolean;
  atualizadoEm: string | null;
  cortada: boolean;
}) {
  const n = (status: string) => horarios.filter((h) => h.status === status).length;
  const porStatus = filtro.status ? horarios.filter((h) => (filtro.status as readonly string[]).includes(h.status)) : horarios;
  const achados = busca ? porStatus.filter((h) => contem(h, busca)) : porStatus;
  const alvo = (o: Partial<Alvo> = {}): Alvo => ({ visao, dias, busca, st: filtro.id, mes, dia, ...o });

  const calendario = visao === "calendario";
  const contagens = contarPorDia(achados);
  // Sem dia escolhido: hoje, se estiver no mês; senão o primeiro dia do mês que tem marcação.
  const diaAberto = dia ?? (hoje.startsWith(mes) ? hoje : ([...contagens.keys()].sort()[0] ?? null));
  const doDia = diaAberto ? achados.filter((h) => h.data_exame === diaAberto).sort(porHorario) : [];
  const porHora = new Map<string, Horario[]>();
  for (const h of doDia) {
    const hora = h.horario ? `${h.horario.slice(0, 2)}h` : "Sem horário";
    porHora.set(hora, [...(porHora.get(hora) ?? []), h]);
  }

  // Lista: hoje e os próximos dias primeiro (do mais perto para o mais longe); depois o passado, do mais recente para o mais antigo.
  const proximos = achados.filter((h) => h.data_exame >= hoje);
  const passados = achados.filter((h) => h.data_exame < hoje).reverse();
  const lista = [...proximos, ...passados];

  const [, mesNum] = mes.split("-").map(Number);
  const sub = `Vêm sozinhas do Klingo${atualizadoEm ? ` (última leitura em ${dataHoraBR(atualizadoEm)})` : ""}.`;

  return (
    <>
      <section aria-label="Resumo da agenda">
        <div className="kpis">
          <Kpi rotulo="Marcações" valor={String(horarios.length)} meta={calendario ? `Exames de RM em ${MESES[mesNum - 1]}` : "Exames de RM com data no período"} cor="var(--s-realizados)" />
          <Kpi rotulo="Abertas" valor={String(n("Agendado"))} meta="Exame de hoje em diante" />
          <Kpi rotulo="Realizadas" valor={String(n("Realizado"))} meta="Atendimento registrado no Klingo" cor="var(--s-realizados)" />
          <Kpi rotulo="Faltaram" valor={String(n("Faltou"))} meta="Sem atendimento depois da data" cor="var(--s-agendados)" />
          <Kpi rotulo="Canceladas" valor={String(n("Cancelado") + n("Reagendado"))} meta={`${n("Reagendado")} delas remarcadas`} />
        </div>
      </section>

      <Painel
        id="t-lista-agenda"
        titulo={calendario ? "Calendário da agenda" : "Marcações de Ressonância"}
        sub={calendario ? `${sub} Toque num dia para ver as marcações dele.` : `${sub} Hoje e os próximos dias primeiro.`}
      >
        <nav className="crm-periodos" aria-label="Forma de ver a agenda">
          <Link href={href(alvo({ visao: "calendario", dia: null }))} className="crm-periodo" aria-current={calendario ? "true" : undefined}>
            Calendário
          </Link>
          <Link href={href(alvo({ visao: "lista" }))} className="crm-periodo" aria-current={calendario ? undefined : "true"}>
            Lista
          </Link>
        </nav>

        <nav className="crm-periodos" aria-label="Situação da marcação">
          {filtros.map((f) => (
            <Link key={f.id} href={href(alvo({ st: f.id }))} className="crm-periodo" aria-current={f.id === filtro.id ? "true" : undefined}>
              {f.rotulo}
            </Link>
          ))}
        </nav>

        <form className="crm-busca" role="search">
          <input type="hidden" name="aba" value="agenda" />
          {calendario ? (
            <>
              <input type="hidden" name="mes" value={mes} />
              {dia && <input type="hidden" name="dia" value={dia} />}
            </>
          ) : (
            <>
              <input type="hidden" name="visao" value="lista" />
              {dias !== 30 && <input type="hidden" name="dias" value={dias} />}
            </>
          )}
          {filtro.id !== "todas" && <input type="hidden" name="st" value={filtro.id} />}
          <label className="sr-only" htmlFor="busca-agenda">
            Buscar marcação
          </label>
          <input id="busca-agenda" name="busca" className="input" placeholder="Buscar por paciente, prontuário, marcação, exame ou convênio" defaultValue={busca} />
          <button type="submit" className="btn">
            Buscar
          </button>
          {busca && (
            <Link href={href(alvo({ busca: "" }))} className="crm-link">
              limpar
            </Link>
          )}
        </form>

        {cortada && <Nota>O período tem marcações demais para uma leitura só: mostrando só as mais antigas. Escolha um período menor.</Nota>}

        {calendario ? (
          <CalendarioAgenda
            mes={mes}
            hoje={hoje}
            dia={diaAberto}
            contagens={contagens}
            hrefCal={(m, d) => href(alvo({ mes: m, dia: d }))}
          />
        ) : lista.length === 0 ? (
          <Vazio>{busca ? `Nada encontrado para “${busca}”.` : "Nenhuma marcação neste filtro e período."}</Vazio>
        ) : (
          <ul className="crm-lista">
            {lista.slice(0, NA_LISTA).map((h) => (
              <ItemHorario key={h.codigo_marcacao} h={h} verValores={verValores} />
            ))}
            {lista.length > NA_LISTA && (
              <li className="crm-item crm-item-meta">
                Mostrando as {NA_LISTA} primeiras de {lista.length}. Use a busca, a situação ou um período menor.
              </li>
            )}
          </ul>
        )}
        <Nota>Para confirmar, cancelar ou remarcar, use o Klingo: esta lista se atualiza sozinha na próxima leitura.</Nota>
      </Painel>

      {calendario && (
        <Painel
          id="t-dia-agenda"
          titulo={diaAberto ? dataPorExtenso(diaAberto) : "Nenhum dia escolhido"}
          sub={
            diaAberto
              ? `${doDia.length} ${doDia.length === 1 ? "marcação" : "marcações"}${filtro.id !== "todas" || busca ? " neste filtro" : ""}, por horário.`
              : "Não há marcações neste mês. Use as setas para ver outro mês."
          }
        >
          {diaAberto && doDia.length === 0 ? (
            <Vazio>{busca ? `Nada encontrado para “${busca}” neste dia.` : "Nenhuma marcação neste dia."}</Vazio>
          ) : (
            [...porHora.entries()].map(([hora, hs]) => (
              <div key={hora} className="cal-hora">
                <h3 className="cal-hora-titulo">
                  {hora} <span>{hs.length}</span>
                </h3>
                <ul className="crm-lista">
                  {hs.map((h) => (
                    <ItemHorario key={h.codigo_marcacao} h={h} verValores={verValores} semData />
                  ))}
                </ul>
              </div>
            ))
          )}
        </Painel>
      )}
    </>
  );
}
