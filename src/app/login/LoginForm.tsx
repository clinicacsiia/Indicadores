"use client";
import { useActionState, useState } from "react";
import { criarPrimeiroAdmin, entrar, solicitarCadastro, type Estado } from "./acoes";

const inicial: Estado = {};

export default function LoginForm({ primeiroUso, expirou }: { primeiroUso: boolean; expirou: boolean }) {
  const [modo, setModo] = useState<"entrar" | "solicitar">("entrar");
  const [e1, a1, p1] = useActionState(entrar, inicial);
  const [e2, a2, p2] = useActionState(solicitarCadastro, inicial);
  const [e3, a3, p3] = useActionState(criarPrimeiroAdmin, inicial);

  if (primeiroUso) {
    return (
      <form action={a3} className="form">
        <h1>Primeiro acesso</h1>
        <p className="nota">Ainda não há usuários. Crie o administrador: você define a sua própria senha.</p>
        <label>Usuário<input name="usuario" autoComplete="username" required minLength={2} maxLength={32} /></label>
        <label>Senha<input name="senha" type="password" autoComplete="new-password" required minLength={8} /></label>
        <label>Confirmar senha<input name="confirmar" type="password" autoComplete="new-password" required /></label>
        {e3.erro && <p className="erro" role="alert">{e3.erro}</p>}
        {e3.ok && <p className="ok">{e3.ok}</p>}
        <button className="btn" disabled={p3}>Criar administrador</button>
      </form>
    );
  }
  if (modo === "solicitar") {
    return (
      <form action={a2} className="form">
        <h1>Pedir cadastro</h1>
        <p className="nota">Escolha um usuário e uma senha. Você poderá entrar depois que um administrador aprovar.</p>
        <label>Usuário<input name="usuario" autoComplete="username" required minLength={2} maxLength={32} /></label>
        <label>Senha<input name="senha" type="password" autoComplete="new-password" required minLength={8} /></label>
        <label>Mensagem (opcional)<textarea name="mensagem" maxLength={200} rows={3} placeholder="Quem é você e por que precisa de acesso" /></label>
        {e2.erro && <p className="erro" role="alert">{e2.erro}</p>}
        {e2.ok && <p className="ok">{e2.ok}</p>}
        <button className="btn" disabled={p2}>Enviar pedido</button>
        <button type="button" className="link" onClick={() => setModo("entrar")}>Voltar</button>
      </form>
    );
  }
  return (
    <form action={a1} className="form">
      <h1>Clínica CSI</h1>
      <p className="nota">Indicadores · entre com o seu usuário</p>
      {expirou && <p className="aviso">Sua sessão terminou. Entre de novo.</p>}
      <label>Usuário<input name="usuario" autoComplete="username" required autoFocus /></label>
      <label>Senha<input name="senha" type="password" autoComplete="current-password" required /></label>
      {e1.erro && <p className="erro" role="alert">{e1.erro}</p>}
      <button className="btn" disabled={p1}>Entrar</button>
      <button type="button" className="link" onClick={() => setModo("solicitar")}>Pedir cadastro</button>
    </form>
  );
}
