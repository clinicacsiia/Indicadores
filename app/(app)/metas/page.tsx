import type { Metadata } from "next";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { IconAlerta, IconCalendario } from "@/app/components/icons";
import { FiltroPeriodo } from "@/app/components/FiltroPeriodo";
import { metasConfig } from "@/lib/metas/config";
import { INICIO_KLINGO, primeiroMesValido } from "@/lib/inicio-klingo";
import { ComparacaoPagante } from "./ComparacaoPagante";
import {
  agoraSaoPaulo,
  analisarPagante,
  calcularPeriodo,
  fimDoMes,
  mesesDisponiveis,
  mesesInteiros,
  serieDiaria,
  type LinhaAtendimento,
  type LinhaAtendimentoDia,
  type ResultadoItem,
  type Situacao,
} from "@/lib/metas/calculo";

// A atualização (server action do formulário) espera as Edge Functions falarem com o Klingo.
export const maxDuration = 300;

export const metadata: Metadata = { title: "Metas" };

const MES_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const DIA_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
const dataBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const diaValido = (iso: string | undefined): iso is string =>
  !!iso && DIA_RE.test(iso) && new Date(`${iso}T12:00:00Z`).toISOString().slice(0, 10) === iso;
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

function BarraConvenio({ sus, naoSus, cetrus, semConvenio }: { sus: number; naoSus: number; cetrus: number; semConvenio: number }) {
  const total = sus + naoSus + cetrus + semConvenio;
  const parte = (v: number) => `${(v / total) * 100}%`;
  return (
    <div className="convenio-bar" aria-hidden="true">
      {sus > 0 && <span className="convenio-seg" data-tipo="sus" style={{ width: parte(sus) }} />}
      {naoSus > 0 && <span className="convenio-seg" data-tipo="nao-sus" style={{ width: parte(naoSus) }} />}
      {cetrus > 0 && <span className="convenio-seg" data-tipo="cetrus" style={{ width: parte(cetrus) }} />}
      {semConvenio > 0 && <span className="convenio-seg" data-tipo="sem" style={{ width: parte(semConvenio) }} />}
    </div>
  );
}

function LinhaConvenio({
  nome,
  sus,
  naoSus,
  cetrus,
  semConvenio,
  destaque,
}: {
  nome: string;
  sus: number;
  naoSus: number;
  cetrus: number;
  semConvenio: number;
  destaque?: boolean;
}) {
  const total = sus + naoSus + cetrus + semConvenio;
  if (total === 0) return null;
  const pctSus = (sus / total) * 100;
  return (
    <li className="convenio-linha" data-destaque={destaque ? "" : undefined}>
      <span className="convenio-nome">{nome}</span>
      <BarraConvenio sus={sus} naoSus={naoSus} cetrus={cetrus} semConvenio={semConvenio} />
      <span className="convenio-num">
        <b>{inteiro.format(sus)}</b> SUS <span className="meta-sep">·</span> <b>{inteiro.format(naoSus)}</b> pagante
        {cetrus > 0 && (
          <>
            <span className="meta-sep"> · </span>
            <b>{inteiro.format(cetrus)}</b> Cetrus
          </>
        )}
        <span className="meta-sep"> · </span>
        {pctTexto(pctSus)} SUS
        {semConvenio > 0 && ` · ${inteiro.format(semConvenio)} sem convênio`}
      </span>
    </li>
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
          {inteiro.format(item.sus)} <span className="meta-sep">/</span> {inteiro.format(item.naoSus)} <span className="meta-sep">/</span>{" "}
          {inteiro.format(item.cetrus)}
        </td>
      )}
      <td>
        <SituacaoPill valor={item.situacao} />
      </td>
    </tr>
  );
}

