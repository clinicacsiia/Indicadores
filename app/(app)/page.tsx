import type { Metadata } from "next";
import { createClient } from "@/lib/supabase/server";
import { IconAlerta, IconCalendario } from "@/app/components/icons";
import { AtualizarTudoForm } from "./atualizar-tudo-form";

// A atualização (server action do AtualizarTudoForm) espera as Edge Functions falarem com o Klingo.
export const maxDuration = 300;

export const metadata: Metadata = { title: "Início" };

type StatusRelatorio = {
  klingo_id: string;
  nome: string;
  categoria: string | null;
  periodicidade: string | null;
  ultimo_periodo: string | null;
  ultimo_sync: string | null;
  dias_sincronizados: number;
  dias_esperados: number;
  pct: number;
};

type Situacao = "batida" | "ritmo" | "atencao" | "atrasado";

function situacaoDe(pct: number): Situacao {
  if (pct >= 100) return "batida";
  if (pct >= 75) return "ritmo";
  if (pct >= 50) return "atencao";
  return "atrasado";
}

function formatarData(iso: string) {
  const [, mes, dia] = iso.split("-");
  return `${dia}/${mes}`;
}

export default async function Home() {
  const supabase = await createClient();
  const { data, error } = await supabase.rpc("status_sincronizacao_relatorios");

  if (error) {
    console.error("Falha ao carregar status dos relatórios:", error.message);
  }

  const relatorios = (data ?? []) as StatusRelatorio[];

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Início</h1>
          <p className="page-lede">
            Status da sincronização dos relatórios liberados para visualização, vindos do Klingo.
          </p>
        </div>
      </header>

      <AtualizarTudoForm />

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar o status dos relatórios agora. Tente novamente em instantes.
        </div>
      )}

      {!error && relatorios.length === 0 && (
        <section className="panel empty">
          <span className="empty-icon">
            <IconCalendario size={26} />
          </span>
          <h2>Nenhum relatório liberado para visualização</h2>
          <p>Libere um relatório em Configurações (dim_relatorio.ativo) para ele aparecer aqui.</p>
        </section>
      )}

      {relatorios.length > 0 && (
        <section className="status-grid" aria-label="Status dos relatórios">
          {relatorios.map((r) => {
            const situacao = situacaoDe(r.pct);
            const faltam = Math.max(r.dias_esperados - r.dias_sincronizados, 0);
            return (
              <article className="panel status-card" key={r.klingo_id}>
                <div className="status-card-head">
                  <div className="status-card-titles">
                    <p className="status-card-cat">{r.categoria ?? "Geral"}</p>
                    <h2 className="status-card-title">{r.nome}</h2>
                  </div>
                  <span className="status-pill" data-status={situacao}>
                    {Math.round(r.pct)}%
                  </span>
                </div>
                <div className="meter" data-status={situacao}>
                  <span className="meter-fill" style={{ width: `${Math.min(r.pct, 100)}%` }} />
                </div>
                <p className="status-card-meta">
                  {r.ultimo_periodo ? `Atualizado até ${formatarData(r.ultimo_periodo)}` : "Nunca sincronizado"}
                  {faltam > 0 && ` · faltam ${faltam} ${faltam === 1 ? "dia" : "dias"}`}
                </p>
              </article>
            );
          })}
        </section>
      )}
    </>
  );
}
