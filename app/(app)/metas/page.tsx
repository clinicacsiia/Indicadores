import type { Metadata } from "next";
import Link from "next/link";
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
  type LinhaAtendimento,
  type ResultadoItem,
  type Situacao,
} from "@/lib/metas/calculo";

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

function SituacaoPill({ valor }: { valor: Situacao }) {
  return (
    <span className="status-pill" data-status={valor}>
      {ROTULO_SITUACAO[valor]}
    </span>
  );
}

function Barra({ pct, esperado, situacao }: { pct: number; esperado: number; situacao: Situacao }) {
  return (
    <div className="meter" data-status={situacao} aria-hidden="true">
      <span className="meter-fill" style={{ width: `${Math.min(pct, 100)}%` }} />
      {esperado > 0 && esperado < 100 && <span className="meter-tick" style={{ left: `${esperado}%` }} />}
    </div>
  );
}

function LinhaMeta({ item, esperado, convenio }: { item: ResultadoItem; esperado: number; convenio: boolean }) {
  return (
    <tr>
      <th scope="row">{item.nome}</th>
      <td>{inteiro.format(item.meta)}</td>
      <td>{inteiro.format(item.realizado)}</td>
      <td className="meta-cell-pct">
        <span className="meta-pct">{pctTexto(item.pct)}</span>
        <Barra pct={item.pct} esperado={esperado} situacao={item.situacao} />
      </td>
      <td>{item.faltam ? inteiro.format(item.faltam) : "—"}</td>
      <td>{item.porDia !== null ? inteiro.format(item.porDia) : "—"}</td>
      <td>{item.projecao !== null ? inteiro.format(item.projecao) : "—"}</td>
      {convenio && (
        <td>
          {inteiro.format(item.sus)} <span className="meta-sep">/</span> {inteiro.format(item.naoSus)}
        </td>
      )}
      <td>
        <SituacaoPill valor={item.situacao} />
      </td>
    </tr>
  );
}

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
  const [{ data: bruto, error }, { data: catalogo }] = await Promise.all([
    // A função aplica a permissão "Pode ver Metas" e já entrega os atendimentos do mês contados.
    supabase.rpc("metas_atendimentos_mes", { p_mes: mes }),
    isAdmin
      ? supabase.from("dim_relatorio").select("klingo_id, nome, ativo").eq("klingo_id", RELATORIO_METAS)
      : Promise.resolve({ data: null }),
  ]);

  // Nunca mostrar error.message na tela: pode conter detalhes internos do Postgres.
  if (error) console.error("Falha ao carregar atendimentos das metas:", error.message);

  const resposta = (bruto ?? null) as RespostaMetas | null;
  const linhas = resposta?.mapeado ? (resposta.linhas ?? []) : [];
  const temDados = linhas.length > 0;
  const resultado = temDados ? calcularMes(metasConfig, mes, linhas, agora) : null;

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
          <h1 className="page-title">Metas</h1>
          <p className="page-lede">
            Atendimentos realizados no mês contra a meta de cada serviço, com o ritmo esperado pelos dias úteis de
            atendimento.
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

      {resultado && (
        <>
          <section aria-label={`Resumo de ${rotuloMes(mes)}`}>
            <div className="kpis">
              <article className="kpi" style={{ "--swatch": "var(--s-realizados)" } as React.CSSProperties}>
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Metas cumpridas
                </h2>
                <p className="kpi-value">{pctTexto(resultado.geral.pct)}</p>
                <p className="kpi-meta">
                  <SituacaoPill valor={resultado.geral.situacao} />
                </p>
                <Barra pct={resultado.geral.pct} esperado={resultado.esperadoPct} situacao={resultado.geral.situacao} />
              </article>
              <article className="kpi" style={{ "--swatch": "var(--s-agendados)" } as React.CSSProperties}>
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Esperado até agora
                </h2>
                <p className="kpi-value">{pctTexto(resultado.esperadoPct)}</p>
                <p className="kpi-meta">
                  {resultado.fechado ? "Mês fechado" : "Pelos dias úteis já passados"}
                </p>
              </article>
              <article className="kpi">
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Dias úteis
                </h2>
                <p className="kpi-value">
                  {umaCasa.format(resultado.diasDecorridos)}
                  <span className="kpi-unit"> de {resultado.diasUteis}</span>
                </p>
                <p className="kpi-meta">
                  {resultado.fechado ? "Todos decorridos" : `Faltam ${umaCasa.format(resultado.diasRestantes)}`}
                </p>
              </article>
              <article className="kpi">
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Metas no ritmo ou batidas
                </h2>
                <p className="kpi-value">
                  {resultado.geral.itensOk}
                  <span className="kpi-unit"> de {resultado.geral.itensTotal}</span>
                </p>
                <p className="kpi-meta">{inteiro.format(resultado.totalAtendimentos)} atendimentos no mês</p>
              </article>
            </div>
          </section>

          {resultado.grupos.map((g) => (
            <section className="panel" key={g.id} aria-labelledby={`grupo-${g.id}`}>
              <div className="panel-head">
                <div>
                  <h2 className="panel-title" id={`grupo-${g.id}`}>
                    {g.nome}
                  </h2>
                  <p className="panel-sub">
                    {g.unidade} · {g.itensOk} de {g.itens.length} no ritmo ou batidas
                  </p>
                </div>
                <div className="meta-group-total">
                  <span className="meta-pct">{pctTexto(g.pct)}</span>
                  <SituacaoPill valor={g.situacao} />
                </div>
              </div>
              <div className="table-wrap" tabIndex={0} role="region" aria-labelledby={`grupo-${g.id}`}>
                <table className="table meta-table">
                  <thead>
                    <tr>
                      <th scope="col">Serviço</th>
                      <th scope="col">Meta</th>
                      <th scope="col">Realizado</th>
                      <th scope="col">Cumprimento</th>
                      <th scope="col">Faltam</th>
                      <th scope="col">Por dia útil</th>
                      <th scope="col">Projeção</th>
                      {resultado.convenioInformado && <th scope="col">SUS / outros</th>}
                      <th scope="col">Situação</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.itens.map((item) => (
                      <LinhaMeta
                        key={item.id}
                        item={item}
                        esperado={resultado.esperadoPct}
                        convenio={resultado.convenioInformado}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}

          <p className="panel-sub meta-legenda">
            O traço no fim de cada barra marca o esperado até agora ({pctTexto(resultado.esperadoPct)}). &ldquo;No
            ritmo&rdquo; = pelo menos o esperado; &ldquo;Atenção&rdquo; = entre 75% e 100% do esperado;
            &ldquo;Atrasado&rdquo; = abaixo de 75%. A projeção mantém o ritmo médio por dia útil até o fim do mês.
            {resposta?.ultimo_dia && ` Dados sincronizados até ${dataCurta(resposta.ultimo_dia)}.`}
          </p>

          {resultado.avisos.map((aviso) => (
            <div className="notice" role="status" key={aviso}>
              <IconAlerta />
              {aviso}
            </div>
          ))}

          {resultado.fora.length > 0 && (
            <details className="panel meta-fora">
              <summary>
                <span className="panel-title">Atendimentos fora de qualquer meta</span>
                <span className="panel-sub">
                  {inteiro.format(resultado.totalForaDasMetas)} de {inteiro.format(resultado.totalAtendimentos)} no mês
                </span>
              </summary>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Atendimentos fora de qualquer meta">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Unidade</th>
                      <th scope="col">Especialidade</th>
                      <th scope="col">Procedimento</th>
                      <th scope="col">Atendimentos</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultado.fora.slice(0, 50).map((f) => (
                      <tr key={`${f.unidade}|${f.especialidade}|${f.procedimento}`}>
                        <th scope="row">{f.unidade}</th>
                        <td>{f.especialidade}</td>
                        <td>{f.procedimento}</td>
                        <td>{inteiro.format(f.qtd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {resultado.fora.length > 50 && (
                <p className="panel-sub meta-legenda">Mostrando os 50 maiores de {resultado.fora.length}.</p>
              )}
            </details>
          )}
        </>
      )}
    </>
  );
}
