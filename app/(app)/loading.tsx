export default function Loading() {
  return (
    <div role="status" aria-live="polite" aria-busy="true" style={{ display: "contents" }}>
      <span className="sr-only">Carregando…</span>
      <div className="page-head" aria-hidden="true">
        <div className="page-head-text" style={{ gap: 10 }}>
          <div className="skeleton" style={{ width: 90, height: 14 }} />
          <div className="skeleton" style={{ width: 220, height: 36 }} />
          <div className="skeleton" style={{ width: 300, height: 16 }} />
        </div>
        <div className="skeleton" style={{ width: 200, height: 32, borderRadius: 999 }} />
      </div>
      <div className="skeleton" style={{ height: 84, borderRadius: 16 }} aria-hidden="true" />
      <div className="kpis" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton" style={{ height: 156, borderRadius: 16 }} />
        ))}
      </div>
      <div className="skeleton" style={{ height: 360, borderRadius: 16 }} aria-hidden="true" />
    </div>
  );
}
