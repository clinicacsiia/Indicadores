import type { MetasConfig } from "./calculo";
// Única fonte das metas e das regras: o mesmo arquivo do painel local ("Acompanhamento de META").
// Para mudar uma meta, edite o metas.json e publique; metas_por_mes ajusta só um mês.
import metas from "../../Acompanhamento de META/metas.json";

export const metasConfig = metas as unknown as MetasConfig;

/** Código do relatório do Klingo que alimenta as metas. */
export const RELATORIO_METAS = "13339";
