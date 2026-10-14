import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS, podeVerPainel } from "@/lib/paineis";
import { IconAlerta } from "@/app/components/icons";
import { PainelFrame } from "./PainelFrame";

type Props = { params: Promise<{ id: string }>; searchParams: Promise<{ de?: string; ate?: string }> };

// Período do filtro: mês inteiro (AAAA-MM) ou dia exato (AAAA-MM-DD); o painel Python confere de novo.
const PERIODO_RE = /^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$/;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const painel = PAINEIS.find((p) => p.id === id);
  return { title: painel?.nome ?? "Painel" };
}

// Os painéis são calculados por funções Python da Vercel (api/painel.py) e entregues como uma página
// completa; aqui ela aparece num iframe do mesmo site (mesma sessão de login). O servidor Python confere
// o login e a permissão de novo — esta checagem só evita mostrar uma tela de erro dentro do quadro.
export default async function PainelPage({ params, searchParams }: Props) {
  const { id } = await params;
  const { de, ate } = await searchParams;
  const painel = PAINEIS.find((p) => p.id === id);
  if (!painel) notFound();

  const profile = await getCurrentProfile();
  if (!podeVerPainel(profile, id)) {
    return (
      <section className="panel empty">
        <h2>Sem acesso a {painel.nome}</h2>
        <p>Peça a um administrador para liberar este painel em Configurações.</p>
      </section>
    );
  }

  const q = new URLSearchParams({ id });
  if (de && ate && PERIODO_RE.test(de) && PERIODO_RE.test(ate)) {
    q.set("de", de);
    q.set("ate", ate);
  }

  return (
    <>
      <noscript>
        <div className="notice" role="alert">
          <IconAlerta />
          Ative o JavaScript para ver o painel.
        </div>
      </noscript>
      <PainelFrame titulo={painel.nome} src={`/api/painel?${q.toString()}`} />
    </>
  );
}
