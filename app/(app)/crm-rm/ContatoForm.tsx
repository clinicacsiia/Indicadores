"use client";

import { useActionState, useEffect, useMemo, useRef, useState } from "react";
import {
  CANAIS,
  ORIGENS_REGISTRO,
  TIPOS_PACIENTE,
  type ConvenioCatalogo,
  type Contato,
  type ExameCatalogo,
  type Preco,
} from "@/lib/crm-rm";
import { atualizarContato, registrarContato, type CrmState } from "./actions";
import { BotaoEnviar, Campo, CamposAcompanhamento, FichaDoExame, Retorno, Seletor, SeletorExame } from "./campos";

const inicial: CrmState = {};

type Catalogo = { exames: ExameCatalogo[]; convenios: ConvenioCatalogo[]; precos: Preco[] };

export function NovoContatoForm({ hoje, catalogo, responsavelPadrao = "" }: { hoje: string; catalogo: Catalogo; responsavelPadrao?: string }) {
  const [state, action] = useActionState(registrarContato, inicial);
  const [exame, setExame] = useState("");
  const [convenio, setConvenio] = useState("Particular");
  const [versao, setVersao] = useState(0);
  const ref = useRef<HTMLFormElement>(null);

  // Registrou: limpa para o próximo contato (a chave nova refaz os campos da situação).
  useEffect(() => {
    if (state.ok) {
      ref.current?.reset();
      setExame("");
      setConvenio("Particular");
      setVersao((v) => v + 1);
    }
  }, [state]);

  const fichaExame = useMemo(() => catalogo.exames.find((e) => e.nome === exame), [catalogo.exames, exame]);
  const preco = useMemo(() => catalogo.precos.find((p) => p.exame === exame), [catalogo.precos, exame]);
  const fichaConvenio = useMemo(() => catalogo.convenios.find((c) => c.nome === convenio), [catalogo.convenios, convenio]);
  const tipos = ["Particular", "Convênio", "SUS", "Cetrus"];

  return (
    <form ref={ref} action={action} className="crm-form" aria-label="Registrar solicitação de Ressonância">
      <Campo id="c-data" rotulo="Data do contato">
        <input id="c-data" name="data_contato" type="date" className="input" defaultValue={hoje} max={hoje} required />
      </Campo>
      <Campo id="c-canal" rotulo="Por onde o paciente chegou" dica="Canal em que ele pediu o exame.">
        <Seletor id="c-canal" name="canal" opcoes={CANAIS} vazio="Escolha" obrigatorio />
      </Campo>
      <Campo id="c-tipo" rotulo="Tipo de paciente">
        <Seletor id="c-tipo" name="tipo_paciente" opcoes={TIPOS_PACIENTE} valor="Novo paciente" obrigatorio />
      </Campo>
      <Campo id="c-exame" rotulo="Exame solicitado" dica="Os nomes são os mesmos do Klingo.">
        <SeletorExame id="c-exame" exames={catalogo.exames} valor={exame} onChange={setExame} />
      </Campo>
      <Campo
        id="c-convenio"
        rotulo="Convênio ou particular"
        dica={
          fichaConvenio?.exige_autorizacao
            ? `Exige autorização${fichaConvenio.prazo_autorizacao ? ` (prazo de ${fichaConvenio.prazo_autorizacao} dias)` : ""}.`
            : "Define sozinho a forma de pagamento."
        }
      >
        <select id="c-convenio" name="convenio" className="select" required value={convenio} onChange={(e) => setConvenio(e.target.value)}>
          <option value="">Escolha</option>
          {tipos.map((t) => {
            const doTipo = catalogo.convenios.filter((c) => c.tipo === t);
            if (!doTipo.length) return null;
            return (
              <optgroup key={t} label={t}>
                {doTipo.map((c) => (
                  <option key={c.id} value={c.nome}>
                    {c.nome}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </select>
      </Campo>
      <Campo id="c-origem" rotulo="Quem registrou" dica="Mesmo campo “Origem” do Klingo.">
        <Seletor id="c-origem" name="origem_registro" opcoes={ORIGENS_REGISTRO} vazio="Não informar" />
      </Campo>
      <FichaDoExame exame={fichaExame} preco={preco} />
      <CamposAcompanhamento key={versao} pre="c" responsavelPadrao={responsavelPadrao} />
      <label className="switch crm-largo">
        <input type="checkbox" name="respondeu" defaultChecked />
        <span className="switch-track" aria-hidden="true" />
        <span className="switch-text">Já respondi a este paciente agora (marca o tempo de primeira resposta)</span>
      </label>
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
      <CamposAcompanhamento pre={`e${contato.id}`} p={contato} />
      <div className="crm-acoes crm-largo">
        <BotaoEnviar texto="Salvar" ocupado="Salvando" />
        <Retorno state={state} okTexto="Salvo." />
      </div>
    </form>
  );
}
