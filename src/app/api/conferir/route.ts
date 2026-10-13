import { ambiente } from "@/lib/ambiente";
import { obterSessao } from "@/lib/sessao";

export const maxDuration = 120;
export const dynamic = "force-dynamic";

/** "Conferir números" (só administrador): cruza os relatórios entre si e devolve cada checagem com esperado × obtido. */
export async function GET(req: Request) {
  const sessao = await obterSessao();
  if (!sessao?.admin) return Response.json({ erro: "Somente administradores." }, { status: 403 });
  const url = new URL("/api/py/conferir", new URL(req.url).origin);
  const cab: Record<string, string> = { "x-interno": ambiente.cronSecret };
  if (process.env.VERCEL_AUTOMATION_BYPASS_SECRET) cab["x-vercel-protection-bypass"] = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
  const r = await fetch(url, { headers: cab, cache: "no-store" }).catch(() => null);
  if (!r?.ok) return Response.json({ erro: "Não foi possível conferir agora." }, { status: 502 });
  return Response.json(await r.json());
}
