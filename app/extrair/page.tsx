import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS } from "@/lib/paineis";
import { paineisParaExtrair } from "@/lib/extrair";
import { Impressao } from "./Impressao";

export const metadata: Metadata = { title: "Extrair relatórios" };

type Props = { searchParams: Promise<{ p?: string }> };

// Página só para imprimir/salvar em PDF (sem menu). Como a Configuração, é só do administrador.
export default async function ExtrairPage({ searchParams }: Props) {
  const { p } = await searchParams;
  const profile = await getCurrentProfile();
  if (profile?.role !== "admin") redirect("/");

  const paineis = paineisParaExtrair(p, PAINEIS);
  if (paineis.length === 0) redirect("/configuracoes?aba=extrair");

  return <Impressao paineis={paineis.map((x) => ({ id: x.id, nome: x.nome }))} />;
}
