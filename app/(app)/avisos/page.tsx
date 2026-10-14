import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS, podeVerPainel } from "@/lib/paineis";
import { IconAlerta } from "@/app/components/icons";
import {
  CAMPOS_AVISO,
  DIAS_RESOLVIDOS,
  PESO_NIVEL,
  voltou,
  type Aviso,
  type EventoAviso,
} from "@/lib/avisos";
import { AvisoCard } from "./AvisoCard";

export const metadata: Metadata = { title: "Avisos" };

type Props = { searchParams: Promise<{ painel?: string; situacao?: string; aviso?: string }> };

const SITUACOES = [
  { id: "abertos", rotulo: "Abertos" },
  { id: "voltaram", rotulo: "Voltaram a acontecer" },
  { id: "fechados", rotulo: "Fechados com justificativa" },
  { id: "resolvidos", rotulo: "Resolvidos" },
  { id: "todos", rotulo: "Todos" },
] as const;
type Situacao = (typeof SITUACOES)[number]["id"];

const ehSituacao = (s: string | undefined): s is Situacao => SITUACOES.some((x) => x.id === s);

function href(painel: string, situacao: Situacao) {
  const q = new URLSearchParams();
  if (painel) q.set("painel", painel);
  if (situacao !== "abertos") q.set("situacao", situacao);
  const s = q.toString();
  return s ? `/avisos?${s}` : "/avisos";
}

function filtra(a: Aviso, situacao: Situacao) {
  switch (situacao) {
    case "abertos":
      return a.status === "aberto";
    case "voltaram":
      return voltou(a);
    case "fechados":
      return a.status === "justificado";
    case "resolvidos":
      return a.status === "resolvido";
    default:
      return true;
  }
}

// Mais urgente primeiro: os que voltaram, depois os mais graves, depois os mais recentes.
function ordem(a: Aviso, b: Aviso) {
  return (
    Number(voltou(b)) - Number(voltou(a)) ||
    PESO_NIVEL[b.nivel] - PESO_NIVEL[a.nivel] ||
    b.ultima_deteccao.localeCompare(a.ultima_deteccao)
  );
}

