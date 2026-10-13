import { type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

export async function proxy(request: NextRequest) {
  return updateSession(request);
}

// /api/* são as funções Python dos painéis (api/*.py): cada uma confere o login e a permissão sozinha e devolve
// 401/403 em vez de redirecionar; o cron diário (/api/preaquecer) não tem cookie de sessão.
export const config = {
  matcher: [
    "/((?!api/|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
