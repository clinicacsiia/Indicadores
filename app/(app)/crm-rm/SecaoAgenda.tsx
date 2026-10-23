// Aba "Agenda": as marcações de Ressonância do Klingo (relatório #13825), lidas sem digitação.
// Quem tem acesso ao CRM vê paciente, telefone e confirmação; confirmar ou cancelar continua sendo no Klingo.
import Link from "next/link";
import type { Horario } from "@/lib/crm-rm";
import { Kpi, Nota, PacienteHorario, Painel, ResumoHorario, Vazio, dataBR, dataHoraBR } from "./comuns";

export type FiltroAgenda = { id: string; rotulo: string; status: readonly string[] | null };

const NA_LISTA = 40;

function href(dias: number, busca: string, st: string) {
  const q = new URLSearchParams({ aba: "agenda" });
  if (dias !== 30) q.set("dias", String(dias));
  if (busca) q.set("busca", busca);
  if (st !== "todas") q.set("st", st);
  return `/crm-rm?${q.toString()}`;
}

const contem = (h: Horario, busca: string) => {
  const t = busca.toLowerCase();
  return [h.codigo_marcacao, h.prontuario, h.paciente, h.exame, h.convenio, h.responsavel, h.id_atendimento].some((v) => (v ?? "").toLowerCase().includes(t));
};

export function SecaoAgenda({
  horarios,
  hoje,
  dias,
  busca,
  filtros,
  filtro,
  verValores,
  atualizadoEm,
  cortada,
}: {
  /** Já limitadas ao período escolhido (exame de `inicio` em diante, inclusive as futuras). */
  horarios: Horario[];
  hoje: string;
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
  // Hoje e os próximos dias primeiro (do mais perto para o mais longe); depois o passado, do mais recente para o mais antigo.
  const proximos = achados.filter((h) => h.data_exame >= hoje);
  const passados = achados.filter((h) => h.data_exame < hoje).reverse();
  const lista = [...proximos, ...passados];

  return (
    <>
      <section aria-label="Resumo da agenda">
        <div className="kpis">
          <Kpi rotulo="Marcações" valor={String(horarios.length)} meta="Exames de RM com data no período" cor="var(--s-realizados)" />
          <Kpi rotulo="Abertas" valor={String(n("Agendado"))} meta="Exame de hoje em diante" />
          <Kpi rotulo="Realizadas" valor={String(n("Realizado"))} meta="Atendimento registrado no Klingo" cor="var(--s-realizados)" />
          <Kpi rotulo="Faltaram" valor={String(n("Faltou"))} meta="Sem atendimento depois da data" cor="var(--s-agendados)" />
          <Kpi rotulo="Canceladas" valor={String(n("Cancelado") + n("Reagendado"))} meta={`${n("Reagendado")} delas remarcadas`} />
        </div>
      </section>

      <Painel
        id="t-lista-agenda"
        titulo="Marcações de Ressonância"
        sub={`Vêm sozinhas do Klingo${atualizadoEm ? ` (última leitura em ${dataHoraBR(atualizadoEm)})` : ""}. Hoje e os próximos dias primeiro.`}
      >
        <nav className="crm-periodos" aria-label="Situação da marcação">
          {filtros.map((f) => (
            <Link key={f.id} href={href(dias, busca, f.id)} className="crm-periodo" aria-current={f.id === filtro.id ? "true" : undefined}>
              {f.rotulo}
            </Link>
          ))}
        </nav>

        <form className="crm-busca" role="search">
          <input type="hidden" name="aba" value="agenda" />
          {dias !== 30 && <input type="hidden" name="dias" value={dias} />}
          {filtro.id !== "todas" && <input type="hidden" name="st" value={filtro.id} />}
          <label className="sr-only" htmlFor="busca-agenda">
            Buscar marcação
          </label>
          <input id="busca-agenda" name="busca" className="input" placeholder="Buscar por paciente, prontuário, marcação, exame ou convênio" defaultValue={busca} />
          <button type="submit" className="btn">
            Buscar
          </button>
          {busca && (
            <Link href={href(dias, "", filtro.id)} className="crm-link">
              limpar
            </Link>
          )}
        </form>

        {cortada && <Nota>O período tem marcações demais para uma leitura só: mostrando só as mais antigas. Escolha um período menor.</Nota>}

        {lista.length === 0 ? (
          <Vazio>{busca ? `Nada encontrado para “${busca}”.` : "Nenhuma marcação neste filtro e período."}</Vazio>
        ) : (
          <ul className="crm-lista">
            {lista.slice(0, NA_LISTA).map((h) => (
              <li key={h.codigo_marcacao} className="crm-item">
                <ResumoHorario h={h} verValores={verValores} />
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
    </>
  );
}
