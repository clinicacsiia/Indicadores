import type { Metadata } from "next";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { veDadosFinanceiros } from "@/lib/paineis";
import { hojeEmBrasilia } from "@/lib/avisos";
import { metasConfig } from "@/lib/metas/config";
import { IconAlerta } from "@/app/components/icons";
import {
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
  doKlingo,
  montarFila,
  podePreencherCrmRm,
  podeVerCrmRm,
  resumirAgenda,
  tamanhoDaFila,
  type AgendaKlingo,
  type ConvenioCatalogo,
  type Contato,
  type ExameCatalogo,
  type Horario,
  type Preco,
} from "@/lib/crm-rm";
import { BarraAtualizacao } from "./BarraAtualizacao";
import { EditarContatoForm, NovoContatoForm } from "./ContatoForm";
import { SecaoAgenda } from "./SecaoAgenda";
import { SecaoIndicadores } from "./SecaoIndicadores";
import { SecaoMeuDia } from "./SecaoMeuDia";
import { Identificacao, Kpi, Nota, PacienteHorario, Painel, ResumoContato, ResumoHorario, Tabela, Vazio, brl, dataBR, dataHoraBR } from "./comuns";

export const metadata: Metadata = { title: "CRM Ressonância" };

type Props = { searchParams: Promise<{ aba?: string; dias?: string; busca?: string; st?: string }> };
type Aba = "meu-dia" | "atender" | "agenda" | "indicadores" | "guia";

const PERIODOS = [
  { dias: 7, rotulo: "7 dias" },
  { dias: 30, rotulo: "30 dias" },
  { dias: 90, rotulo: "90 dias" },
  { dias: 0, rotulo: "Tudo" },
];
const LIMITE = 3000;
/** O PostgREST entrega no máximo 1.000 linhas por chamada: a agenda do Klingo é lida em páginas. */
const PAGINA_AGENDA = 1000;
const MAX_PAGINAS_AGENDA = 15;
/** Fim da leitura da agenda: traz também as marcações futuras. */
const ATE_AGENDA = "2099-12-31";
/** Filtros da lista da Agenda: valor na URL -> o que mostra. */
const FILTROS_AGENDA = [
  { id: "todas", rotulo: "Todas", status: null },
  { id: "abertas", rotulo: "Abertas", status: ["Agendado"] },
  { id: "feitas", rotulo: "Realizadas", status: ["Realizado"] },
  { id: "faltas", rotulo: "Faltaram", status: ["Faltou"] },
  { id: "canceladas", rotulo: "Canceladas", status: ["Cancelado", "Reagendado"] },
] as const;
const NA_LISTA = 40;
/** A fila de trabalho não respeita o filtro de período: pendência velha continua sendo pendência. */
const JANELA_FILA = 180;

function hrefDe(aba: Aba, dias: number, busca?: string, st?: string) {
  const q = new URLSearchParams({ aba });
  if (dias !== 30) q.set("dias", String(dias));
  if (busca) q.set("busca", busca);
  if (st && st !== "todas") q.set("st", st);
  return `/crm-rm?${q.toString()}`;
}

type Cliente = Awaited<ReturnType<typeof createClient>>;

async function lerAgenda(supabase: Cliente, de: string): Promise<{ linhas: AgendaKlingo[]; erro: string | null; cortada: boolean }> {
  const linhas: AgendaKlingo[] = [];
  for (let pagina = 0; pagina < MAX_PAGINAS_AGENDA; pagina++) {
    const { data, error } = await supabase
      .rpc("crm_rm_agenda_klingo", { p_de: de, p_ate: ATE_AGENDA })
      .range(pagina * PAGINA_AGENDA, (pagina + 1) * PAGINA_AGENDA - 1);
    if (error) return { linhas, erro: error.message, cortada: false };
    const lote = (data ?? []) as unknown as AgendaKlingo[];
    linhas.push(...lote);
    if (lote.length < PAGINA_AGENDA) return { linhas, erro: null, cortada: false };
  }
  return { linhas, erro: null, cortada: true };
}

const metaRM = () => {
  const [grupoId, itemId] = CHAVE_META_RM.split("/");
  return metasConfig.grupos.find((g) => g.id === grupoId)?.itens.find((i) => i.id === itemId)?.meta ?? null;
};

