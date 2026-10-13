/**
 * Carrega no Supabase a história que estava nas planilhas do legado (Dados do Indicadores CSI\*.xlsx), para o site nascer com os meses antigos.
 * Depois a sincronização refaz os meses recentes. Os .xlsx ficam FORA do Git.
 *
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... npx tsx scripts/importar_planilhas.ts "<pasta com os .xlsx>" [--simular]
 *
 * Procura (em qualquer subpasta): Acompanhamento de META.xlsx, Faturamento.xlsx, Financeiro.xlsx, Despesas.xlsx, Indicadores.xlsx,
 * "Cesta de Exames.xlsx", Suprimentos.xlsx, Atendimento.xlsx e "Custos dos Itens.xlsx" (nomes do campo "arquivo" de cada relatorios.json).
 */
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { createClient } from "@supabase/supabase-js";
import { DEFINICOES, MENUS, type MenuId } from "../src/klingo/config";
import { gravarBloco } from "../src/klingo/gravar";
import { lerCustos, lerPlanilhaMenu } from "../src/klingo/planilhas";

const ARQUIVO: Record<MenuId, string> = {
  metas: "Acompanhamento de META.xlsx",
  faturamento: String(DEFINICOES.faturamento.arquivo), financeiro: String(DEFINICOES.financeiro.arquivo), despesas: String(DEFINICOES.despesas.arquivo),
  indicadores: String(DEFINICOES.indicadores.arquivo), cesta: String(DEFINICOES.cesta.arquivo), suprimentos: String(DEFINICOES.suprimentos.arquivo), atendimento: String(DEFINICOES.atendimento.arquivo),
};

function achar(pasta: string, nome: string): string | null {
  for (const e of readdirSync(pasta)) {
    const p = join(pasta, e);
    if (statSync(p).isDirectory()) { const r = achar(p, nome); if (r) return r; }
    else if (e.toLowerCase() === nome.toLowerCase()) return p;
  }
  return null;
}

async function principal() {
  const [pasta, ...flags] = process.argv.slice(2);
  if (!pasta) { console.error("Uso: npx tsx scripts/importar_planilhas.ts <pasta> [--simular]"); process.exit(2); }
  const simular = flags.includes("--simular");
  const sb = simular ? null : createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!, { auth: { persistSession: false } });
  for (const menu of MENUS) {
    const arq = achar(pasta, ARQUIVO[menu]);
    if (!arq) { console.log(`- ${menu}: ${ARQUIVO[menu]} não encontrado (pulado)`); continue; }
    const blocos = await lerPlanilhaMenu(arq, menu);
    const linhas = blocos.reduce((t, b) => t + b.tabela.linhas.length, 0);
    console.log(`- ${menu}: ${blocos.length} bloco(s), ${linhas} linha(s)`);
    if (!sb) continue;
    for (const b of blocos) await gravarBloco(sb, menu, b.aba, b.mes, b.tabela, b.apagarOutros);
    if (blocos.length) await sb.rpc("subir_versao", { p_menu: menu });
  }
  const custos = achar(pasta, "Custos dos Itens.xlsx");
  if (custos) {
    const itens = await lerCustos(custos);
    console.log(`- custos dos itens: ${itens.length} item(ns), ${itens.filter((i) => i.custo != null).length} com custo informado`);
    if (sb && itens.length) { const { error } = await sb.from("custos_itens").upsert(itens, { onConflict: "item" }); if (error) throw new Error(error.message); }
  }
  console.log(simular ? "Simulação concluída (nada foi gravado)." : "Importação concluída.");
}
principal().catch((e) => { console.error("Falhou:", e instanceof Error ? e.message : e); process.exit(1); });
