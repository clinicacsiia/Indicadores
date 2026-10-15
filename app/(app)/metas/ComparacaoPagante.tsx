import { IconAlerta } from "@/app/components/icons";
import type { Achado, ResultadoGrupo, ResultadoItem, ResultadoMes, SerieDiaria, Situacao } from "@/lib/metas/calculo";

// Comparação "com SUS × só pagante" das metas: barras de cumprimento, linhas de evolução e a leitura automática.
// Só quantidade e porcentagem: as Metas não trazem valores em R$, então não há nada de dinheiro a esconder aqui.

const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const pctTexto = (v: number) => `${umaCasa.format(v)}%`;
const ppTexto = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${umaCasa.format(Math.abs(v))} p.p.`;
const dataCurta = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const ROTULO_SITUACAO: Record<Situacao, string> = {
  batida: "Meta batida",
  ritmo: "No ritmo",
  atencao: "Atenção",
  atrasado: "Atrasado",
};

function BarraDupla({ total, pagante, esperado }: { total: number; pagante: number; esperado: number }) {
  const marca = esperado > 0 && esperado < 100 ? <span className="meter-tick" style={{ left: `${esperado}%` }} /> : null;
  return (
    <div className="pagante-barras" aria-hidden="true">
      <div className="pagante-trilho">
        <span className="pagante-fill" data-serie="total" style={{ width: `${Math.min(total, 100)}%` }} />
        {marca}
      </div>
      <div className="pagante-trilho">
        <span className="pagante-fill" data-serie="pagante" style={{ width: `${Math.min(pagante, 100)}%` }} />
        {marca}
      </div>
    </div>
  );
}

function LinhaComparacao({
  nome,
  total,
  pagante,
  esperado,
  situacaoPagante,
  nivel,
}: {
  nome: string;
  total: number;
  pagante: number;
  esperado: number;
  situacaoPagante: Situacao;
  nivel: "geral" | "grupo" | "item";
}) {
  const dif = pagante - total;
  return (
    <li className="pagante-linha" data-nivel={nivel}>
      <span className="pagante-nome">{nome}</span>
      <BarraDupla total={total} pagante={pagante} esperado={esperado} />
      <span className="pagante-num">
        <span className="pagante-par" data-serie="total">
          Com SUS <b>{pctTexto(total)}</b>
        </span>
        <span className="pagante-par" data-serie="pagante">
          Só pagante <b>{pctTexto(pagante)}</b>
        </span>
        <span className="pagante-dif">{ppTexto(dif)}</span>
        <span className="status-pill" data-status={situacaoPagante}>
          {ROTULO_SITUACAO[situacaoPagante]}
        </span>
      </span>
    </li>
  );
}

// ───────── gráficos de linha (SVG) ─────────

const L = 640;
const A = 240;
const MARGEM = { topo: 14, direita: 16, base: 28, esquerda: 38 };

type Ponto = { dia: string; y: number | null };

function escalaX(n: number) {
  const largura = L - MARGEM.esquerda - MARGEM.direita;
  return (i: number) => MARGEM.esquerda + (n <= 1 ? largura / 2 : (i / (n - 1)) * largura);
}
const escalaY = (v: number, max: number) => MARGEM.topo + (1 - Math.min(Math.max(v, 0), max) / max) * (A - MARGEM.topo - MARGEM.base);

/** Teto do eixo: o maior valor desenhado arredondado para cima (de 20 em 20, no mínimo 20 e no máximo 100), para a linha não ficar espremida na base. */
function tetoDoEixo(valores: (number | null)[]): number {
  const maior = Math.max(0, ...valores.filter((v): v is number => v !== null));
  return Math.min(100, Math.max(20, Math.ceil(maior / 20) * 20));
}

function caminho(pontos: Ponto[], x: (i: number) => number, max: number): string {
  let d = "";
  let aberto = false;
  pontos.forEach((p, i) => {
    if (p.y === null) {
      aberto = false;
      return;
    }
    d += `${aberto ? "L" : "M"}${x(i).toFixed(1)} ${escalaY(p.y, max).toFixed(1)} `;
    aberto = true;
  });
  return d.trim();
}

function Grade({ n, dias, x, max }: { n: number; dias: string[]; x: (i: number) => number; max: number }) {
  const passo = Math.max(1, Math.ceil(n / 6));
  const marcas = dias.map((d, i) => ({ d, i })).filter(({ i }) => i % passo === 0 || i === n - 1);
  return (
    <g className="grafico-grade">
      {[0, 0.25, 0.5, 0.75, 1].map((f) => f * max).map((v) => (
        <g key={v}>
          <line x1={MARGEM.esquerda} x2={L - MARGEM.direita} y1={escalaY(v, max)} y2={escalaY(v, max)} />
          <text x={MARGEM.esquerda - 6} y={escalaY(v, max) + 4} textAnchor="end">
            {umaCasa.format(v)}%
          </text>
        </g>
      ))}
      {marcas.map(({ d, i }) => (
        <text key={d} x={x(i)} y={A - 8} textAnchor="middle">
          {dataCurta(d)}
        </text>
      ))}
    </g>
  );
}

function Serie({ nome, pontos, x, max, serie, tracejada }: { nome: string; pontos: Ponto[]; x: (i: number) => number; max: number; serie: string; tracejada?: boolean }) {
  const ultimo = [...pontos.keys()].reverse().find((i) => pontos[i].y !== null);
  return (
    <g className="grafico-serie" data-serie={serie} data-tracejada={tracejada ? "" : undefined}>
      <path d={caminho(pontos, x, max)} fill="none" />
      {ultimo !== undefined && pontos[ultimo].y !== null && (
        <circle cx={x(ultimo)} cy={escalaY(pontos[ultimo].y as number, max)} r={4}>
          <title>{`${nome}: ${pctTexto(pontos[ultimo].y as number)} em ${dataCurta(pontos[ultimo].dia)}`}</title>
        </circle>
      )}
      {pontos.map(
        (p, i) =>
          p.y !== null && (
            <circle key={p.dia} className="grafico-alvo" cx={x(i)} cy={escalaY(p.y, max)} r={8}>
              <title>{`${nome} em ${dataCurta(p.dia)}: ${pctTexto(p.y)}`}</title>
            </circle>
          )
      )}
    </g>
  );
}

function GraficoAcumulado({ serie }: { serie: SerieDiaria }) {
  const n = serie.pontos.length;
  const x = escalaX(n);
  const dias = serie.pontos.map((p) => p.dia);
  const max = tetoDoEixo(serie.pontos.flatMap((p) => [p.esperado, p.total, p.pagante]));
  const ult = [...serie.pontos].reverse().find((p) => p.total !== null && p.pagante !== null);
  const resumo = ult
    ? `Em ${dataCurta(ult.dia)}: esperado ${pctTexto(ult.esperado)}, com SUS ${pctTexto(ult.total ?? 0)}, só pagante ${pctTexto(ult.pagante ?? 0)}.`
    : "Sem atendimentos sincronizados no período.";
  return (
    <figure className="grafico">
      <figcaption>
        <b>Cumprimento acumulado das metas</b>
        <span>% da meta de todos os serviços, dia a dia</span>
      </figcaption>
      <div className="grafico-rolagem" tabIndex={0} role="group" aria-label="Gráfico de cumprimento acumulado">
      <svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label={`Cumprimento acumulado das metas, com SUS e só pagante, contra o esperado. ${resumo}`}>
        <Grade n={n} dias={dias} x={x} max={max} />
        <Serie nome="Esperado" serie="esperado" tracejada x={x} max={max} pontos={serie.pontos.map((p) => ({ dia: p.dia, y: p.esperado }))} />
        <Serie nome="Com SUS" serie="total" x={x} max={max} pontos={serie.pontos.map((p) => ({ dia: p.dia, y: p.total }))} />
        <Serie nome="Só pagante" serie="pagante" x={x} max={max} pontos={serie.pontos.map((p) => ({ dia: p.dia, y: p.pagante }))} />
      </svg>
      </div>
      <div className="grafico-legenda" aria-hidden="true">
        <span data-serie="total">Com SUS</span>
        <span data-serie="pagante">Só pagante</span>
        <span data-serie="esperado">Esperado pelos dias úteis</span>
      </div>
    </figure>
  );
}

function GraficoParticipacao({ serie }: { serie: SerieDiaria }) {
  const n = serie.pontos.length;
  const x = escalaX(n);
  const dias = serie.pontos.map((p) => p.dia);
  const media = serie.participacaoPeriodo;
  const pontos = serie.pontos.map((p) => ({ dia: p.dia, y: p.participacao }));
  if (!pontos.some((p) => p.y !== null)) return null;
  return (
    <figure className="grafico">
      <figcaption>
        <b>Participação do pagante</b>
        <span>% de pagante entre SUS + pagante, média dos últimos 7 dias</span>
      </figcaption>
      <div className="grafico-rolagem" tabIndex={0} role="group" aria-label="Gráfico de participação do pagante">
      <svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label={`Participação do pagante nos atendimentos, média móvel de 7 dias${media !== null ? `; média do período ${pctTexto(media)}` : ""}.`}>
        <Grade n={n} dias={dias} x={x} max={100} />
        {media !== null && <Serie nome="Média do período" serie="esperado" tracejada x={x} max={100} pontos={serie.pontos.map((p) => ({ dia: p.dia, y: media }))} />}
        <Serie nome="Pagante (média de 7 dias)" serie="pagante" x={x} max={100} pontos={pontos} />
      </svg>
      </div>
      <div className="grafico-legenda" aria-hidden="true">
        <span data-serie="pagante">Pagante, média de 7 dias</span>
        {media !== null && <span data-serie="esperado">Média do período ({pctTexto(media)})</span>}
      </div>
    </figure>
  );
}

// ───────── seção ─────────

export function ComparacaoPagante({
  resultado,
  serie,
  achados,
  nomePeriodo,
}: {
  resultado: ResultadoMes;
  serie: SerieDiaria | null;
  achados: Achado[];
  nomePeriodo: string;
}) {
  const esperado = resultado.esperadoPct;
  const itensPorGrupo = (g: ResultadoGrupo): ResultadoItem[] => g.itens.filter((i) => i.meta > 0);
  return (
    <section className="panel" aria-labelledby="pagante-titulo">
      <div className="panel-head">
        <div>
          <h2 className="panel-title" id="pagante-titulo">
            Metas com SUS × só pagante
          </h2>
          <p className="panel-sub">
            O cumprimento da mesma meta contando todos os atendimentos e contando só o pagante (convênio que não é SUS e particular). Em porcentagem da
            meta, sem valores em R$.
          </p>
        </div>
      </div>

      <div className="convenio-legenda" aria-hidden="true">
        <span data-tipo="pg-total">Com SUS</span>
        <span data-tipo="pg-pagante">Só pagante</span>
        {esperado > 0 && esperado < 100 && <span data-tipo="pg-esperado">Esperado até agora ({pctTexto(esperado)})</span>}
      </div>

      <ul className="pagante-lista">
        <LinhaComparacao
          nome="Todas as metas"
          nivel="geral"
          total={resultado.geral.pct}
          pagante={resultado.geral.pctPagante}
          esperado={esperado}
          situacaoPagante={resultado.geral.situacaoPagante}
        />
        {resultado.grupos.map((g) => (
          <li key={g.id} className="pagante-grupo">
            <ul className="pagante-lista pagante-lista-interna">
              <LinhaComparacao nome={g.nome} nivel="grupo" total={g.pct} pagante={g.pctPagante} esperado={esperado} situacaoPagante={g.situacaoPagante} />
              <li>
                <details className="pagante-detalhes">
                  <summary>Por serviço ({itensPorGrupo(g).length})</summary>
                  <ul className="pagante-lista pagante-lista-interna">
                    {itensPorGrupo(g).map((i) => (
                      <LinhaComparacao
                        key={i.id}
                        nome={i.nome}
                        nivel="item"
                        total={i.pct}
                        pagante={i.pctPagante}
                        esperado={esperado}
                        situacaoPagante={i.situacaoPagante}
                      />
                    ))}
                  </ul>
                </details>
              </li>
            </ul>
          </li>
        ))}
      </ul>

      {serie && serie.pontos.length > 0 ? (
        <div className="graficos-linha">
          <GraficoAcumulado serie={serie} />
          <GraficoParticipacao serie={serie} />
        </div>
      ) : (
        <p className="panel-sub pagante-aviso">
          <IconAlerta size={16} /> A evolução dia a dia ainda não está disponível para este {nomePeriodo}.
        </p>
      )}

      {achados.length > 0 && (
        <div className="analise" role="region" aria-label="Leitura da comparação">
          <h3 className="analise-titulo">O que os números mostram</h3>
          <ul>
            {achados.map((a) => (
              <li key={a.texto} data-tom={a.tom}>
                {a.texto}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
