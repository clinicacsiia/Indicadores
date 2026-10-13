import { describe, expect, it } from "vitest";
import { enfileirarAtualizacao, processarFila } from "@/klingo/motor";
import { FalhaDeRede, RespostaInvalida, TokenInvalido } from "@/klingo/erros";
import { decodificarBloco } from "@/klingo/gravar";
import type { RespostaValida } from "@/klingo/tipos";
import { bancoFalso } from "./banco-falso";

const agora = () => new Date("2026-10-13T15:00:00Z");   // 12:00 em Salvador
const sem = async () => {};
const valida = (colunas: string[], linhas: Record<string, string | null>[]): RespostaValida => ({ id: 1, limit: false, colunas, linhas });

describe("motor da fila", () => {
  it("enfileira um item por relatório/mês + aquecimento dos painéis afetados", async () => {
    const b = bancoFalso();
    const r = await enfileirarAtualizacao({ sb: b.sb, agora }, ["indicadores"], "ana");
    expect(r.menus).toEqual(["indicadores", "faturamento", "financeiro"]);   // Indicadores atualiza Faturamento e Financeiro junto
    const baixar = b.t.fila_sincronizacao.filter((i) => i.tipo === "baixar");
    expect(baixar.some((i) => i.menu === "faturamento" && i.aba === "Faturas Emitidas" && i.mes === "2026-06")).toBe(true);
    expect(baixar.find((i) => i.aba === "Guias")?.mes).toBeNull();
    expect(b.t.fila_sincronizacao.filter((i) => i.tipo === "aquecer").map((i) => i.menu).sort()).toEqual(["cesta", "faturamento", "financeiro", "indicadores"]);
  });

  it("baixa, grava o mês inteiro, sobe a versão, registra o histórico e libera a trava", async () => {
    const b = bancoFalso();
    await enfileirarAtualizacao({ sb: b.sb, agora }, ["suprimentos"], "ana");
    const aquecidos: string[] = [];
    const res = await processarFila({
      sb: b.sb, agora, esperar: sem, aquecer: async (m) => { aquecidos.push(m); },
      baixar: async () => valida(["Item", "Movimentação - Quantidade Consolidada"], [{ Item: "LUVA", "Movimentação - Quantidade Consolidada": "10" }]),
    });
    expect(res.restantes).toBe(0);
    expect(res.lotesConcluidos).toBe(1);
    expect(b.t.fila_sincronizacao.every((i) => i.estado === "ok")).toBe(true);
    const bloco = b.t.dados_blocos.find((l) => l.aba === "Movimentações" && l.mes === "2026-10")!;
    expect(decodificarBloco(bloco.conteudo)).toEqual([["LUVA", 10]]);   // número convertido pela lista "numeros" do relatorios.json
    expect(b.t.dados_versao).toEqual([{ menu: "suprimentos", versao: 1 }]);
    expect(b.t.historico_atualizacoes[0]).toMatchObject({ modulo_id: "suprimentos", status: "ok", usuario: "ana" });
    expect(aquecidos).toEqual(["suprimentos"]);
    expect(b.travaLiberada()).toBe(true);
  });

  it("resposta fora do formato derruba só aquele relatório/mês: vira aviso e o resto segue", async () => {
    const b = bancoFalso();
    await enfileirarAtualizacao({ sb: b.sb, agora }, ["suprimentos"], "ana");
    await processarFila({ sb: b.sb, agora, esperar: sem, baixar: async (i) => { if (i.aba === "Solicitações") throw new RespostaInvalida("formato estranho"); return valida(["Item"], [{ Item: "X" }]); } });
    expect(b.t.fila_sincronizacao.filter((i) => i.estado === "erro").every((i) => i.aba === "Solicitações")).toBe(true);
    expect(b.t.historico_atualizacoes[0].status).toBe("aviso");
    expect(b.t.dados_blocos.some((l) => l.aba === "Movimentações")).toBe(true);
    expect(b.t.dados_versao).toHaveLength(1);
  });

  it("token recusado aborta tudo: nada é gravado e o histórico diz token_invalido", async () => {
    const b = bancoFalso();
    await enfileirarAtualizacao({ sb: b.sb, agora }, ["faturamento"], "ana");
    await processarFila({ sb: b.sb, agora, esperar: sem, baixar: async () => { throw new TokenInvalido("recusado"); } });
    expect(b.t.dados_blocos).toHaveLength(0);
    expect(b.t.fila_sincronizacao.filter((i) => i.estado === "pendente")).toHaveLength(0);
    expect(b.t.historico_atualizacoes.every((h) => h.status === "token_invalido")).toBe(true);
    expect(b.t.dados_versao).toHaveLength(0);
    expect(b.travaLiberada()).toBe(true);
  });

  it("queda de rede também aborta (erro no histórico, versão intacta)", async () => {
    const b = bancoFalso();
    await enfileirarAtualizacao({ sb: b.sb, agora }, ["metas"], "automático");
    await processarFila({ sb: b.sb, agora, esperar: sem, baixar: async () => { throw new FalhaDeRede("sem rede"); } });
    expect(b.t.historico_atualizacoes[0]).toMatchObject({ modulo_id: "metas", status: "erro", usuario: "automático" });
    expect(b.t.dados_versao).toHaveLength(0);
  });

  it("relatório sem filtro de data substitui a aba inteira (apaga os outros meses)", async () => {
    const b = bancoFalso();
    b.t.dados_blocos.push({ menu: "indicadores", aba: "Baixas", mes: "2026-09", colunas: [], linhas: 0, conteudo: "" });
    await enfileirarAtualizacao({ sb: b.sb, agora }, ["indicadores"], "ana");
    await processarFila({ sb: b.sb, agora, esperar: sem, baixar: async () => valida(["Baixa - Id"], [{ "Baixa - Id": "1" }]) });
    const baixas = b.t.dados_blocos.filter((l) => l.aba === "Baixas");
    expect(baixas.map((l) => l.mes)).toEqual(["2026-10"]);   // "Mês (filtro)" = mês em que foi baixado
  });

  it("só um processador por vez (lease): o segundo sai sem fazer nada", async () => {
    const b = bancoFalso();
    await enfileirarAtualizacao({ sb: b.sb, agora }, ["suprimentos"], "ana");
    let segundo: unknown;
    await processarFila({ sb: b.sb, agora, esperar: sem, baixar: async () => { segundo ??= await processarFila({ sb: b.sb, agora, esperar: sem }); return valida(["Item"], []); } });
    expect((segundo as { restantes: number }).restantes).toBe(-1);
  });
});
