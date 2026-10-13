// Gráficos das Metas (porte do painel local "Acompanhamento de META"): barras, linhas e rosca em
// HTML/SVG puro, sem biblioteca. Nada aqui precisa de JavaScript no navegador; as dicas ao passar
// o mouse usam o atributo title.
import type { ReactNode } from "react";

const num = (n: number, d = 0) => n.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
export const pctTxt = (n: number | null | undefined, d = 1) => (n == null || Number.isNaN(n) ? "—" : `${num(n, d)}%`);

export type ItemBarra = {
  rotulo: string;
  valor: number;
  texto: string;
  extra?: string;
  tip?: string;
  /** Só quando a cor tem significado (alerta). */
  cor?: "crit" | "warn";
  /** Valor de referência: traço preto (ex.: esperado até hoje). */
  marca?: number | null;
};

export function Barras({ itens, max, vazio = "Sem dados neste mês." }: { itens: ItemBarra[]; max?: number; vazio?: string }) {
  if (!itens.length) return <p className="mp-vazio">{vazio}</p>;
  const teto = max || Math.max(...itens.map((i) => Math.max(i.valor, i.marca || 0)), 1);
  const maiorTexto = Math.max(...itens.map((i) => i.texto.length + (i.extra ? i.extra.length * 0.85 + 1 : 0)));
  const reserva = Math.round(maiorTexto * 7.8 + 30);
  const pos = (v: number) => `calc((100% - ${reserva}px) * ${Math.min(Math.max(v, 0) / teto, 1).toFixed(4)})`;
  return (
    <div className="mp-barras">
      {itens.map((i) => (
        <div className="mp-barra" key={i.rotulo} data-cor={i.cor} title={i.tip ?? `${i.rotulo}\n${i.texto}`}>
          <div className="mp-barra-rot">{i.rotulo}</div>
          <div className="mp-barra-area">
            <div className="mp-barra-fill" style={{ width: `max(${pos(i.valor)}, 2px)` }} />
            <span
              className="mp-barra-val"
              style={i.marca != null && i.marca > i.valor ? { marginLeft: `calc(${pos(i.marca)} - ${pos(i.valor)} + 2px)` } : undefined}
            >
              {i.texto}
              {i.extra && <small>{i.extra}</small>}
            </span>
            {i.marca != null && <i className="mp-barra-marca" style={{ left: pos(i.marca) }} />}
          </div>
        </div>
      ))}
    </div>
  );
}

export type SerieLinha = {
  nome: string;
  cor: string;
  traco?: boolean;
  larg?: number;
  principal?: boolean;
  pontos: { x: number; y: number }[];
};

