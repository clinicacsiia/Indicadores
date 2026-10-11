"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type PontoDia = {
  dia: string; // AAAA-MM-DD
  agendados: number | null;
  realizados: number | null;
};

const SERIES = [
  { chave: "agendados", rotulo: "Agendamentos", cor: "var(--s-agendados)" },
  { chave: "realizados", rotulo: "Atendimentos finalizados", cor: "var(--s-realizados)" },
] as const;

const MARGEM = { topo: 14, direita: 16, base: 30, esquerda: 44 };

const inteiro = new Intl.NumberFormat("pt-BR");
const compacto = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

function ms(iso: string) {
  return Date.parse(`${iso}T12:00:00Z`);
}

function curto(iso: string) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

function longo(iso: string) {
  const data = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "UTC",
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(ms(iso)));
  return data.replace(".", "");
}

// Escolhe de 3 a 5 marcas "redondas" até o máximo (0, 50, 100...).
function marcasDoEixo(max: number) {
  if (max <= 0) return { topo: 4, marcas: [0, 1, 2, 3, 4] };
  const bruto = max / 4;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const frac = bruto / potencia;
  const passo = (frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 2.5 ? 2.5 : frac <= 5 ? 5 : 10) * potencia;
  const marcas: number[] = [];
  for (let v = 0; v <= max + passo * 0.999; v += passo) marcas.push(Math.round(v * 100) / 100);
  return { topo: marcas[marcas.length - 1], marcas };
}

