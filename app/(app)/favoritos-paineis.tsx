import type { Painel } from "@/lib/paineis";
import type { FavoritoItem } from "@/lib/favoritos";
import { EscolherGraficos } from "./escolher-graficos";
import { FavoritoCartao } from "./favorito-cartao";

export function FavoritosPaineis({ paineis, favoritos }: { paineis: Painel[]; favoritos: FavoritoItem[] }) {
  if (paineis.length === 0) {
    return (
      <section className="panel" aria-labelledby="titulo-favoritos">
        <div className="panel-head" style={{ paddingBottom: 12 }}>
          <div>
            <h2 className="panel-title" id="titulo-favoritos">
              Meus gráficos
            </h2>
            <p className="panel-sub">
              Você ainda não tem nenhum painel liberado. Peça a um administrador para liberar os painéis que você precisa; os gráficos deles vão poder ser escolhidos aqui.
            </p>
          </div>
        </div>
      </section>
    );
  }

  const nomes = new Map(paineis.map((p) => [p.id, p.nome]));
  // só os que a pessoa ainda pode ver (a permissão pode ter sido retirada depois de favoritar)
  const visiveis = favoritos.filter((f) => nomes.has(f.painel_id));

  return (
    <section className="panel" aria-labelledby="titulo-favoritos">
      <div className="panel-head" style={{ paddingBottom: 12 }}>
        <div>
          <h2 className="panel-title" id="titulo-favoritos">
            Meus gráficos
          </h2>
          <p className="panel-sub">Os gráficos que você escolheu dos painéis, direto aqui no Início.</p>
        </div>
      </div>

      <div className="panel-body" style={{ paddingTop: 0 }}>
        <EscolherGraficos paineis={paineis} favoritos={visiveis} />

        {visiveis.length === 0 ? (
          <p className="panel-sub" style={{ marginTop: 16 }}>
            Nenhum gráfico escolhido ainda. Abra “Escolher gráficos” acima e marque os títulos que quiser ver aqui.
          </p>
        ) : (
          <div className="favoritos-grid">
            {visiveis.map((f) => (
              <FavoritoCartao key={`${f.painel_id}\u0001${f.aba}\u0001${f.chave}`} item={f} nomePainel={nomes.get(f.painel_id) ?? f.painel_id} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