export function Linhas({
  series,
  xRot,
  aria,
  tipX,
  W = 760,
  H = 260,
  ml = 38,
  mr = 96,
  mt = 26,
  mb = 26,
}: {
  series: SerieLinha[];
  xRot: number[];
  aria: string;
  tipX: (x: number) => string;
  W?: number;
  H?: number;
  ml?: number;
  mr?: number;
  mt?: number;
  mb?: number;
}) {
  const vivas = series.filter((s) => s.pontos.length);
  if (!vivas.length) return null;
  const todos = vivas.flatMap((s) => s.pontos);
  const x0 = Math.min(...todos.map((p) => p.x));
  const x1 = Math.max(...todos.map((p) => p.x));
  const topo = Math.max(...todos.map((p) => p.y), 1) * 1.08;
  const X = (x: number) => ml + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (W - ml - mr);
  const Y = (v: number) => mt + (1 - Math.min(Math.max(v, 0), topo) / topo) * (H - mt - mb);

  // Rótulos na ponta de cada linha (valor + nome), afastados para não se sobreporem.
  const fins = vivas
    .map((s) => ({ s, u: s.pontos[s.pontos.length - 1], y: 0 }))
    .map((f) => ({ ...f, y: Y(f.u.y) }))
    .sort((a, b) => a.y - b.y);
  const passo = 30;
  for (let i = 1; i < fins.length; i++) if (fins[i].y - fins[i - 1].y < passo) fins[i].y = fins[i - 1].y + passo;
  const baixo = H - 21;
  for (let i = fins.length - 1; i >= 0; i--) {
    const lim = i === fins.length - 1 ? baixo : fins[i + 1].y - passo;
    if (fins[i].y > lim) fins[i].y = lim;
  }
  if (fins.length && fins[0].y < mt - 4) fins[0].y = mt - 4;

  const xs = [...new Set(todos.map((p) => p.x))].sort((a, b) => a - b);
  const larg = xs.length > 1 ? ((W - ml - mr) / (x1 - x0)) * Math.min(...xs.slice(1).map((v, i) => v - xs[i])) : W - ml - mr;

  return (
    <svg className="mp-grafico" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria}>
      <line className="mp-base" x1={ml} x2={W - mr} y1={Y(0)} y2={Y(0)} />
      {xRot.map((x) => (
        <text key={x} x={X(x)} y={H - 7} textAnchor="middle">
          {x}
        </text>
      ))}
      {vivas.map((s) => {
        const u = s.pontos[s.pontos.length - 1];
        return (
          <g key={s.nome}>
            <polyline
              fill="none"
              stroke={s.cor}
              strokeWidth={s.larg || (s.principal ? 2.6 : 1.8)}
              strokeDasharray={s.traco ? "6 4" : undefined}
              strokeLinejoin="round"
              strokeLinecap="round"
              points={s.pontos.map((p) => `${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ")}
            />
            {s.principal && <circle cx={X(u.x)} cy={Y(u.y)} r={4.5} fill={s.cor} stroke="var(--surface)" strokeWidth={2} />}
          </g>
        );
      })}
      {fins.map(({ s, u, y }) => (
        <g key={`f-${s.nome}`}>
          <text className={s.principal ? "mp-rot-fim" : undefined} x={X(u.x) + 10} y={y + 4}>
            {pctTxt(u.y, 0)}
          </text>
          <text className="mp-rot-nome" x={X(u.x) + 10} y={y + 17}>
            {s.nome}
          </text>
        </g>
      ))}
      {xs.map((x) => (
        <rect key={`a-${x}`} x={X(x) - larg / 2} y={mt - 6} width={larg} height={H - mt - mb + 6} fill="transparent">
          <title>{tipX(x)}</title>
        </rect>
      ))}
    </svg>
  );
}

export type Fatia = { rotulo: string; valor: number };
const TONS = ["var(--brand)", "var(--ink-3)", "var(--s-neutra)", "var(--line-strong)"];

export function Rosca({ fatias, centro }: { fatias: Fatia[]; centro: { num: string; rot: string } }) {
  const f = fatias.filter((x) => x.valor > 0).sort((a, b) => b.valor - a.valor).slice(0, 4);
  const tot = f.reduce((s, x) => s + x.valor, 0);
  if (!tot) return <p className="mp-vazio">Sem dados neste mês.</p>;
  const r = 52;
  const C = 2 * Math.PI * r;
  let acum = 0;
  return (
    <div className="mp-donut">
      <svg viewBox="0 0 148 148" role="img" aria-label={f.map((x) => `${x.rotulo}: ${pctTxt((x.valor / tot) * 100, 0)}`).join("; ")}>
        {f.map((x, i) => {
          const len = (x.valor / tot) * C;
          const arco = (
            <circle
              key={x.rotulo}
              cx={74}
              cy={74}
              r={r}
              fill="none"
              stroke={TONS[i]}
              strokeWidth={24}
              strokeDasharray={`${Math.max(len - (f.length > 1 ? 1.5 : 0), 0.5)} ${C}`}
              strokeDashoffset={-acum}
              transform="rotate(-90 74 74)"
            >
              <title>{`${x.rotulo}\n${num(x.valor)} (${pctTxt((x.valor / tot) * 100, 1)})`}</title>
            </circle>
          );
          acum += len;
          return arco;
        })}
        <text className="mp-c-num" x={74} y={76} textAnchor="middle" style={{ fontSize: `${Math.max(Math.min(21, 70 / (centro.num.length * 0.58)), 11).toFixed(1)}px` }}>
          {centro.num}
        </text>
        <text className="mp-c-rot" x={74} y={91} textAnchor="middle">
          {centro.rot}
        </text>
      </svg>
      <ul className="mp-donut-leg">
        {f.map((x, i) => (
          <li key={x.rotulo} style={{ "--c": TONS[i] } as React.CSSProperties}>
            <i />
            <span>{x.rotulo}</span>
            <span className="v">
              {num(x.valor)}
              <small>{pctTxt((x.valor / tot) * 100, 0)}</small>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Comparação com sentido: ▲ verde quando melhora, ▼ vermelho quando piora. */
export function Delta({ v, sufixo, d = 0, unidade = "%" }: { v: number | null; sufixo?: ReactNode; d?: number; unidade?: "%" | "pp" }) {
  if (v == null || Number.isNaN(v)) return null;
  const igual = Math.abs(v) < 0.05;
  const cls = igual ? "igual" : v >= 0 ? "sobe" : "desce";
  const corpo = `${num(Math.abs(v), d)}${unidade === "pp" ? " pp" : "%"}`;
  return (
    <>
      <span className={`mp-delta ${cls}`}>
        {igual ? "● " : v >= 0 ? "▲ +" : "▼ −"}
        {corpo}
      </span>{" "}
      {sufixo}
    </>
  );
}
