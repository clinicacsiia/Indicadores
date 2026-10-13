import modulos from "@/modulos.json";

// Painéis em Python (Faturamento, Financeiro, ...). A lista vem do modulos.json, o mesmo arquivo que o
// código Python lê: um painel novo entra nos dois lados ao mesmo tempo. As Metas têm aba própria no site.
export type Painel = { id: string; nome: string; descricao: string };

export const PAINEIS: Painel[] = modulos.modulos
  .filter((m) => m.tipo === "relatorios")
  .map((m) => ({ id: m.id, nome: m.nome, descricao: m.descricao }));

type PerfilComPermissoes = { role: string; permissions: Record<string, boolean> } | null;

// Admin vê todos; os demais só os painéis marcados em Configurações. Painel novo nasce BLOQUEADO
// (tem dado financeiro e, em alguns, identificação de paciente) — o contrário de Relatórios e Metas.
// A mesma regra é aplicada de novo no servidor Python (portal_nuvem.py), que é quem entrega os dados.
export function podeVerPainel(perfil: PerfilComPermissoes, id: string): boolean {
  if (!perfil) return false;
  return perfil.role === "admin" || perfil.permissions?.[id] === true;
}
