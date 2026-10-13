"use client";

import { useState, useTransition } from "react";
import { IconEstrela } from "@/app/components/icons";
import { alternarFavorito } from "./favoritos-actions";

export function FavoritoEstrela({ painelId, favoritado }: { painelId: string; favoritado: boolean }) {
  const [pendente, startTransition] = useTransition();
  const [erro, setErro] = useState<string | null>(null);

  return (
    <span className="favorito-estrela-wrap">
      <button
        type="button"
        className="favorito-estrela"
        data-ativo={favoritado || undefined}
        aria-pressed={favoritado}
        aria-label={favoritado ? "Remover dos favoritos do Início" : "Adicionar aos favoritos do Início"}
        title={favoritado ? "Remover dos favoritos" : "Favoritar"}
        disabled={pendente}
        onClick={() =>
          startTransition(async () => {
            const resultado = await alternarFavorito(painelId);
            setErro(resultado?.error ?? null);
          })
        }
      >
        <IconEstrela size={18} preenchida={favoritado} />
      </button>
      {erro && (
        <span role="alert" className="favorito-erro">
          {erro}
        </span>
      )}
    </span>
  );
}
