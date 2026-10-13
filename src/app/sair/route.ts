import { NextResponse } from "next/server";
import { COOKIE_SESSAO } from "@/lib/seguranca";
import { supabaseDoUsuario } from "@/lib/supabase/servidor";

export async function GET(req: Request) {
  const sup = await supabaseDoUsuario();
  await sup.auth.signOut();
  const r = NextResponse.redirect(new URL("/login", req.url));
  r.cookies.delete(COOKIE_SESSAO);
  return r;
}
