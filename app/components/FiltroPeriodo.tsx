import Link from "next/link";
import { somarDias } from "@/lib/metas/calculo";

const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
const rotuloMes = (mes: string) => `${MESES[Number(mes.slice(5)) - 1]}/${mes.slice(0, 4)}`;
const rotuloMesCurto = (mes: string) => `${MESES[Number(mes.slice(5)) - 1].slice(0, 3)}/${mes.slice(2, 4)}`;

// Barra de filtros padrão das telas: atalhos de mês, atalhos de dias e período livre (De / Até). É a mesma barra que os painéis em
// Python montam por dentro (painel_base.js), com as mesmas classes, para todas as abas terem o mesmo filtro.
export function FiltroPeriodo({
  basePath,
  rotuloMeses = "Mês",
  meses,
  mesAtivo,
  de,
  ate,
  min,
  max,
  hoje,
  nome = "Período",
}: {
  basePath: string;
  rotuloMeses?: string;
  meses: string[]; // do mais recente ao mais antigo
  mesAtivo: string | null; // o período ativo é este mês inteiro
  de: string;
  ate: string;
  min: string;
  max: string;
  hoje: string;
  nome?: string;
}) {
  const recentes = meses.slice(0, 6);
  const outros = meses.slice(6);
  const atalhos = [7, 30, 90].map((n) => {
    const ini = somarDias(hoje, 1 - n);
    return { n, de: ini < min ? min : ini, ativo: mesAtivo === null && de === ini && ate === hoje };
  });

  return (
    <section className="toolbar" aria-label={nome}>
      <div>
        <span className="toolbar-label" id="rotulo-meses">
          {rotuloMeses}
        </span>
        <div className="seg" role="group" aria-labelledby="rotulo-meses">
          {recentes.map((m) => (
            <Link key={m} href={`${basePath}?mes=${m}`} className="seg-item" aria-current={m === mesAtivo ? "true" : undefined}>
              {rotuloMesCurto(m)}
            </Link>
          ))}
        </div>
      </div>

      {outros.length > 0 && (
        <form method="get" action={basePath} className="field" aria-label="Outros meses">
          <label className="field-label" htmlFor="filtro-outros">
            Outros meses
          </label>
          <span style={{ display: "flex", gap: 8 }}>
            <select id="filtro-outros" name="mes" className="select" defaultValue={outros.includes(mesAtivo ?? "") ? (mesAtivo ?? "") : ""}>
              {!outros.includes(mesAtivo ?? "") && <option value="">Escolher…</option>}
              {outros.map((m) => (
                <option key={m} value={m}>
                  {rotuloMes(m)}
                </option>
              ))}
            </select>
            <button type="submit" className="btn">
              Ir
            </button>
          </span>
        </form>
      )}

      <div>
        <span className="toolbar-label" id="rotulo-atalhos">
          Últimos dias
        </span>
        <div className="seg" role="group" aria-labelledby="rotulo-atalhos">
          {atalhos.map((a) => (
            <Link key={a.n} href={`${basePath}?de=${a.de}&ate=${hoje}`} className="seg-item" aria-current={a.ativo ? "true" : undefined}>
              {a.n} dias
            </Link>
          ))}
        </div>
      </div>

      <form method="get" action={basePath} className="range-form" aria-label="Período livre">
        <div className="field">
          <label className="field-label" htmlFor="filtro-de">
            De
          </label>
          <input id="filtro-de" className="input" type="date" name="de" defaultValue={de} min={min} max={max} required />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="filtro-ate">
            Até
          </label>
          <input id="filtro-ate" className="input" type="date" name="ate" defaultValue={ate} min={min} max={max} required />
        </div>
        <button type="submit" className="btn btn-primary">
          Aplicar
        </button>
      </form>
    </section>
  );
}
