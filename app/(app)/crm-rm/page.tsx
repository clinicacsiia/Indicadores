import type { Metadata } from "next";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { veDadosFinanceiros } from "@/lib/paineis";
import { hojeEmBrasilia } from "@/lib/avisos";
import { metasConfig } from "@/lib/metas/config";
import { IconAlerta } from "@/app/components/icons";
import {
  CAMPOS_AGENDA,
  CAMPOS_CONTATO,
  CAMPOS_CONVENIO,
  CAMPOS_EXAME,
  CHAVE_META_RM,
  MOTIVOS_PERDA,
  SITUACOES,
  SITUACOES_PERDA,
  STATUS_AGENDA,
  calcular,
  calcularMarketing,
  codigoContato,
  montarFila,
  podePreencherCrmRm,
  podeVerCrmRm,
  tamanhoDaFila,
  type ConvenioCatalogo,
  type Contato,
  type ExameCatalogo,
  type Horario,
  type Preco,
} from "@/lib/crm-rm";
import { EditarContatoForm, NovoContatoForm } from "./ContatoForm";
import { EditarHorarioForm, NovoHorarioForm, type OpcaoContato } from "./HorarioForm";
import { SecaoIndicadores } from "./SecaoIndicadores";
import { SecaoMeuDia } from "./SecaoMeuDia";
import { Identificacao, Nota, Painel, ResumoContato, ResumoHorario, Tabela, Vazio, brl, dataBR } from "./comuns";

export const metadata: Metadata = { title: "CRM Ressonância" };

type Props = { searchParams: Promise<{ aba?: string; dias?: string; busca?: string }> };
type Aba = "meu-dia" | "atender" | "agenda" | "indicadores" | "guia";

const PERIODOS = [
  { dias: 7, rotulo: "7 dias" },
  { dias: 30, rotulo: "30 dias" },
  { dias: 90, rotulo: "90 dias" },
  { dias: 0, rotulo: "Tudo" },
];
const LIMITE = 3000;
const NA_LISTA = 40;
/** A fila de trabalho não respeita o filtro de período: pendência velha continua sendo pendência. */
const JANELA_FILA = 180;

function hrefDe(aba: Aba, dias: number, busca?: string) {
  const q = new URLSearchParams({ aba });
  if (dias !== 30) q.set("dias", String(dias));
  if (busca) q.set("busca", busca);
  return `/crm-rm?${q.toString()}`;
}

const metaRM = () => {
  const [grupoId, itemId] = CHAVE_META_RM.split("/");
  return metasConfig.grupos.find((g) => g.id === grupoId)?.itens.find((i) => i.id === itemId)?.meta ?? null;
};

