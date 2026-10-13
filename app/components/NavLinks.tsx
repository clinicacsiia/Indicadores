"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconConfig, IconMetas, IconPainel } from "./icons";
import type { Painel } from "@/lib/paineis";

export function NavLinks({ isAdmin, paineis }: { isAdmin: boolean; paineis: Painel[] }) {
  const pathname = usePathname();

  const links = [
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
        </Link>
      ))}
    </nav>
  );
}
