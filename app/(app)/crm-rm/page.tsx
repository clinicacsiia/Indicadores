import type { Metadata } from "next";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { veDadosFinanceiros } from "@/lib/paineis";
import { hojeEmBrasilia } from "@/lib/avisos";
import { IconAlerta } from "@/app/components/icons";
import {
  CAMPOS_AGENDA,
  CAMPOS_CONTATO,
  MOTIVOS_PERDA,
  SITUACOES,
  SITUACOES_PERDA,
  STATUS_AGENDA,
  calcular,
  codigoContato,
  paraRetomar,
  podePreencherCrmRm,
  podeVerCrmRm,
  type Contato,
  type Horario,
  type Indicadores,
} from "@/lib/crm-rm";
import { EditarContatoForm, NovoContatoForm } from "./ContatoForm";
import { EditarHorarioForm, NovoHorarioForm, type OpcaoContato } from "./HorarioForm";

export const metadata: Metadata = { title: "CRM Ressonância" };

type Props = { searchParams: Promise<{ aba?: string; dias?: string }> };
type Aba = "indicadores" | "contatos" | "agenda" | "como";

const PERIODOS = [
  { dias: 7, rotulo: "7 dias" },
  { dias: 30, rotulo: "30 dias" },
  { dias: 90, rotulo: "90 dias" },
  { dias: 0, rotulo: "Tudo" },
];
const LIMITE = 2000;
const NA_LISTA = 40;

const dataBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const pct = (n: number | null) => (n === null ? "—" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`);
const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const horas = (n: number) => `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} h`;
const hora = (h: string | null) => (h ? h.slice(0, 5) : "");

function pilula(estado: string): string | undefined {
  if (["Agendado", "Realizado"].includes(estado)) return "ritmo";
  if (["Não agendou", "Desistiu", "Faltou"].includes(estado)) return "atrasado";
  if (["Orçamento enviado", "Aguardando resposta", "Aguardando autorização"].includes(estado)) return "atencao";
  return undefined;
}

function hrefDe(aba: Aba, dias: number) {
  const q = new URLSearchParams({ aba });
  if (dias !== 30) q.set("dias", String(dias));
  return `/crm-rm?${q.toString()}`;
}

// Leitura rápida dos gargalos do período, em linguagem simples (sem inventar causa: só aponta onde está o volume).
function destaques(i: Indicadores): string[] {
  const t: string[] = [];
  const topo = i.perdasPorMotivo[0];
  if (topo && i.perdidos >= 3) {
    t.push(`Maior motivo de perda: ${topo.motivo} (${topo.n} de ${i.perdidos} contatos perdidos, ${pct(topo.pct)}). Gargalo ${topo.categoria === "Comercial" ? "comercial" : topo.categoria === "Agenda" ? "de agenda" : topo.categoria === "Convênio" ? "de convênio" : "a investigar"}.`);
  }
  const canais = i.porCanal.filter((c) => c.solicitacoes >= 5);
  if (canais.length >= 2) {
    const pior = [...canais].sort((a, b) => (a.conversao ?? 0) - (b.conversao ?? 0))[0];
    t.push(`Canal que menos converte: ${pior.canal} (${pct(pior.conversao)} de ${pior.solicitacoes} solicitações agendaram).`);
  }
  const sem = i.faltasPorConfirmacao.filter((c) => c.confirmacao !== "Confirmou" && c.agendados >= 5);
  const conf = i.faltasPorConfirmacao.find((c) => c.confirmacao === "Confirmou");
  if (sem.length && conf && conf.taxa !== null) {
    const pior = [...sem].sort((a, b) => (b.taxa ?? 0) - (a.taxa ?? 0))[0];
    if ((pior.taxa ?? 0) > conf.taxa) t.push(`Quem está "${pior.confirmacao}" falta ${pct(pior.taxa)} das vezes; quem confirmou, ${pct(conf.taxa)}. A confirmação ativa tem espaço.`);
  }
  if (i.vagasElegiveis >= 3 && i.pctRecuperadas !== null) {
    t.push(`${i.vagasElegiveis - i.vagasRecuperadas} de ${i.vagasElegiveis} vagas de faltas e cancelamentos ficaram sem ser reocupadas (${pct(100 - i.pctRecuperadas)}).`);
  }
  if (i.horasParadas > 0 && i.motivosOperacionais[0]) {
    t.push(`Equipamento com ${horas(i.horasParadas)} paradas ou em atraso; mais frequente: ${i.motivosOperacionais[0].motivo}.`);
  }
  return t;
}

function Kpi({ rotulo, valor, meta, cor }: { rotulo: string; valor: string; meta?: string; cor?: string }) {
  return (
    <article className="kpi" style={cor ? ({ "--swatch": cor } as React.CSSProperties) : undefined}>
      <h3 className="kpi-label">
        <span className="swatch" aria-hidden="true" />
        {rotulo}
      </h3>
      <p className="kpi-value">{valor}</p>
      {meta && <p className="kpi-meta">{meta}</p>}
    </article>
  );
}

function Painel({ titulo, sub, id, children }: { titulo: string; sub?: string; id: string; children: React.ReactNode }) {
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel-head">
        <div>
          <h2 className="panel-title" id={id}>
            {titulo}
          </h2>
          {sub && <p className="panel-sub">{sub}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

export default async function CrmRmPage({ searchParams }: Props) {
  const { aba: abaParam, dias: diasParam } = await searchParams;
  const profile = await getCurrentProfile();
  const pVer = podeVerCrmRm(profile);
  const pPreencher = podePreencherCrmRm(profile);
  const verValores = veDadosFinanceiros(profile);
  const hoje = hojeEmBrasilia();

  if (!pVer && !pPreencher) {
    return (
      <>
        <header className="page-head">
          <div className="page-head-text">
            <span className="eyebrow">Clínica CSI</span>
            <h1 className="page-title">CRM Ressonância</h1>
          </div>
        </header>
        <section className="panel empty">
          <span className="empty-icon">
            <IconAlerta size={26} />
          </span>
          <h2>Você ainda não tem acesso ao CRM da Ressonância</h2>
          <p>Peça a um administrador para liberar o seu acesso em Configurações.</p>
        </section>
      </>
    );
  }

  const abas: { id: Aba; rotulo: string }[] = [
    ...(pVer ? [{ id: "indicadores" as const, rotulo: "Indicadores" }] : []),
    { id: "contatos", rotulo: "CRM – Contatos" },
    { id: "agenda", rotulo: "Agenda – RM" },
    { id: "como", rotulo: "Como preencher" },
  ];
  const aba: Aba = abas.some((a) => a.id === abaParam) ? (abaParam as Aba) : abas[0].id;
  const diasNum = Number(diasParam);
  const dias = PERIODOS.some((p) => p.dias === diasNum) && diasParam !== undefined ? diasNum : 30;
  const inicio = dias > 0 ? hojeEmBrasilia(-dias + 1) : "0000-01-01";

  const supabase = await createClient();
  let contatos: Contato[] = [];
  let horarios: Horario[] = [];
  let opcoesContato: OpcaoContato[] = [];
  let falhou = false;

  if (aba !== "como") {
    // RLS: quem vê o CRM lê tudo; quem só preenche lê apenas o que registrou.
    const [c, h] = await Promise.all([
      supabase.from("crm_rm_contato").select(CAMPOS_CONTATO).gte("data_contato", inicio).order("data_contato", { ascending: false }).order("id", { ascending: false }).limit(LIMITE),
      supabase.from("crm_rm_agenda").select(CAMPOS_AGENDA).gte("data_exame", inicio).order("data_exame", { ascending: false }).order("horario", { ascending: false }).limit(LIMITE),
    ]);
    if (c.error || h.error) {
      falhou = true;
      console.error("Falha ao carregar o CRM da RM:", c.error?.message ?? h.error?.message);
    }
    contatos = (c.data ?? []) as unknown as Contato[];
    horarios = (h.data ?? []) as unknown as Horario[];

    if (aba === "agenda" && pPreencher) {
      // Contatos "Agendado" que ainda não têm horário na Agenda (os últimos 120 dias).
      const [ag, usados] = await Promise.all([
        supabase.from("crm_rm_contato").select(CAMPOS_CONTATO).eq("situacao", "Agendado").gte("data_contato", hojeEmBrasilia(-120)).order("id", { ascending: false }).limit(300),
        supabase.from("crm_rm_agenda").select("contato_id").not("contato_id", "is", null).limit(5000),
      ]);
      const ocupados = new Set((usados.data ?? []).map((u) => u.contato_id as number));
      opcoesContato = ((ag.data ?? []) as unknown as Contato[])
        .filter((x) => !ocupados.has(x.id))
        .map((x) => ({
          id: x.id,
          rotulo: `${codigoContato(x.id)} · ${dataBR(x.data_contato)} · ${x.exame} · ${x.forma_pagamento}`,
          exame: x.exame,
          forma: x.forma_pagamento,
          valor: x.valor_informado,
        }));
    }
  }

  const exemplos = contatos.some((x) => x.exemplo) || horarios.some((x) => x.exemplo);
  const passados = horarios.filter((h) => h.data_exame <= hoje);
  const futuros = horarios.filter((h) => h.data_exame > hoje && h.status === "Agendado").length;
  const ind = aba === "indicadores" ? calcular(contatos, passados, futuros) : null;
  const retomar = aba === "indicadores" ? paraRetomar(contatos, hoje) : [];
  const avisos = ind ? destaques(ind) : [];

  const periodos = (
    <nav className="crm-periodos" aria-label="Período">
      {PERIODOS.map((p) => (
        <Link key={p.dias} href={hrefDe(aba, p.dias)} className="crm-periodo" aria-current={p.dias === dias ? "true" : undefined}>
          {p.rotulo}
        </Link>
      ))}
    </nav>
  );

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">CRM Ressonância</h1>
          <p className="page-lede">
            O caminho do paciente na Ressonância Magnética: procurou o exame, recebeu orçamento ou autorização, agendou, compareceu e fez. Registre cada passo
            para ver onde se perdem pacientes e faturamento.
          </p>
        </div>
      </header>

      {exemplos && (
        <p className="crm-aviso" role="note">
          Os registros marcados como <strong>Exemplo</strong> são só de demonstração, para você ver a tela funcionando. O administrador pode apagá-los.
        </p>
      )}
      {falhou && (
        <div className="notice" role="alert">
          <IconAlerta />
          <span>Não foi possível carregar os registros agora. Tente de novo em instantes.</span>
        </div>
      )}

      <nav className="config-abas" aria-label="Seções do CRM da Ressonância">
        {abas.map((a) => (
          <Link key={a.id} href={hrefDe(a.id, dias)} className="config-aba" aria-current={aba === a.id ? "page" : undefined}>
            {a.rotulo}
          </Link>
        ))}
      </nav>

      {aba !== "como" && periodos}

      {aba === "indicadores" && ind && (
        <>
          {avisos.length > 0 && (
            <Painel id="t-destaques" titulo="O que olhar primeiro" sub="Resumo automático do período escolhido.">
              <ul className="crm-destaques">
                {avisos.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Painel>
          )}

          <section aria-label="Resumo do período">
            <div className="kpis">
              <Kpi rotulo="Solicitações recebidas" valor={String(ind.solicitacoes)} meta={`${ind.emAberto} ainda em andamento`} cor="var(--s-realizados)" />
              <Kpi rotulo="Taxa de conversão" valor={pct(ind.conversao)} meta="Solicitações que viraram agendamento" cor="var(--s-realizados)" />
              <Kpi rotulo="Absenteísmo" valor={pct(ind.absenteismo)} meta={`${ind.faltas} faltas em ${ind.realizados + ind.faltas} horários com resultado`} cor="var(--s-agendados)" />
              <Kpi rotulo="Vagas recuperadas" valor={pct(ind.pctRecuperadas)} meta={`${ind.vagasRecuperadas} de ${ind.vagasElegiveis} faltas e cancelamentos`} />
              {verValores && <Kpi rotulo="Receita realizada" valor={brl(ind.receitaRealizada)} meta={`${ind.realizados} exames feitos`} cor="var(--s-realizados)" />}
              {verValores && <Kpi rotulo="Previsto nas faltas" valor={brl(ind.valorPrevistoFaltas)} meta="Potencial bruto, não perda contábil" cor="var(--s-agendados)" />}
              {verValores && <Kpi rotulo="Orçado e perdido" valor={brl(ind.valorPerdido)} meta={`${ind.perdidos} contatos que não agendaram ou desistiram`} cor="var(--s-agendados)" />}
              {verValores && <Kpi rotulo="Orçado em aberto" valor={brl(ind.valorEmAberto)} meta="Ainda dá para recuperar" />}
            </div>
          </section>

          <Painel id="t-funil" titulo="Funil do paciente" sub="Da procura ao exame feito. Passe o mouse (ou toque) em cada etapa para ver o que ela conta.">
            <ol className="crm-funil">
              {ind.funil.map((e, idx) => {
                const base = Math.max(1, ind.funil[0].n);
                const anterior = idx === 0 ? null : ind.funil[idx - 1].n;
                return (
                  <li key={e.id} title={e.dica}>
                    <span className="crm-funil-nome">{e.rotulo}</span>
                    <span className="crm-funil-trilho" aria-hidden="true">
                      <span style={{ width: `${Math.min(100, (e.n / base) * 100)}%` }} />
                    </span>
                    <span className="crm-funil-valor">
                      {e.n}
                      {anterior !== null && anterior > 0 && <small> {pct((e.n / anterior) * 100)} da etapa anterior</small>}
                    </span>
                  </li>
                );
              })}
            </ol>
            <p className="crm-nota">
              Atenção: as etapas olham períodos diferentes. Solicitações e agendamentos contam pela data do contato; exames feitos, pela data do exame.
              {ind.aRealizar > 0 && ` Há ainda ${ind.aRealizar} ${ind.aRealizar === 1 ? "horário" : "horários"} marcado${ind.aRealizar === 1 ? "" : "s"} para os próximos dias.`}
            </p>
          </Painel>

          <div className="crm-duas">
            <Painel id="t-perdas" titulo="Por que perdemos pacientes" sub="Contatos que não agendaram ou desistiram, por motivo.">
              {ind.perdasPorMotivo.length === 0 ? (
                <p className="crm-vazio">Nenhuma perda registrada no período.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">Motivo</th>
                        <th scope="col">Tipo de gargalo</th>
                        <th scope="col">Contatos</th>
                        <th scope="col">%</th>
                        {verValores && <th scope="col">Orçado</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {ind.perdasPorMotivo.map((m) => (
                        <tr key={m.motivo}>
                          <th scope="row">{m.motivo}</th>
                          <td>{m.categoria}</td>
                          <td>{m.n}</td>
                          <td>{pct(m.pct)}</td>
                          {verValores && <td>{m.valor > 0 ? brl(m.valor) : "—"}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Painel>

            <Painel id="t-retomar" titulo="Para retomar hoje" sub="Contatos em aberto com retorno marcado para hoje ou antes.">
              {retomar.length === 0 ? (
                <p className="crm-vazio">Nenhum retorno atrasado.</p>
              ) : (
                <ul className="crm-lista">
                  {retomar.slice(0, 8).map((c) => (
                    <li key={c.id} className="crm-item">
                      <div className="crm-item-topo">
                        <strong>{codigoContato(c.id)}</strong>
                        <span className="status-pill" data-status={pilula(c.situacao)}>
                          {c.situacao}
                        </span>
                        <span className="crm-item-meta">
                          {c.exame} · {c.forma_pagamento}
                          {verValores && c.valor_informado !== null ? ` · ${brl(c.valor_informado)}` : ""}
                        </span>
                      </div>
                      <p className="crm-item-meta">
                        Retorno {c.data_retorno && c.data_retorno < hoje ? "atrasado desde" : "marcado para"} {dataBR(c.data_retorno as string)}
                        {c.proxima_acao ? ` · ${c.proxima_acao}` : ""}
                        {c.responsavel ? ` · ${c.responsavel}` : ""}
                      </p>
                    </li>
                  ))}
                  {retomar.length > 8 && <li className="crm-item crm-item-meta">E mais {retomar.length - 8} na aba CRM – Contatos.</li>}
                </ul>
              )}
            </Painel>
          </div>

          <div className="crm-duas">
            <Painel id="t-absent" titulo="Faltas e confirmação" sub="Quem faltou, de acordo com a resposta antes do exame (só horários com resultado).">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Confirmação prévia</th>
                      <th scope="col">Horários</th>
                      <th scope="col">Faltas</th>
                      <th scope="col">Taxa de falta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ind.faltasPorConfirmacao.map((c) => (
                      <tr key={c.confirmacao}>
                        <th scope="row">{c.confirmacao}</th>
                        <td>{c.agendados}</td>
                        <td>{c.faltas}</td>
                        <td>{pct(c.taxa)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {ind.motivosFalta.length > 0 && (
                <p className="crm-nota">
                  Motivos das faltas: {ind.motivosFalta.map((m) => `${m.motivo} (${m.n})`).join(" · ")}.
                </p>
              )}
              <p className="crm-nota">
                Cancelamentos: {ind.cancelamentos} · Reagendados: {ind.reagendados}. Absenteísmo = faltas ÷ (exames feitos + faltas); horários ainda pendentes não entram.
              </p>
            </Painel>

            <Painel id="t-forma" titulo="Particular × Convênio" sub="Os gargalos mudam conforme a forma de pagamento.">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col"> </th>
                      <th scope="col">Solicitações</th>
                      <th scope="col">Conversão</th>
                      <th scope="col">Exames feitos</th>
                      <th scope="col">Absenteísmo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ind.porForma.map((f) => (
                      <tr key={f.forma}>
                        <th scope="row">{f.forma}</th>
                        <td>{f.solicitacoes}</td>
                        <td>{pct(f.conversao)}</td>
                        <td>{f.realizados}</td>
                        <td>{pct(f.absenteismo)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Painel>
          </div>

          <div className="crm-duas">
            <Painel id="t-canal" titulo="Por onde chegam" sub="Canal de entrada e quantos viraram agendamento.">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Canal</th>
                      <th scope="col">Solicitações</th>
                      <th scope="col">Agendaram</th>
                      <th scope="col">Conversão</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ind.porCanal.map((c) => (
                      <tr key={c.canal}>
                        <th scope="row">{c.canal}</th>
                        <td>{c.solicitacoes}</td>
                        <td>{c.agendadas}</td>
                        <td>{pct(c.conversao)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Painel>

            <Painel id="t-op" titulo="Equipamento e sala" sub="Problemas operacionais anotados nos horários.">
              {ind.motivosOperacionais.length === 0 ? (
                <p className="crm-vazio">Nenhum problema operacional registrado no período.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">Motivo</th>
                        <th scope="col">Ocorrências</th>
                        <th scope="col">Horas paradas</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ind.motivosOperacionais.map((m) => (
                        <tr key={m.motivo}>
                          <th scope="row">{m.motivo}</th>
                          <td>{m.n}</td>
                          <td>{m.horas > 0 ? horas(m.horas) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="crm-nota">Total no período: {horas(ind.horasParadas)} de equipamento parado ou em atraso.</p>
            </Painel>
          </div>
        </>
      )}

      {aba === "contatos" && (
        <>
          {pPreencher && (
            <Painel id="t-novo-contato" titulo="Registrar contato" sub="Um registro por pedido de exame recebido, mesmo que o paciente não agende. Sem nome, CPF ou dado clínico.">
              <NovoContatoForm hoje={hoje} />
            </Painel>
          )}
          <Painel id="t-lista-contatos" titulo={pVer ? "Contatos do período" : "Seus contatos do período"} sub="Do mais recente para o mais antigo. Abra “Atualizar” depois de cada conversa com o paciente.">
            {contatos.length === 0 ? (
              <p className="crm-vazio">Nenhum contato no período.</p>
            ) : (
              <ul className="crm-lista">
                {contatos.slice(0, NA_LISTA).map((c) => (
                  <li key={c.id} className="crm-item">
                    <div className="crm-item-topo">
                      <strong>{codigoContato(c.id)}</strong>
                      <span className="status-pill" data-status={pilula(c.situacao)}>
                        {c.situacao}
                      </span>
                      <span className="crm-item-meta">
                        {dataBR(c.data_contato)} · {c.canal} · {c.exame} · {c.forma_pagamento}
                        {c.convenio ? ` (${c.convenio})` : ""}
                        {verValores && c.valor_informado !== null ? ` · ${brl(c.valor_informado)}` : ""}
                      </span>
                      {c.exemplo && <span className="badge">Exemplo</span>}
                    </div>
                    {(c.motivo_perda || (c.proxima_acao && c.proxima_acao !== "Sem ação") || c.data_retorno) && (
                      <p className="crm-item-meta">
                        {c.motivo_perda ? `Motivo: ${c.motivo_perda}` : ""}
                        {c.motivo_perda && (c.proxima_acao || c.data_retorno) ? " · " : ""}
                        {SITUACOES_PERDA.includes(c.situacao) || c.proxima_acao === "Sem ação" ? "" : c.proxima_acao ? `Próxima ação: ${c.proxima_acao}` : ""}
                        {!SITUACOES_PERDA.includes(c.situacao) && c.data_retorno ? ` · retorno ${dataBR(c.data_retorno)}` : ""}
                      </p>
                    )}
                    {c.observacoes && <p className="crm-item-texto">{c.observacoes}</p>}
                    <details className="crm-detalhes">
                      <summary>Atualizar</summary>
                      <EditarContatoForm contato={c} />
                    </details>
                  </li>
                ))}
                {contatos.length > NA_LISTA && (
                  <li className="crm-item crm-item-meta">Mostrando os {NA_LISTA} mais recentes de {contatos.length}. Escolha um período menor para ver os outros.</li>
                )}
              </ul>
            )}
          </Painel>
        </>
      )}

      {aba === "agenda" && (
        <>
          {pPreencher && (
            <Painel id="t-novo-horario" titulo="Registrar horário" sub="Um registro por horário reservado. Reagendar não é contato novo: marque o antigo como Reagendado e registre o novo horário.">
              <NovoHorarioForm hoje={hoje} contatos={opcoesContato} verValores={verValores} />
            </Painel>
          )}
          <Painel id="t-lista-agenda" titulo={pVer ? "Horários do período" : "Seus horários do período"} sub="Depois da data do exame, abra “Atualizar” e informe se foi realizado, faltou ou cancelou.">
            {horarios.length === 0 ? (
              <p className="crm-vazio">Nenhum horário no período.</p>
            ) : (
              <ul className="crm-lista">
                {horarios.slice(0, NA_LISTA).map((h) => (
                  <li key={h.id} className="crm-item">
                    <div className="crm-item-topo">
                      <span className="status-pill" data-status={pilula(h.status)}>
                        {h.status}
                      </span>
                      <span className="crm-item-meta">
                        {dataBR(h.data_exame)}
                        {h.horario ? ` ${hora(h.horario)}` : ""} · {h.exame} · {h.forma_pagamento}
                        {h.contato_id ? ` · ${codigoContato(h.contato_id)}` : " · encaixe"}
                        {verValores && h.valor_realizado !== null ? ` · ${brl(h.valor_realizado)}` : verValores && h.valor_previsto !== null ? ` · previsto ${brl(h.valor_previsto)}` : ""}
                      </span>
                      {h.exemplo && <span className="badge">Exemplo</span>}
                    </div>
                    <p className="crm-item-meta">
                      Confirmação: {h.confirmacao}
                      {h.motivo_falta ? ` · Motivo: ${h.motivo_falta}` : ""}
                      {h.vaga_recuperada !== "Não se aplica" ? ` · Vaga recuperada: ${h.vaga_recuperada}` : ""}
                      {h.motivo_operacional ? ` · ${h.motivo_operacional}${h.horas_paradas ? ` (${horas(h.horas_paradas)})` : ""}` : ""}
                    </p>
                    <details className="crm-detalhes">
                      <summary>Atualizar</summary>
                      <EditarHorarioForm horario={h} />
                    </details>
                  </li>
                ))}
                {horarios.length > NA_LISTA && (
                  <li className="crm-item crm-item-meta">Mostrando os {NA_LISTA} mais recentes de {horarios.length}. Escolha um período menor para ver os outros.</li>
                )}
              </ul>
            )}
          </Painel>
        </>
      )}

      {aba === "como" && (
        <>
          <Painel id="t-como" titulo="Como preencher" sub="Em que ordem, quem faz e quando.">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Etapa</th>
                    <th scope="col">Quem preenche</th>
                    <th scope="col">O que registrar</th>
                    <th scope="col">Quando</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">1. CRM – Contatos</th>
                    <td>Equipe de atendimento</td>
                    <td>Uma linha por pedido de exame recebido, mesmo que o paciente não agende.</td>
                    <td>No primeiro contato</td>
                  </tr>
                  <tr>
                    <th scope="row">2. Atualizar o contato</th>
                    <td>Equipe de atendimento</td>
                    <td>Nova situação, motivo se perdeu, próxima ação e data de retorno. Não apague oportunidades perdidas.</td>
                    <td>Depois de cada conversa</td>
                  </tr>
                  <tr>
                    <th scope="row">3. Agenda – RM</th>
                    <td>Agendamento / recepção</td>
                    <td>Uma linha por horário reservado. Reagendar não conta como contato novo.</td>
                    <td>Ao agendar e depois da data do exame</td>
                  </tr>
                  <tr>
                    <th scope="row">4. Indicadores</th>
                    <td>Coordenação</td>
                    <td>Acompanhar os números e escolher os três maiores gargalos da semana.</td>
                    <td>Reunião semanal de 30 minutos</td>
                  </tr>
                  <tr>
                    <th scope="row">5. Privacidade</th>
                    <td>Todos</td>
                    <td>Nunca escrever nome, CPF ou dado clínico. Cada registro tem só um código (RM-0001).</td>
                    <td>Sempre</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Painel>

          <Painel id="t-dic-sit" titulo="Dicionário: situação do contato" sub="O que cada opção quer dizer e o que a equipe faz.">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Situação</th>
                    <th scope="col">O que significa</th>
                    <th scope="col">O que fazer</th>
                  </tr>
                </thead>
                <tbody>
                  {SITUACOES.map((s) => (
                    <tr key={s.id}>
                      <th scope="row">{s.id}</th>
                      <td>{s.significado}</td>
                      <td>{s.acao}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Painel>

          <Painel id="t-dic-mot" titulo="Dicionário: motivo da perda" sub="Separa o que é problema comercial, de agenda, de convênio ou clínico.">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Motivo</th>
                    <th scope="col">Tipo de gargalo</th>
                    <th scope="col">O que significa</th>
                    <th scope="col">O que fazer</th>
                  </tr>
                </thead>
                <tbody>
                  {MOTIVOS_PERDA.map((m) => (
                    <tr key={m.id}>
                      <th scope="row">{m.id}</th>
                      <td>{m.categoria}</td>
                      <td>{m.significado}</td>
                      <td>{m.acao}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Painel>

          <Painel id="t-dic-ag" titulo="Dicionário: status da agenda" sub="Como classificar cada horário depois do exame.">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Status</th>
                    <th scope="col">O que significa</th>
                    <th scope="col">O que fazer</th>
                  </tr>
                </thead>
                <tbody>
                  {STATUS_AGENDA.map((s) => (
                    <tr key={s.id}>
                      <th scope="row">{s.id}</th>
                      <td>{s.significado}</td>
                      <td>{s.acao}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Painel>
        </>
      )}
    </>
  );
}
