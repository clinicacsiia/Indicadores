"use client";

import { useState } from "react";
import { useFormStatus } from "react-dom";
import {
  CONFIRMACOES,
  MAX_OBS,
  MOTIVOS_FALTA,
  MOTIVOS_OPERACIONAIS,
  MOTIVOS_PERDA,
  PROXIMAS_ACOES,
  SAI_DO_COMPARECIMENTO,
  SITUACOES,
  SITUACOES_PERDA,
  STATUS_AGENDA,
  VAGA_RECUPERADA,
  type Contato,
  type Horario,
} from "@/lib/crm-rm";
import type { CrmState } from "./actions";

export function Campo({ id, rotulo, dica, children }: { id: string; rotulo: string; dica?: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {rotulo}
      </label>
      {children}
      {dica && (
        <span className="crm-dica" id={`${id}-dica`}>
          {dica}
        </span>
      )}
    </div>
  );
}

export function Seletor({
  id,
  name,
  opcoes,
  valor,
  onChange,
  vazio,
  obrigatorio,
}: {
  id: string;
  name: string;
  opcoes: readonly string[];
  valor?: string;
  onChange?: (v: string) => void;
  vazio?: string;
  obrigatorio?: boolean;
}) {
  const controlado = onChange !== undefined;
  return (
    <select
      id={id}
      name={name}
      className="select"
      required={obrigatorio}
      {...(controlado ? { value: valor ?? "", onChange: (e) => onChange(e.target.value) } : { defaultValue: valor ?? "" })}
    >
      {vazio !== undefined && <option value="">{vazio}</option>}
      {opcoes.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

export function BotaoEnviar({ texto, ocupado }: { texto: string; ocupado: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className="btn btn-primary" disabled={pending}>
      {pending && <span className="spinner" aria-hidden="true" />}
      {pending ? ocupado : texto}
    </button>
  );
}

export function Retorno({ state, okTexto }: { state: CrmState; okTexto: string }) {
  return (
    <span role="status" aria-live="polite" className="crm-retorno" data-erro={state.error ? "true" : undefined}>
      {state.error ?? (state.ok ? okTexto : "")}
    </span>
  );
}

const dinheiro = (n: number | null | undefined) => (n === null || n === undefined ? "" : n.toFixed(2).replace(".", ","));

// Situação, motivo, valor, próxima ação, retorno, responsável e observações: o que se atualiza a cada conversa com o paciente.
export function CamposAcompanhamento({ pre, p, contato }: { pre: string; p?: Contato; contato?: boolean }) {
  const [situacao, setSituacao] = useState<string>(p?.situacao ?? "Novo contato");
  const perdeu = (SITUACOES_PERDA as string[]).includes(situacao);
  const info = SITUACOES.find((s) => s.id === situacao);
  return (
    <>
      <Campo id={`${pre}-situacao`} rotulo="Situação" dica={info ? `${info.significado}.` : undefined}>
        <Seletor id={`${pre}-situacao`} name="situacao" opcoes={SITUACOES.map((s) => s.id)} valor={situacao} onChange={setSituacao} obrigatorio />
      </Campo>
      {perdeu && (
        <Campo id={`${pre}-motivo`} rotulo="Motivo da perda" dica="Obrigatório quando não agendou ou desistiu.">
          <Seletor id={`${pre}-motivo`} name="motivo_perda" opcoes={MOTIVOS_PERDA.map((m) => m.id)} valor={p?.motivo_perda ?? ""} vazio="Escolha" obrigatorio />
        </Campo>
      )}
      <Campo id={`${pre}-valor`} rotulo="Valor informado (R$)" dica="O que foi passado ao paciente. Em branco para convênio.">
        <input id={`${pre}-valor`} name="valor_informado" className="input" inputMode="decimal" placeholder="0,00" defaultValue={dinheiro(p?.valor_informado)} />
      </Campo>
      <Campo id={`${pre}-acao`} rotulo="Próxima ação">
        <Seletor id={`${pre}-acao`} name="proxima_acao" opcoes={PROXIMAS_ACOES} valor={p?.proxima_acao ?? ""} vazio="Nenhuma" />
      </Campo>
      <Campo id={`${pre}-retorno`} rotulo="Data do retorno" dica="Quando falar de novo com o paciente.">
        <input id={`${pre}-retorno`} name="data_retorno" type="date" className="input" min={p?.data_contato} defaultValue={p?.data_retorno ?? ""} />
      </Campo>
      <Campo id={`${pre}-resp`} rotulo="Responsável">
        <input id={`${pre}-resp`} name="responsavel" className="input" maxLength={60} placeholder="Quem atendeu" defaultValue={p?.responsavel ?? ""} />
      </Campo>
      <div className="field crm-largo">
        <label className="field-label" htmlFor={`${pre}-obs`}>
          Observações
        </label>
        <textarea
          id={`${pre}-obs`}
          name="observacoes"
          className="input crm-texto"
          rows={2}
          maxLength={MAX_OBS}
          placeholder={contato ? "Sem nome, CPF ou dado clínico do paciente." : "Sem dado que identifique o paciente."}
          defaultValue={p?.observacoes ?? ""}
        />
      </div>
    </>
  );
}

// Status, confirmação, motivo, vaga recuperada, valor, horas paradas e motivo operacional: o que se atualiza depois do exame.
export function CamposResultado({ pre, h }: { pre: string; h?: Horario }) {
  const [status, setStatus] = useState<string>(h?.status ?? "Agendado");
  const saiu = (SAI_DO_COMPARECIMENTO as string[]).includes(status);
  const info = STATUS_AGENDA.find((s) => s.id === status);
  return (
    <>
      <Campo id={`${pre}-status`} rotulo="Status da agenda" dica={info ? `${info.significado}.` : undefined}>
        <Seletor id={`${pre}-status`} name="status" opcoes={STATUS_AGENDA.map((s) => s.id)} valor={status} onChange={setStatus} obrigatorio />
      </Campo>
      <Campo id={`${pre}-conf`} rotulo="Confirmação prévia" dica="O que o paciente respondeu antes do exame.">
        <Seletor id={`${pre}-conf`} name="confirmacao" opcoes={CONFIRMACOES} valor={h?.confirmacao ?? "Não contatado"} obrigatorio />
      </Campo>
      {saiu && (
        <>
          <Campo id={`${pre}-falta`} rotulo="Motivo da falta ou cancelamento">
            <Seletor id={`${pre}-falta`} name="motivo_falta" opcoes={MOTIVOS_FALTA} valor={h?.motivo_falta ?? ""} vazio="Não informado" />
          </Campo>
          <Campo id={`${pre}-vaga`} rotulo="Vaga recuperada?" dica="Sim = outro paciente ocupou o horário.">
            <Seletor id={`${pre}-vaga`} name="vaga_recuperada" opcoes={VAGA_RECUPERADA} valor={h?.vaga_recuperada ?? "Não se aplica"} obrigatorio />
          </Campo>
        </>
      )}
      {status === "Realizado" && (
        <Campo id={`${pre}-real`} rotulo="Valor realizado (R$)">
          <input id={`${pre}-real`} name="valor_realizado" className="input" inputMode="decimal" placeholder="0,00" defaultValue={dinheiro(h?.valor_realizado ?? h?.valor_previsto)} />
        </Campo>
      )}
      <Campo id={`${pre}-horas`} rotulo="Horas paradas ou de atraso" dica="Tempo do equipamento sem exame neste horário.">
        <input id={`${pre}-horas`} name="horas_paradas" className="input" inputMode="decimal" placeholder="0" defaultValue={h?.horas_paradas ?? ""} />
      </Campo>
      <Campo id={`${pre}-op`} rotulo="Motivo operacional" dica="Só se houve problema na sala.">
        <Seletor id={`${pre}-op`} name="motivo_operacional" opcoes={MOTIVOS_OPERACIONAIS} valor={h?.motivo_operacional ?? ""} vazio="Nenhum" />
      </Campo>
    </>
  );
}
