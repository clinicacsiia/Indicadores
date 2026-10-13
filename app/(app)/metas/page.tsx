import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { IconAlerta, IconCalendario } from "@/app/components/icons";
import { AtualizarForm } from "../atualizar-form";
import { metasConfig, RELATORIO_METAS } from "@/lib/metas/config";
import {
  agoraSaoPaulo,
  calcularMes,
  fimDoMes,
  mesesDisponiveis,
  LIMITE_ATENCAO,
  type LinhaAtendimento,
  type ResultadoItem,
  type ResultadoMes,
  type Situacao,
} from "@/lib/metas/calculo";
import { Barras, Delta, Linhas, Rosca, pctTxt, type ItemBarra } from "./graficos";

// A atualização (server action do formulário) espera as Edge Functions falarem com o Klingo.
export const maxDuration = 300;

export const metadata: Metadata = { title: "Metas" };

const MES_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const MESES = [
  "Janeiro",
  "Fevereiro",
  "Março",
  "Abril",
  "Maio",
  "Junho",
  "Julho",
  "Agosto",
  "Setembro",
  "Outubro",
  "Novembro",
  "Dezembro",
];
const ROTULO_SITUACAO: Record<Situacao, string> = {
  batida: "Meta batida",
  ritmo: "No ritmo",
  atencao: "Atenção",
  atrasado: "Atrasado",
};
const HORAS_ATE_DESATUALIZADO = 36;

const inteiro = new Intl.NumberFormat("pt-BR");
const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

const pctTexto = (v: number) => `${umaCasa.format(v)}%`;
const rotuloMes = (mes: string) => `${MESES[Number(mes.slice(5)) - 1]}/${mes.slice(0, 4)}`;
const rotuloMesCurto = (mes: string) => `${MESES[Number(mes.slice(5)) - 1].slice(0, 3)}/${mes.slice(2, 4)}`;
const dataCurta = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

type RespostaMetas = {
  mapeado: boolean;
  convenio?: boolean;
  linhas?: LinhaAtendimento[];
  ultimo_sync?: string | null;
  ultimo_dia?: string | null;
  dias_sincronizados?: number;
};

const ROTULO_FECHADO: Record<Situacao, string> = {
  batida: "Meta batida",
  ritmo: "No ritmo",
  atencao: "Quase lá",
  atrasado: "Abaixo da meta",
};

function SituacaoPill({ valor, fechado = false }: { valor: Situacao; fechado?: boolean }) {
  return (
    <span className="status-pill" data-status={valor}>
      {(fechado ? ROTULO_FECHADO : ROTULO_SITUACAO)[valor]}
    </span>
  );
}

const dataBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const corDe = (s: Situacao): "crit" | "warn" | undefined => (s === "atrasado" ? "crit" : s === "atencao" ? "warn" : undefined);
const dias1 = (v: number) => umaCasa.format(Number(v.toFixed(1)));

/** Projeção de fechamento do conjunto: cada meta limitada a 100%, como no percentual geral. */
function projecaoGeral(r: ResultadoMes): number | null {
  const itens = r.grupos.flatMap((g) => g.itens);
  const meta = itens.reduce((s, i) => s + i.meta, 0);
  return meta ? (itens.reduce((s, i) => s + Math.min(i.projecao ?? i.realizado, i.meta), 0) / meta) * 100 : null;
}

/** Mesmo ponto do mês anterior: atendimentos e % acumulado até o último dia completo. */
function pontoComparavel(r: ResultadoMes, ant: ResultadoMes | null) {
  if (!ant || !r.serie.length || !ant.serie.length) return null;
  const hojeDia = r.serie.filter((d) => d.n != null).length;
  const k = r.fechado ? r.serie.length : hojeDia - 1;
  if (k < 1 || ant.serie.length < k) return null;
  const antK = r.fechado ? ant.serie.length : k;
  const somaN = (x: ResultadoMes, n: number) => x.serie.slice(0, n).reduce((s, d) => s + (d.n ?? 0), 0);
  return {
    k,
    curN: somaN(r, k),
    antN: somaN(ant, antK),
    curPct: r.serie[k - 1].pct ?? 0,
    antPct: ant.serie[antK - 1].pct ?? 0,
    total: r.fechado,
  };
}