export default async function CrmRmPage({ searchParams }: Props) {
  const { aba: abaParam, dias: diasParam, busca: buscaParam } = await searchParams;
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
    ...(pPreencher ? [{ id: "meu-dia" as const, rotulo: "Meu dia" }] : []),
    { id: "atender", rotulo: "Atender" },
    { id: "agenda", rotulo: "Agenda" },
    ...(pVer ? [{ id: "indicadores" as const, rotulo: "Indicadores" }] : []),
    { id: "guia", rotulo: "Guia" },
  ];
  const aba: Aba = abas.some((a) => a.id === abaParam) ? (abaParam as Aba) : abas[0].id;
  const diasNum = Number(diasParam);
  const dias = PERIODOS.some((p) => p.dias === diasNum) && diasParam !== undefined ? diasNum : 30;
  const inicio = dias > 0 ? hojeEmBrasilia(-dias + 1) : "0000-01-01";
  const busca = (buscaParam ?? "").trim().slice(0, 40);

  const supabase = await createClient();

  // Catálogo: a lista de exames e convênios com o nome exato do Klingo, e o preço praticado.
  const [cat, conv, pr] = await Promise.all([
    supabase.from("crm_rm_exame").select(CAMPOS_EXAME).eq("ativo", true).order("grupo").order("atendimentos", { ascending: false }),
    supabase.from("crm_rm_convenio").select(CAMPOS_CONVENIO).eq("ativo", true).order("tipo").order("atendimentos", { ascending: false }),
    supabase.rpc("crm_rm_precos", { p_meses: 6 }),
  ]);
  const exames = (cat.data ?? []) as unknown as ExameCatalogo[];
  const convenios = (conv.data ?? []) as unknown as ConvenioCatalogo[];
  const precos = (pr.data ?? []) as unknown as Preco[];
  const grupoDoExame = (nome: string) => exames.find((e) => e.nome === nome)?.grupo ?? "Outros";

  // Registros. RLS entrega tudo a quem vê o CRM e só o próprio a quem apenas preenche.
  const deDados = aba === "meu-dia" ? hojeEmBrasilia(-JANELA_FILA) : inicio;
  const [c, h] = await Promise.all([
    supabase.from("crm_rm_contato").select(CAMPOS_CONTATO).gte("data_contato", deDados).order("data_contato", { ascending: false }).order("id", { ascending: false }).limit(LIMITE),
    supabase.from("crm_rm_agenda").select(CAMPOS_AGENDA).gte("data_exame", deDados).order("data_exame", { ascending: false }).order("horario", { ascending: false }).limit(LIMITE),
  ]);
  const falhou = Boolean(c.error || h.error);
  if (falhou) console.error("Falha ao carregar o CRM da RM:", c.error?.message ?? h.error?.message);
  const contatos = (c.data ?? []) as unknown as Contato[];
  const horarios = (h.data ?? []) as unknown as Horario[];

  const exemplos = contatos.some((x) => x.exemplo) || horarios.some((x) => x.exemplo);
  const passados = horarios.filter((x) => x.data_exame <= hoje);
  const futuros = horarios.filter((x) => x.data_exame > hoje && x.status === "Agendado").length;

  const fila = montarFila(contatos, horarios, hoje, (n) => hojeEmBrasilia(n));
  const pendencias = tamanhoDaFila(fila);

  // Indicadores: quanto da operação real o CRM está capturando (só admin lê o Klingo, por isso a função).
  let klingoRealizados: number | null = null;
  if (aba === "indicadores") {
    const { data: kr, error } = await supabase.rpc("crm_rm_realizados_klingo", { p_de: dias > 0 ? inicio : "2026-01-01", p_ate: hoje });
    if (error) console.error("Falha ao ler o volume do Klingo:", error.message);
    else klingoRealizados = typeof kr === "number" ? kr : null;
  }

  const ind = aba === "indicadores" ? calcular(contatos, passados, futuros) : null;
  const mkt = aba === "indicadores" ? calcularMarketing(contatos, passados, grupoDoExame) : null;

  // Agenda: contatos "Agendado" que ainda não têm horário registrado.
  let opcoesContato: OpcaoContato[] = [];
  if (aba === "agenda" && pPreencher) {
    const [ag, usados] = await Promise.all([
      supabase.from("crm_rm_contato").select(CAMPOS_CONTATO).eq("situacao", "Agendado").gte("data_contato", hojeEmBrasilia(-120)).order("id", { ascending: false }).limit(300),
      supabase.from("crm_rm_agenda").select("contato_id").not("contato_id", "is", null).limit(5000),
    ]);
    const ocupados = new Set((usados.data ?? []).map((u) => u.contato_id as number));
    opcoesContato = ((ag.data ?? []) as unknown as Contato[])
      .filter((x) => !ocupados.has(x.id))
      .map((x) => ({
        id: x.id,
        rotulo: `${codigoContato(x.id)} · ${dataBR(x.data_contato)} · ${x.exame} · ${x.convenio ?? x.forma_pagamento}`,
        exame: x.exame,
        forma: x.forma_pagamento,
        valor: x.valor_informado,
      }));
  }

  // Busca na aba Atender: código RM-0001, código do Klingo, telefone ou texto do exame/observação.
  const achados = busca
    ? contatos.filter((x) => {
        const t = busca.toLowerCase();
        return (
          codigoContato(x.id).toLowerCase().includes(t) ||
          String(x.id) === busca ||
          (x.codigo_klingo ?? "").toLowerCase().includes(t) ||
          (x.telefone ?? "").includes(busca.replace(/\D/g, "")) ||
          x.exame.toLowerCase().includes(t) ||
          (x.observacoes ?? "").toLowerCase().includes(t)
        );
      })
    : contatos;

  const rotuloPeriodo = dias > 0 ? `últimos ${dias} dias` : "todo o período";
  const catalogo = { exames, convenios, precos };

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">CRM Ressonância</h1>
          <p className="page-lede">
            O caminho do paciente na Ressonância Magnética: procurou o exame, recebeu orçamento ou autorização, agendou, compareceu e fez. Registre
            cada passo para ver onde se perdem pacientes e faturamento.
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
            {a.id === "meu-dia" && pendencias > 0 && <span className="config-aba-n">{pendencias}</span>}
          </Link>
        ))}
      </nav>

      {(aba === "atender" || aba === "agenda" || aba === "indicadores") && (
        <nav className="crm-periodos" aria-label="Período">
          {PERIODOS.map((p) => (
            <Link key={p.dias} href={hrefDe(aba, p.dias, busca)} className="crm-periodo" aria-current={p.dias === dias ? "true" : undefined}>
              {p.rotulo}
            </Link>
          ))}
        </nav>
      )}

      {aba === "meu-dia" && <SecaoMeuDia fila={fila} hoje={hoje} verValores={verValores} />}

      {aba === "indicadores" && ind && mkt && (
        <SecaoIndicadores ind={ind} mkt={mkt} verValores={verValores} klingoRealizados={klingoRealizados} metaMes={metaRM()} rotuloPeriodo={rotuloPeriodo} />
      )}

      {aba === "atender" && (
        <>
          {pPreencher && (
            <Painel
              id="t-novo-contato"
              titulo="Registrar contato"
              sub="Um registro por pedido de exame recebido, mesmo que o paciente não agende. Nunca escreva o nome do paciente: use o código do Klingo."
            >
              <NovoContatoForm hoje={hoje} catalogo={catalogo} />
            </Painel>
          )}

          <Painel
            id="t-lista-contatos"
            titulo={pVer ? "Contatos do período" : "Seus contatos do período"}
            sub="Do mais recente para o mais antigo. Abra “Atualizar” depois de cada conversa."
          >
            <form className="crm-busca" role="search">
              <input type="hidden" name="aba" value="atender" />
              {dias !== 30 && <input type="hidden" name="dias" value={dias} />}
              <label className="sr-only" htmlFor="busca">
                Buscar contato
              </label>
              <input id="busca" name="busca" className="input" placeholder="Buscar por RM-0001, código do Klingo, telefone ou exame" defaultValue={busca} />
              <button type="submit" className="btn">
                Buscar
              </button>
              {busca && (
                <Link href={hrefDe("atender", dias)} className="crm-link">
                  limpar
                </Link>
              )}
            </form>

            {achados.length === 0 ? (
              <Vazio>{busca ? `Nada encontrado para “${busca}”.` : "Nenhum contato no período."}</Vazio>
            ) : (
              <ul className="crm-lista">
                {achados.slice(0, NA_LISTA).map((x) => (
                  <li key={x.id} className="crm-item">
                    <ResumoContato c={x} verValores={verValores} />
                    <Identificacao c={x} />
                    {(x.motivo_perda || (x.proxima_acao && x.proxima_acao !== "Sem ação") || x.data_retorno) && (
                      <p className="crm-item-meta">
                        {x.motivo_perda ? `Motivo: ${x.motivo_perda}` : ""}
                        {x.motivo_perda && !SITUACOES_PERDA.includes(x.situacao) ? " · " : ""}
                        {!SITUACOES_PERDA.includes(x.situacao) && x.proxima_acao && x.proxima_acao !== "Sem ação" ? `Próxima ação: ${x.proxima_acao}` : ""}
                        {!SITUACOES_PERDA.includes(x.situacao) && x.data_retorno ? ` · retorno ${dataBR(x.data_retorno)}` : ""}
                      </p>
                    )}
                    {x.observacoes && <p className="crm-item-texto">{x.observacoes}</p>}
                    <details className="crm-detalhes">
                      <summary>Atualizar</summary>
                      <EditarContatoForm contato={x} />
                    </details>
                  </li>
                ))}
                {achados.length > NA_LISTA && (
                  <li className="crm-item crm-item-meta">
                    Mostrando os {NA_LISTA} mais recentes de {achados.length}. Use a busca ou escolha um período menor.
                  </li>
                )}
              </ul>
            )}
          </Painel>
        </>
      )}

      {aba === "agenda" && (
        <>
          {pPreencher && (
            <Painel
              id="t-novo-horario"
              titulo="Registrar horário"
              sub="Um registro por horário reservado. Reagendar não é contato novo: marque o antigo como Reagendado e registre o novo horário."
            >
              <NovoHorarioForm hoje={hoje} contatos={opcoesContato} exames={exames} precos={precos} verValores={verValores} />
            </Painel>
          )}
          <Painel
            id="t-lista-agenda"
            titulo={pVer ? "Horários do período" : "Seus horários do período"}
            sub="Depois da data do exame, informe se foi realizado, faltou ou cancelou (a aba Meu dia faz isso num clique)."
          >
            {horarios.length === 0 ? (
              <Vazio>Nenhum horário no período.</Vazio>
            ) : (
              <ul className="crm-lista">
                {horarios.slice(0, NA_LISTA).map((x) => (
                  <li key={x.id} className="crm-item">
                    <ResumoHorario h={x} verValores={verValores} />
                    <p className="crm-item-meta">
                      Confirmação: {x.confirmacao}
                      {x.motivo_falta ? ` · Motivo: ${x.motivo_falta}` : ""}
                      {x.vaga_recuperada !== "Não se aplica" ? ` · Vaga recuperada: ${x.vaga_recuperada}` : ""}
                      {x.motivo_operacional ? ` · ${x.motivo_operacional}` : ""}
                    </p>
                    <details className="crm-detalhes">
                      <summary>Atualizar</summary>
                      <EditarHorarioForm horario={x} />
                    </details>
                  </li>
                ))}
                {horarios.length > NA_LISTA && (
                  <li className="crm-item crm-item-meta">
                    Mostrando os {NA_LISTA} mais recentes de {horarios.length}. Escolha um período menor para ver os outros.
                  </li>
                )}
              </ul>
            )}
          </Painel>
        </>
      )}

      {aba === "guia" && (
        <>
          <Painel id="t-como" titulo="Como preencher" sub="Em que ordem, quem faz e quando.">
            <Tabela colunas={["Etapa", "Quem faz", "O que registrar", "Quando"]}>
              <tr>
                <th scope="row">1. Atender</th>
                <td>Call center e recepção</td>
                <td>Uma linha por pedido de exame recebido, mesmo que a pessoa não agende.</td>
                <td>No primeiro contato</td>
              </tr>
              <tr>
                <th scope="row">2. Atualizar</th>
                <td>Call center e recepção</td>
                <td>Nova situação, motivo se perdeu, próxima ação e data de retorno. Não apague oportunidade perdida.</td>
                <td>Depois de cada conversa</td>
              </tr>
              <tr>
                <th scope="row">3. Agenda</th>
                <td>Agendamento e recepção</td>
                <td>Uma linha por horário reservado. Reagendar não conta como contato novo.</td>
                <td>Ao agendar</td>
              </tr>
              <tr>
                <th scope="row">4. Meu dia</th>
                <td>Call center e recepção</td>
                <td>Responder, confirmar os exames de amanhã, fechar o resultado e preencher as vagas que abriram.</td>
                <td>Todo dia, começando por aí</td>
              </tr>
              <tr>
                <th scope="row">5. Indicadores</th>
                <td>Coordenação</td>
                <td>Escolher os três maiores gargalos da semana e agir.</td>
                <td>Reunião semanal de 30 minutos</td>
              </tr>
              <tr>
                <th scope="row">6. Privacidade</th>
                <td>Todos</td>
                <td>Nunca escrever nome ou dado clínico. Identifique pelo código do Klingo; telefone só se precisar ligar.</td>
                <td>Sempre</td>
              </tr>
            </Tabela>
          </Painel>

          <Painel id="t-catalogo" titulo="Exames de Ressonância" sub="Os nomes são os mesmos do Klingo. O preço é o que a clínica praticou nos últimos 6 meses.">
            <Tabela colunas={verValores ? ["Exame", "Grupo", "Sedação", "Preparo", "Particular", "Convênio (média)"] : ["Exame", "Grupo", "Sedação", "Preparo"]}>
              {exames.map((e) => {
                const p = precos.find((x) => x.exame === e.nome);
                return (
                  <tr key={e.id}>
                    <th scope="row">{e.nome}</th>
                    <td>{e.grupo}</td>
                    <td>{e.sedacao ? "Sim" : "Não"}</td>
                    <td>{e.preparo ?? "Não cadastrado"}</td>
                    {verValores && <td>{p?.particular_mediana != null ? brl(p.particular_mediana) : "—"}</td>}
                    {verValores && <td>{p?.convenio_medio != null ? brl(p.convenio_medio) : "—"}</td>}
                  </tr>
                );
              })}
            </Tabela>
            <Nota>
              Preparo, contraste e duração ainda não foram cadastrados pela clínica. Até lá, confirme com a equipe técnica antes de orientar o
              paciente. O preço é referência, não tabela oficial.
            </Nota>
          </Painel>

          <Painel id="t-convenios-guia" titulo="Convênios atendidos" sub="Se o convênio do paciente não está aqui, a clínica não atende: ofereça o particular.">
            <Tabela colunas={["Convênio", "Tipo", "Exige autorização", "Prazo"]}>
              {convenios.map((x) => (
                <tr key={x.id}>
                  <th scope="row">{x.nome}</th>
                  <td>{x.tipo}</td>
                  <td>{x.exige_autorizacao === null ? "Não cadastrado" : x.exige_autorizacao ? "Sim" : "Não"}</td>
                  <td>{x.prazo_autorizacao ? `${x.prazo_autorizacao} dias` : "—"}</td>
                </tr>
              ))}
            </Tabela>
          </Painel>

          <Painel id="t-dic-sit" titulo="Situação do contato" sub="O que cada opção quer dizer e o que fazer.">
            <Tabela colunas={["Situação", "O que significa", "O que fazer"]}>
              {SITUACOES.map((s) => (
                <tr key={s.id}>
                  <th scope="row">{s.id}</th>
                  <td>{s.significado}</td>
                  <td>{s.acao}</td>
                </tr>
              ))}
            </Tabela>
          </Painel>

          <Painel id="t-dic-mot" titulo="Motivo da perda e o que fazer" sub="Separa o que é problema comercial, de agenda, de convênio ou clínico.">
            <Tabela colunas={["Motivo", "Gargalo", "O que significa", "Passo a passo"]}>
              {MOTIVOS_PERDA.map((m) => (
                <tr key={m.id}>
                  <th scope="row">{m.id}</th>
                  <td>{m.categoria}</td>
                  <td>{m.significado}</td>
                  <td>
                    <ol className="crm-passos">
                      {m.roteiro.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ol>
                  </td>
                </tr>
              ))}
            </Tabela>
          </Painel>

          <Painel id="t-dic-ag" titulo="Status da agenda" sub="Como classificar cada horário depois do exame.">
            <Tabela colunas={["Status", "O que significa", "O que fazer"]}>
              {STATUS_AGENDA.map((s) => (
                <tr key={s.id}>
                  <th scope="row">{s.id}</th>
                  <td>{s.significado}</td>
                  <td>{s.acao}</td>
                </tr>
              ))}
            </Tabela>
          </Painel>
        </>
      )}
    </>
  );
}