export default async function CrmRmPage({ searchParams }: Props) {
  const { aba: abaParam, dias: diasParam, busca: buscaParam, st: stParam } = await searchParams;
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
  // O Klingo entrou em operação em setembro/2026: "Tudo" começa no ano, o que já cobre tudo (o PostgreSQL não aceita o ano 0000).
  const inicio = dias > 0 ? hojeEmBrasilia(-dias + 1) : "2026-01-01";
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

  // Contatos digitados pela equipe. RLS entrega tudo a quem vê o CRM e só o próprio a quem apenas preenche.
  const deContatos = aba === "meu-dia" ? hojeEmBrasilia(-JANELA_FILA) : inicio;
  const c = await supabase.from("crm_rm_contato").select(CAMPOS_CONTATO).gte("data_contato", deContatos).order("data_contato", { ascending: false }).order("id", { ascending: false }).limit(LIMITE);

  // Agenda: vem sozinha do Klingo. A fila (e o número na aba Meu dia) olha os últimos 7 dias em qualquer aba;
  // Agenda e Indicadores olham o período escolhido.
  const ultimos7 = hojeEmBrasilia(-7);
  const [ag, lida] = await Promise.all([
    lerAgenda(supabase, aba === "agenda" || aba === "indicadores" ? (inicio < ultimos7 ? inicio : ultimos7) : ultimos7),
    supabase.rpc("crm_rm_agenda_atualizada_em"),
  ]);

  if (c.error) console.error("Falha ao carregar os contatos do CRM da RM:", c.error.message);
  if (ag.erro) console.error("Falha ao carregar a agenda do Klingo no CRM da RM:", ag.erro);
  const contatos = (c.data ?? []) as unknown as Contato[];
  const horarios = ag.linhas.map((a) => doKlingo(a, hoje));
  // Fim da última coleta do #13825; se a função não responder, vale a leitura mais recente entre as marcações carregadas.
  const atualizadoEm =
    (typeof lida.data === "string" ? lida.data : null) ??
    horarios.reduce<string | null>((mais, x) => (mais === null || x.atualizado_em > mais ? x.atualizado_em : mais), null);
  // A coleta é automática a cada ~5 h: passar de 12 h sem leitura nova é sinal de coleta parada.
  const HORAS_ATE_DESATUALIZADA = 12;
  const desatualizada = atualizadoEm !== null && Date.now() - new Date(atualizadoEm).getTime() > HORAS_ATE_DESATUALIZADA * 3_600_000;

  const exemplos = contatos.some((x) => x.exemplo);
  // O que cai no período escolhido (a fila usa `horarios` inteiro: os últimos 7 dias valem mesmo com o filtro em 7 dias).
  const doPeriodo = horarios.filter((x) => x.data_exame >= inicio);
  const passados = doPeriodo.filter((x) => x.data_exame <= hoje);
  const futuros = doPeriodo.filter((x) => x.data_exame > hoje && x.status === "Agendado").length;
  const marcacoesNovas = doPeriodo.filter((x) => x.agendado_em !== null && x.agendado_em.slice(0, 10) >= inicio).length;
  const filtroAgenda = FILTROS_AGENDA.find((f) => f.id === stParam) ?? FILTROS_AGENDA[0];

  const fila = montarFila(contatos, horarios, hoje, (n) => hojeEmBrasilia(n));
  const pendencias = tamanhoDaFila(fila);

  const ind = aba === "indicadores" ? calcular(contatos, passados, futuros, marcacoesNovas) : null;
  const mkt = aba === "indicadores" ? calcularMarketing(contatos, doPeriodo, grupoDoExame) : null;
  const agenda = aba === "indicadores" ? resumirAgenda(doPeriodo, grupoDoExame) : null;

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
            O caminho do paciente na Ressonância Magnética: procurou o exame, recebeu orçamento ou autorização, agendou, compareceu e fez. A equipe
            registra a procura; a agenda (marcação, confirmação, exame feito, falta e cancelamento) vem sozinha do Klingo.
          </p>
        </div>
      </header>

      {exemplos && (
        <p className="crm-aviso" role="note">
          Os registros marcados como <strong>Exemplo</strong> são só de demonstração, para você ver a tela funcionando. O administrador pode apagá-los.
        </p>
      )}
      {c.error && (
        <div className="notice" role="alert">
          <IconAlerta />
          <span>Não foi possível carregar os contatos registrados agora. Tente de novo em instantes.</span>
        </div>
      )}
      {ag.erro && (
        <div className="notice" role="alert">
          <IconAlerta />
          <span>Não foi possível carregar a agenda do Klingo agora. Toque em “Atualizar tela” em instantes; se continuar, avise um administrador.</span>
        </div>
      )}

      <BarraAtualizacao lidoEm={atualizadoEm ? dataHoraBR(atualizadoEm) : null} demora={desatualizada} />

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
            <Link key={p.dias} href={hrefDe(aba, p.dias, busca, aba === "agenda" ? filtroAgenda.id : undefined)} className="crm-periodo" aria-current={p.dias === dias ? "true" : undefined}>
              {p.rotulo}
            </Link>
          ))}
        </nav>
      )}

      {aba === "meu-dia" && <SecaoMeuDia fila={fila} hoje={hoje} verValores={verValores} />}

      {aba === "indicadores" && ind && mkt && agenda && (
        <SecaoIndicadores ind={ind} mkt={mkt} agenda={agenda} verValores={verValores} metaMes={metaRM()} rotuloPeriodo={rotuloPeriodo} />
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
        <SecaoAgenda
          horarios={doPeriodo}
          hoje={hoje}
          dias={dias}
          busca={busca}
          filtros={FILTROS_AGENDA}
          filtro={filtroAgenda}
          verValores={verValores}
          atualizadoEm={atualizadoEm}
          cortada={ag.cortada}
        />
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
                <td>Ninguém digita</td>
                <td>
                  Vem do Klingo. Para a agenda ficar certa, mantenha o Klingo em dia: registre a confirmação, abra o atendimento quando o paciente
                  chegar e use o motivo “Remarcado” ao cancelar uma marcação que o paciente vai refazer.
                </td>
                <td>Sempre, no Klingo</td>
              </tr>
              <tr>
                <th scope="row">4. Meu dia</th>
                <td>Call center e recepção</td>
                <td>Responder, confirmar os exames dos próximos dias (e registrar a resposta no Klingo), ligar para quem faltou e oferecer as vagas que abriram.</td>
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
                <td>
                  Ao registrar um contato, nunca escreva nome ou dado clínico: use o código do Klingo. A Agenda mostra nome e telefone vindos do
                  Klingo, só para quem tem acesso ao CRM; não repasse.
                </td>
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

          <Painel id="t-dic-ag" titulo="Status da agenda" sub="Como o status de cada marcação é decidido a partir do Klingo.">
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
