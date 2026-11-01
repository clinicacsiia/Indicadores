import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Sem acesso anônimo: toda rota exige sessão válida, exceto /login e a página do paciente (/p/<código>).
// Isso é reforçado aqui E pelas policies de RLS no banco (defesa em profundidade).
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const isLoginRoute = request.nextUrl.pathname.startsWith("/login");
  // Página do paciente (/p/<código>): pública de propósito. O código do link é a chave; quem não o conhece não entra, e o banco só atende o servidor do site.
  const isPortalPaciente = request.nextUrl.pathname.startsWith("/p/");

  if (isPortalPaciente) {
    return response;
  }

  if (!user && !isLoginRoute) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  if (user && isLoginRoute) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return response;
}
