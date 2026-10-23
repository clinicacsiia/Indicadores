// Peças de tela repetidas nas seções do CRM da Ressonância (todas server components).
import { codigoContato, telefoneBonito, linkWhatsApp, type Contato, type Horario } from "@/lib/crm-rm";

export const dataBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
export const hhmm = (h: string | null) => (h ? h.slice(0, 5) : "");
export const pct = (n: number | null) => (n === null ? "—" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`);
export const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
export const num = (n: number) => n.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
/** "2026-10-23T13:43:19+00:00" -> "23/10 13:43" (a hora do carimbo vem em UTC; o Brasil fica 3 h atrás). */
export const dataHoraBR = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

/** Verde = andou; vermelho = parou; amarelo = esperando. */
export function pilula(estado: string): string | undefined {
  if (["Agendado", "Realizado", "Confirmou"].includes(estado)) return "ritmo";
  if (["Não agendou", "Desistiu", "Faltou", "Cancelado"].includes(estado)) return "atrasado";
  if (["Orçamento enviado", "Aguardando resposta", "Aguardando autorização", "Não respondeu", "Reagendado"].includes(estado)) return "atencao";
  return undefined;
}

export function Painel({
  titulo,
  sub,
  id,
  contador,
  children,
}: {
  titulo: string;
  sub?: string;
  id: string;
  contador?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel-head">
        <div>
          <h2 className="panel-title" id={id}>
            {titulo}
            {contador !== undefined && contador > 0 && <span className="crm-contador">{contador}</span>}
          </h2>
          {sub && <p className="panel-sub">{sub}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

export function Kpi({ rotulo, valor, meta, cor }: { rotulo: string; valor: string; meta?: React.ReactNode; cor?: string }) {
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

export function Tabela({ colunas, children }: { colunas: string[]; children: React.ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {colunas.map((c) => (
              <th scope="col" key={c}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export const Vazio = ({ children }: { children: React.ReactNode }) => <p className="crm-vazio">{children}</p>;
export const Nota = ({ children }: { children: React.ReactNode }) => <p className="crm-nota">{children}</p>;

/** Como achar a pessoa: código do Klingo e, se houver, telefone com atalho do WhatsApp. */
export function Identificacao({ c }: { c: Contato }) {
  const zap = linkWhatsApp(c.telefone);
  if (!c.codigo_klingo && !c.telefone) return <span className="crm-item-meta">Sem código nem telefone — não dá para retomar</span>;
  return (
    <span className="crm-item-meta crm-identificacao">
      {c.codigo_klingo && <span>Klingo {c.codigo_klingo}</span>}
      {c.telefone && (
        <>
          <span>{telefoneBonito(c.telefone)}</span>
          {zap && (
            <a href={zap} target="_blank" rel="noopener noreferrer" className="crm-link">
              abrir WhatsApp
            </a>
          )}
        </>
      )}
    </span>
  );
}

/** Linha de resumo de um contato, usada nas filas e nas listas. */
export function ResumoContato({ c, verValores }: { c: Contato; verValores: boolean }) {
  return (
    <div className="crm-item-topo">
      <strong>{codigoContato(c.id)}</strong>
      <span className="status-pill" data-status={pilula(c.situacao)}>
        {c.situacao}
      </span>
      <span className="crm-item-meta">
        {dataBR(c.data_contato)} · {c.canal} · {c.exame} · {c.convenio ?? c.forma_pagamento}
        {verValores && c.valor_informado !== null ? ` · ${brl(c.valor_informado)}` : ""}
      </span>
      {c.exemplo && <span className="badge">Exemplo</span>}
    </div>
  );
}

/** Linha de resumo de uma marcação do Klingo. */
export function ResumoHorario({ h, verValores }: { h: Horario; verValores: boolean }) {
  return (
    <div className="crm-item-topo">
      <span className="status-pill" data-status={pilula(h.status)}>
        {h.status}
      </span>
      <span className="crm-item-meta">
        {dataBR(h.data_exame)}
        {h.horario ? ` ${hhmm(h.horario)}` : ""} · {h.exame} · {h.convenio ?? h.forma_pagamento}
        {` · marcação ${h.codigo_marcacao}`}
        {verValores && h.valor !== null && h.valor > 0 ? ` · ${brl(h.valor)}` : ""}
      </span>
    </div>
  );
}

/** Paciente da marcação: nome, prontuário e telefone com atalho do WhatsApp. Vem do Klingo, só para quem tem acesso ao CRM. */
export function PacienteHorario({ h }: { h: Horario }) {
  const zap = linkWhatsApp(h.telefone);
  return (
    <span className="crm-item-meta crm-identificacao">
      <span>{h.paciente ?? "Paciente sem nome no Klingo"}</span>
      {h.prontuario && <span>Prontuário {h.prontuario}</span>}
      {h.telefone ? (
        <>
          <span>{telefoneBonito(h.telefone)}</span>
          {zap && (
            <a href={zap} target="_blank" rel="noopener noreferrer" className="crm-link">
              abrir WhatsApp
            </a>
          )}
        </>
      ) : (
        <span>Sem telefone no Klingo</span>
      )}
    </span>
  );
}
