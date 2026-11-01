"use client";

import { useActionState, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { confirmarPresenca, enviarMensagem, pedirRemarcacao, type AcaoPaciente } from "./actions";

const inicial: AcaoPaciente = {};

// Botões e formulários da página do paciente. Cada ação vai ao servidor do site, que fala com o banco; o navegador nunca vê a chave.
export function Acoes({ token, podeAgir, confirmou }: { token: string; podeAgir: boolean; confirmou: boolean }) {
  const router = useRouter();
  const [confirmando, iniciarConfirmacao] = useTransition();
  const [resultado, setResultado] = useState<AcaoPaciente>(inicial);
  const [remarcar, remarcarAcao, remarcando] = useActionState(pedirRemarcacao.bind(null, token), inicial);

  if (!podeAgir) return null;
  return (
    <section className="portal-bloco" aria-label="O que você pode fazer">
      {confirmou ? (
        <p className="portal-ok" role="status">
          ✔ Presença confirmada. Esperamos você!
        </p>
      ) : (
        <button
          type="button"
          className="btn btn-primary portal-botao"
          disabled={confirmando}
          onClick={() =>
            iniciarConfirmacao(async () => {
              setResultado(await confirmarPresenca(token));
              router.refresh();
            })
          }
        >
          {confirmando ? "Confirmando…" : "Confirmo minha presença"}
        </button>
      )}
      {resultado.erro && (
        <p className="portal-erro" role="alert">
          {resultado.erro}
        </p>
      )}

      <details className="portal-remarcar">
        <summary>Preciso remarcar</summary>
        <form action={remarcarAcao} className="portal-form">
          <label className="field">
            <span className="field-label">Quer nos contar o motivo ou a melhor data? (opcional)</span>
            <textarea className="input" name="nota" rows={3} maxLength={500} />
          </label>
          <button type="submit" className="btn" disabled={remarcando}>
            {remarcando ? "Enviando…" : "Pedir para remarcar"}
          </button>
          {remarcar.erro && (
            <p className="portal-erro" role="alert">
              {remarcar.erro}
            </p>
          )}
          {remarcar.ok && (
            <p className="portal-ok" role="status">
              {remarcar.mensagem}
            </p>
          )}
        </form>
      </details>
    </section>
  );
}

export function FormMensagem({ token }: { token: string }) {
  const [estado, acao, enviando] = useActionState(enviarMensagem.bind(null, token), inicial);
  const caixa = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    if (estado.ok && caixa.current) caixa.current.value = "";
  }, [estado]);
  return (
    <form action={acao} className="portal-form">
      <label className="field">
        <span className="field-label">Escreva para a equipe</span>
        <textarea ref={caixa} className="input" name="texto" rows={3} maxLength={1000} required />
      </label>
      <button type="submit" className="btn btn-primary" disabled={enviando}>
        {enviando ? "Enviando…" : "Enviar mensagem"}
      </button>
      {estado.erro && (
        <p className="portal-erro" role="alert">
          {estado.erro}
        </p>
      )}
    </form>
  );
}
