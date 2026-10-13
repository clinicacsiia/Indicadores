"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconConfig, IconMetas, IconRelatorios } from "./icons";

export function NavLinks({ isAdmin }: { isAdmin: boolean }) {
  const pathname = usePathname();

  const links = [
    { href: "/", rotulo: "Relatórios", icone: <IconRelatorios />, ativo: pathname === "/" },
    { href: "/metas", rotulo: "Metas", icone: <IconMetas />, ativo: pathname.startsWith("/metas") },
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
        </Link>
      ))}
    </nav>
  );
}