function Secao({ n, titulo, children }: { n: string; titulo: string; children: ReactNode }) {
  return (
    <div className="mp-tier">
      <div className="mp-tier-h">
        <b>{n}</b>
        <span>{titulo}</span>
      </div>
      {children}
    </div>
  );
}

function Kpi({ rotulo, valor, destaque, comp, sub, ruim }: { rotulo: string; valor: ReactNode; destaque?: boolean; comp?: ReactNode; sub?: ReactNode; ruim?: boolean }) {
  return (
    <article className={`mp-kpi${destaque ? " destaque" : ""}`}>
      <h3 className="mp-kpi-rot">{rotulo}</h3>
      <p className={`mp-kpi-num${ruim ? " ruim" : ""}`}>{valor}</p>
      {comp && <p className="mp-kpi-comp">{comp}</p>}
      {sub && <p className="mp-kpi-sub">{sub}</p>}
    </article>
  );
}

function Acordeao({ titulo, dica, children }: { titulo: string; dica?: string; children: ReactNode }) {
  return (
    <details className="mp-acord">
      <summary>
        {titulo}
        {dica && <small>{dica}</small>}
      </summary>
      <div className="mp-acord-corpo">{children}</div>
    </details>
  );
}

const NumCell = ({ children }: { children: ReactNode }) => <td className="n">{children}</td>;

