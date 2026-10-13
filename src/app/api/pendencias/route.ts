import { ehMenu } from "@/klingo/config";
import { obterSessao, podeVerMenu } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

/** GET /api/pendencias?painel=faturamento: alertas marcados como resolvidos naquele painel (não traz nada de outros painéis). */
export async function GET(req: Request) {
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const painel = new URL(req.url).searchParams.get("painel");
  if (!ehMenu(painel) || !podeVerMenu(sessao, painel)) return Response.json({ erro: "Sem acesso." }, { status: 403 });
  const { data } = await admin().from("pendencias_resolvidas").select("chave, titulo, usuario, quando, versao").eq("painel", painel);
  return Response.json({ itens: data ?? [] });
}
