"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useFormStatus } from "react-dom";
import { MAX_JUSTIFICATIVA, MIN_JUSTIFICATIVA, hojeEmBrasilia } from "@/lib/avisos";
import { fecharAviso, reabrirAviso, type AvisoAcaoState } from "./actions";

const inicial: AvisoAcaoState = {};

function Enviar({ rotulo, enviando, primario, name, value }: { rotulo: string; enviando: string; primario?: boolean; name?: string; value?: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" name={name} value={value} className={primario ? "btn btn-primary" : "btn"} disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? enviando : rotulo}
    </button>
  );
}

// Fechar um aviso exige dizer o que foi feito (ou por que ele pode ser aceito) e, se já houver, a data prevista. Abre sozinho quando a pessoa
// chegou pelo botão "Justificar e fechar" do painel (o endereço termina em #aviso-<id>).
export function FecharAviso({ id, persistente }: { id: number; persistente: boolean }) {
  const [state, action] = useActionState(fecharAviso, inicial);
  const [aberto, setAberto] = useState(false);
  const [texto, setTexto] = useState("");
  const campo = useRef<HTMLTextAreaElement>(null);
  const tamanho = texto.trim().length;

  useEffect(() => {
    if (window.location.hash === `#aviso-${id}`) setAberto(true);
  }, [id]);

  useEffect(() => {
    if (aberto && window.location.hash === `#aviso-${id}`) campo.current?.focus();
  }, [aberto, id]);

  return (
    <details
      className="aviso-fechar"
      open={aberto}
      onToggle={(e) => setAberto((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>Justificar e fechar</summary>
      <form action={action} className="aviso-fechar-form">
        <input type="hidden" name="id" value={id} />
        <div className="field">
          <label className="field-label" htmlFor={`justificativa-${id}`}>
            O que foi feito, ou por que este aviso pode ser fechado?
          </label>
          <textarea
            id={`justificativa-${id}`}
            ref={campo}
            name="justificativa"
            className="input aviso-textarea"
            rows={3}
            required
            minLength={MIN_JUSTIFICATIVA}
            maxLength={MAX_JUSTIFICATIVA}
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            aria-describedby={`ajuda-${id}`}
            placeholder="Ex.: Corrigi os lançamentos 123 e 124 no Klingo; confirmei com o faturamento."
          />
          <span id={`ajuda-${id}`} className="aviso-ajuda">
            {tamanho < MIN_JUSTIFICATIVA
              ? `Escreva pelo menos ${MIN_JUSTIFICATIVA} caracteres (${tamanho}/${MIN_JUSTIFICATIVA}). `
              : ""}
            Justificar não corrige o Klingo: se o dado está errado ou faltando, corrija lá. {" "}
            {persistente
              ? "Este aviso pode ser aceito: fica como informação enquanto continuar igual e reabre se piorar."
              : "Na próxima atualização dos dados o painel confere: se o problema sumiu, o aviso fica resolvido; se continuar, ele reabre (a não ser que você informe uma data prevista)."}
          </span>
        </div>
        <div className="field">
          <label className="field-label" htmlFor={`previsto-${id}`}>
            Já tem data para resolver ou enviar? <span className="aviso-opcional">(opcional)</span>
          </label>
          <input id={`previsto-${id}`} name="previsto" type="date" className="input aviso-data" min={hojeEmBrasilia()} max={hojeEmBrasilia(365)} aria-describedby={`ajuda-data-${id}`} />
          <span id={`ajuda-data-${id}`} className="aviso-ajuda">
            Até essa data o aviso fica como informação, mesmo com os dados atualizados. Passou a data e o problema continua: ele reabre e conta como recorrência.
          </span>
        </div>
        {state.error && (
          <p className="aviso-erro" role="alert">
            {state.error}
          </p>
        )}
        <div className="aviso-fechar-acoes">
          <Enviar rotulo="Fechar aviso" enviando="Fechando" primario />
        </div>
      </form>
    </details>
  );
}

// Quem vê a informação e discorda reabre o aviso: os dois botões contam como recorrência.
export function ReabrirAviso({ id }: { id: number }) {
  const [state, action] = useActionState(reabrirAviso, inicial);
  return (
    <form action={action} className="aviso-reabrir">
      <input type="hidden" name="id" value={id} />
      <Enviar rotulo="Ainda não resolvi" enviando="Reabrindo" name="motivo" value="nao_resolvi" />
      <Enviar rotulo="Não explica o problema" enviando="Reabrindo" name="motivo" value="nao_explicou" />
      {state.error && (
        <p className="aviso-erro" role="alert">
          {state.error}
        </p>
      )}
    </form>
  );
}
