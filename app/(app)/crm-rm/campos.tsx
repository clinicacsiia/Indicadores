"use client";

import { useState } from "react";
import { useFormStatus } from "react-dom";
import {
  MAX_OBS,
  MOTIVOS_PERDA,
  PROXIMAS_ACOES,
  SITUACOES,
  SITUACOES_PERDA,
  roteiroDoMotivo,
  telefoneBonito,
  type Contato,
  type ExameCatalogo,
  type Preco,
} from "@/lib/crm-rm";
import type { CrmState } from "./actions";

export const dinheiro = (n: number | null | undefined) => (n === null || n === undefined ? "" : n.toFixed(2).replace(".", ","));
export const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });

export function Campo({ id, rotulo, dica, children }: { id: string; rotulo: string; dica?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {rotulo}
      </label>
      {children}
      {dica && <span className="crm-dica">{dica}</span>}
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

export function BotaoEnviar({ texto, ocupado, secundario }: { texto: string; ocupado: string; secundario?: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={secundario ? "btn" : "btn btn-primary"} disabled={pending}>
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

/** Lista de exames agrupada, com o nome exato do Klingo. */
export function SeletorExame({
  id,
  exames,
  valor,
  onChange,
}: {
  id: string;
  exames: ExameCatalogo[];
  valor: string;
  onChange: (v: string) => void;
}) {
  const grupos = [...new Set(exames.map((e) => e.grupo))].sort();
  return (
    <select id={id} name="exame" className="select" required value={valor} onChange={(e) => onChange(e.target.value)}>
      <option value="">Escolha o exame</option>
      {grupos.map((g) => (
        <optgroup key={g} label={g}>
          {exames
            .filter((e) => e.grupo === g)
            .map((e) => (
              <option key={e.id} value={e.nome}>
                {e.nome}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

/** O que a atendente precisa saber na hora: preço praticado, preparo, sedação e duração. */
export function FichaDoExame({ exame, preco }: { exame: ExameCatalogo | undefined; preco: Preco | undefined }) {
  if (!exame) return null;
  const temPreco = preco && (preco.particular_mediana !== null || preco.convenio_medio !== null);
  return (
    <div className="crm-ficha crm-largo">
      <strong className="crm-ficha-titulo">{exame.nome}</strong>
      <ul className="crm-ficha-lista">
        {temPreco ? (
          <li>
            <span>Preço praticado</span>
            <b>
              {preco?.particular_mediana !== null && preco?.particular_mediana !== undefined
                ? `Particular ${brl(preco.particular_mediana)}${
                    preco.particular_min !== null && preco.particular_max !== null && preco.particular_min !== preco.particular_max
                      ? ` (de ${brl(preco.particular_min)} a ${brl(preco.particular_max)})`
                      : ""
                  }`
                : "Particular: sem registro"}
              {preco?.convenio_medio !== null && preco?.convenio_medio !== undefined ? ` · Convênio ${brl(preco.convenio_medio)} em média` : ""}
            </b>
          </li>
        ) : (
          <li>
            <span>Preço praticado</span>
            <b>Sem registro nos últimos meses — confirme com o faturamento</b>
          </li>
        )}
        <li>
          <span>Sedação</span>
          <b>{exame.sedacao ? "Sim — avise o valor diferente e o preparo da anestesia" : "Não"}</b>
        </li>
        <li>
          <span>Contraste</span>
          <b>{exame.contraste ?? "Não cadastrado — pergunte à equipe técnica"}</b>
        </li>
        <li>
          <span>Duração</span>
          <b>{exame.duracao_min ? `${exame.duracao_min} minutos` : "Não cadastrada"}</b>
        </li>
        <li>
          <span>Preparo</span>
          <b>{exame.preparo ?? "Não cadastrado — pergunte à equipe técnica antes de orientar o paciente"}</b>
        </li>
        {exame.observacao && (
          <li>
            <span>Observação</span>
            <b>{exame.observacao}</b>
          </li>
        )}
      </ul>
      <span className="crm-dica">O preço vem do que a clínica cobrou nos últimos 6 meses (Klingo). Serve de referência, não é tabela oficial.</span>
    </div>
  );
}

/** Passo a passo do motivo da perda, para quem está começando saber o que fazer. */
export function Roteiro({ motivo }: { motivo: string }) {
  const passos = roteiroDoMotivo(motivo);
  if (!passos.length) return null;
  return (
    <div className="crm-roteiro crm-largo">
      <strong>O que fazer quando o motivo é “{motivo}”</strong>
      <ol>
        {passos.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ol>
    </div>
  );
}

/** Situação, motivo, valor, próxima ação, retorno e identificação: o que muda a cada conversa. */
export function CamposAcompanhamento({ pre, p, responsavelPadrao = "" }: { pre: string; p?: Contato; responsavelPadrao?: string }) {
  const [situacao, setSituacao] = useState<string>(p?.situacao ?? "Novo contato");
  const [motivo, setMotivo] = useState<string>(p?.motivo_perda ?? "");
  const perdeu = (SITUACOES_PERDA as string[]).includes(situacao);
  const info = SITUACOES.find((s) => s.id === situacao);
  return (
    <>
      <Campo id={`${pre}-situacao`} rotulo="Situação" dica={info ? `${info.significado}. ${info.acao}.` : undefined}>
        <Seletor id={`${pre}-situacao`} name="situacao" opcoes={SITUACOES.map((s) => s.id)} valor={situacao} onChange={setSituacao} obrigatorio />
      </Campo>
      {(situacao === "Agendado" || situacao === "Aguardando autorização") && (
        <p className="crm-aviso crm-largo" role="note">
          <strong>Faça no Klingo:</strong>{" "}
          {situacao === "Agendado"
            ? "a marcação do exame. Aqui só se anota o código da marcação; este site não agenda nem atualiza o Klingo."
            : "o pedido de autorização ao convênio. Este site não envia nem atualiza nada no Klingo; aqui você só acompanha."}
        </p>
      )}
      {perdeu && (
        <Campo id={`${pre}-motivo`} rotulo="Motivo da perda" dica="Obrigatório quando não agendou ou desistiu.">
          <Seletor id={`${pre}-motivo`} name="motivo_perda" opcoes={MOTIVOS_PERDA.map((m) => m.id)} valor={motivo} onChange={setMotivo} vazio="Escolha" obrigatorio />
        </Campo>
      )}
      <Campo id={`${pre}-valor`} rotulo="Valor informado (R$)" dica="O que foi passado ao paciente.">
        <input id={`${pre}-valor`} name="valor_informado" className="input" inputMode="decimal" placeholder="0,00" defaultValue={dinheiro(p?.valor_informado)} />
      </Campo>
      {!perdeu && (
        <>
          <Campo id={`${pre}-acao`} rotulo="Próxima ação">
            <Seletor id={`${pre}-acao`} name="proxima_acao" opcoes={PROXIMAS_ACOES} valor={p?.proxima_acao ?? ""} vazio="Nenhuma" />
          </Campo>
          <Campo id={`${pre}-retorno`} rotulo="Data do retorno" dica="Quando falar de novo. Vira a fila da aba Meu dia.">
            <input id={`${pre}-retorno`} name="data_retorno" type="date" className="input" min={p?.data_contato} defaultValue={p?.data_retorno ?? ""} />
          </Campo>
        </>
      )}
      <Campo id={`${pre}-codigo`} rotulo="Código no Klingo" dica={situacao === "Agendado" ? "Obrigatório: o código da marcação já feita no Klingo." : "Do paciente ou da marcação. É assim que você acha a pessoa depois."}>
        <input id={`${pre}-codigo`} name="codigo_klingo" className="input" maxLength={30} placeholder="ex.: 184323" required={situacao === "Agendado"} defaultValue={p?.codigo_klingo ?? ""} />
      </Campo>
      <Campo id={`${pre}-tel`} rotulo="Telefone (opcional)" dica="Só para retomar o contato. Não aparece nos indicadores.">
        <input id={`${pre}-tel`} name="telefone" className="input" inputMode="tel" maxLength={16} placeholder="(71) 99999-8888" defaultValue={telefoneBonito(p?.telefone ?? null)} />
      </Campo>
      <Campo id={`${pre}-resp`} rotulo="Responsável">
        <input id={`${pre}-resp`} name="responsavel" className="input" maxLength={60} placeholder="Quem atendeu" defaultValue={p ? (p.responsavel ?? "") : responsavelPadrao} />
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
          placeholder="O que o paciente pediu, o que ficou combinado. Sem dado clínico."
          defaultValue={p?.observacoes ?? ""}
        />
      </div>
      {perdeu && motivo && <Roteiro motivo={motivo} />}
    </>
  );
}
