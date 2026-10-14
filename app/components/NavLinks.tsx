"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconAviso, IconConfig, IconInicio, IconMetas, IconPainel } from "./icons";
import type { Painel } from "@/lib/paineis";

type Props = {
  isAdmin: boolean;
  paineis: Painel[];
  // Avisos abertos que esta pessoa pode ver (e quantos são críticos), para o contador do menu.
  avisos: { abertos: number; criticos: number };
};

export function NavLinks({ isAdmin, paineis, avisos }: Props) {
  const pathname = usePathname();

  const links: {
    href: string;
    rotulo: string;
    icone: React.ReactNode;
    ativo: boolean;
    contador?: number;
    critico?: boolean;
  }[] = [
    { href: "/", rotulo: "Início", icone: <IconInicio />, ativo: pathname === "/" },
    {
      href: "/avisos",
      rotulo: "Avisos",
      icone: <IconAviso />,
      ativo: pathname.startsWith("/avisos"),
      contador: avisos.abertos,
      critico: avisos.criticos > 0,
    },
    { href: "/metas", rotulo: "Metas", icone: <IconMetas />, ativo: pathname.startsWith("/metas") },
    ...paineis.map((p) => ({
      href: `/painel/${p.id}`,
      rotulo: p.nome,
      icone: <IconPainel />,
      ativo: pathname === `/painel/${p.id}`,
    })),
    ...(isAdmin
      ? [
          {
            href: "/configuracoes",
            rotulo: "Configurações",
            icone: <IconConfig />,
            ativo: pathname.startsWith("/configuracoes"),
          },
        ]
      : []),
  ];

  return (
    <nav className="sidebar-nav" aria-label="Principal">
      <span className="nav-title">Menu</span>
      {links.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className="nav-link"
          aria-current={l.ativo ? "page" : undefined}
        >
          {l.icone}
          {l.rotulo}
          {l.contador ? (
            <span className="nav-contador" data-critico={l.critico ? "true" : undefined}>
              <span aria-hidden="true">{l.contador > 99 ? "99+" : l.contador}</span>
              <span className="sr-only">
                {l.contador} {l.contador === 1 ? "aviso aberto" : "avisos abertos"}
              </span>
            </span>
          ) : null}
        </Link>
      ))}
    </nav>
  );
}