export default async function MetasPage({ searchParams }: { searchParams: Promise<{ mes?: string }> }) {
  const profile = await getCurrentProfile();
  const podeVer = profile?.role === "admin" || profile?.permissions?.metas !== false;

  if (profile && !podeVer) {
    return (
      <>
        <header className="page-head">
          <div className="page-head-text">
            <span className="eyebrow">Clínica CSI</span>
            <h1 className="page-title">Metas</h1>
          </div>
        </header>
        <section className="panel empty">
          <span className="empty-icon">
            <IconAlerta size={26} />
          </span>
          <h2>Você ainda não tem acesso às Metas</h2>
          <p>Peça a um administrador para liberar o seu acesso em Configurações.</p>
        </section>
      </>
    );
  }

  const isAdmin = profile?.role === "admin";
  const agora = agoraSaoPaulo();
  const mesAtual = agora.hoje.slice(0, 7);
  const primeiroMes = metasConfig.primeiro_mes > mesAtual ? mesAtual : metasConfig.primeiro_mes;
  const meses = mesesDisponiveis(primeiroMes, mesAtual);

  const { mes: mesPedido } = await searchParams;
  const mes = mesPedido && MES_RE.test(mesPedido) && meses.includes(mesPedido) ? mesPedido : mesAtual;

  const supabase = await createClient();
  // Todos os meses até o escolhido: o anterior serve de comparação e o SUS x sem SUS mostra um mês por barra.
  const mesesAte = meses.filter((m) => m <= mes);
  const [respostasMeses, { data: catalogo }] = await Promise.all([
    // A função aplica a permissão "Pode ver Metas" e já entrega os atendimentos do mês contados.
    Promise.all(mesesAte.map((m) => supabase.rpc("metas_atendimentos_mes", { p_mes: m }))),
    isAdmin
      ? supabase.from("dim_relatorio").select("klingo_id, nome, ativo").eq("klingo_id", RELATORIO_METAS)
      : Promise.resolve({ data: null }),
  ]);

  const { data: bruto, error } = respostasMeses[0];
  // Nunca mostrar error.message na tela: pode conter detalhes internos do Postgres.
  if (error) console.error("Falha ao carregar atendimentos das metas:", error.message);

  const resposta = (bruto ?? null) as RespostaMetas | null;
  const calculados = mesesAte.map((m, i) => {
    const r = (respostasMeses[i].data ?? null) as RespostaMetas | null;
    const l = r?.mapeado ? (r.linhas ?? []) : [];
    return l.length > 0 ? calcularMes(metasConfig, m, l, agora) : null;
  });
  const resultado = calculados[0] ?? null;
  const ant = calculados[1] ?? null;

  const ultimoDia = mes === mesAtual ? agora.hoje : fimDoMes(mes);
  const primeiroDia = `${mes}-01`;

  let sync: { texto: string; estado: "ok" | "stale" | "none" } = { texto: "Ainda sem sincronização", estado: "none" };
  if (resposta?.ultimo_sync) {
    const quando = new Date(resposta.ultimo_sync);
    const horas = (Date.now() - quando.getTime()) / 36e5;
    const fmt = (opts: Intl.DateTimeFormatOptions) =>
      new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", ...opts }).format(quando);
    const mesmoDia = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(quando) === agora.hoje;
    sync = {
      texto: `Atualizado ${mesmoDia ? "hoje" : "em " + fmt({ day: "2-digit", month: "2-digit" })} às ${fmt({ timeStyle: "short" })}`,
      // Mês já fechado não envelhece: só avisa quando o mês corrente está sem atualização recente.
      estado: mes === mesAtual && horas > HORAS_ATE_DESATUALIZADO ? "stale" : "ok",
    };
  }

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Acompanhamento de Metas</h1>
          <p className="page-lede">
            {rotuloMes(mes)}
            {resposta?.ultimo_dia && ` · último atendimento: ${dataBR(resposta.ultimo_dia)}`}
            {resposta?.ultimo_sync &&
              ` · dados consultados no Klingo em ${new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" }).format(new Date(resposta.ultimo_sync))}`}
          </p>
        </div>
        <span className="chip" data-state={sync.estado}>
          <span className="chip-dot" aria-hidden="true" />
          {sync.texto}
        </span>
      </header>

      <section className="toolbar" aria-label="Mês">
        <div>
          <span className="toolbar-label" id="rotulo-meses">
            Mês
          </span>
          <div className="seg" role="group" aria-labelledby="rotulo-meses">
            {meses.map((m) => (
              <Link key={m} href={`/metas?mes=${m}`} className="seg-item" aria-current={m === mes ? "true" : undefined}>
                {rotuloMesCurto(m)}
              </Link>
            ))}
          </div>
        </div>
      </section>

      {isAdmin && catalogo && catalogo.length > 0 && (
        <AtualizarForm
          key={mes}
          relatorios={catalogo}
          relatorioPadrao={RELATORIO_METAS}
          de={primeiroDia}
          ate={ultimoDia}
          max={agora.hoje}
        />
      )}

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar as metas agora. Tente novamente em instantes.
        </div>
      )}

      {!error && !resultado && (
        <section className="panel empty">
          <span className="empty-icon">
            <IconCalendario size={26} />
          </span>
          <h2>Nenhum atendimento em {rotuloMes(mes)}</h2>
          <p>
            {isAdmin
              ? `Ainda não há atendimentos do relatório #${RELATORIO_METAS} para este mês. Use "Atualizar" acima para buscar no Klingo.`
              : "Ainda não há atendimentos sincronizados para este mês. Peça a um administrador para atualizar."}
          </p>
        </section>
      )}

      {resultado && <Painel r={resultado} ant={ant} historico={mesesAte.map((m, i) => ({ mes: m, r: calculados[i] })).reverse()} ultimoDia={resposta?.ultimo_dia ?? null} />}
    </>
  );
}

// ───────── o painel em si (mesmas seções do painel local: Resumo, Análise, Detalhes) ─────────

