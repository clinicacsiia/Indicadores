"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconAviso, IconConfig, IconInicio, IconMetas, IconPainel, IconCrm } from "./icons";
import type { Painel } from "@/lib/paineis";

type Props = {
  isAdmin: boolean;
  paineis: Painel[];
  // Aba CRM Ressonância: aparece só para quem pode ver os indicadores ou preencher o formulário.
  crmRm: boolean;
  // Avisos abertos que esta pessoa pode ver (e quantos são críticos), para o contador do menu.
  avisos: { abertos: number; criticos: number };
  // Pedidos de acesso aguardando aprovação (só o administrador vê), para o contador de Configurações.
  pedidos: number;
};

export function NavLinks({ isAdmin, paineis, crmRm, avisos, pedidos }: Props) {
  const pathname = usePathname();

  const links: {
    href: string;
    rotulo: string;
    icone: React.ReactNode;
    ativo: boolean;
    contador?: number;
    critico?: boolean;
    textoContador?: (n: number) => string;
  }[] = [
    { href: "/", rotulo: "Início", icone: <IconInicio />, ativo: pathname === "/" },
    {
      href: "/avisos",
      rotulo: "Avisos",
      icone: <IconAviso />,
      ativo: pathname.startsWith("/avisos"),
      contador: avisos.abertos,
      critico: avisos.criticos > 0,
      textoContador: (n) => `${n} ${n === 1 ? "aviso aberto" : "avisos abertos"}`,
    },
    { href: "/metas", rotulo: "Metas", icone: <IconMetas />, ativo: pathname.startsWith("/metas") },
    ...(crmRm ? [{ href: "/crm-rm", rotulo: "CRM Ressonância", icone: <IconCrm />, ativo: pathname.startsWith("/crm-rm") }] : []),
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
            contador: pedidos,
            critico: pedidos > 0,
            textoContador: (n: number) => `${n} ${n === 1 ? "pedido de acesso aguardando" : "pedidos de acesso aguardando"} aprovação`,
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
                {l.textoContador?.(l.contador)}
              </span>
            </span>
          ) : null}
        </Link>
      ))}
    </nav>
  );
}
