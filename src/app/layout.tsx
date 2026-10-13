import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Clínica CSI · Indicadores", description: "Painel gerencial da Clínica CSI", robots: { index: false, follow: false } };
export const viewport: Viewport = { width: "device-width", initialScale: 1, colorScheme: "light dark" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
