// Aba Qualidade: ocorrências, reclamações e elogios lançados à mão (o Klingo não traz esse dado).
// Duas permissões em profiles.permissions, as duas desligadas até o administrador marcar em Configurações:
//   qualidade_preencher = pode lançar (e ver o que ela mesma lançou)
//   qualidade           = pode ver o indicador inteiro e marcar uma ocorrência como resolvida
// Administrador tem as duas sempre. O banco (RLS da tabela `ocorrencia`) aplica a mesma regra.
export const PERMISSAO_QUALIDADE_VER = "qualidade";
export const PERMISSAO_QUALIDADE_PREENCHER = "qualidade_preencher";

type Perfil = { role: string; permissions: Record<string, boolean | string> } | null;

export const podeVerQualidade = (p: Perfil) => !!p && (p.role === "admin" || p.permissions?.[PERMISSAO_QUALIDADE_VER] === true);
export const podePreencherQualidade = (p: Perfil) => !!p && (p.role === "admin" || p.permissions?.[PERMISSAO_QUALIDADE_PREENCHER] === true);

export const UNIDADES = ["CSI 1", "CSI 2", "CSI Pediatria"] as const;
export const SETORES = ["Recepção", "Coleta", "Imagem", "Consultório", "Faturamento", "Estrutura e limpeza", "Outro"] as const;
export const TIPOS = [
  { id: "reclamacao", rotulo: "Reclamação" },
  { id: "ocorrencia", rotulo: "Ocorrência" },
  { id: "elogio", rotulo: "Elogio" },
] as const;
export const GRAVIDADES = [
  { id: "baixa", rotulo: "Baixa" },
  { id: "media", rotulo: "Média" },
  { id: "alta", rotulo: "Alta" },
] as const;

export type Tipo = (typeof TIPOS)[number]["id"];
export type Gravidade = (typeof GRAVIDADES)[number]["id"];

export const MIN_DESCRICAO = 10;
export const MAX_DESCRICAO = 1000;

export const CAMPOS_OCORRENCIA = "id, data_ocorrencia, unidade, setor, tipo, gravidade, descricao, status, resolvida_em, criado_em, exemplo";

export type Ocorrencia = {
  id: number;
  data_ocorrencia: string; // AAAA-MM-DD
  unidade: string;
  setor: string;
  tipo: Tipo;
  gravidade: Gravidade;
  descricao: string;
  status: "aberta" | "resolvida";
  resolvida_em: string | null;
  criado_em: string;
  exemplo: boolean;
};

export const rotuloTipo = (t: string) => TIPOS.find((x) => x.id === t)?.rotulo ?? t;
export const rotuloGravidade = (g: string) => GRAVIDADES.find((x) => x.id === g)?.rotulo ?? g;

const DIA_MS = 86_400_000;
const dias = (iso: string) => Date.parse(`${iso}T12:00:00Z`) / DIA_MS;

export type ResumoMes = {
  total: number;
  reclamacoes: number;
  ocorrencias: number;
  elogios: number;
  // Reclamações e ocorrências (elogio não tem o que resolver)
  problemas: number;
  resolvidos: number;
  pctResolvidos: number | null;
  diasMedios: number | null; // da data da ocorrência até a resolução
  altasAbertas: number;
};

export function resumir(linhas: Ocorrencia[]): ResumoMes {
  const problemas = linhas.filter((o) => o.tipo !== "elogio");
  const resolvidas = problemas.filter((o) => o.status === "resolvida" && o.resolvida_em);
  const espera = resolvidas.map((o) => dias(o.resolvida_em as string) - dias(o.data_ocorrencia));
  return {
    total: linhas.length,
    reclamacoes: linhas.filter((o) => o.tipo === "reclamacao").length,
    ocorrencias: linhas.filter((o) => o.tipo === "ocorrencia").length,
    elogios: linhas.filter((o) => o.tipo === "elogio").length,
    problemas: problemas.length,
    resolvidos: resolvidas.length,
    pctResolvidos: problemas.length ? (resolvidas.length / problemas.length) * 100 : null,
    diasMedios: espera.length ? espera.reduce((a, b) => a + b, 0) / espera.length : null,
    altasAbertas: problemas.filter((o) => o.gravidade === "alta" && o.status === "aberta").length,
  };
}

export const mesDe = (iso: string) => iso.slice(0, 7);

export function mesAnterior(mes: string): string {
  const [a, m] = mes.split("-").map(Number);
  return m === 1 ? `${a - 1}-12` : `${a}-${String(m - 1).padStart(2, "0")}`;
}

export function agruparPor(linhas: Ocorrencia[], chave: (o: Ocorrencia) => string): { nome: string; total: number; problemas: number }[] {
  const mapa = new Map<string, { nome: string; total: number; problemas: number }>();
  for (const o of linhas) {
    const k = chave(o);
    const item = mapa.get(k) ?? { nome: k, total: 0, problemas: 0 };
    item.total += 1;
    if (o.tipo !== "elogio") item.problemas += 1;
    mapa.set(k, item);
  }
  return [...mapa.values()].sort((a, b) => b.problemas - a.problemas || b.total - a.total || a.nome.localeCompare(b.nome));
}