export default async function AvisosPage({ searchParams }: Props) {
  const { painel: painelParam, situacao: situacaoParam, aviso: avisoParam } = await searchParams;
  const supabase = await createClient();
  const profile = await getCurrentProfile();
  const ehAdmin = profile?.role === "admin";

  // RLS (can_view_painel) já entrega só o que a pessoa pode ver; o administrador vê todos os painéis.
  const { data, error } = await supabase.from("aviso").select(CAMPOS_AVISO).order("id", { ascending: true });
  if (error) console.error("Falha ao carregar avisos:", error.message);

  const limite = Date.now() - DIAS_RESOLVIDOS * 86_400_000;
  const todos = ((data ?? []) as unknown as Aviso[]).filter(
    (a) => a.status !== "resolvido" || a.recorrencias > 0 || (a.resolvido_em && new Date(a.resolvido_em).getTime() > limite),
  );

  // Vindo do botão "Justificar e fechar" do painel: leva direto ao aviso.
  if (painelParam && avisoParam) {
    const alvo = todos.find((a) => a.painel === painelParam && a.chave === avisoParam);
    if (alvo) redirect(`/avisos?painel=${encodeURIComponent(alvo.painel)}&situacao=todos#aviso-${alvo.id}`);
  }

  const painelesComAviso = PAINEIS.filter((p) => podeVerPainel(profile, p.id) && todos.some((a) => a.painel === p.id));
  const painelEscolhido = painelesComAviso.some((p) => p.id === painelParam) ? (painelParam as string) : "";
  const situacao: Situacao = ehSituacao(situacaoParam) ? situacaoParam : "abertos";

  const doPainel = painelEscolhido ? todos.filter((a) => a.painel === painelEscolhido) : todos;
  const mostrados = doPainel.filter((a) => filtra(a, situacao)).sort(ordem);

  const contagem = Object.fromEntries(SITUACOES.map((s) => [s.id, doPainel.filter((a) => filtra(a, s.id)).length])) as Record<Situacao, number>;
  const criticosAbertos = doPainel.filter((a) => a.status === "aberto" && a.nivel === "critico").length;

  // Histórico só dos avisos que aparecem agora.
  let eventos: EventoAviso[] = [];
  if (mostrados.length) {
    const { data: ev, error: erroEv } = await supabase
      .from("aviso_evento")
      .select("id, aviso_id, quando, tipo, usuario, detalhe")
      .in("aviso_id", mostrados.map((a) => a.id))
      .order("quando", { ascending: false })
      .order("id", { ascending: false })
      .limit(3000);
    if (erroEv) console.error("Falha ao carregar o histórico dos avisos:", erroEv.message);
    eventos = (ev ?? []) as EventoAviso[];
  }
  const eventosDo = (id: number) => eventos.filter((e) => e.aviso_id === id);

  // Agrupa por painel, na ordem do menu.
  const grupos = PAINEIS.map((p) => ({ painel: p, itens: mostrados.filter((a) => a.painel === p.id) })).filter((g) => g.itens.length);

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Avisos</h1>
          <p className="page-lede">
            {ehAdmin
              ? "As pendências de todos os painéis. "
              : "As pendências dos painéis que você pode ver. "}
            Para fechar um aviso é preciso justificar. O painel confere a cada atualização dos dados: se o problema sumir, o aviso fica resolvido; se
            continuar ou voltar, ele reabre e mostra quantas vezes isso aconteceu.
          </p>
        </div>
      </header>

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar os avisos agora. Tente novamente em instantes.
        </div>
      )}

      <section className="avisos-resumo" aria-label="Resumo">
        <div className="panel avisos-numero" data-tom={contagem.abertos ? (criticosAbertos ? "critico" : "atencao") : "ok"}>
          <span className="avisos-numero-valor">{contagem.abertos}</span>
          <span className="avisos-numero-rotulo">Abertos{criticosAbertos > 0 && ` · ${criticosAbertos} crítico${criticosAbertos === 1 ? "" : "s"}`}</span>
        </div>
        <div className="panel avisos-numero" data-tom={contagem.voltaram ? "atencao" : "ok"}>
          <span className="avisos-numero-valor">{contagem.voltaram}</span>
          <span className="avisos-numero-rotulo">Voltaram a acontecer</span>
        </div>
        <div className="panel avisos-numero">
          <span className="avisos-numero-valor">{contagem.fechados}</span>
          <span className="avisos-numero-rotulo">Fechados com justificativa</span>
        </div>
        <div className="panel avisos-numero">
          <span className="avisos-numero-valor">{contagem.resolvidos}</span>
          <span className="avisos-numero-rotulo">Resolvidos (últimos {DIAS_RESOLVIDOS} dias)</span>
        </div>
      </section>

      <nav className="avisos-filtros" aria-label="Filtros">
        <div className="avisos-filtro-grupo" role="group" aria-label="Situação">
          {SITUACOES.map((s) => (
            <Link key={s.id} href={href(painelEscolhido, s.id)} className="avisos-filtro" aria-current={situacao === s.id ? "true" : undefined}>
              {s.rotulo}
              <span className="avisos-filtro-n">{contagem[s.id]}</span>
            </Link>
          ))}
        </div>
        {painelesComAviso.length > 1 && (
          <div className="avisos-filtro-grupo" role="group" aria-label="Painel">
            <Link href={href("", situacao)} className="avisos-filtro" aria-current={!painelEscolhido ? "true" : undefined}>
              Todos os painéis
            </Link>
            {painelesComAviso.map((p) => (
              <Link key={p.id} href={href(p.id, situacao)} className="avisos-filtro" aria-current={painelEscolhido === p.id ? "true" : undefined}>
                {p.nome}
                <span className="avisos-filtro-n">{todos.filter((a) => a.painel === p.id && a.status === "aberto").length}</span>
              </Link>
            ))}
          </div>
        )}
      </nav>

      {!error && grupos.length === 0 && (
        <section className="panel empty">
          <h2>{todos.length === 0 ? "Nenhum aviso ainda" : "Nada por aqui"}</h2>
          <p>
            {todos.length === 0
              ? "Os avisos aparecem quando um painel é atualizado e encontra algo para corrigir."
              : situacao === "abertos"
                ? "Nenhum aviso aberto neste filtro. Tudo em ordem."
                : "Nenhum aviso nesta situação."}
          </p>
        </section>
      )}

      {grupos.map(({ painel, itens }) => (
        <section key={painel.id} className="avisos-grupo" aria-labelledby={`grupo-${painel.id}`}>
          <h2 className="panel-title avisos-grupo-titulo" id={`grupo-${painel.id}`}>
            {painel.nome}
            <span className="avisos-grupo-n">{itens.length}</span>
            <Link href={`/painel/${painel.id}`} className="avisos-grupo-link">
              Abrir painel
            </Link>
          </h2>
          <div className="avisos-lista">
            {itens.map((a) => (
              <AvisoCard key={a.id} aviso={a} eventos={eventosDo(a.id)} />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
