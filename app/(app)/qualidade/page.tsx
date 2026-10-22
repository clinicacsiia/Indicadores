import type { Metadata } from "next";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { hojeEmBrasilia } from "@/lib/avisos";
import { IconAlerta } from "@/app/components/icons";
import {
  CAMPOS_OCORRENCIA,
  agruparPor,
  mesAnterior,
  mesDe,
  podePreencherQualidade,
  podeVerQualidade,
  resumir,
  rotuloGravidade,
  rotuloTipo,
  type Ocorrencia,
} from "@/lib/qualidade";
import { FormularioOcorrencia } from "./FormularioOcorrencia";
import { ResolverBotao } from "./ResolverBotao";

export const metadata: Metadata = { title: "Qualidade" };

type Props = { searchParams: Promise<{ mes?: string }> };

const MES_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
const nomeMes = (mes: string) => `${MESES[Number(mes.slice(5, 7)) - 1]} de ${mes.slice(0, 4)}`;
const dataBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const pct = (n: number | null) => (n === null ? "—" : `${Math.round(n)}%`);
const diasTxt = (n: number | null) => (n === null ? "—" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ${n === 1 ? "dia" : "dias"}`);

function variacao(atual: number, anterior: number): string {
  if (!anterior && !atual) return "Igual ao mês anterior";
  if (!anterior) return "Sem registros no mês anterior";
  const d = atual - anterior;
  if (d === 0) return "Igual ao mês anterior";
  return `${d > 0 ? "+" : "−"}${Math.abs(d)} em relação ao mês anterior`;
}

export default async function QualidadePage({ searchParams }: Props) {
  const { mes: mesParam } = await searchParams;
  const profile = await getCurrentProfile();
  const pVer = podeVerQualidade(profile);
  const pPreencher = podePreencherQualidade(profile);
  const hoje = hojeEmBrasilia();

  if (!pVer && !pPreencher) {
    return (
      <>
        <header className="page-head">
          <div className="page-head-text">
            <span className="eyebrow">Clínica CSI</span>
            <h1 className="page-title">Qualidade</h1>
          </div>
        </header>
        <section className="panel empty">
          <span className="empty-icon">
            <IconAlerta size={26} />
          </span>
          <h2>Você ainda não tem acesso à Qualidade</h2>
          <p>Peça a um administrador para liberar o seu acesso em Configurações.</p>
        </section>
      </>
    );
  }

  // RLS entrega tudo a quem vê o indicador e só o que a própria pessoa lançou a quem só preenche.
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("ocorrencia")
    .select(CAMPOS_OCORRENCIA)
    .order("data_ocorrencia", { ascending: false })
    .order("id", { ascending: false })
    .limit(3000);
  if (error) console.error("Falha ao carregar ocorrências:", error.message);
  const todas = (data ?? []) as unknown as Ocorrencia[];

  // Meses: os 6 últimos até o atual (mais qualquer mês com registro mais antigo que o usuário abriu pelo endereço).
  const atual = mesDe(hoje);
  const meses = [atual];
  for (let i = 0; i < 5; i++) meses.push(mesAnterior(meses[meses.length - 1]));
  const mes = mesParam && MES_RE.test(mesParam) && mesParam <= atual ? mesParam : atual;
  if (!meses.includes(mes)) meses.push(mes);
  meses.sort().reverse();

  const doMes = todas.filter((o) => mesDe(o.data_ocorrencia) === mes);
  const resumo = resumir(doMes);
  const anterior = resumir(todas.filter((o) => mesDe(o.data_ocorrencia) === mesAnterior(mes)));
  const porSetor = agruparPor(doMes, (o) => o.setor);
  const porUnidade = agruparPor(doMes, (o) => o.unidade);
  const maxSetor = Math.max(1, ...porSetor.map((s) => s.problemas));
  const temExemplo = todas.some((o) => o.exemplo);

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Qualidade</h1>
          <p className="page-lede">
            Reclamações, ocorrências e elogios registrados pela equipe, por mês, unidade e setor. Os dados são lançados à mão porque o Klingo não
            traz esse registro.
          </p>
        </div>
      </header>

      {temExemplo && (
        <p className="qual-aviso" role="note">
          Há registros de <strong>exemplo</strong> nesta tela, só para demonstração (marcados na lista). O administrador pode apagá-los.
        </p>
      )}

      {pPreencher && (
        <section className="panel" aria-labelledby="titulo-registrar">
          <div className="panel-head">
            <div>
              <h2 className="panel-title" id="titulo-registrar">
                Registrar
              </h2>
              <p className="panel-sub">Não coloque nome, CPF ou outro dado que identifique o paciente.</p>
            </div>
          </div>
          <FormularioOcorrencia hoje={hoje} />
        </section>
      )}

      {pVer ? (
        <>
          <nav className="qual-meses" aria-label="Mês">
            {meses.map((m) => (
              <Link key={m} href={m === atual ? "/qualidade" : `/qualidade?mes=${m}`} aria-current={m === mes ? "true" : undefined} className="qual-mes">
                {MESES[Number(m.slice(5, 7)) - 1].slice(0, 3)}/{m.slice(2, 4)}
              </Link>
            ))}
          </nav>

          <section aria-label={`Resumo de ${nomeMes(mes)}`}>
            <div className="kpis">
              <article className="kpi" style={{ "--swatch": "var(--s-agendados)" } as React.CSSProperties}>
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Reclamações e ocorrências
                </h2>
                <p className="kpi-value">{resumo.problemas}</p>
                <p className="kpi-meta">{variacao(resumo.problemas, anterior.problemas)}</p>
              </article>
              <article className="kpi" style={{ "--swatch": "var(--s-realizados)" } as React.CSSProperties}>
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Elogios
                </h2>
                <p className="kpi-value">{resumo.elogios}</p>
                <p className="kpi-meta">{variacao(resumo.elogios, anterior.elogios)}</p>
              </article>
              <article className="kpi">
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Resolvidas
                </h2>
                <p className="kpi-value">{pct(resumo.pctResolvidos)}</p>
                <p className="kpi-meta">
                  {resumo.resolvidos} de {resumo.problemas}
                </p>
              </article>
              <article className="kpi">
                <h2 className="kpi-label">
                  <span className="swatch" aria-hidden="true" />
                  Tempo médio para resolver
                </h2>
                <p className="kpi-value">{diasTxt(resumo.diasMedios)}</p>
                <p className="kpi-meta">
                  {resumo.altasAbertas > 0 ? `${resumo.altasAbertas} de gravidade alta ainda aberta${resumo.altasAbertas > 1 ? "s" : ""}` : "Nenhuma de gravidade alta aberta"}
                </p>
              </article>
            </div>
          </section>

          {doMes.length === 0 ? (
            <section className="panel empty">
              <h2>Nenhum registro em {nomeMes(mes)}</h2>
              <p>Quando alguém registrar, o resumo aparece aqui.</p>
            </section>
          ) : (
            <>
              <div className="qual-duas">
                <section className="panel" aria-labelledby="titulo-setor">
                  <div className="panel-head">
                    <div>
                      <h2 className="panel-title" id="titulo-setor">
                        Por setor
                      </h2>
                      <p className="panel-sub">Reclamações e ocorrências em {nomeMes(mes)}.</p>
                    </div>
                  </div>
                  <ul className="qual-barras">
                    {porSetor.map((s) => (
                      <li key={s.nome}>
                        <span className="qual-barras-nome">{s.nome}</span>
                        <span className="qual-barras-trilho" aria-hidden="true">
                          <span style={{ width: `${(s.problemas / maxSetor) * 100}%` }} />
                        </span>
                        <span className="qual-barras-valor">{s.problemas}</span>
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="panel" aria-labelledby="titulo-unidade">
                  <div className="panel-head">
                    <div>
                      <h2 className="panel-title" id="titulo-unidade">
                        Por unidade
                      </h2>
                    </div>
                  </div>
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th scope="col">Unidade</th>
                          <th scope="col">Problemas</th>
                          <th scope="col">Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {porUnidade.map((u) => (
                          <tr key={u.nome}>
                            <th scope="row">{u.nome}</th>
                            <td>{u.problemas}</td>
                            <td>{u.total}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </div>
            </>
          )}
        </>
      ) : null}

      <section className="panel" aria-labelledby="titulo-lista">
        <div className="panel-head">
          <div>
            <h2 className="panel-title" id="titulo-lista">
              {pVer ? `Registros de ${nomeMes(mes)}` : "Seus registros"}
            </h2>
            <p className="panel-sub">{pVer ? "Do mais recente para o mais antigo." : "Só você vê o que registrou."}</p>
          </div>
        </div>
        {(pVer ? doMes : todas).length === 0 ? (
          <p className="panel-sub" style={{ padding: "0 20px 20px" }}>
            Nada registrado ainda.
          </p>
        ) : (
          <ul className="qual-lista">
            {(pVer ? doMes : todas).slice(0, 200).map((o) => (
              <li key={o.id} className="qual-item">
                <div className="qual-item-topo">
                  <span className="status-pill" data-status={o.tipo === "elogio" ? "ritmo" : o.gravidade === "alta" ? "atrasado" : o.gravidade === "media" ? "atencao" : undefined}>
                    {rotuloTipo(o.tipo)}
                    {o.tipo !== "elogio" && ` · ${rotuloGravidade(o.gravidade)}`}
                  </span>
                  <span className="qual-item-meta">
                    {dataBR(o.data_ocorrencia)} · {o.unidade} · {o.setor}
                  </span>
                  {o.exemplo && <span className="badge">Exemplo</span>}
                  {o.tipo !== "elogio" && (
                    <span className="qual-item-estado" data-resolvida={o.status === "resolvida" ? "true" : undefined}>
                      {o.status === "resolvida" && o.resolvida_em ? `Resolvida em ${dataBR(o.resolvida_em)}` : "Aberta"}
                    </span>
                  )}
                </div>
                <p className="qual-item-texto">{o.descricao}</p>
                {pVer && o.tipo !== "elogio" && o.status === "aberta" && <ResolverBotao id={o.id} />}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
