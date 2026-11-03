import type { ResultadoMes, Situacao } from "@/lib/metas/calculo";

// Registro dos meses que já fecharam: (1) o último mês fechado, meta × realizado de cada serviço; (2) a evolução do cumprimento mês a mês.
// Só quantidade e porcentagem (as Metas não trazem R$). Server component: SVG simples, sem biblioteca.

const inteiro = new Intl.NumberFormat("pt-BR");
const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const pctTexto = (v: number) => `${umaCasa.format(v)}%`;
const MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const mesCurto = (mes: string) => `${MESES_CURTOS[Number(mes.slice(5)) - 1]}/${mes.slice(2, 4)}`;
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
const mesLongo = (mes: string) => `${MESES[Number(mes.slice(5)) - 1]}/${mes.slice(0, 4)}`;
const ROTULO: Record<Situacao, string> = { batida: "Meta batida", ritmo: "No ritmo", atencao: "Atenção", atrasado: "Atrasado" };

export type MesFechado = { mes: string; resultado: ResultadoMes };

// ───────── gráfico 1: último mês fechado, serviço a serviço ─────────

const TETO_BARRA = 120; // a barra enche até 120% da meta; acima disso só o número conta

function GraficoUltimoMes({ ultimo }: { ultimo: MesFechado }) {
  const r = ultimo.resultado;
  const itens = r.grupos.flatMap((g) => g.itens.filter((i) => i.meta > 0).map((i) => ({ ...i, grupo: g.nome })));
  const batidas = itens.filter((i) => i.pct >= 100).length;
  return (
    <figure className="grafico hist-ultimo">
      <figcaption>
        <b>{mesLongo(ultimo.mes)}: meta × realizado</b>
        <span>
          {batidas} de {itens.length} metas batidas · geral {pctTexto(r.geral.pct)}
        </span>
      </figcaption>
      <ul className="hist-lista" aria-label={`Cumprimento de cada serviço em ${mesLongo(ultimo.mes)}`}>
        {itens.map((i) => (
          <li key={`${i.grupo}|${i.id}`} className="hist-linha">
            <span className="hist-nome">
              {i.nome} <small>{i.grupo}</small>
            </span>
            <span className="hist-trilho" aria-hidden="true">
              <span className="hist-fill" data-status={i.situacao} style={{ width: `${(Math.min(i.pct, TETO_BARRA) / TETO_BARRA) * 100}%` }} />
              <span className="hist-meta-tick" style={{ left: `${(100 / TETO_BARRA) * 100}%` }} />
            </span>
            <span className="hist-num">
              <b>{pctTexto(i.pct)}</b> · {inteiro.format(i.realizado)} de {inteiro.format(i.meta)}
              <span className="sr-only"> ({ROTULO[i.situacao]})</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="grafico-legenda" aria-hidden="true">
        <span data-serie="hist-ok">Meta batida</span>
        <span data-serie="hist-atencao">Entre 75% e 100%</span>
        <span data-serie="hist-atrasado">Abaixo de 75%</span>
        <span data-serie="esperado">Traço = 100% da meta</span>
      </div>
    </figure>
  );
}

// ───────── gráfico 2: evolução mês a mês ─────────

const L = 640;
const A = 260;
const M = { topo: 14, direita: 16, base: 30, esquerda: 42 };
const SERIES: { id: string; nome: string; valor: (r: ResultadoMes) => number | null }[] = [
  { id: "geral", nome: "Geral", valor: (r) => r.geral.pct },
  { id: "csi1", nome: "CSI 1", valor: (r) => r.grupos.find((g) => g.id === "csi1")?.pct ?? null },
  { id: "csi2", nome: "CSI 2", valor: (r) => r.grupos.find((g) => g.id === "csi2")?.pct ?? null },
  { id: "pediatria", nome: "CSI Pediatria", valor: (r) => r.grupos.find((g) => g.id === "pediatria")?.pct ?? null },
];

function GraficoEvolucao({ fechados }: { fechados: MesFechado[] }) {
  const n = fechados.length;
  const largura = L - M.esquerda - M.direita;
  const x = (i: number) => M.esquerda + (n <= 1 ? largura / 2 : (i / (n - 1)) * largura);
  const maior = Math.max(100, ...SERIES.flatMap((s) => fechados.map((f) => s.valor(f.resultado) ?? 0)));
  const max = Math.ceil(maior / 20) * 20;
  const y = (v: number) => M.topo + (1 - Math.min(Math.max(v, 0), max) / max) * (A - M.topo - M.base);
  const ticks = Array.from({ length: max / 20 + 1 }, (_, k) => k * 20);
  const passo = Math.max(1, Math.ceil(n / 8));
  const resumo = fechados.map((f) => `${mesLongo(f.mes)}: ${pctTexto(f.resultado.geral.pct)}`).join("; ");
  return (
    <figure className="grafico hist-evolucao">
      <figcaption>
        <b>Como estamos indo, mês a mês</b>
        <span>% da meta cumprida em cada mês fechado, no geral e por unidade</span>
      </figcaption>
      <div className="grafico-rolagem" tabIndex={0} role="group" aria-label="Gráfico de cumprimento mês a mês">
        <svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label={`Cumprimento geral das metas por mês fechado. ${resumo}.`}>
          <g className="grafico-grade">
            {ticks.map((v) => (
              <g key={v}>
                <line x1={M.esquerda} x2={L - M.direita} y1={y(v)} y2={y(v)} data-cem={v === 100 ? "" : undefined} />
                <text x={M.esquerda - 6} y={y(v) + 4} textAnchor="end">
                  {v}%
                </text>
              </g>
            ))}
            {fechados.map((f, i) =>
              i % passo === 0 || i === n - 1 ? (
                <text key={f.mes} x={x(i)} y={A - 8} textAnchor="middle">
                  {mesCurto(f.mes)}
                </text>
              ) : null
            )}
          </g>
          {SERIES.map((s) => {
            const pts = fechados.map((f, i) => ({ f, i, v: s.valor(f.resultado) })).filter((p): p is { f: MesFechado; i: number; v: number } => p.v !== null);
            return (
              <g key={s.id} className="grafico-serie" data-serie={`hist-${s.id}`}>
                <path d={pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ")} fill="none" />
                {pts.map((p) => (
                  <circle key={p.f.mes} cx={x(p.i)} cy={y(p.v)} r={s.id === "geral" ? 4.5 : 3.5}>
                    <title>{`${s.nome} em ${mesLongo(p.f.mes)}: ${pctTexto(p.v)}`}</title>
                  </circle>
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="grafico-legenda" aria-hidden="true">
        {SERIES.map((s) => (
          <span key={s.id} data-serie={`hist-${s.id}`}>
            {s.nome}
          </span>
        ))}
        <span data-serie="esperado">Tracejada = 100% da meta</span>
      </div>
      {n === 1 && <p className="panel-sub">Só há um mês fechado até agora; a linha ganha forma a partir do segundo.</p>}
    </figure>
  );
}

export function HistoricoMetas({ fechados }: { fechados: MesFechado[] }) {
  if (fechados.length === 0) return null;
  const ultimo = fechados[fechados.length - 1];
  return (
    <section className="panel" aria-labelledby="historico-titulo">
      <div className="panel-head">
        <div>
          <h2 className="panel-title" id="historico-titulo">
            Meses que já passaram
          </h2>
          <p className="panel-sub">
            O registro dos meses fechados, com a meta que valia em cada um, para ver como estamos indo. Não muda com o período escolhido acima.
          </p>
        </div>
      </div>
      <div className="graficos-linha">
        <GraficoUltimoMes ultimo={ultimo} />
        <GraficoEvolucao fechados={fechados} />
      </div>
    </section>
  );
}
