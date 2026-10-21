import { PERMISSAO_ATENDIMENTO_VISAO, RESPONSAVEIS_ATENDIMENTO } from "@/lib/paineis";

// "Atendimento: o que a pessoa vê". Só tem efeito se a tela Atendimento estiver liberada; administradores sempre veem tudo.
export function VisaoAtendimento({ id, valor }: { id: string; valor: string }) {
  // um id que não está mais no responsaveis.json continua aparecendo (e continua restringindo): o administrador vê o que está salvo e troca
  const conhecido = valor === "" || RESPONSAVEIS_ATENDIMENTO.some((r) => r.id === valor);
  return (
    <div className="field">
      <label className="field-label" htmlFor={`visao-${id}`}>
        Atendimento: o que a pessoa vê
      </label>
      <select id={`visao-${id}`} name={PERMISSAO_ATENDIMENTO_VISAO} className="select" defaultValue={valor}>
        <option value="">Tudo (a clínica inteira)</option>
        {RESPONSAVEIS_ATENDIMENTO.map((r) => (
          <option key={r.id} value={r.id}>
            Só {r.nome} — {r.area}
          </option>
        ))}
        {!conhecido && <option value={valor}>{valor} (não existe mais — troque)</option>}
      </select>
      <span className="switch-hint">
        Com “Só …”, o Atendimento dessa pessoa traz apenas os setores escolhidos (os outros números nem chegam ao navegador) e os avisos do Atendimento ficam escondidos.
      </span>
    </div>
  );
}
