import { describe, expect, it } from "vitest";
import { linhasDeMetas } from "@/klingo/metas";
import { RespostaInvalida } from "@/klingo/erros";

const base = { id: 13339, limit: false, colunas: [], linhas: [{
  "Exames Realizados": "123", Unidade: "CSI", "Procedimento - Classes": '["RM","CONTRASTADO"]', Especialidade: "RADIO",
  "Data do Atendimento": "2026-10-07 08:13:26", Procedimento: "RM CRANIO", Operadora: "SUS" }] };

describe("linhasDeMetas (porte de para_linhas)", () => {
  it("converte classes JSON em texto, calcula o mês e traz o convênio da Operadora", () => {
    const t = linhasDeMetas(base);
    expect(t.linhas[0]).toEqual([123, "CSI", "RM, CONTRASTADO", "RADIO", "2026-10-07 08:13:26", "RM CRANIO", "2026-10", "SUS"]);
  });
  it("recusa a resposta inteira se alguma linha não tem ID inteiro ou data válida", () => {
    const ruim = { ...base, linhas: [...base.linhas, { ...base.linhas[0], "Exames Realizados": "abc" }] };
    expect(() => linhasDeMetas(ruim)).toThrow(RespostaInvalida);
  });
});
