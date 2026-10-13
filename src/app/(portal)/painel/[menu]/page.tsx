import { notFound } from "next/navigation";
import { ehMenu, NOME_DO_MENU } from "@/klingo/config";
import { exigirSessao, podeVerMenu } from "@/lib/sessao";
import PainelFrame from "./PainelFrame";

export async function generateMetadata({ params }: { params: Promise<{ menu: string }> }) {
  const { menu } = await params;
  return { title: `${ehMenu(menu) ? NOME_DO_MENU[menu] : "Painel"} · Clínica CSI` };
}

export default async function Painel({ params, searchParams }: { params: Promise<{ menu: string }>; searchParams: Promise<{ de?: string; ate?: string; visao?: string }> }) {
  const { menu } = await params;
  const sp = await searchParams;
  const sessao = await exigirSessao();
  if (!ehMenu(menu) || !podeVerMenu(sessao, menu)) notFound();
  const q = new URLSearchParams();
  for (const k of ["de", "ate", "visao"] as const) if (sp[k] && /^[\w.-]{1,20}$/.test(sp[k]!)) q.set(k, sp[k]!);
  return <PainelFrame menu={menu} consulta={q.toString()} />;
}
