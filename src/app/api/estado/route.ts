import { ehMenu } from "@/klingo/config";
import { travaAtiva, versaoDosDados } from "@/lib/atualizacao";
import { obterSessao, podeVerMenu } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";

export const dynamic = "force-dynamic";

/** Estado dos dados de um menu: versão (muda quando chegam dados novos), se alguém está atualizando e se o token do Klingo foi recusado. */
export async function GET(req: Request) {
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const menu = new URL(req.url).searchParams.get("menu");
  if (!ehMenu(menu) || !podeVerMenu(sessao, menu)) return Response.json({ erro: "Sem acesso." }, { status: 403 });
  const [{ versao, atualizadoEm }, trava, { data: ultimo }] = await Promise.all([
    versaoDosDados(menu), travaAtiva(),
    admin().from("historico_atualizacoes").select("status, data_hora").eq("modulo_id", menu).neq("status", "ja_em_dia").order("id", { ascending: false }).limit(1).maybeSingle(),
  ]);
  return Response.json({
    versao, atualizado_em: atualizadoEm,
    atualizando: trava ? { modulo: trava.modulo, usuario: trava.usuario } : null,
    token_invalido: ultimo?.status === "token_invalido",
  });
}
