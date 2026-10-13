/** Público: só diz que o portal está de pé. Nada mais sem sessão. */
export const dynamic = "force-dynamic";
export function GET() {
  return Response.json({ portal: true });
}
