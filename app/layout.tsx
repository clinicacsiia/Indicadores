import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Figtree } from "next/font/google";
import "./globals.css";

const figtree = Figtree({
  subsets: ["latin", "latin-ext"],
  variable: "--font-figtree",
  display: "swap",
});

const bricolage = Bricolage_Grotesque({
  subsets: ["latin", "latin-ext"],
  variable: "--font-bricolage",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Indicadores | Clínica CSI",
    template: "%s | Indicadores · Clínica CSI",
  },
  description: "Painel de indicadores da Clínica CSI: agendamentos, atendimentos e valores por dia.",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0b2623" },
    { media: "(prefers-color-scheme: dark)", color: "#07110f" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR" className={`${figtree.variable} ${bricolage.variable}`}>
      <body>{children}</body>
    </html>
  );
}
