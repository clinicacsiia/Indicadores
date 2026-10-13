import { MENUS, type MenuId } from "@/klingo/config";
import { enfileirarAtualizacao } from "@/klingo/motor";
import { processarEEncadear, travaAtiva } from "@/lib/atualizacao";
import { lerConfiguracoes } from "@/lib/configuracoes";
import { segredoConfere } from "@/lib/seguranca";
import { admin } from "@/lib/supabase/admin";

export const maxDuration = 60;
export const dynamic = "force-dynamic";

/**
 * Verificação automática (pg_cron a cada 30 min): para cada menu, se os dados têm menos que intervalo_minimo_minutos, não consulta o Klingo.
 * Os que estão velhos entram na fila como "automático". Respeita a trava única (uma atualização por vez).
 */
async function tratar(req: Request) {
  if (!segredoConfere(req.headers.get("authorization"))) return Response.json({ erro: "não autorizado" }, { status: 401 });
  const db = admin();
  const origem = new URL(req.url).origin;
  try {
    const cfg = await lerConfiguracoes();
    if (cfg.verificacao_automatica_minutos === 0) return Response.json({ pulou: "desligada" });
    if (await travaAtiva()) return Response.json({ pulou: "ocupado" });
    const { data } = await db.from("dados_versao").select("menu, atualizado_em");
    const idade = new Map((data ?? []).map((r) => [r.menu as string, (Date.now() - Date.parse(r.atualizado_em)) / 60000]));
    const velhos = MENUS.filter((m) => (idade.get(m) ?? Infinity) >= cfg.intervalo_minimo_minutos) as MenuId[];
    if (!velhos.length) return Response.json({ pulou: "em dia" });
    const { data: trava } = await db.rpc("adquirir_trava", { p_modulo: velhos[0], p_usuario: "automático", p_minutos: 30 });
    if (!trava?.ok) return Response.json({ pulou: "ocupado" });
    try { await enfileirarAtualizacao({ sb: db }, velhos, "automático"); } catch (e) { await db.rpc("liberar_trava"); throw e; }
    const r = await processarEEncadear(origem);
    return Response.json({ menus: velhos, ...r });
  } catch (e) {
    console.error("verificar:", (e as Error).message);
    return Response.json({ erro: "falha na verificação" }, { status: 500 });
  }
}
export const POST = tratar;
export const GET = tratar;
