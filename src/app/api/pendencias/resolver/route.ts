import { ehMenu } from "@/klingo/config";
import { versaoDosDados } from "@/lib/atualizacao";
import { auditar } from "@/lib/auditoria";
import { lerJson, validarPost } from "@/lib/seguranca";
import { obterSessao, podeVerMenu } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

/** Marca um alerta como resolvido. Guarda a versão dos dados no momento (para saber se o alerta "ainda aparece" depois da próxima atualização). */
export async function POST(req: Request) {
  const recusa = validarPost(req);
  if (recusa) return recusa;
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const c = await lerJson<{ painel?: string; chave?: string; titulo?: string }>(req);
  if (!c || !ehMenu(c.painel) || !podeVerMenu(sessao, c.painel)) return Response.json({ erro: "Sem acesso." }, { status: 403 });
  if (!c.chave || c.chave.length > 200 || !c.chave.includes("|")) return Response.json({ erro: "Alerta inválido." }, { status: 400 });
  const { versao } = await versaoDosDados(c.painel);
  const { error } = await admin().from("pendencias_resolvidas").upsert({
    painel: c.painel, chave: c.chave, titulo: String(c.titulo ?? "").slice(0, 200), usuario: sessao.usuario, quando: new Date().toISOString(), versao: versao ?? 0,
  });
  if (error) return Response.json({ erro: "Não foi possível marcar agora." }, { status: 500 });
  await auditar("pendencia_resolvida", sessao.usuario, { painel: c.painel, chave: c.chave });
  return Response.json({ ok: true });
}
