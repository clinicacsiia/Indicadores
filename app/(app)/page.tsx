import type { Metadata } from "next";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { Sparkline } from "@/app/components/Sparkline";
import { TendenciaChart, type PontoDia } from "@/app/components/TendenciaChart";
import { IconAlerta, IconCalendario } from "@/app/components/icons";
import { AtualizarForm } from "./atualizar-form";

// A atualização (server action desta página) espera as Edge Functions falarem com o Klingo.
export const maxDuration = 300;

export const metadata: Metadata = { title: "Relatórios" };

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_LINHAS = 5000;
const PAGINA = 1000;
const HORAS_ATE_DESATUALIZADO = 36;

// Ordem das colunas na tabela; indicadores desconhecidos vão para o fim.
const COLUNAS = [
  { codigo: "agendamentos_total", rotulo: "Agendamentos" },
  { codigo: "atendimentos_finalizados", rotulo: "Atendimentos finalizados" },
  { codigo: "atendimentos_avulsos", rotulo: "Atendimentos avulsos" },
  { codigo: "valor_total_procedimentos", rotulo: "Valor dos procedimentos" },
];

// A mesma cor identifica o mesmo indicador no card e no gráfico.
const COR_POR_CODIGO: Record<string, string> = {
  agendamentos_total: "var(--s-agendados)",
  atendimentos_finalizados: "var(--s-realizados)",
};
const COR_NEUTRA = "var(--s-neutra)";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brlInteiro = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});
const inteiro = new Intl.NumberFormat("pt-BR");
const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

function formatarValor(valor: number, unidade: string | null) {
  return unidade === "BRL" ? brl.format(valor) : inteiro.format(valor);
}

function formatarValorCard(valor: number, unidade: string | null) {
  return unidade === "BRL" ? brlInteiro.format(valor) : inteiro.format(valor);
}

function formatarMedia(valor: number, unidade: string | null) {
  return unidade === "BRL" ? brlInteiro.format(valor) : umaCasa.format(valor);
}

