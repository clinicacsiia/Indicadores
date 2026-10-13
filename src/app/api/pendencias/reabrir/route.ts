import { ehMenu } from "@/klingo/config";
import { auditar } from "@/lib/auditoria";
import { lerJson, validarPost } from "@/lib/seguranca";
import { obterSessao, podeVerMenu } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const recusa = validarPost(req);
  if (recusa) return recusa;
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const c = await lerJson<{ painel?: string; chave?: string }>(req);
  if (!c || !ehMenu(c.painel) || !podeVerMenu(sessao, c.painel) || !c.chave) return Response.json({ erro: "Sem acesso." }, { status: 403 });
  const { error } = await admin().from("pendencias_resolvidas").delete().eq("painel", c.painel).eq("chave", c.chave);
  if (error) return Response.json({ erro: "Não foi possível reabrir agora." }, { status: 500 });
  await auditar("pendencia_reaberta", sessao.usuario, { painel: c.painel, chave: c.chave });
  return Response.json({ ok: true });
}
