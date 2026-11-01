import type { Metadata } from "next";
import { chamarPortal } from "@/lib/portal-servidor";
import { diaPorExtenso, ROTULO_SITUACAO, textoDoMotivo, tokenValido } from "@/lib/portal";
import { AtualizarSozinho } from "@/app/(app)/atualizar-sozinho";
import { Acoes, FormMensagem } from "./Acoes";

// Página pública do paciente (sem login): o código do link é a chave. Nunca indexar nem repassar o endereço a outros sites.
export const metadata: Metadata = {
  title: "Seu atendimento | Clínica CSI",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};
export const dynamic = "force-dynamic";

type Props = { params: Promise<{ token: string }> };

export default async function PaginaDoPaciente({ params }: Props) {
  const { token } = await params;
  const r = tokenValido(token) ? await chamarPortal("portal_ver", { p_token: token }) : ({ ok: false, motivo: "invalido" } as const);

  if (!r.ok) {
    return (
      <main className="portal">
        <header className="portal-topo">
          <strong>Clínica CSI</strong>
        </header>
        <section className="portal-bloco" role="alert">
          <h1>Não foi possível abrir</h1>
          <p>{textoDoMotivo(r.motivo)}</p>
        </section>
      </main>
    );
  }

  const quando = (iso: string) => new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

  return (
    <main className="portal">
      <AtualizarSozinho rapido={false} segundos={30} />
      <header className="portal-topo">
        <strong>Clínica CSI</strong>
      </header>

      <section className="portal-bloco">
        <h1>{r.nome ? `Olá, ${r.nome}!` : "Olá!"}</h1>
        <p className="portal-dia">
          {diaPorExtenso(r.data)}
          {r.unidade ? ` · ${r.unidade}` : ""}
        </p>
        <ul className="portal-exames">
          {r.exames.map((e, i) => (
            <li key={i} data-situacao={e.situacao}>
              <span className="portal-hora">{e.hora}</span>
              <span className="portal-exame">{e.exame}</span>
              <span className="portal-situacao">{ROTULO_SITUACAO[e.situacao] ?? e.situacao}</span>
            </li>
          ))}
        </ul>
      </section>

      <Acoes token={token} podeAgir={r.pode_agir} confirmou={!!r.confirmou_em} />

      <section className="portal-bloco" aria-label="Conversa com a equipe">
        <h2>Conversa com a equipe</h2>
        {r.mensagens.length === 0 ? (
          <p className="portal-vazio">Nenhuma mensagem ainda.</p>
        ) : (
          <div className="portal-conversa" role="log" aria-live="polite">
            {r.mensagens.map((m, i) => (
              <div key={i} className="portal-msg" data-de={m.de}>
                <span className="portal-msg-topo">
                  <strong>{m.de === "paciente" ? "Você" : "Clínica CSI"}</strong> <time dateTime={m.quando}>{quando(m.quando)}</time>
                </span>
                <span className="portal-msg-texto">{m.texto}</span>
              </div>
            ))}
          </div>
        )}
        <FormMensagem token={token} />
      </section>

      <footer className="portal-rodape">
        <p>
          Esta é uma conversa com a equipe da clínica. Não envie documentos nem informações de saúde por aqui. Em caso de urgência, ligue para a clínica ou procure um serviço de emergência.
        </p>
      </footer>
    </main>
  );
}
