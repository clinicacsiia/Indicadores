import Link from "next/link";
import type { Painel } from "@/lib/paineis";
import { FavoritoEstrela } from "./favorito-estrela";

export function FavoritosPaineis({ paineis, favoritos }: { paineis: Painel[]; favoritos: string[] }) {
  const favoritados = favoritos
    .map((id) => paineis.find((p) => p.id === id))
    .filter((p): p is Painel => p !== undefined);

  if (paineis.length === 0) {
    return (
      <section className="panel" aria-labelledby="titulo-favoritos">
        <div className="panel-head" style={{ paddingBottom: 12 }}>
          <div>
            <h2 className="panel-title" id="titulo-favoritos">
              Meus painéis
            </h2>
            <p className="panel-sub">
              Você ainda não tem nenhum painel liberado. Peça a um administrador para liberar os painéis que você precisa; eles vão aparecer aqui.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="panel" aria-labelledby="titulo-favoritos">
      <div className="panel-head" style={{ paddingBottom: 12 }}>
        <div>
          <h2 className="panel-title" id="titulo-favoritos">
            Meus painéis
          </h2>
          <p className="panel-sub">
            Marque com a estrela os painéis que você quer ver direto aqui no Início.
          </p>
        </div>
      </div>

      <div className="panel-body" style={{ paddingTop: 0 }}>
        <ul className="favoritos-chips" aria-label="Painéis disponíveis">
          {paineis.map((p) => (
            <li className="favoritos-chip" key={p.id}>
              <FavoritoEstrela painelId={p.id} favoritado={favoritos.includes(p.id)} />
              <Link href={`/painel/${p.id}`} className="favoritos-chip-nome">
                {p.nome}
              </Link>
            </li>
          ))}
        </ul>

        {favoritados.length === 0 ? (
          <p className="panel-sub" style={{ marginTop: 16 }}>
            Nenhum painel favoritado ainda. Clique na estrela ao lado de um painel acima para fixá-lo aqui.
          </p>
        ) : (
          <div className="favoritos-grid">
            {favoritados.map((p) => (
              <article className="favorito-card" key={p.id} aria-label={p.nome}>
                <div className="favorito-card-head">
                  <div>
                    <h3 className="favorito-card-titulo">{p.nome}</h3>
                    <p className="panel-sub">{p.descricao}</p>
                  </div>
                  <div className="favorito-card-acoes">
                    <Link href={`/painel/${p.id}`} className="favorito-abrir">
                      Abrir completo
                    </Link>
                    <FavoritoEstrela painelId={p.id} favoritado />
                  </div>
                </div>
                <iframe className="favorito-frame" title={p.nome} src={`/api/painel?id=${p.id}`} referrerPolicy="same-origin" />
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
