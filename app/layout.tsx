import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Indicadores",
  description: "Painel de indicadores conectado ao Supabase",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
