import { processarEEncadear } from "@/lib/atualizacao";
import { segredoConfere } from "@/lib/seguranca";

export const maxDuration = 60;
export const dynamic = "force-dynamic";

/** Retoma a fila (pg_cron a cada minuto e o próprio auto-encadeamento chamam). Só com o segredo (CRON_SECRET). */
async function tratar(req: Request) {
  if (!segredoConfere(req.headers.get("authorization"))) return Response.json({ erro: "não autorizado" }, { status: 401 });
  try {
    const r = await processarEEncadear(new URL(req.url).origin);
    return Response.json(r);
  } catch (e) {
    console.error("processar fila:", (e as Error).message);
    return Response.json({ erro: "falha ao processar a fila" }, { status: 500 });
  }
}
export const POST = tratar;
export const GET = tratar;
