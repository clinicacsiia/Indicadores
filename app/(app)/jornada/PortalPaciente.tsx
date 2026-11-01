"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { linkWhatsAppComTexto, mensagemDoLink, urlDoPortal } from "@/lib/portal";

type Acesso = { expira_em: string; ultimo_acesso_em: string | null; n_acessos: number; revogado_em: string | null };

const quando = (iso: string) => new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

// Link seguro do paciente: a equipe gera, copia ou abre o WhatsApp com a mensagem pronta. O código só aparece aqui, logo depois de gerado (o banco guarda só o hash).
export function PortalPaciente({ cardId, nome, dataRef, celular, confirmouEm }: { cardId: number; nome: string | null; dataRef: string; celular: string | null; confirmouEm: string | null }) {
  const [acesso, setAcesso] = useState<Acesso | null | undefined>(undefined);
  const [url, setUrl] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [copiado, setCopiado] = useState(false);

  const ler = useCallback(async () => {
    const { data } = await createClient()
      .from("jornada_portal_acesso")
      .select("expira_em, ultimo_acesso_em, n_acessos, revogado_em")
      .eq("card_id", cardId)
      .is("revogado_em", null)
      .gt("expira_em", new Date().toISOString())
      .order("id", { ascending: false })
      .limit(1);
    setAcesso(((data ?? [])[0] as Acesso | undefined) ?? null);
  }, [cardId]);

  useEffect(() => {
    setUrl(null);
    setErro(null);
    setCopiado(false);
    setAcesso(undefined);
    void ler();
  }, [ler]);

  const gerar = async () => {
    setOcupado(true);
    setErro(null);
    const { data, error } = await createClient().rpc("jornada_portal_gerar_link", { p_card: cardId });
    setOcupado(false);
    if (error) {
      setErro(error.message || "Não foi possível gerar o link.");
      return;
    }
    setUrl(urlDoPortal(window.location.origin, (data as { token: string }).token));
    await ler();
  };

  const revogar = async () => {
    setOcupado(true);
    setErro(null);
    const { error } = await createClient().rpc("jornada_portal_revogar_link", { p_card: cardId });
    setOcupado(false);
    if (error) setErro(error.message || "Não foi possível revogar o link.");
    setUrl(null);
    await ler();
  };

  const copiar = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopiado(true);
    } catch {
      setErro("Não foi possível copiar. Selecione o link e copie à mão.");
    }
  };

  const wa = url ? linkWhatsAppComTexto(celular, mensagemDoLink(nome, dataRef, url)) : null;

  return (
    <section className="jornada-portal" aria-label="Link do paciente">
      <h3>Paciente no site</h3>
      {confirmouEm && <p className="jornada-portal-ok">✔ O paciente confirmou a presença pelo site às {quando(confirmouEm)}. Registre no Klingo (há uma tarefa para isso).</p>}
      {acesso === undefined ? (
        <p className="panel-sub">Carregando…</p>
      ) : acesso ? (
        <p className="panel-sub">
          Link ativo até {quando(acesso.expira_em)} · {acesso.n_acessos} {acesso.n_acessos === 1 ? "acesso" : "acessos"}
          {acesso.ultimo_acesso_em ? ` · último às ${quando(acesso.ultimo_acesso_em)}` : ""}
        </p>
      ) : (
        <p className="panel-sub">Nenhum link ativo.</p>
      )}
      <div className="jornada-botoes">
        <button type="button" className="btn" disabled={ocupado} onClick={() => void gerar()}>
          {acesso ? "Gerar novo link (o anterior para de valer)" : "Gerar link do paciente"}
        </button>
        {acesso && (
          <button type="button" className="btn" disabled={ocupado} onClick={() => void revogar()}>
            Revogar link
          </button>
        )}
      </div>
      {url && (
        <div className="jornada-portal-link">
          <input className="input" readOnly value={url} aria-label="Link do paciente" onFocus={(e) => e.currentTarget.select()} />
          <div className="jornada-botoes">
            <button type="button" className="btn" onClick={() => void copiar()}>
              {copiado ? "Copiado ✔" : "Copiar"}
            </button>
            {wa ? (
              <a className="btn btn-primary" href={wa} target="_blank" rel="noopener noreferrer">
                Abrir WhatsApp com a mensagem
              </a>
            ) : (
              <span className="panel-sub">Sem celular válido no Klingo: copie o link e envie por outro canal.</span>
            )}
          </div>
          <p className="panel-sub">Este link aparece só agora. Quem tiver o link vê o primeiro nome, o dia e os exames. Não envie por canal onde outras pessoas possam ler.</p>
        </div>
      )}
      {erro && (
        <p className="jornada-erro" role="alert">
          {erro}
        </p>
      )}
    </section>
  );
}
