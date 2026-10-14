import type { Metadata } from "next";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { PAINEIS, podeVerPainel } from "@/lib/paineis";
import { listarFavoritos } from "@/lib/favoritos";
import {
  alertasDoCartao,
  descricaoDoCartao,
  haQuanto,
  horaLocal,
  resumoDaColeta,
  situacaoDe,
  temProblema,
  type PainelRenovando,
  type StatusRelatorio,
} from "@/lib/inicio";
import { IconAlerta, IconCalendario } from "@/app/components/icons";
import { AtualizarTudoForm } from "./atualizar-tudo-form";
import { AtualizarSozinho } from "./atualizar-sozinho";
import { FavoritosPaineis } from "./favoritos-paineis";

// A atualização (server action do AtualizarTudoForm) espera as Edge Functions falarem com o Klingo.
export const maxDuration = 300;

export const metadata: Metadata = { title: "Início" };

export default async function Home() {
  const supabase = await createClient();
  const [{ data, error }, renovandoRes, profile, favoritos] = await Promise.all([
    supabase.rpc("status_coleta_relatorios"),
    supabase.rpc("paineis_renovando"),
    getCurrentProfile(),
    listarFavoritos(),
  ]);

  if (error) {
    console.error("Falha ao carregar status dos relatórios:", error.message);
  }

  // sem a lista de "atualizando agora" o resto da tela continua valendo
  if (renovandoRes.error) console.error("Falha ao ver painéis em atualização:", renovandoRes.error.message);

  const relatorios = (data ?? []) as StatusRelatorio[];
  const renovando = ((renovandoRes.data ?? []) as PainelRenovando[]).flatMap((r) => {
    const painel = PAINEIS.find((p) => p.id === r.painel);
    return painel && podeVerPainel(profile, painel.id) ? [{ ...r, nome: painel.nome }] : [];
  });
  const paineisDisponiveis = PAINEIS.filter((p) => podeVerPainel(profile, p.id));
  const ehAdmin = profile?.role === "admin";
  const agora = Date.now();
  const resumo = resumoDaColeta(relatorios, agora);

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Início</h1>
          <p className="page-lede">
            Status da coleta dos relatórios ativos do Klingo: os dias recentes dos diários e os meses dos mensais.
          </p>
        </div>
      </header>

      <AtualizarSozinho rapido={renovando.length > 0} />

      <AtualizarTudoForm />

      {renovando.length > 0 && (
        <div className="painel-aviso" data-tipo="info" role="status" aria-live="polite">
          <div className="painel-aviso-linha">
            <span className="painel-aviso-nome">
              <span className="spinner" aria-hidden="true" />
              <strong>Atualizando agora: {renovando.map((r) => r.nome).join(", ")}</strong>
            </span>
            <span>
              {renovando
                .map((r) => {
                  const falta = r.previsto_s - r.decorrido_s;
                  const texto = falta > 3 ? `faltam cerca de ${falta} s` : "quase pronto";
                  return renovando.length === 1 ? texto : `${r.nome}: ${texto}`;
                })
                .join(" · ")}
            </span>
          </div>
        </div>
      )}

      <FavoritosPaineis paineis={paineisDisponiveis} favoritos={favoritos} />

      {error && (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar o status dos relatórios agora. Tente novamente em instantes.
        </div>
      )}

      {ehAdmin && !error && relatorios.length === 0 && (
        <section className="panel empty">
          <span className="empty-icon">
            <IconCalendario size={26} />
          </span>
          <h2>Nenhum relatório ativo</h2>
          <p>Marque ativo = true em dim_relatorio nos relatórios que você precisa para eles aparecerem aqui.</p>
        </section>
      )}

      {ehAdmin && relatorios.length > 0 && (
        <details className="panel coleta-grupo">
          <summary>
            <h2 className="panel-title" id="titulo-sincronizacao">
              Coleta dos relatórios
            </h2>
            <span className="panel-sub">
              {resumo.completos} de {resumo.total} completos
              {resumo.incompletos > 0 && ` · ${resumo.incompletos} ainda sendo coletados`}
              {resumo.problemas > 0 && ` · ${resumo.problemas} com pausa ou erro`}
              {resumo.ultimo && ` · última coleta ${haQuanto(resumo.ultimo, agora)} (${horaLocal(resumo.ultimo)})`}
            </span>
          </summary>
          {resumo.parada && (
            <div className="notice" role="alert" style={{ margin: "0 20px 12px" }}>
              <IconAlerta />
              {resumo.ultimo
                ? "Nenhum relatório foi coletado nos últimos 30 minutos. A coleta automática (a cada 5 minutos) pode estar parada."
                : "Nenhum relatório foi coletado ainda."}
            </div>
          )}
          <div className="status-grid coleta-grupo-corpo" aria-label="Status dos relatórios">
            {relatorios.map((r) => {
              const situacao = situacaoDe(r);
              const alertas = alertasDoCartao(r);
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
                  <p className="status-card-meta">{descricaoDoCartao(r)}</p>
                  {alertas.map((a) => (
                    <p className="status-card-alerta" data-tipo={a.tipo} key={a.texto}>
                      {a.texto}
                    </p>
                  ))}
                  {ehAdmin && temProblema(r) && r.ultimo_erro && (
                    <p className="status-card-meta" title={r.ultimo_erro}>
                      Último erro: {r.ultimo_erro}
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        </details>
      )}
    </>
  );
}