export function TendenciaChart({ dados }: { dados: PontoDia[] }) {
  const caixa = useRef<HTMLDivElement>(null);
  const [largura, setLargura] = useState(720);
  const [ativo, setAtivo] = useState<number | null>(null);

  useEffect(() => {
    const el = caixa.current;
    if (!el) return;
    const medir = () => setLargura(Math.max(260, Math.floor(el.clientWidth)));
    medir();
    const obs = new ResizeObserver(medir);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const altura = largura < 520 ? 220 : 280;
  const areaL = largura - MARGEM.esquerda - MARGEM.direita;
  const areaA = altura - MARGEM.topo - MARGEM.base;

  const { eixo, xs, inicio, fim } = useMemo(() => {
    const maior = Math.max(0, ...dados.flatMap((d) => [d.agendados ?? 0, d.realizados ?? 0]));
    const t = dados.map((d) => ms(d.dia));
    return { eixo: marcasDoEixo(maior), xs: t, inicio: t[0] ?? 0, fim: t[t.length - 1] ?? 0 };
  }, [dados]);

  const x = (i: number) =>
    dados.length === 1 || fim === inicio
      ? MARGEM.esquerda + areaL / 2
      : MARGEM.esquerda + ((xs[i] - inicio) / (fim - inicio)) * areaL;
  const y = (v: number) => MARGEM.topo + (1 - v / eixo.topo) * areaA;

  const caminho = (chave: "agendados" | "realizados") => {
    let d = "";
    let emSegmento = false;
    dados.forEach((p, i) => {
      const v = p[chave];
      if (v === null) {
        emSegmento = false;
        return;
      }
      d += `${emSegmento ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
      emSegmento = true;
    });
    return d.trim();
  };

  // Rótulos do eixo X: poucos e espaçados, sempre incluindo primeiro e último.
  const qtdRotulos = Math.max(2, Math.min(dados.length, Math.floor(areaL / 76)));
  const indicesRotulo = useMemo(() => {
    if (dados.length <= 1) return [0];
    // Marcas igualmente espaçadas no tempo; cada uma usa o dia com dados mais próximo.
    const set = new Set<number>();
    for (let k = 0; k < qtdRotulos; k++) {
      const alvo = inicio + (k / (qtdRotulos - 1)) * (fim - inicio);
      let melhor = 0;
      for (let i = 1; i < xs.length; i++) {
        if (Math.abs(xs[i] - alvo) < Math.abs(xs[melhor] - alvo)) melhor = i;
      }
      set.add(melhor);
    }
    return [...set].sort((a, b) => a - b);
  }, [dados.length, qtdRotulos, xs, inicio, fim]);

  function indiceMaisProximo(clientX: number, rect: DOMRect) {
    const px = clientX - rect.left;
    let melhor = 0;
    let menor = Infinity;
    for (let i = 0; i < dados.length; i++) {
      const dist = Math.abs(x(i) - px);
      if (dist < menor) {
        menor = dist;
        melhor = i;
      }
    }
    return melhor;
  }

  function aoTeclar(e: React.KeyboardEvent) {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const passo = e.key === "ArrowRight" ? 1 : -1;
      setAtivo((atual) => {
        const base = atual ?? (passo === 1 ? -1 : dados.length);
        return Math.min(dados.length - 1, Math.max(0, base + passo));
      });
    } else if (e.key === "Escape") {
      setAtivo(null);
    }
  }

  const dest = ativo !== null ? dados[ativo] : null;
  const ultimo = dados.length - 1;
  const tooltipEsquerda = ativo !== null && x(ativo) > largura * 0.6;

  const resumo = SERIES.map((s) => {
    const total = dados.reduce((acc, d) => acc + (d[s.chave] ?? 0), 0);
    return `${s.rotulo}: ${inteiro.format(total)} no período`;
  }).join(". ");

  return (
    <div className="chart" ref={caixa}>
      <svg
        width={largura}
        height={altura}
        viewBox={`0 0 ${largura} ${altura}`}
        role="img"
        aria-label={`Gráfico de linhas por dia. ${resumo}. A tabela abaixo traz os valores de cada dia.`}
        tabIndex={0}
        onKeyDown={aoTeclar}
        onBlur={() => setAtivo(null)}
        onPointerMove={(e) => setAtivo(indiceMaisProximo(e.clientX, e.currentTarget.getBoundingClientRect()))}
        onPointerLeave={() => setAtivo(null)}
      >
        {eixo.marcas.map((v) => (
          <g key={v}>
            <line
              className={v === 0 ? "chart-axis" : "chart-grid"}
              x1={MARGEM.esquerda}
              x2={largura - MARGEM.direita}
              y1={y(v)}
              y2={y(v)}
            />
            <text x={MARGEM.esquerda - 8} y={y(v)} textAnchor="end" dominantBaseline="middle">
              {compacto.format(v)}
            </text>
          </g>
        ))}

        {indicesRotulo.map((i, k) => (
          <text
            key={dados[i].dia}
            x={x(i)}
            y={altura - 8}
            textAnchor={dados.length === 1 ? "middle" : k === 0 ? "start" : k === indicesRotulo.length - 1 ? "end" : "middle"}
          >
            {curto(dados[i].dia)}
          </text>
        ))}

        {ativo !== null && (
          <line
            className="chart-cross"
            x1={x(ativo)}
            x2={x(ativo)}
            y1={MARGEM.topo}
            y2={MARGEM.topo + areaA}
          />
        )}

        {SERIES.map((s) => (
          <g key={s.chave}>
            {dados.length > 1 && (
              <path
                d={caminho(s.chave)}
                fill="none"
                stroke={s.cor}
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {/* Ponto final (ou o dia sob o cursor), com anel da cor da superfície. */}
            {[ativo ?? ultimo].map((i) => {
              const v = dados[i]?.[s.chave];
              return v === null || v === undefined ? null : (
                <circle
                  key={i}
                  cx={x(i)}
                  cy={y(v)}
                  r="4.5"
                  fill={s.cor}
                  stroke="var(--surface)"
                  strokeWidth="2"
                />
              );
            })}
          </g>
        ))}
      </svg>

      {dest && ativo !== null && (
        <div
          className="chart-tooltip"
          style={{
            left: tooltipEsquerda ? undefined : x(ativo) + 14,
            right: tooltipEsquerda ? largura - x(ativo) + 14 : undefined,
          }}
          role="status"
        >
          <div className="chart-tooltip-title">{longo(dest.dia)}</div>
          {SERIES.map((s) => (
            <div className="chart-tooltip-row" key={s.chave}>
              <span className="legend-line" style={{ "--swatch": s.cor } as React.CSSProperties} />
              {s.rotulo}
              <strong>{dest[s.chave] === null ? "—" : inteiro.format(dest[s.chave]!)}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
