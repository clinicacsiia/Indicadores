import { RespostaInvalida } from "./erros";
import type { Celula, RespostaValida } from "./tipos";
import type { Tabela } from "./transformar";
import { paraData } from "./transformar";

export const COLUNAS_METAS = ["Exames Realizados", "Unidade", "Procedimento - Classes", "Especialidade", "Data do Atendimento", "Procedimento", "Mês", "Convênio"];

/**
 * Porte de para_linhas (extrair_laudo.py): "Exames Realizados" é o ID do atendimento (conta-se linhas, não soma); as classes vêm como lista
 * JSON e viram "A, B"; "Mês" é calculado; "Convênio" (no Klingo "Operadora") é opcional. Recusa a resposta inteira se alguma linha não
 * tiver ID inteiro ou data válida (nada é gravado).
 */
export function linhasDeMetas(r: RespostaValida): Tabela {
  const defeitos: string[] = [];
  const linhas: Celula[][] = [];
  r.linhas.forEach((l, i) => {
    let classes = String(l["Procedimento - Classes"] ?? "");
    try { const j = JSON.parse(classes); if (Array.isArray(j)) classes = j.join(", "); } catch { /* já vem em texto */ }
    const id = Number.parseInt(String(l["Exames Realizados"] ?? ""), 10);
    const quando = paraData(typeof l["Data do Atendimento"] === "string" ? (l["Data do Atendimento"] as string) : null);
    if (!Number.isInteger(id) || !quando) {
      defeitos.push(`linha ${i + 1} (ID ${JSON.stringify(l["Exames Realizados"])}, data ${JSON.stringify(l["Data do Atendimento"])})`);
      return;
    }
    const conv = String(l["Operadora"] ?? l["Convênio"] ?? "").trim();
    linhas.push([id, (l["Unidade"] as string) ?? null, classes, (l["Especialidade"] as string) ?? null, quando, (l["Procedimento"] as string) ?? null, quando.slice(0, 7), conv || null]);
  });
  if (defeitos.length) throw new RespostaInvalida(`${defeitos.length} linha(s) sem ID ou sem data válida, nada foi gravado: ${defeitos.slice(0, 3).join("; ")}${defeitos.length > 3 ? "…" : ""}`);
  return { colunas: COLUNAS_METAS, linhas, avisos: [] };
}
