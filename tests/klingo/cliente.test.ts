import { describe, expect, it, vi } from "vitest";
import { baixarIntervalo, baixarTexto, lerToken, montarUrl } from "@/klingo/cliente";
import { FalhaDeRede, LimiteAtingido, RelatorioComErro, TokenInvalido } from "@/klingo/erros";

const TOKEN = "abcdef1234567890";
const sem = async () => {};
const ok = (corpo: unknown) => new Response(JSON.stringify(corpo), { status: 200, headers: { "X-RateLimit-Remaining": "900" } });

describe("cliente da API do Klingo", () => {
  it("monta a URL com os filtros e o ':' escapado (%3A)", () => {
    expect(montarUrl(26, { periodo: "l", "periodo-from": "2026-10-01" })).toBe("https://api-externa.klingo.app/api/info/relatorio?id=26&%3Aperiodo=l&%3Aperiodo-from=2026-10-01");
  });
  it("lê o token só do ambiente e recusa formato inválido", () => {
    expect(lerToken({ KLINGO_APP_TOKEN: TOKEN })).toBe(TOKEN);
    expect(() => lerToken({})).toThrow(TokenInvalido);
    expect(() => lerToken({ KLINGO_APP_TOKEN: "tem espaço no meio" })).toThrow(/formato inválido/);
  });
  it("401 = token inválido, sem repetir", async () => {
    const f = vi.fn(async () => new Response("Unauthorized", { status: 401 }));
    await expect(baixarTexto("u", { token: TOKEN, fetchImpl: f as never, esperar: sem })).rejects.toBeInstanceOf(TokenInvalido);
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("429 espera o Retry-After e repete; depois dá certo", async () => {
    const esperas: number[] = [];
    const f = vi.fn().mockResolvedValueOnce(new Response("", { status: 429, headers: { "Retry-After": "7" } })).mockResolvedValueOnce(ok({ a: 1 }));
    const t = await baixarTexto("u", { token: TOKEN, fetchImpl: f as never, esperar: async (ms) => { esperas.push(ms); } });
    expect(JSON.parse(t)).toEqual({ a: 1 });
    expect(esperas).toEqual([7000]);
  });
  it("5xx e rede caída: 3 tentativas e FalhaDeRede", async () => {
    const f = vi.fn(async () => { throw new Error("ECONNRESET"); });
    await expect(baixarTexto("u", { token: TOKEN, fetchImpl: f as never, esperar: sem })).rejects.toBeInstanceOf(FalhaDeRede);
    expect(f).toHaveBeenCalledTimes(3);
    const g = vi.fn(async () => new Response("", { status: 503 }));
    await expect(baixarTexto("u", { token: TOKEN, fetchImpl: g as never, esperar: sem })).rejects.toBeInstanceOf(FalhaDeRede);
  });
  it("outro 4xx é erro do relatório (não derruba o resto)", async () => {
    const f = vi.fn(async () => new Response("bad", { status: 422 }));
    await expect(baixarTexto("u", { token: TOKEN, fetchImpl: f as never, esperar: sem })).rejects.toBeInstanceOf(RelatorioComErro);
  });
  it("envia o token no cabeçalho X-APP-TOKEN", async () => {
    const f = vi.fn(async () => ok({}));
    await baixarTexto("u", { token: TOKEN, fetchImpl: f as never, esperar: sem });
    const init = (f.mock.calls[0] as unknown as [string, { headers: Record<string, string> }])[1];
    expect(init.headers["X-APP-TOKEN"]).toBe(TOKEN);
  });
});

describe("baixarIntervalo: limit:true divide o período ao meio", () => {
  const corpo = (de: string, ate: string, limit: boolean, n: number) => ({
    id: 5, error: null, limit,
    inputs: [{ id: "periodo0", type: "per-date", value: "l" }],
    result: { columns: [{ name: "col0", title: "Dia" }], rows: n, data: Array.from({ length: n }, () => ({ col0: `${de}..${ate}` })) },
  });
  it("junta as duas metades", async () => {
    const chamadas: string[] = [];
    const f = vi.fn(async (url: string) => {
      const u = new URL(url), de = u.searchParams.get(":periodo0-from")!, ate = u.searchParams.get(":periodo0-to")!;
      chamadas.push(`${de}|${ate}`);
      return ok(corpo(de, ate, de === "2026-10-01" && ate === "2026-10-31", 2));
    });
    const r = await baixarIntervalo(5, "periodo0", "2026-10-01", "2026-10-31", { token: TOKEN, fetchImpl: f as never, esperar: sem });
    expect(chamadas).toEqual(["2026-10-01|2026-10-31", "2026-10-01|2026-10-16", "2026-10-17|2026-10-31"]);
    expect(r.linhas).toHaveLength(4);
    expect(r.limit).toBe(false);
  });
  it("se não dá para dividir mais (um dia só), é erro: nunca trunca calado", async () => {
    const f = vi.fn(async (url: string) => { const u = new URL(url); return ok(corpo(u.searchParams.get(":periodo0-from")!, u.searchParams.get(":periodo0-to")!, true, 1)); });
    await expect(baixarIntervalo(5, "periodo0", "2026-10-01", "2026-10-01", { token: TOKEN, fetchImpl: f as never, esperar: sem })).rejects.toBeInstanceOf(LimiteAtingido);
  });
});
