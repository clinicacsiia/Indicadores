"use client";

import { useActionState, useEffect, useMemo, useRef, useState } from "react";
import { type ExameCatalogo, type Horario, type Preco } from "@/lib/crm-rm";
import { atualizarHorario, registrarHorario, type CrmState } from "./actions";
import { BotaoEnviar, Campo, CamposResultado, FichaDoExame, Retorno, Seletor, SeletorExame } from "./campos";

const inicial: CrmState = {};

export type OpcaoContato = { id: number; rotulo: string; exame: string; forma: string; valor: number | null };

export function NovoHorarioForm({
  hoje,
  contatos,
  exames,
  precos,
  verValores,
}: {
  hoje: string;
  contatos: OpcaoContato[];
  exames: ExameCatalogo[];
  precos: Preco[];
  verValores: boolean;
}) {
  const [state, action] = useActionState(registrarHorario, inicial);
  const [contato, setContato] = useState("");
  const [exame, setExame] = useState("");
  const [forma, setForma] = useState("Particular");
  const [previsto, setPrevisto] = useState("");
  const ref = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.ok) {
      ref.current?.reset();
      setContato("");
      setExame("");
      setForma("Particular");
      setPrevisto("");
    }
  }, [state]);

  // Escolher o contato já preenche exame, forma de pagamento e valor previsto.
  const escolher = (id: string) => {
    setContato(id);
    const c = contatos.find((x) => String(x.id) === id);
    if (c) {
      setExame(c.exame);
      setForma(c.forma);
      if (c.valor !== null) setPrevisto(c.valor.toFixed(2).replace(".", ","));
    }
  };

  const ficha = useMemo(() => exames.find((e) => e.nome === exame), [exames, exame]);
  const preco = useMemo(() => precos.find((p) => p.exame === exame), [precos, exame]);

  return (
    <form ref={ref} action={action} className="crm-form" aria-label="Registrar horário reservado na Ressonância">
      <Campo id="h-contato" rotulo="Contato do CRM" dica="Só aparecem contatos com situação Agendado. Sem contato = encaixe pedido direto pelo médico.">
        <select id="h-contato" name="contato_id" className="select" value={contato} onChange={(e) => escolher(e.target.value)}>
          <option value="">Sem contato (encaixe)</option>
          {contatos.map((c) => (
            <option key={c.id} value={c.id}>
              {c.rotulo}
            </option>
          ))}
        </select>
      </Campo>
      <Campo id="h-data" rotulo="Data do exame">
        <input id="h-data" name="data_exame" type="date" className="input" defaultValue={hoje} required />
      </Campo>
      <Campo id="h-hora" rotulo="Horário">
        <input id="h-hora" name="horario" type="time" className="input" step={900} />
      </Campo>
      <Campo id="h-exame" rotulo="Exame">
        <SeletorExame id="h-exame" exames={exames} valor={exame} onChange={setExame} />
      </Campo>
      <Campo id="h-forma" rotulo="Forma de pagamento">
        <Seletor id="h-forma" name="forma_pagamento" opcoes={["Particular", "Convênio", "SUS", "Cetrus"]} valor={forma} onChange={setForma} obrigatorio />
      </Campo>
      <Campo id="h-previsto" rotulo="Valor previsto (R$)" dica="Quanto o exame deve render se for feito.">
        <input id="h-previsto" name="valor_previsto" className="input" inputMode="decimal" placeholder="0,00" value={previsto} onChange={(e) => setPrevisto(e.target.value)} />
      </Campo>
      <Campo id="h-cod" rotulo="Código da marcação no Klingo" dica="Opcional agora, essencial quando a agenda for integrada.">
        <input id="h-cod" name="codigo_marcacao" className="input" inputMode="numeric" maxLength={12} placeholder="ex.: 20621" />
      </Campo>
      <FichaDoExame exame={ficha} preco={preco} />
      <input type="hidden" name="status" value="Agendado" />
      <input type="hidden" name="confirmacao" value="Não contatado" />
      <div className="crm-acoes crm-largo">
        <BotaoEnviar texto="Registrar horário" ocupado="Registrando" />
        <Retorno state={state} okTexto="Horário registrado. Depois do exame, feche o resultado na aba Meu dia." />
        {!verValores && <span className="crm-dica">Os valores em R$ não aparecem nas listas para o seu perfil.</span>}
      </div>
    </form>
  );
}

export function EditarHorarioForm({ horario }: { horario: Horario }) {
  const [state, action] = useActionState(atualizarHorario, inicial);
  return (
    <form action={action} className="crm-form crm-form-editar" aria-label={`Atualizar horário ${horario.id}`}>
      <input type="hidden" name="id" value={horario.id} />
      <CamposResultado pre={`h${horario.id}`} h={horario} />
      <div className="crm-acoes crm-largo">
        <BotaoEnviar texto="Salvar" ocupado="Salvando" />
        <Retorno state={state} okTexto="Salvo." />
      </div>
    </form>
  );
}
