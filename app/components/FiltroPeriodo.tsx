// Barra de filtros padrão das telas: período livre por data (De / Até). É a mesma barra que os painéis em
// Python montam por dentro (painel_base.js), com as mesmas classes, para todas as abas terem o mesmo filtro.
export function FiltroPeriodo({
  basePath,
  de,
  ate,
  min,
  max,
  nome = "Período",
}: {
  basePath: string;
  rotuloMeses?: string; // sem uso: mantidos para não mexer nas telas que chamam o componente
  meses?: string[];
  mesAtivo?: string | null;
  de: string;
  ate: string;
  min: string;
  max: string;
  hoje?: string;
  nome?: string;
}) {
  return (
    <section className="toolbar" aria-label={nome}>
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