function Painel({
  r,
  ant,
  historico,
  ultimoDia,
}: {
  r: ResultadoMes;
  ant: ResultadoMes | null;
  historico: { mes: string; r: ResultadoMes | null }[];
  ultimoDia: string | null;
}) {
  const itens = r.grupos.flatMap((g) => g.itens.map((i) => ({ ...i, grupo: g.nome })));
  const aberto = !r.fechado && r.esperadoPct > 0;
  const marca = aberto ? r.esperadoPct : r.fechado ? 100 : null;
  const antRot = ant ? rotuloMes(ant.mes) : "";
  const pc = pontoComparavel(r, ant);
  const g = r.geral;
  const proj = projecaoGeral(r);
  const atras = itens.filter((i) => i.situacao === "atrasado").length;
  const aten = itens.filter((i) => i.situacao === "atencao").length;
  const frase: Record<Situacao, string> = {
    batida: "Todas as metas do mês foram batidas.",
    ritmo: r.fechado ? "Mês encerrado." : "No ritmo: o realizado está igual ou acima do esperado para hoje.",
    atencao: r.fechado ? "Mês encerrado, perto de fechar as metas." : "Atenção: o realizado está um pouco abaixo do esperado para hoje.",
    atrasado: r.fechado ? "Mês encerrado abaixo das metas." : "Atrasado: o realizado está bem abaixo do esperado para hoje.",
  };
  const contraAnt = pc ? `contra o mesmo ponto de ${antRot}${pc.total ? "" : ` (até o dia ${pc.k})`}` : "";

  // ritmo por meta ("o ritmo de hoje dá conta do que falta?")
  const ritmoMeta =
    r.fechado || r.diasDecorridos < 0.5
      ? []
      : itens
          .filter((i) => i.faltam > 0 && i.porDia)
          .map((i) => {
            const media = i.realizado / r.diasDecorridos;
            return { ...i, media, razao: (media / (i.porDia as number)) * 100 };
          })
          .sort((a, b) => a.razao - b.razao);

  const comSus = historico.filter((h) => h.r?.convenioInformado) as { mes: string; r: ResultadoMes }[];

  return (
    <>
      <Secao n="Resumo" titulo="Os números do mês e o ritmo das metas">
        <div className="mp-kpis">
          <Kpi
            destaque
            rotulo={`Metas cumpridas em ${rotuloMes(r.mes)}`}
            valor={`${inteiro.format(Math.round(g.pct))}%`}
            comp={
              <>
                {aberto && <Delta v={g.pct - r.esperadoPct} unidade="pp" sufixo={`contra o esperado até hoje (${pctTxt(r.esperadoPct, 0)})`} />}
                {aberto && pc && <br />}
                {pc && <Delta v={pc.curPct - pc.antPct} unidade="pp" sufixo={contraAnt} />}
                {!aberto && !pc && <SituacaoPill valor={g.situacao} fechado={r.fechado} />}
              </>
            }
            sub={
              <>
                <SituacaoPill valor={g.situacao} fechado={r.fechado} />
                <br />
                <b>{frase[g.situacao]}</b> {g.itensOk} de {g.itensTotal} metas {r.fechado ? "foram batidas" : "estão batidas ou no ritmo"}.
              </>
            }
          />
          <Kpi
            rotulo="Atendimentos no mês"
            valor={inteiro.format(r.totalAtendimentos)}
            comp={
              pc ? (
                <Delta v={pc.antN ? ((pc.curN - pc.antN) / Math.abs(pc.antN)) * 100 : null} d={1} sufixo={contraAnt} />
              ) : r.fechado ? (
                "Mês fechado."
              ) : (
                "Sem mês anterior para comparar."
              )
            }
            sub={`${inteiro.format(r.totalForaDasMetas)} fora de qualquer meta${ultimoDia ? ` · último atendimento ${dataBR(ultimoDia)}` : ""}`}
          />
          {r.fechado ? (
            <Kpi rotulo="Dias úteis" valor={inteiro.format(r.diasUteis)} sub="Mês fechado" />
          ) : (
            <Kpi
              rotulo="Projeção de fechamento"
              valor={proj == null ? "—" : pctTxt(proj, 0)}
              comp={proj == null ? undefined : <Delta v={proj - 100} unidade="pp" sufixo="contra a meta (100%)" />}
              sub={r.diasDecorridos >= 0.5 ? "Se o ritmo médio dos dias passados continuar." : "Ainda cedo para projetar."}
            />
          )}
          <Kpi
            rotulo="Metas em risco"
            valor={inteiro.format(atras + aten)}
            ruim={atras > 0}
            comp={
              atras || aten ? (
                <>
                  <span className="mp-delta desce">{inteiro.format(atras)} atrasada(s)</span>
                  {aten > 0 && (
                    <>
                      {" · "}
                      <span className="mp-delta igual">{inteiro.format(aten)} em atenção</span>
                    </>
                  )}
                </>
              ) : (
                <span className="mp-delta sobe">Nenhuma em risco</span>
              )
            }
            sub={`de ${itens.length} metas`}
          />
          {!r.fechado && (
            <Kpi
              rotulo="Dias úteis"
              valor={
                <>
                  {dias1(r.diasDecorridos)}
                  <span className="kpi-unit"> de {r.diasUteis}</span>
                </>
              }
              comp={
                <>
                  Restam <b>{dias1(r.diasRestantes)}</b> dias úteis
                </>
              }
              sub="Hoje conta só até agora."
            />
          )}
        </div>

        {r.serie.length > 0 && (
          <section className="mp-bloco">
            <h2>Ritmo das metas no mês</h2>
            <p className="mp-nota">
              Quanto das metas já foi cumprido a cada dia (cada meta conta até 100%). A linha tracejada é onde deveria estar pelos dias úteis; a clara é o mês anterior.
            </p>
            <Linhas
              aria="Percentual das metas cumprido por dia, contra o esperado"
              xRot={[1, 5, 10, 15, 20, 25, r.serie.length].filter((x, i, a) => x <= r.serie.length && a.indexOf(x) === i)}
              tipX={(x) => {
                const p = r.serie.find((z) => z.d === x);
                const a = ant?.serie.find((z) => z.d === x && z.pct != null);
                return (
                  `Dia ${x}\n` +
                  (p?.pct != null ? `Feito: ${pctTxt(p.pct, 1)} das metas (${inteiro.format(p.n ?? 0)} atendimentos no dia)\n` : "") +
                  `Esperado: ${pctTxt(p?.esp, 1)}` +
                  (a ? `\n${antRot}: ${pctTxt(a.pct, 1)}` : "")
                );
              }}
              series={[
                ...(ant
                  ? [
                      {
                        nome: antRot,
                        cor: "var(--line-strong)",
                        larg: 1.6,
                        pontos: ant.serie.filter((z) => z.pct != null && z.d <= r.serie.length).map((z) => ({ x: z.d, y: z.pct as number })),
                      },
                    ]
                  : []),
                { nome: "Esperado", cor: "var(--s-neutra)", traco: true, pontos: r.serie.map((z) => ({ x: z.d, y: z.esp })) },
                { nome: rotuloMes(r.mes), cor: "var(--brand)", principal: true, pontos: r.serie.filter((z) => z.pct != null).map((z) => ({ x: z.d, y: z.pct as number })) },
              ]}
            />
          </section>
        )}
      </Secao>

      <Secao n="Análise" titulo="Cada meta e cada unidade">
        <section className="mp-bloco">
          <h2>Cada meta, da mais atrasada para a mais folgada</h2>
          <p className="mp-nota">
            {r.fechado ? "A marca preta é a meta (100%)." : `A marca preta é onde cada barra deveria estar hoje (${pctTxt(r.esperadoPct, 0)}).`} A barra só muda de cor quando a meta está em atenção ou atrasada.
          </p>
          <Barras
            max={Math.max(100, ...itens.map((i) => i.pct))}
            itens={[...itens]
              .sort((a, b) => a.pct - b.pct)
              .map<ItemBarra>((i) => ({
                rotulo: `${i.nome} · ${i.grupo}`,
                valor: i.pct,
                texto: pctTxt(i.pct, 0),
                extra: `${inteiro.format(i.realizado)} de ${inteiro.format(i.meta)}`,
                cor: r.fechado ? (i.pct < 100 ? "warn" : undefined) : corDe(i.situacao),
                marca,
                tip:
                  `${i.nome} (${i.grupo})\nFeito: ${inteiro.format(i.realizado)} de ${inteiro.format(i.meta)} (${pctTxt(i.pct)})` +
                  (!r.fechado && marca ? `\nEsperado até hoje: ~${inteiro.format(Math.round((i.meta * r.esperadoPct) / 100))} (${pctTxt(r.esperadoPct)})` : "") +
                  (i.faltam ? `\nFaltam ${inteiro.format(i.faltam)}` : ""),
              }))}
          />
        </section>

        {ritmoMeta.length > 0 && (
          <section className="mp-bloco">
            <h2>O ritmo de hoje dá conta do que falta?</h2>
            <p className="mp-nota">
              Para cada meta ainda aberta: quanto se faz por dia útil hoje, em % do que seria preciso fazer por dia para bater a meta (a marca preta é 100%). Abaixo de 100% = no ritmo atual a meta não fecha.
            </p>
            <Barras
              max={Math.max(150, ...ritmoMeta.map((i) => i.razao))}
              itens={ritmoMeta.map<ItemBarra>((i) => ({
                rotulo: `${i.nome} · ${i.grupo}`,
                valor: i.razao,
                texto: pctTxt(i.razao, 0),
                extra: `faz ${umaCasa.format(i.media)}/dia · precisa ${inteiro.format(i.porDia as number)}/dia`,
                cor: i.razao < 100 * LIMITE_ATENCAO ? "crit" : i.razao < 100 ? "warn" : undefined,
                marca: 100,
                tip:
                  `${i.nome} (${i.grupo})\nFaz ${umaCasa.format(i.media)} por dia útil, precisa de ~${inteiro.format(i.porDia as number)} por dia útil\nFaltam ${inteiro.format(i.faltam)} em ${dias1(r.diasRestantes)} dias úteis` +
                  (i.projecao != null ? `\nNo ritmo atual fecha com ~${inteiro.format(i.projecao)} (${pctTxt((i.projecao / i.meta) * 100, 0)})` : ""),
              }))}
            />
          </section>
        )}

        <section className="mp-bloco mp-grid2">
          <div>
            <h2>Cumprimento por unidade</h2>
            <p className="mp-nota">Percentual das metas de cada unidade{marca ? ", com a marca do esperado" : ""}.</p>
            <Barras
              max={Math.max(100, ...r.grupos.map((x) => x.pct))}
              itens={r.grupos.map<ItemBarra>((x) => ({
                rotulo: x.nome,
                valor: x.pct,
                texto: pctTxt(x.pct, 0),
                extra: `${x.itensOk} de ${x.itens.length} metas ok`,
                cor: corDe(x.situacao),
                marca,
                tip: `${x.nome}\n${x.unidade}\nFeito: ${pctTxt(x.pct)}` + (!r.fechado && marca ? `\nEsperado até hoje: ${pctTxt(r.esperadoPct)}` : ""),
              }))}
            />
          </div>
          <div>
            <h2>Atendimentos por unidade</h2>
            <p className="mp-nota">Atendimentos que contam em alguma meta e os que ficaram de fora.</p>
            <Rosca
              centro={{ num: inteiro.format(r.totalAtendimentos), rot: "atendimentos" }}
              fatias={[
                ...r.grupos.map((x) => ({ rotulo: x.nome, valor: x.itens.reduce((s, i) => s + i.realizado, 0) })),
                { rotulo: "Fora das metas", valor: r.totalForaDasMetas },
              ]}
            />
          </div>
        </section>

        {comSus.length > 0 && (
          <section className="mp-bloco">
            <h2>SUS e sem SUS, por meta e por mês</h2>
            <p className="mp-nota">Cada barra é um mês da meta, dividida entre atendimentos SUS e sem SUS. A escala é a mesma entre os meses de uma mesma meta.</p>
            <div className="mp-sus-leg">
              <span style={{ "--c": "var(--brand)" } as React.CSSProperties}>
                <i />
                SUS
              </span>
              <span style={{ "--c": "var(--line-strong)" } as React.CSSProperties}>
                <i />
                Sem SUS
              </span>
            </div>
            {r.grupos.map((gr) => (
              <div key={gr.id}>
                <h3 className="mp-sus-grupo">{gr.nome}</h3>
                <div className="mp-sus-grade">
                  {gr.itens.map((it) => {
                    const por = comSus.map((h) => {
                      const i = h.r.grupos.find((x) => x.id === gr.id)?.itens.find((x) => x.id === it.id);
                      return { mes: h.mes, s: i?.sus ?? 0, n: i?.naoSus ?? 0 };
                    });
                    const max = Math.max(...por.map((p) => p.s + p.n), 1);
                    return (
                      <div className="mp-sus-meta" key={it.id}>
                        <h4>{it.nome}</h4>
                        {por.map((p) => {
                          const tot = p.s + p.n;
                          const w = (v: number) => `${((v / max) * 100).toFixed(2)}%`;
                          return (
                            <div className="mp-sus-lin" key={p.mes}>
                              <span className="mp-sus-mes">{rotuloMes(p.mes)}</span>
                              <div
                                className="mp-sus-barra"
                                title={`${it.nome} · ${rotuloMes(p.mes)}\nSUS: ${inteiro.format(p.s)}${tot ? ` (${pctTxt((p.s / tot) * 100, 0)})` : ""}\nSem SUS: ${inteiro.format(p.n)}\nTotal: ${inteiro.format(tot)}`}
                              >
                                {p.s > 0 && <i style={{ width: w(p.s), background: "var(--brand)" }} />}
                                {p.n > 0 && <i style={{ width: w(p.n), background: "var(--line-strong)" }} />}
                              </div>
                              <span className="mp-sus-num">
                                <b>{inteiro.format(p.s)}</b> SUS · {inteiro.format(p.n)} sem SUS
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </section>
        )}
      </Secao>

      <Secao n="Detalhes" titulo="Tabelas completas (clique para abrir)">
        <section className="mp-bloco">
          {r.grupos.map((gr) => {
            const semConv = gr.itens.reduce((s, i) => s + i.semConvenio, 0);
            return (
              <Acordeao key={gr.id} titulo={`${gr.nome}: cada meta`} dica={`${pctTxt(gr.pct, 0)} · ${gr.itensOk} de ${gr.itens.length} ok`}>
                <p className="mp-unidade">{gr.unidade}</p>
                {r.convenioInformado && semConv > 0 && (
                  <p className="mp-nota">{inteiro.format(semConv)} atendimento(s) deste mês estão sem convênio e não entram em SUS nem em Sem SUS.</p>
                )}
                <TabelaMetas r={r} itens={gr.itens} />
              </Acordeao>
            );
          })}
          <Acordeao titulo="Todos os números em tabela" dica={`${itens.length} metas`}>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Todas as metas">
              <table className="table meta-table">
                <thead>
                  <tr>
                    <th scope="col">Unidade</th>
                    <th scope="col">Meta</th>
                    <th scope="col" className="n">Meta (qtd)</th>
                    <th scope="col" className="n">Feito</th>
                    {r.convenioInformado && <th scope="col" className="n">SUS</th>}
                    {r.convenioInformado && <th scope="col" className="n">Sem SUS</th>}
                    <th scope="col" className="n">%</th>
                    <th scope="col" className="n">Faltam</th>
                    <th scope="col">Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {r.grupos.flatMap((gr) =>
                    gr.itens.map((i) => (
                      <tr key={`${gr.id}/${i.id}`}>
                        <td>{gr.nome}</td>
                        <th scope="row">{i.nome}</th>
                        <NumCell>{inteiro.format(i.meta)}</NumCell>
                        <NumCell>{inteiro.format(i.realizado)}</NumCell>
                        {r.convenioInformado && <NumCell>{inteiro.format(i.sus)}</NumCell>}
                        {r.convenioInformado && <NumCell>{inteiro.format(i.naoSus)}</NumCell>}
                        <NumCell>{pctTxt(i.pct)}</NumCell>
                        <NumCell>{inteiro.format(i.faltam)}</NumCell>
                        <td>
                          <SituacaoPill valor={i.situacao} fechado={r.fechado} />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Acordeao>
          {r.serie.length > 0 && (
            <Acordeao titulo="Dia a dia" dica={`${r.serie.filter((d) => d.pct != null).length} dias`}>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Dia a dia">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Dia</th>
                      <th scope="col" className="n">Atendimentos</th>
                      <th scope="col" className="n">Metas cumpridas (acumulado)</th>
                      <th scope="col" className="n">Esperado (acumulado)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.serie
                      .filter((d) => d.pct != null)
                      .map((d) => (
                        <tr key={d.d}>
                          <th scope="row">{d.d}</th>
                          <NumCell>{inteiro.format(d.n ?? 0)}</NumCell>
                          <NumCell>{pctTxt(d.pct, 1)}</NumCell>
                          <NumCell>{pctTxt(d.esp, 1)}</NumCell>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </Acordeao>
          )}
          <Acordeao
            titulo={`Atendimentos que não entram em nenhuma meta (${inteiro.format(r.totalForaDasMetas)} de ${inteiro.format(r.totalAtendimentos)})`}
            dica={`${r.fora.length} procedimentos`}
          >
            <p className="mp-nota">
              Conferência: são os atendimentos do relatório que não foram contados em nenhuma meta. Se algum deles deveria contar, ajuste a regra no <b>metas.json</b>.
            </p>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Atendimentos fora de qualquer meta">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Unidade</th>
                    <th scope="col">Especialidade</th>
                    <th scope="col">Procedimento</th>
                    <th scope="col" className="n">Qtd</th>
                  </tr>
                </thead>
                <tbody>
                  {r.fora.map((f) => (
                    <tr key={`${f.unidade}|${f.especialidade}|${f.procedimento}`}>
                      <th scope="row">{f.unidade}</th>
                      <td>{f.especialidade}</td>
                      <td>{f.procedimento}</td>
                      <NumCell>{inteiro.format(f.qtd)}</NumCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Acordeao>
        </section>
      </Secao>

      {r.avisos.map((aviso) => (
        <div className="notice" role="status" key={aviso}>
          <IconAlerta />
          {aviso}
        </div>
      ))}

      <p className="panel-sub meta-legenda">
        Percentual geral = soma dos exames feitos ÷ soma das metas, cada meta contando no máximo até 100%. A marca preta nas barras mostra onde a barra deveria estar hoje, pelos dias úteis de atendimento que já passaram. “Precisa por dia” = quanto falta ÷ dias úteis que restam; “No ritmo atual” = quanto o mês fecha se o ritmo médio dos dias passados continuar. Situação: Meta batida (100% ou mais) · No ritmo (igual ou acima do esperado) · Atenção (pelo menos {Math.round(LIMITE_ATENCAO * 100)}% do esperado) · Atrasado (menos que isso). Fonte: Klingo, relatório “Atendimentos – Acompanhamento de Metas por Unidade e Procedimento – Mensal”.
      </p>
    </>
  );
}

function TabelaMetas({ r, itens }: { r: ResultadoMes; itens: ResultadoItem[] }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Metas da unidade">
      <table className="table meta-table">
        <thead>
          <tr>
            <th scope="col">Meta</th>
            <th scope="col" className="n">Meta (qtd)</th>
            <th scope="col" className="n">Feito</th>
            {r.convenioInformado && <th scope="col" className="n">SUS</th>}
            {r.convenioInformado && <th scope="col" className="n">Sem SUS</th>}
            <th scope="col" className="n">%</th>
            <th scope="col" className="n">Faltam</th>
            <th scope="col" className="n">Precisa por dia útil</th>
            <th scope="col" className="n">No ritmo atual fecha</th>
            <th scope="col">Situação</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((i) => (
            <tr key={i.id}>
              <th scope="row">{i.nome}</th>
              <NumCell>{inteiro.format(i.meta)}</NumCell>
              <NumCell>{inteiro.format(i.realizado)}</NumCell>
              {r.convenioInformado && <NumCell>{inteiro.format(i.sus)}</NumCell>}
              {r.convenioInformado && <NumCell>{inteiro.format(i.naoSus)}</NumCell>}
              <NumCell>{pctTxt(i.pct)}</NumCell>
              <NumCell>{inteiro.format(i.faltam)}</NumCell>
              <NumCell>{i.porDia != null ? `~${inteiro.format(i.porDia)}` : "—"}</NumCell>
              <NumCell>{i.projecao != null && i.realizado < i.meta ? `~${inteiro.format(i.projecao)} (${pctTxt((i.projecao / i.meta) * 100, 0)})` : "—"}</NumCell>
              <td>
                <SituacaoPill valor={i.situacao} fechado={r.fechado} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
