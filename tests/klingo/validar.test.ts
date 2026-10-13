import { describe, expect, it } from "vitest";
import { validarResposta } from "@/klingo/validar";
import { RelatorioComErro, RespostaInvalida } from "@/klingo/erros";

const resp = (extra: Record<string, unknown> = {}, linhas: Record<string, unknown>[] = [{ col0: 1, col1: "x" }]) => ({
  id: 26, title: "Receita", error: null, limit: false,
  inputs: [{ id: "periodo", type: "per-date", value: "l" }],
  result: { columns: [{ name: "col0", title: "Valor" }, { name: "col1", title: "Nome" }], rows: linhas.length, data: linhas },
  ...extra,
});
const periodo = { chave: "periodo", codigo: "l" };

describe("validarResposta (armadilhas medidas na API do Klingo)", () => {
  it("aceita a resposta boa e traduz colN para os títulos", () => {
    const r = validarResposta(resp(), 26, { periodo });
    expect(r.colunas).toEqual(["Valor", "Nome"]);
    expect(r.linhas).toEqual([{ Valor: "1", Nome: "x" }]);
  });
  it("normaliza número e texto alternando (1 e '1' viram o mesmo texto)", () => {
    const a = validarResposta(resp({}, [{ col0: 1, col1: "x" }]), 26);
    const b = validarResposta(resp({}, [{ col0: "1", col1: "x" }]), 26);
    expect(a.linhas).toEqual(b.linhas);
  });
  it("relatório inexistente: erro vem com HTTP 200 e status_code 400", () => {
    expect(() => validarResposta({ status_code: 400, msg: "Relatório não encontrado: 9" }, 9)).toThrow(RelatorioComErro);
    expect(() => validarResposta({ status_code: 400, msg: "Relatório não encontrado: 9" }, 9)).toThrow(/não encontrado/);
  });
  it('filtro/data inválidos: error "." com result null', () => {
    expect(() => validarResposta({ id: 26, error: ".", result: null }, 26)).toThrow(RelatorioComErro);
  });
  it("período sem registros: result é string vazia, vale como vazio", () => {
    const r = validarResposta(resp({ result: "" }), 26, { periodo });
    expect(r.linhas).toEqual([]);
    expect(r.colunas).toEqual([]);
  });
  it("chave de filtro errada NÃO dá erro no Klingo (ele devolve 'hoje'): recusa se o código aplicado não bate", () => {
    expect(() => validarResposta(resp({ inputs: [{ id: "periodo", type: "per-date", value: "h" }] }), 26, { periodo })).toThrow(/aplicou o período/);
  });
  it("recusa quando o relatório não tem o filtro pedido mas tem outro filtro de data", () => {
    expect(() => validarResposta(resp({ inputs: [{ id: "periodo0", type: "per-date", value: "l" }] }), 26, { periodo })).toThrow(RespostaInvalida);
  });
  it("sem filtro de data e com linhas: recusa; vazio vale como vazio", () => {
    expect(() => validarResposta(resp({ inputs: [] }), 26, { periodo })).toThrow(/não tem o filtro/);
    expect(validarResposta(resp({ inputs: [], result: "" }), 26, { periodo }).linhas).toEqual([]);
  });
  it("recusa id diferente do pedido", () => {
    expect(() => validarResposta(resp({ id: 27 }), 26)).toThrow(/devolveu o 27/);
  });
  it("recusa resposta incompleta (rows anunciadas ≠ linhas)", () => {
    const r = resp(); (r.result as { rows: number }).rows = 5;
    expect(() => validarResposta(r, 26)).toThrow(/incompleta/);
  });
  it("com limit:true não exige que rows bata (quem pede divide o período)", () => {
    const r = resp({ limit: true }); (r.result as { rows: number }).rows = 5;
    expect(validarResposta(r, 26).limit).toBe(true);
  });
  it("recusa títulos repetidos e coluna que não existe", () => {
    const dup = resp(); (dup.result as { columns: { name: string; title: string }[] }).columns[1].title = "Valor";
    expect(() => validarResposta(dup, 26)).toThrow(/mesmo título/);
    expect(() => validarResposta(resp({}, [{ col9: 1 }]), 26)).toThrow(/não é coluna/);
  });
  it("recusa valor que não é escalar e coluna exigida ausente", () => {
    expect(() => validarResposta(resp({}, [{ col0: { a: 1 } }]), 26)).toThrow(/valor do tipo/);
    expect(() => validarResposta(resp(), 26, { exigidas: ["Paciente"] })).toThrow(/mudou o relatório/);
  });
  it("não é JSON de objeto", () => {
    expect(() => validarResposta("texto", 26)).toThrow(RespostaInvalida);
  });
});
