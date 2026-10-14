import modulos from "@/modulos.json";

// Painéis em Python (Faturamento, Financeiro, ...). A lista vem do modulos.json, o mesmo arquivo que o
// código Python lê: um painel novo entra nos dois lados ao mesmo tempo. As Metas têm aba própria no site.
//
// `financeiro` diz o que o painel tem de dinheiro (receita, despesa, valores em R$):
//   "total"   = é praticamente só dinheiro: sem "Dados financeiros" o painel nem abre;
//   "parcial" = é misto: abre, mas o servidor tira os valores em R$ da página;
//   null      = sem dinheiro ("nenhum" no modulos.json; painel sem o campo conta como "total").
export type FinanceiroDoPainel = "total" | "parcial" | null;
export type Painel = { id: string; nome: string; descricao: string; financeiro: FinanceiroDoPainel };

// Painel sem o campo conta como "total": esquecer de preencher bloqueia, não libera. Quem não tem dinheiro diz "nenhum".
function financeiroDe(valor: string | undefined): FinanceiroDoPainel {
  if (valor === "nenhum") return null;
  return valor === "parcial" ? "parcial" : "total";
}

export const PAINEIS: Painel[] = modulos.modulos
  .filter((m) => m.tipo === "relatorios")
  .map((m) => ({
    id: m.id,
    nome: m.nome,
    descricao: m.descricao,
    financeiro: financeiroDe((m as { financeiro?: string }).financeiro),
  }));

// Chave em profiles.permissions. Não pode ser "financeiro": as chaves do painel são os ids dos painéis, e já existe um com esse id.
export const PERMISSAO_FINANCEIRA = "dados_financeiros";

type PerfilComPermissoes = { role: string; permissions: Record<string, boolean> } | null;

// Admin vê receitas, despesas e valores; os demais só com "Dados financeiros" marcado em Configurações.
export function veDadosFinanceiros(perfil: PerfilComPermissoes): boolean {
  if (!perfil) return false;
  return perfil.role === "admin" || perfil.permissions?.[PERMISSAO_FINANCEIRA] === true;
}

// Admin vê todos; os demais só os painéis marcados em Configurações. Painel novo nasce BLOQUEADO
// (tem dado financeiro e, em alguns, identificação de paciente) — o contrário de Relatórios e Metas.
// Painel só de dinheiro ainda exige "Dados financeiros". A mesma regra é aplicada de novo no servidor
// Python (portal_nuvem.py), que é quem entrega os dados, e no banco (can_view_painel) para os avisos.
export function podeVerPainel(perfil: PerfilComPermissoes, id: string): boolean {
  if (!perfil) return false;
  if (perfil.role === "admin") return true;
  if (perfil.permissions?.[id] !== true) return false;
  const painel = PAINEIS.find((p) => p.id === id);
  return painel?.financeiro !== "total" || veDadosFinanceiros(perfil);
}
