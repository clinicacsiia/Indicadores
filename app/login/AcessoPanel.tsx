"use client";

import { useState } from "react";
import { LoginForm } from "./LoginForm";
import { SolicitarAcessoForm } from "./SolicitarAcessoForm";

export function AcessoPanel() {
  const [pedindo, setPedindo] = useState(false);

  return (
    <>
      <div>
        <h1>{pedindo ? "Solicitar acesso" : "Entrar"}</h1>
        <p className="lede">
          {pedindo
            ? "Escolha o seu usuário e uma senha. Um administrador vai aprovar o pedido e liberar as telas que você pode ver."
            : "Use o usuário e a senha da equipe para acessar os indicadores."}
        </p>
      </div>
      {pedindo ? (
        <SolicitarAcessoForm onVoltar={() => setPedindo(false)} />
      ) : (
        <LoginForm onSolicitarAcesso={() => setPedindo(true)} />
      )}
    </>
  );
}
