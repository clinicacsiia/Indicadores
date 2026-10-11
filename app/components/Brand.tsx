import Link from "next/link";

export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="9" fill="#1553b8" />
      <rect x="7" y="16" width="4.5" height="9" rx="1.6" fill="#fff" fillOpacity="0.55" />
      <rect x="13.75" y="11" width="4.5" height="14" rx="1.6" fill="#fff" fillOpacity="0.8" />
      <rect x="20.5" y="6" width="4.5" height="19" rx="1.6" fill="#fff" />
    </svg>
  );
}

// "Clínica CSI" é a marca; "Indicadores" é o nome do sistema.
export function Brand({ href }: { href?: string }) {
  const content = (
    <>
      <BrandMark />
      <span className="brand-text">
        <span className="brand-name">Clínica CSI</span>
        <span className="brand-sub">Indicadores</span>
      </span>
    </>
  );

  return href ? (
    <Link href={href} className="brand" aria-label="Clínica CSI Indicadores, ir para Relatórios">
      {content}
    </Link>
  ) : (
    <div className="brand">{content}</div>
  );
}
