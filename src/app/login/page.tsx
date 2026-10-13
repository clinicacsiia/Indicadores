import { redirect } from "next/navigation";
import { obterSessao } from "@/lib/sessao";
import { haUsuarios } from "./acoes";
import LoginForm from "./LoginForm";

export const dynamic = "force-dynamic";

export default async function Login({ searchParams }: { searchParams: Promise<{ expirou?: string }> }) {
  if (await obterSessao()) redirect("/");
  const sp = await searchParams;
  return (
    <main className="login">
      <LoginForm primeiroUso={!(await haUsuarios())} expirou={sp.expirou === "1"} />
    </main>
  );
}
