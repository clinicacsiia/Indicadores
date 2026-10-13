import { menusDoUsuario, obterSessao } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";
import { hojeSalvador } from "@/klingo/datas";

export const dynamic = "force-dynamic";

/** GET /periodos: meses com dados nos painéis que o usuário pode ver (para o seletor "Período do relatório" do Exportar). */
export async function GET() {
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const ids = (await menusDoUsuario(sessao)).map((m) => m.id);
  if (!ids.length) return Response.json({ meses: [], hoje: hojeSalvador().ym });
  const { data } = await admin().from("dados_blocos").select("mes").in("menu", ids).limit(5000);
  const meses = [...new Set((data ?? []).map((r) => r.mes as string))].filter((m) => m >= "2026-02").sort();
  return Response.json({ meses, hoje: hojeSalvador().ym });
}