export default async function MetasPage({ searchParams }: { searchParams: Promise<{ mes?: string; de?: string; ate?: string }> }) {
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

  const agora = agoraSaoPaulo();
  const mesAtual = agora.hoje.slice(0, 7);
  const primeiroMesMetas = primeiroMesValido(metasConfig.primeiro_mes); // nunca antes do uso do Klingo, mesmo que o metas.json peça
  const primeiroMes = primeiroMesMetas > mesAtual ? mesAtual : primeiroMesMetas;
  const meses = mesesDisponiveis(primeiroMes, mesAtual);

  const { mes: mesPedido, de: dePedido, ate: atePedido } = await searchParams;
  // Período: um mês (?mes=AAAA-MM) ou dias livres (?de=AAAA-MM-DD&ate=AAAA-MM-DD). Datas que cobrem um mês inteiro viram esse mês.
  const minimo = `${primeiroMes}-01`;
  const maximo = fimDoMes(mesAtual);
  let de = `${mesAtual}-01`;
  let ate = maximo;
  if (diaValido(dePedido) && diaValido(atePedido)) {
    [de, ate] = dePedido <= atePedido ? [dePedido, atePedido] : [atePedido, dePedido];
    if (de < minimo) de = minimo;
    if (ate > maximo) ate = maximo;
    if (ate < de) ate = de;
  } else if (mesPedido && MES_RE.test(mesPedido) && meses.includes(mesPedido)) {
    de = `${mesPedido}-01`;
    ate = fimDoMes(mesPedido);
  }
  const inteiros = mesesInteiros(de, ate);
  const mesUnico = inteiros && inteiros.de === inteiros.ate ? inteiros.de : null; // o período é exatamente um mês
  const mes = de.slice(0, 7);
  const rotulo = mesUnico
    ? rotuloMes(mesUnico)
    : inteiros
      ? `${rotuloMes(inteiros.de)} a ${rotuloMes(inteiros.ate)}`
      : de === ate
        ? dataBR(de)
        : `${dataBR(de)} a ${dataBR(ate)}`;
  const nomePeriodo = mesUnico ? "mês" : "período";

  const supabase = await createClient();
  // A função aplica a permissão "Pode ver Metas" e já entrega os atendimentos do mês contados.
  const { data: bruto, error } = mesUnico
    ? await supabase.rpc("metas_atendimentos_mes", { p_mes: mesUnico })
    : await supabase.rpc("metas_atendimentos_periodo", { p_de: de, p_ate: ate });

  // Nunca mostrar error.message na tela: pode conter detalhes internos do Postgres.
  if (error) console.error("Falha ao carregar atendimentos das metas:", error.message);

  const resposta = (bruto ?? null) as RespostaMetas | null;
  const linhas = resposta?.mapeado ? (resposta.linhas ?? []) : [];
  const temDados = linhas.length > 0;
  const resultado = temDados ? calcularPeriodo(metasConfig, de, ate, linhas, agora) : null;

  // Comparação com SUS × só pagante: a evolução dia a dia vem de outra função (mesmas regras de contagem, separada por dia).
  // Se ela falhar ou ainda não existir no banco, a comparação aparece sem os gráficos de linha.
  let serie: ReturnType<typeof serieDiaria> | null = null;
  if (resultado?.convenioInformado) {
    const { data: porDia, error: erroDia } = await supabase.rpc("metas_atendimentos_por_dia", { p_de: de, p_ate: ate });
    if (erroDia) console.error("Falha ao carregar atendimentos das metas por dia:", erroDia.message);
    else {
      const resp = (porDia ?? null) as { mapeado: boolean; linhas?: LinhaAtendimentoDia[] } | null;
      if (resp?.mapeado)
        serie = serieDiaria(
          metasConfig,
          de,
          ate,
          (resp.linhas ?? []).map((l) => ({ ...l, dia: String(l.dia).slice(0, 10) })),
          agora
        );
    }
  }
  const achados = resultado?.convenioInformado ? analisarPagante(resultado, serie) : [];

  let sync: { texto: string; estado: "ok" | "stale" | "none" } = { texto: "Ainda sem sincronização", estado: "none" };
  if (resposta?.ultimo_sync) {
    const quando = new Date(resposta.ultimo_sync);
    const horas = (Date.now() - quando.getTime()) / 36e5;
    const fmt = (opts: Intl.DateTimeFormatOptions) =>
      new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", ...opts }).format(quando);
    const mesmoDia = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(quando) === agora.hoje;
    sync = {
      texto: `Atualizado ${mesmoDia ? "hoje" : "em " + fmt({ day: "2-digit", month: "2-digit" })} às ${fmt({ timeStyle: "short" })}`,
      // Período já fechado não envelhece: só avisa quando ele ainda está em andamento e sem atualização recente.
      estado: ate >= agora.hoje && horas > HORAS_ATE_DESATUALIZADO ? "stale" : "ok",
    };
  }

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Metas</h1>
          <p className="page-lede">
            Atendimentos realizados no mês ou em qualquer período contra a meta de cada serviço, com o ritmo esperado pelos dias úteis de
            atendimento.
          </p>
        </div>
        <span className="chip" data-state={sync.estado}>
          <span className="chip-dot" aria-hidden="true" />
          {sync.texto}
        </span>
      </header>

      <FiltroPeriodo
        basePath="/metas"
        meses={meses}
        mesAtivo={mesUnico}
        de={de}
        ate={ate}
        min={minimo}
        max={maximo}
        hoje={agora.hoje}
        dica={`Os dados começam em ${rotuloMes(INICIO_KLINGO)}, quando o Klingo passou a ser usado; o que vem de antes é de teste ou do sistema anterior e não entra.`}
      />

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
          <h2>Nenhum atendimento em {rotulo}</h2>
          <p>{`Ainda não há atendimentos sincronizados para ${mesUnico ? "este mês" : "este período"}.`}</p>
        </section>
      )}

      {resultado && (
        <>
          <section aria-label={`Resumo de ${rotulo}`}>
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
                  {resultado.fechado ? (mesUnico ? "Mês fechado" : "Período fechado") : "Pelos dias úteis já passados"}
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
                <p className="kpi-meta">{inteiro.format(resultado.totalAtendimentos)} atendimentos no {nomePeriodo}</p>
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
                      {resultado.convenioInformado && <th scope="col">SUS / pagante / Cetrus</th>}
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
            &ldquo;Atrasado&rdquo; = abaixo de 75%. A projeção mantém o ritmo médio por dia útil até o fim do {nomePeriodo}. Num período livre, a meta de cada mês vale pela parte dos dias úteis dele que cai dentro do período.
            {resposta?.ultimo_dia && ` Dados sincronizados até ${dataCurta(resposta.ultimo_dia)}.`}
          </p>

          {resultado.avisos.map((aviso) => (
            <div className="notice" role="status" key={aviso}>
              <IconAlerta />
              {aviso}
            </div>
          ))}

          {resultado.convenioInformado && (
            <section className="panel" aria-labelledby="convenio-titulo">
              <div className="panel-head">
                <div>
                  <h2 className="panel-title" id="convenio-titulo">
                    SUS, pagante e Cetrus
                  </h2>
                  <p className="panel-sub">
                    Quanto dos atendimentos que contam nas metas foi pelo SUS, quanto foi por outro convênio ou particular (pagante) e quanto foi do Cetrus, um
                    curso que não é SUS nem pagante.
                  </p>
                </div>
              </div>
              <div className="convenio-legenda" aria-hidden="true">
                <span data-tipo="sus">SUS</span>
                <span data-tipo="nao-sus">Pagante</span>
                {resultado.convenio.cetrus > 0 && <span data-tipo="cetrus">Cetrus</span>}
                {resultado.convenio.semConvenio > 0 && <span data-tipo="sem">Sem convênio informado</span>}
              </div>
              <ul className="convenio-lista">
                <LinhaConvenio nome="Todas as metas" {...resultado.convenio} destaque />
                {resultado.grupos.map((g) => (
                  <LinhaConvenio
                    key={g.id}
                    nome={g.nome}
                    sus={g.itens.reduce((s, i) => s + i.sus, 0)}
                    naoSus={g.itens.reduce((s, i) => s + i.naoSus, 0)}
                    cetrus={g.itens.reduce((s, i) => s + i.cetrus, 0)}
                    semConvenio={g.itens.reduce((s, i) => s + i.semConvenio, 0)}
                  />
                ))}
              </ul>
            </section>
          )}

          {resultado.convenioInformado && (
            <ComparacaoPagante resultado={resultado} serie={serie} achados={achados} nomePeriodo={nomePeriodo} />
          )}

          {resultado.fora.length > 0 && (
            <details className="panel meta-fora">
              <summary>
                <span className="panel-title">Atendimentos fora de qualquer meta</span>
                <span className="panel-sub">
                  {inteiro.format(resultado.totalForaDasMetas)} de {inteiro.format(resultado.totalAtendimentos)} no {nomePeriodo}
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
