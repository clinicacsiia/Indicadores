import { ehMenu } from "@/klingo/config";
import { ambiente } from "@/lib/ambiente";
import { obterSessao, podeVerMenu } from "@/lib/sessao";

export const maxDuration = 300;   // o cálculo em Python pode levar alguns segundos na primeira abertura de um período novo
export const dynamic = "force-dynamic";

const CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'";

/** Página de um painel (a mesma que o legado gerava), calculada em Python e guardada em cache por (menu, período, versão dos dados). */
export async function GET(req: Request, { params }: { params: Promise<{ menu: string }> }) {
  const { menu } = await params;
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  if (!ehMenu(menu) || !podeVerMenu(sessao, menu)) return Response.json({ erro: "Sem acesso a este painel." }, { status: 403 });

  const url = new URL(req.url);
  const de = url.searchParams.get("de") ?? "", ate = url.searchParams.get("ate") ?? "";
  const ok = (v: string) => v === "" || /^\d{4}-(0[1-9]|1[0-2])$/.test(v);
  if (!ok(de) || !ok(ate)) return Response.json({ erro: "Período inválido." }, { status: 400 });

  const alvo = new URL("/api/py/painel", url.origin);
  alvo.searchParams.set("menu", menu);
  if (de) alvo.searchParams.set("de", de);
  if (ate) alvo.searchParams.set("ate", ate);
  const cab: Record<string, string> = { "x-interno": ambiente.cronSecret };
  if (process.env.VERCEL_AUTOMATION_BYPASS_SECRET) cab["x-vercel-protection-bypass"] = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;

  let r: Response;
  try { r = await fetch(alvo, { headers: cab, cache: "no-store" }); } catch { return Response.json({ erro: "Não foi possível montar o painel agora." }, { status: 502 }); }
  if (!r.ok) return Response.json({ erro: "Não foi possível montar o painel agora." }, { status: 502 });   // detalhe só no log do servidor
  return new Response(await r.text(), {
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff" },
  });
}
