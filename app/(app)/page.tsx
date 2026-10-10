import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { getCurrentProfile } from "@/lib/supabase/profile";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_LINHAS = 5000;
const PAGINA = 1000;

// Ordem das colunas na tabela; indicadores desconhecidos vão para o fim.
const COLUNAS = [
  { codigo: "agendamentos_total", rotulo: "Agendamentos" },
  { codigo: "atendimentos_finalizados", rotulo: "Atendimentos finalizados" },
  { codigo: "atendimentos_avulsos", rotulo: "Atendimentos avulsos" },
  { codigo: "valor_total_procedimentos", rotulo: "Valor dos procedimentos" },
];

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const inteiro = new Intl.NumberFormat("pt-BR");

function formatarValor(valor: number, unidade: string | null) {
  return unidade === "BRL" ? brl.format(valor) : inteiro.format(valor);
}

function formatarData(iso: string) {
  const [ano, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${ano}`;
}

function somarDias(iso: string, dias: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

function hojeSaoPaulo() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

type Indicador = {
  codigo: string;
  nome: string;
  valor: number;
  unidade: string | null;
  periodo: string;
};

export default async function RelatoriosPage({
  searchParams,
}: {
  searchParams: Promise<{ de?: string; ate?: string }>;
}) {
  const profile = await getCurrentProfile();
  const podeVer = profile?.role === "admin" || profile?.permissions?.relatorios !== false;

  if (profile && !podeVer) {
    return (
      <>
        <h1>Relatórios</h1>
        <p>Você não tem permissão para ver os relatórios. Fale com um administrador.</p>
      </>
    );
  }

  const params = await searchParams;
  const hoje = hojeSaoPaulo();
  const ate = params.ate && DATE_RE.test(params.ate) ? params.ate : hoje;
  const de = params.de && DATE_RE.test(params.de) && params.de <= ate ? params.de : somarDias(ate, -29);

  const supabase = await createClient();

  // RLS garante que isso só retorna dados para quem está autenticado e pode ver
  // Relatórios; o proxy já bloqueia a rota antes mesmo de chegar aqui.
  // O PostgREST devolve no máximo 1000 linhas por requisição; busca em páginas.
  async function carregarIndicadores() {
    const linhas: Indicador[] = [];
    for (let inicio = 0; inicio < MAX_LINHAS; inicio += PAGINA) {
      const { data, error } = await supabase
        .from("indicadores")
        .select("codigo, nome, valor, unidade, periodo")
        .gte("periodo", de)
        .lte("periodo", ate)
        .order("periodo", { ascending: false })
        .order("codigo")
        .range(inicio, inicio + PAGINA - 1);
      if (error) return { data: null, error };
      linhas.push(...((data ?? []) as Indicador[]));
      if (!data || data.length < PAGINA) break;
    }
    return { data: linhas, error: null };
  }

  const [{ data, error }, { data: ultimaSync }] = await Promise.all([
    carregarIndicadores(),
    supabase
      .from("sync_runs")
      .select("finished_at")
      .eq("status", "success")
      .order("finished_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);

  // Nunca mostrar error.message na tela: pode conter detalhes internos do Postgres.
  if (error) {
    console.error("Falha ao carregar indicadores:", error.message);
  }

  const indicadores = data ?? [];

  const codigosExtras = [...new Set(indicadores.map((i) => i.codigo))].filter(
    (codigo) => !COLUNAS.some((c) => c.codigo === codigo)
  );
  const colunas = [
    ...COLUNAS,
    ...codigosExtras.map((codigo) => ({
      codigo,
      rotulo: indicadores.find((i) => i.codigo === codigo)?.nome ?? codigo,
    })),
  ];

  const unidades = new Map(indicadores.map((i) => [i.codigo, i.unidade]));
  const totais = new Map<string, number>();
  const porDia = new Map<string, Map<string, number>>();
  for (const item of indicadores) {
    const valor = Number(item.valor);
    totais.set(item.codigo, (totais.get(item.codigo) ?? 0) + valor);
    if (!porDia.has(item.periodo)) porDia.set(item.periodo, new Map());
    porDia.get(item.periodo)!.set(item.codigo, valor);
  }
  const dias = [...porDia.keys()].sort().reverse();

  const atalhos = [
    { rotulo: "7 dias", de: somarDias(hoje, -6), ate: hoje },
    { rotulo: "30 dias", de: somarDias(hoje, -29), ate: hoje },
    { rotulo: "90 dias", de: somarDias(hoje, -89), ate: hoje },
    { rotulo: "Este ano", de: `${hoje.slice(0, 4)}-01-01`, ate: hoje },
  ];

  const ultimaSyncTexto = ultimaSync?.finished_at
    ? new Intl.DateTimeFormat("pt-BR", {
        timeZone: "America/Sao_Paulo",
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(ultimaSync.finished_at))
    : null;

  return (
    <>
      <h1>Relatórios</h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        Agendados x realizados (Klingo), totais por dia.
        {ultimaSyncTexto && <> Última sincronização: {ultimaSyncTexto}.</>}
      </p>

      <form method="get" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", margin: "16px 0" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          De
          <input type="date" name="de" defaultValue={de} max={hoje} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          Até
          <input type="date" name="ate" defaultValue={ate} max={hoje} />
        </label>
        <button type="submit">Filtrar</button>
        <span style={{ display: "flex", gap: 8, marginLeft: 8 }}>
          {atalhos.map((a) => (
            <Link key={a.rotulo} href={`/?de=${a.de}&ate=${a.ate}`}>
              {a.rotulo}
            </Link>
          ))}
        </span>
      </form>

      {error && <p style={{ color: "crimson" }}>Não foi possível carregar os indicadores agora.</p>}

      {!error && dias.length === 0 && (
        <p>Nenhum indicador sincronizado entre {formatarData(de)} e {formatarData(ate)}.</p>
      )}

      {dias.length > 0 && (
        <>
          <h2 style={{ fontSize: 18 }}>
            Totais de {formatarData(de)} a {formatarData(ate)} ({dias.length} {dias.length === 1 ? "dia" : "dias"} com dados)
          </h2>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
            {colunas.map((c) => (
              <div
                key={c.codigo}
                style={{ border: "1px solid #ddd", borderRadius: 8, padding: "12px 16px", minWidth: 180 }}
              >
                <div style={{ color: "#666", fontSize: 13 }}>{c.rotulo}</div>
                <div style={{ fontSize: 22, fontWeight: 600 }}>
                  {formatarValor(totais.get(c.codigo) ?? 0, unidades.get(c.codigo) ?? null)}
                </div>
              </div>
            ))}
          </div>

          <h2 style={{ fontSize: 18 }}>Por dia</h2>
          <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #ddd" }}>
                <th align="left">Data</th>
                {colunas.map((c) => (
                  <th key={c.codigo} align="right">
                    {c.rotulo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dias.map((dia) => (
                <tr key={dia} style={{ borderBottom: "1px solid #f0f0f0" }}>
                  <td>{formatarData(dia)}</td>
                  {colunas.map((c) => {
                    const valor = porDia.get(dia)!.get(c.codigo);
                    return (
                      <td key={c.codigo} align="right">
                        {valor === undefined ? "—" : formatarValor(valor, unidades.get(c.codigo) ?? null)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
