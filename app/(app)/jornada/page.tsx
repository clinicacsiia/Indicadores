import type { Metadata } from "next";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";
import { carregarQuadro, podeVerJornada, type DadosQuadro } from "@/lib/jornada";
import { IconAlerta } from "@/app/components/icons";
import { BarraColeta } from "@/app/components/BarraColeta";
import { AtualizarSozinho } from "../atualizar-sozinho";
import { Quadro } from "./Quadro";

export const metadata: Metadata = { title: "Jornada" };

export default async function JornadaPage() {
  const profile = await getCurrentProfile();

  if (!podeVerJornada(profile)) {
    return (
      <>
        <header className="page-head">
          <div className="page-head-text">
            <span className="eyebrow">Clínica CSI</span>
            <h1 className="page-title">Jornada do paciente</h1>
          </div>
        </header>
        <div className="notice" role="alert">
          <IconAlerta />
          Você ainda não tem acesso a esta tela. Peça a um administrador para liberar a Jornada em Configurações.
        </div>
      </>
    );
  }

  const supabase = await createClient();
  let dados: DadosQuadro | null = null;
  try {
    dados = await carregarQuadro(supabase);
  } catch (e) {
    console.error("Falha ao carregar o quadro da Jornada:", e instanceof Error ? e.message : e);
  }

  return (
    <>
      <header className="page-head">
        <div className="page-head-text">
          <span className="eyebrow">Clínica CSI</span>
          <h1 className="page-title">Jornada do paciente</h1>
          <p className="page-lede">
            Cada cartão é um paciente em um dia e uma unidade, com os exames dentro. As colunas do Klingo andam sozinhas; as da equipe ainda não podem ser movidas nesta versão (somente leitura).
          </p>
        </div>
      </header>

      <AtualizarSozinho rapido={false} segundos={30} />
      <BarraColeta />

      {dados ? (
        <Quadro dados={dados} />
      ) : (
        <div className="notice" role="alert">
          <IconAlerta />
          Não foi possível carregar o quadro agora. Tente novamente em instantes.
        </div>
      )}
    </>
  );
}