function formatarData(iso: string) {
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

function diaDaSemana(iso: string) {
  return new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC", weekday: "short" })
    .format(new Date(`${iso}T12:00:00Z`))
    .replace(".", "");
}

function ehFimDeSemana(iso: string) {
  const d = new Date(`${iso}T12:00:00Z`).getUTCDay();
  return d === 0 || d === 6;
}

function somarDias(iso: string, dias: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

function hojeSaoPaulo() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

type Indicador = {
  codigo: string;
  nome: string;
  valor: number;
  unidade: string | null;
  periodo: string;
};

export default async function RelatoriosPage({
  searchParams,
}: {
  searchParams: Promise<{ de?: string; ate?: string }>;
}) {
  const profile = await getCurrentProfile();
  const podeVer = profile?.role === "admin" || profile?.permissions?.relatorios !== false;

  if (profile && !podeVer) {
    return (
      <>
        <header className="page-head">
          <div className="page-head-text">
            <span className="eyebrow">Clínica CSI</span>
            <h1 className="page-title">Relatórios</h1>
          </div>
        </header>
        <section className="panel empty">
          <span className="empty-icon">
            <IconAlerta size={26} />
          </span>
          <h2>Você ainda não tem acesso aos Relatórios</h2>
          <p>Peça a um administrador para liberar o seu acesso em Configurações.</p>
        </section>
      </>
    );
  }

  const params = await searchParams;
  const hoje = hojeSaoPaulo();
  const ate = params.ate && DATE_RE.test(params.ate) ? params.ate : hoje;
  const de = params.de && DATE_RE.test(params.de) && params.de <= ate ? params.de : somarDias(ate, -29);

  const supabase = await createClient();

  // RLS garante que isso só retorna dados para quem está autenticado e pode ver
  // Relatórios; o proxy já bloqueia a rota antes mesmo de chegar aqui.
  // O PostgREST devolve no máximo 1000 linhas por requisição; busca em páginas.
  async function carregarIndicadores() {
    const linhas: Indicador[] = [];
    for (let inicio = 0; inicio < MAX_LINHAS; inicio += PAGINA) {
      const { data, error } = await supabase
        .from("indicadores")
        .select("codigo, nome, valor, unidade, periodo")
        .gte("periodo", de)
        .lte("periodo", ate)
        .order("periodo", { ascending: false })
        .order("codigo")
        .range(inicio, inicio + PAGINA - 1);
      if (error) return { data: null, error };
      linhas.push(...((data ?? []) as Indicador[]));
      if (!data || data.length < PAGINA) break;
    }
    return { data: linhas, error: null };
  }

  const isAdmin = profile?.role === "admin";

  const [{ data, error }, { data: ultimaSync }, { data: catalogo }] = await Promise.all([
    carregarIndicadores(),
    supabase
      .from("sync_runs")
      .select("finished_at")
      .eq("status", "success")
      .order("finished_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    // Só admin escolhe o relatório a atualizar; os demais nem consultam o catálogo.
    isAdmin
      ? supabase
          .from("dim_relatorio")
          .select("klingo_id, nome, ativo")
          .is("supersedido_por", null)
          .order("ativo", { ascending: false })
          .order("nome")
      : Promise.resolve({ data: null }),
  ]);

  // Período sugerido para atualizar: o do filtro, limitado aos últimos 31 dias dele.
  const deAtualizar = de < somarDias(ate, -30) ? somarDias(ate, -30) : de;

  // Nunca mostrar error.message na tela: pode conter detalhes internos do Postgres.
  if (error) {
    console.error("Falha ao carregar indicadores:", error.message);
  }

  const indicadores = data ?? [];

  const codigosExtras = [...new Set(indicadores.map((i) => i.codigo))].filter(
    (codigo) => !COLUNAS.some((c) => c.codigo === codigo)
  );
  const colunas = [
    ...COLUNAS,
    ...codigosExtras.map((codigo) => ({
      codigo,
      rotulo: indicadores.find((i) => i.codigo === codigo)?.nome ?? codigo,
    })),
  ];

  const unidades = new Map(indicadores.map((i) => [i.codigo, i.unidade]));
  const totais = new Map<string, number>();
  const porDia = new Map<string, Map<string, number>>();
  for (const item of indicadores) {
    const valor = Number(item.valor);
    totais.set(item.codigo, (totais.get(item.codigo) ?? 0) + valor);
    if (!porDia.has(item.periodo)) porDia.set(item.periodo, new Map());
    porDia.get(item.periodo)!.set(item.codigo, valor);
  }
  const diasAsc = [...porDia.keys()].sort();
  const dias = [...diasAsc].reverse();

  const serieDe = (codigo: string) =>
    diasAsc.map((d) => porDia.get(d)!.get(codigo)).filter((v): v is number => v !== undefined);

  const pontosGrafico: PontoDia[] = diasAsc.map((dia) => ({
    dia,
    agendados: porDia.get(dia)!.get("agendamentos_total") ?? null,
    realizados: porDia.get(dia)!.get("atendimentos_finalizados") ?? null,
  }));
  const temGrafico = pontosGrafico.some((p) => p.agendados !== null || p.realizados !== null);

  const atalhos = [
    { rotulo: "7 dias", de: somarDias(hoje, -6), ate: hoje },
    { rotulo: "30 dias", de: somarDias(hoje, -29), ate: hoje },
    { rotulo: "90 dias", de: somarDias(hoje, -89), ate: hoje },
    { rotulo: "Este ano", de: `${hoje.slice(0, 4)}-01-01`, ate: hoje },
  ];

  let sync: { texto: string; estado: "ok" | "stale" | "none" } = {
    texto: "Ainda sem sincronização",
    estado: "none",
  };
  if (ultimaSync?.finished_at) {
    const quando = new Date(ultimaSync.finished_at);
    const horas = (Date.now() - quando.getTime()) / 36e5;
    const fmt = (opts: Intl.DateTimeFormatOptions) =>
      new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", ...opts }).format(quando);
    const mesmoDia =
      new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(quando) === hoje;
    const hora = fmt({ timeStyle: "short" });
    sync = {
      texto: `Atualizado ${mesmoDia ? "hoje" : "em " + fmt({ day: "2-digit", month: "2-digit" })} às ${hora}`,
      estado: horas > HORAS_ATE_DESATUALIZADO ? "stale" : "ok",
    };
  }

  const qtdDias = dias.length;

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Relatórios</h1>
          <p className="page-lede">Agendados e realizados por dia, vindos do Klingo.</p>
        </div>
        <span className="chip" data-state={sync.estado}>
          <span className="chip-dot" aria-hidden="true" />
          {sync.texto}
        </span>
      </header>

      <section className="toolbar" aria-label="Período">
        <div>
          <span className="toolbar-label" id="rotulo-atalhos">
            Período
          </span>
          <div className="seg" role="group" aria-labelledby="rotulo-atalhos">
            {atalhos.map((a) => (
              <Link
                key={a.rotulo}
                href={`/?de=${a.de}&ate=${a.ate}`}
                className="seg-item"
                aria-current={a.de === de && a.ate === ate ? "true" : undefined}
              >
                {a.rotulo}
              </Link>
            ))}
          </div>
        </div>

        <form method="get" className="range-form">
          <div className="field">
            <label className="field-label" htmlFor="filtro-de">
              De
            </label>
            <input id="filtro-de" className="input" type="date" name="de" defaultValue={de} max={hoje} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="filtro-ate">
              Até
            </label>
            <input id="filtro-ate" className="input" type="date" name="ate" defaultValue={ate} max={hoje} />
          </div>
          <button type="submit" className="btn btn-primary">
            Aplicar
          </button>
        </form>
      </section>

      {isAdmin && catalogo && catalogo.length > 0 && (
        <AtualizarForm relatorios={catalogo} de={deAtualizar} ate={ate} max={hoje} />
      )}

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar os indicadores agora. Tente novamente em instantes.
        </div>
      )}

      {!error && qtdDias === 0 && (
        <section className="panel empty">
          <span className="empty-icon">
            <IconCalendario size={26} />
          </span>
          <h2>Nenhum dado neste período</h2>
          <p>
            Não há indicadores sincronizados entre {formatarData(de)} e {formatarData(ate)}. Tente um
            período maior.
          </p>
          <Link className="btn btn-primary" href={`/?de=${somarDias(hoje, -89)}&ate=${hoje}`}>
            Ver os últimos 90 dias
          </Link>
        </section>
      )}

      {qtdDias > 0 && (
        <>
          <section aria-label="Totais do período">
            <div className="kpis">
              {colunas.map((c) => {
                const unidade = unidades.get(c.codigo) ?? null;
                const total = totais.get(c.codigo) ?? 0;
                const cor = COR_POR_CODIGO[c.codigo] ?? COR_NEUTRA;
                const mediaPorDia = qtdDias > 0 ? total / qtdDias : 0;
                return (
                  <article className="kpi" key={c.codigo} style={{ "--swatch": cor } as React.CSSProperties}>
                    <h2 className="kpi-label">
                      <span className="swatch" aria-hidden="true" />
                      {c.rotulo}
                    </h2>
                    <p className="kpi-value" title={formatarValor(total, unidade)}>
                      {formatarValorCard(total, unidade)}
                    </p>
                    <p className="kpi-meta">Média de {formatarMedia(mediaPorDia, unidade)} por dia</p>
                    <Sparkline valores={serieDe(c.codigo)} cor={cor} />
                  </article>
                );
              })}
            </div>
          </section>

          {temGrafico && (
            <section className="panel" aria-labelledby="titulo-grafico">
              <div className="panel-head">
                <div>
                  <h2 className="panel-title" id="titulo-grafico">
                    Agendados × realizados
                  </h2>
                  <p className="panel-sub">
                    {formatarData(de)} a {formatarData(ate)} · {qtdDias} {qtdDias === 1 ? "dia" : "dias"} com dados
                  </p>
                </div>
                <ul className="legend" aria-label="Legenda">
                  <li>
                    <span className="legend-line" style={{ "--swatch": "var(--s-agendados)" } as React.CSSProperties} />
                    Agendamentos
                  </li>
                  <li>
                    <span className="legend-line" style={{ "--swatch": "var(--s-realizados)" } as React.CSSProperties} />
                    Atendimentos finalizados
                  </li>
                </ul>
              </div>
              <div className="panel-body">
                <TendenciaChart dados={pontosGrafico} />
              </div>
            </section>
          )}

          <section className="panel" aria-labelledby="titulo-tabela">
            <div className="panel-head">
              <div>
                <h2 className="panel-title" id="titulo-tabela">
                  Por dia
                </h2>
                <p className="panel-sub">Do mais recente ao mais antigo. Fins de semana em fundo mais claro.</p>
              </div>
            </div>
            <div className="table-wrap" tabIndex={0} role="region" aria-labelledby="titulo-tabela">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Data</th>
                    {colunas.map((c) => (
                      <th key={c.codigo} scope="col">
                        {c.rotulo}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dias.map((dia) => (
                    <tr key={dia} data-weekend={ehFimDeSemana(dia)}>
                      <th scope="row">
                        <span className="weekday">{diaDaSemana(dia)}</span>
                        {formatarData(dia)}
                      </th>
                      {colunas.map((c) => {
                        const valor = porDia.get(dia)!.get(c.codigo);
                        return valor === undefined ? (
                          <td key={c.codigo} className="empty-cell">
                            —
                          </td>
                        ) : (
                          <td key={c.codigo}>{formatarValor(valor, unidades.get(c.codigo) ?? null)}</td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row">Total</th>
                    {colunas.map((c) => (
                      <td key={c.codigo}>{formatarValor(totais.get(c.codigo) ?? 0, unidades.get(c.codigo) ?? null)}</td>
                    ))}
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
