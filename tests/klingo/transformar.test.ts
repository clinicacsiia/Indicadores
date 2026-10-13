import { describe, expect, it } from "vitest";
import { mesclarPorChave, paraData, paraNumero, tipar } from "@/klingo/transformar";

describe("paraNumero", () => {
  it.each([["1", 1], ["1234.5", 1234.5], ["1.234,56", 1234.56], ["R$ 10,50", 10.5], ["-3", -3], [" 7 ", 7]])("%s -> %s", (e, s) => expect(paraNumero(e as string)).toBe(s));
  it.each([[""], ["abc"], [null], ["1,2,3"]])("%s -> null", (e) => expect(paraNumero(e as string | null)).toBeNull());
});

describe("paraData", () => {
  it("aceita ISO com hora, ISO só data e dd/mm/aaaa (com ou sem hora)", () => {
    expect(paraData("2026-10-07 08:13:26")).toBe("2026-10-07 08:13:26");
    expect(paraData("2026-10-07T08:13:26")).toBe("2026-10-07 08:13:26");
    expect(paraData("2026-10-07")).toBe("2026-10-07");
    expect(paraData("07/10/2026")).toBe("2026-10-07");
    expect(paraData("07/10/2026 08:13")).toBe("2026-10-07 08:13:00");
  });
  it("recusa data impossível e texto qualquer", () => {
    expect(paraData("31/02/2026")).toBeNull();
    expect(paraData("0206-13-40")).toBeNull();
    expect(paraData("ontem")).toBeNull();
    expect(paraData(null)).toBeNull();
  });
});

describe("tipar", () => {
  const resp = { id: 1, limit: false, colunas: ["Id", "Valor", "Data", "Faixa Etária", "Obs"], linhas: [
    { Id: "1", Valor: "1.234,50", Data: "07/10/2026", "Faixa Etária": "'30-39", Obs: "" },
    { Id: "2", Valor: "x", Data: "lixo", "Faixa Etária": "40-49", Obs: "ok" }] };
  it("converte numeros/datas, tira o apóstrofo e esvazia texto em branco", () => {
    const t = tipar(resp, { aba: "A", numeros: ["Id", "Valor"], datas: { Data: "dd/mm/yyyy" }, limpar_apostrofo: ["Faixa Etária"] });
    expect(t.linhas[0]).toEqual([1, 1234.5, "2026-10-07", "30-39", null]);
    expect(t.linhas[1]).toEqual([2, null, null, "40-49", "ok"]);
    expect(t.avisos).toHaveLength(2);
  });
  it("recusa quando a chave não existe nas colunas", () => {
    expect(() => tipar(resp, { aba: "A", chave: ["Fatura - Id"] })).toThrow(/chave/);
  });
});

describe("mesclarPorChave (upsert)", () => {
  const ant = { colunas: ["Id", "Status"], linhas: [[1, "A Enviar"], [2, "Enviada"]], avisos: [] };
  it("a linha nova prevalece e as antigas continuam", () => {
    const { tabela } = mesclarPorChave(ant, { colunas: ["Id", "Status"], linhas: [[1, "Enviada"], [3, "A Enviar"]], avisos: [] }, ["Id"]);
    expect(tabela.linhas.sort((a, b) => Number(a[0]) - Number(b[0]))).toEqual([[1, "Enviada"], [2, "Enviada"], [3, "A Enviar"]]);
  });
  it("descarta (e conta) linha sem a chave completa", () => {
    const { descartadas, tabela } = mesclarPorChave(null, { colunas: ["Id", "Status"], linhas: [[null, "x"], [5, "y"]], avisos: [] }, ["Id"]);
    expect(descartadas).toBe(1);
    expect(tabela.linhas).toEqual([[5, "y"]]);
  });
});
