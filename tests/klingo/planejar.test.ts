import { describe, expect, it } from "vitest";
import { planejarMenu } from "@/klingo/planejar";
import { DEFINICOES, MENUS } from "@/klingo/config";

const hoje = { ym: "2026-10", dia: 13 };
const por = (itens: ReturnType<typeof planejarMenu>, aba: string) => itens.filter((i) => i.relatorio.aba === aba).map((i) => i.mes);

describe("planejarMenu (regras do relatorios.json do legado)", () => {
  it("todas as definições carregam e cada relatório tem id e aba", () => {
    for (const m of MENUS) for (const r of DEFINICOES[m].relatorios) { expect(r.id).toBeGreaterThan(0); expect(r.aba).toBeTruthy(); }
  });
  it("revisar_meses: 2 rebaixa os 2 meses mais recentes (e baixa os que faltam)", () => {
    const itens = planejarMenu("faturamento", new Set(), hoje);
    expect(por(itens, "Receita Produzida")).toEqual(["2026-09", "2026-10"]);
    const so = planejarMenu("faturamento", new Set(["Receita Produzida|2026-09", "Receita Produzida|2026-10"]), { ym: "2026-12", dia: 2 });
    expect(por(so, "Receita Produzida")).toEqual(["2026-11", "2026-12"]);
  });
  it("sem revisar_meses: rebaixa TODOS os meses desde o primeiro (o status muda com o tempo); Faturas Emitidas vai desde 2026-06", () => {
    const itens = planejarMenu("faturamento", new Set(), hoje);
    expect(por(itens, "Faturas Emitidas")).toEqual(["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]);
    expect(por(itens, "Controle por Convênio")).toEqual(["2026-09", "2026-10"]);
  });
  it("meses_a_frente: 3 no #13328 baixa 3 meses futuros", () => {
    expect(por(planejarMenu("faturamento", new Set(), hoje), "Faturas em Aberto")).toEqual(["2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]);
  });
  it("sem_periodo baixa inteiro, uma vez, sem mês", () => {
    const itens = planejarMenu("indicadores", new Set(), hoje);
    expect(itens.filter((i) => i.relatorio.sem_periodo).map((i) => [i.relatorio.aba, i.mes])).toEqual([["Guias", null], ["Baixas", null]]);
    expect(por(itens, "Glosas e Recursos")).toEqual(["2026-09", "2026-10"]);
  });
  it("Suprimentos: sem chave nem revisar, desde fev/2026", () => {
    expect(por(planejarMenu("suprimentos", new Set(), hoje), "Movimentações")[0]).toBe("2026-02");
  });
  it("Metas: mês corrente; nos primeiros 5 dias, também o anterior", () => {
    expect(por(planejarMenu("metas", new Set(["Dados|2026-09", "Dados|2026-10"]), hoje), "Dados")).toEqual(["2026-10"]);
    expect(por(planejarMenu("metas", new Set(["Dados|2026-09", "Dados|2026-10"]), { ym: "2026-10", dia: 3 }), "Dados")).toEqual(["2026-09", "2026-10"]);
  });
  it("revisar_meses: 1 (#13404) rebaixa só o mês corrente; os que faltam também", () => {
    expect(por(planejarMenu("atendimento", new Set(["Fluxo na Recepção|2026-09"]), hoje), "Fluxo na Recepção")).toEqual(["2026-10"]);
  });
});
