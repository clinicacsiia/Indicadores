"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { CANAIS, EXAMES, FORMAS_PAGAMENTO, TIPOS_PACIENTE } from "@/lib/crm-rm";
import { atualizarContato, registrarContato, type CrmState } from "./actions";
import { BotaoEnviar, Campo, CamposAcompanhamento, Retorno, Seletor } from "./campos";
import type { Contato } from "@/lib/crm-rm";

const inicial: CrmState = {};

export function NovoContatoForm({ hoje }: { hoje: string }) {
  const [state, action] = useActionState(registrarContato, inicial);
  const [forma, setForma] = useState("Particular");
  const [versao, setVersao] = useState(0);
  const ref = useRef<HTMLFormElement>(null);

  // Registrou: limpa para o próximo contato (a chave nova refaz os campos da situação).
  useEffect(() => {
    if (state.ok) {
      ref.current?.reset();
      setForma("Particular");
      setVersao((v) => v + 1);
    }
  }, [state]);

  return (
    <form ref={ref} action={action} className="crm-form" aria-label="Registrar solicitação de Ressonância">
      <Campo id="c-data" rotulo="Data do contato">
        <input id="c-data" name="data_contato" type="date" className="input" defaultValue={hoje} max={hoje} required />
      </Campo>
      <Campo id="c-canal" rotulo="Por onde entrou" dica="Canal em que o paciente pediu o exame.">
        <Seletor id="c-canal" name="canal" opcoes={CANAIS} vazio="Escolha" obrigatorio />
      </Campo>
      <Campo id="c-tipo" rotulo="Tipo de paciente">
        <Seletor id="c-tipo" name="tipo_paciente" opcoes={TIPOS_PACIENTE} valor="Novo paciente" obrigatorio />
      </Campo>
      <Campo id="c-exame" rotulo="Exame solicitado">
        <Seletor id="c-exame" name="exame" opcoes={EXAMES} vazio="Escolha" obrigatorio />
      </Campo>
      <Campo id="c-forma" rotulo="Particular ou convênio">
        <Seletor id="c-forma" name="forma_pagamento" opcoes={FORMAS_PAGAMENTO} valor={forma} onChange={setForma} obrigatorio />
      </Campo>
      {forma === "Convênio" && (
        <Campo id="c-convenio" rotulo="Qual convênio">
          <input id="c-convenio" name="convenio" className="input" maxLength={60} />
        </Campo>
      )}
      <CamposAcompanhamento key={versao} pre="c" contato />
      <div className="crm-acoes crm-largo">
        <BotaoEnviar texto="Registrar contato" ocupado="Registrando" />
        <Retorno state={state} okTexto="Contato registrado." />
      </div>
    </form>
  );
}

export function EditarContatoForm({ contato }: { contato: Contato }) {
  const [state, action] = useActionState(atualizarContato, inicial);
  return (
    <form action={action} className="crm-form crm-form-editar" aria-label={`Atualizar contato ${contato.id}`}>
      <input type="hidden" name="id" value={contato.id} />
      <input type="hidden" name="data_contato" value={contato.data_contato} />
      <CamposAcompanhamento pre={`e${contato.id}`} p={contato} contato />
      <div className="crm-acoes crm-largo">
        <BotaoEnviar texto="Salvar" ocupado="Salvando" />
        <Retorno state={state} okTexto="Salvo." />
      </div>
    </form>
  );
}
