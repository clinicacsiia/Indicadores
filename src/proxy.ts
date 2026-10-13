import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { COOKIE_SESSAO, lerSessaoAssinada } from "@/lib/seguranca";

/** Exige sessão em tudo, menos /login, /estado, /sair, as rotas /api/cron (têm segredo próprio) e /api/py (a função Python confere o segredo). */
const PUBLICAS = [/^\/login(\/|$)/, /^\/estado$/, /^\/sair$/, /^\/api\/cron\//, /^\/api\/py\//, /^\/_next\//, /^\/favicon/, /^\/icon/];

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLICAS.some((r) => r.test(pathname))) return NextResponse.next();

  const resposta = NextResponse.next({ request: req });
  const sup = createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    cookies: {
      getAll: () => req.cookies.getAll(),
      setAll: (lista) => lista.forEach(({ name, value, options }) => resposta.cookies.set(name, value, options)),   // renova o token
    },
  });
  const { data } = await sup.auth.getUser();
  const ass = lerSessaoAssinada(req.cookies.get(COOKIE_SESSAO)?.value);
  const valida = !!data.user && !!ass && ass.userId === data.user.id;
  if (valida) return resposta;

  if (pathname.startsWith("/api/")) return NextResponse.json({ erro: "Entre para continuar." }, { status: 401 });
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = data.user ? "?expirou=1" : "";
  return NextResponse.redirect(url);
}

export const config = { matcher: ["/((?!_next/static|_next/image|.*\\.(?:svg|png|jpg|ico|css|js)$).*)"] };
