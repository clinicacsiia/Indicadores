// Mini gráfico de tendência para os cards. Só desenha; os valores exatos ficam
// no card e na tabela. O ponto final é um elemento HTML para não distorcer com
// o preserveAspectRatio="none" do SVG.
export function Sparkline({ valores, cor }: { valores: number[]; cor: string }) {
  if (valores.length === 0) return <div className="spark" aria-hidden="true" />;

  const W = 100;
  const H = 40;
  const pad = 5;
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const faixa = max - min || 1;

  const pontos = valores.map((v, i) => {
    const x = valores.length === 1 ? W / 2 : (i / (valores.length - 1)) * W;
    // Série constante fica no meio em vez de colar na base.
    const y = max === min ? H / 2 : pad + (1 - (v - min) / faixa) * (H - pad * 2);
    return { x, y };
  });

  const linha = pontos.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
  const area = `${linha} L${pontos[pontos.length - 1].x.toFixed(2)} ${H} L${pontos[0].x.toFixed(2)} ${H} Z`;
  const ultimo = pontos[pontos.length - 1];

  return (
    <div className="spark" style={{ "--swatch": cor } as React.CSSProperties} aria-hidden="true">
      {pontos.length > 1 && (
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <path d={area} fill={cor} fillOpacity="0.1" />
          <path
            d={linha}
            fill="none"
            stroke={cor}
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      )}
      <span
        className="spark-dot"
        style={{ left: `${ultimo.x}%`, top: `${(ultimo.y / H) * 100}%` }}
      />
    </div>
  );
}
