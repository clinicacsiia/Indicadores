// Calendário do mês para a aba "Agenda": cada dia mostra quantas marcações de Ressonância há e como elas estão (abertas, feitas, faltas, canceladas).
// Cada dia é um link: o detalhe do dia aparece abaixo, na mesma página (sem JavaScript no navegador).
import Link from "next/link";
import { semanasDoMes, somarMeses, type ContagemDia } from "@/lib/crm-rm";

export const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
export const DIAS_DA_SEMANA = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"];
const SIGLAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

const LEGENDA: { chave: keyof Omit<ContagemDia, "total">; rotulo: string }[] = [
  { chave: "abertas", rotulo: "Abertas" },
  { chave: "feitas", rotulo: "Realizadas" },
  { chave: "faltas", rotulo: "Faltaram" },
  { chave: "canceladas", rotulo: "Canceladas ou remarcadas" },
];

/** "2026-10-24" -> "sábado, 24 de outubro de 2026". */
export function dataPorExtenso(dia: string): string {
  const [a, m, d] = dia.split("-").map(Number);
  return `${DIAS_DA_SEMANA[new Date(Date.UTC(a, m - 1, d)).getUTCDay()]}, ${d} de ${MESES[m - 1]} de ${a}`;
}

export function CalendarioAgenda({
  mes,
  hoje,
  dia,
  contagens,
  hrefCal,
}: {
  /** "AAAA-MM". */
  mes: string;
  hoje: string;
  /** Dia aberto no detalhe, "AAAA-MM-DD". */
  dia: string | null;
  contagens: Map<string, ContagemDia>;
  hrefCal: (mes: string, dia: string | null) => string;
}) {
  const [ano, m] = mes.split("-").map(Number);
  const celulas = semanasDoMes(mes).flat();
  const maior = Math.max(1, ...[...contagens.values()].map((c) => c.total));
  const mesDeHoje = hoje.slice(0, 7);

  return (
    <div className="cal">
      <div className="cal-nav">
        <Link href={hrefCal(somarMeses(mes, -1), null)} className="btn btn-pequeno" aria-label="Mês anterior">
          ‹
        </Link>
        <h3 className="cal-titulo">
          {MESES[m - 1]} de {ano}
        </h3>
        <Link href={hrefCal(somarMeses(mes, 1), null)} className="btn btn-pequeno" aria-label="Próximo mês">
          ›
        </Link>
        {(mes !== mesDeHoje || dia !== hoje) && (
          <Link href={hrefCal(mesDeHoje, hoje)} className="btn btn-pequeno cal-hoje">
            Hoje
          </Link>
        )}
      </div>

      <div className="cal-semana" aria-hidden="true">
        {SIGLAS.map((s) => (
          <span key={s}>{s}</span>
        ))}
      </div>

      <ol className="cal-grade" aria-label={`Dias de ${MESES[m - 1]} de ${ano}`}>
        {celulas.map((d, i) => {
          if (d === null) return <li key={`fora-${i}`} className="cal-fora" aria-hidden="true" />;
          const c = contagens.get(d);
          const numero = Number(d.slice(8));
          const rotulo = c
            ? `${numero} de ${MESES[m - 1]}: ${c.total} ${c.total === 1 ? "marcação" : "marcações"} (${c.abertas} abertas, ${c.feitas} realizadas, ${c.faltas} faltas, ${c.canceladas} canceladas ou remarcadas)`
            : `${numero} de ${MESES[m - 1]}: sem marcações`;
          return (
            <li key={d}>
              <Link
                href={hrefCal(mes, d)}
                className="cal-dia"
                data-hoje={d === hoje ? "true" : undefined}
                data-sel={d === dia ? "true" : undefined}
                data-vazio={c ? undefined : "true"}
                aria-current={d === hoje ? "date" : undefined}
                aria-label={d === dia ? `${rotulo} (aberto abaixo)` : rotulo}
              >
                <span className="cal-num">{numero}</span>
                {c && (
                  <>
                    <span className="cal-total">{c.total}</span>
                    <span className="cal-chips" aria-hidden="true">
                      {LEGENDA.map((l) => c[l.chave] > 0 && <span key={l.chave} className="cal-chip" data-tipo={l.chave}>{c[l.chave]}</span>)}
                    </span>
                    <span className="cal-barra" style={{ width: `${(c.total / maior) * 100}%` }} aria-hidden="true" />
                  </>
                )}
              </Link>
            </li>
          );
        })}
      </ol>

      <ul className="cal-legenda" aria-label="Legenda">
        {LEGENDA.map((l) => (
          <li key={l.chave}>
            <span className="cal-chip" data-tipo={l.chave} aria-hidden="true">
              {" "}
            </span>
            {l.rotulo}
          </li>
        ))}
      </ul>
    </div>
  );
}
