import { gunzipSync, gzipSync } from "node:zlib";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { Celula } from "./tipos";
import type { Tabela } from "./transformar";

/** Linhas do bloco: JSON + gzip + base64 (dados_blocos.conteudo). */
export const codificarBloco = (linhas: Celula[][]): string => gzipSync(Buffer.from(JSON.stringify(linhas), "utf-8")).toString("base64");
export const decodificarBloco = (b64: string): Celula[][] => JSON.parse(gunzipSync(Buffer.from(b64, "base64")).toString("utf-8"));

export async function lerBloco(sb: SupabaseClient, menu: string, aba: string, mes: string): Promise<Tabela | null> {
  const { data, error } = await sb.from("dados_blocos").select("colunas, conteudo").eq("menu", menu).eq("aba", aba).eq("mes", mes).maybeSingle();
  if (error) throw new Error(`ler bloco ${menu}/${aba}/${mes}: ${error.message}`);
  if (!data) return null;
  return { colunas: data.colunas as string[], linhas: decodificarBloco(data.conteudo as string), avisos: [] };
}

/** Grava (ou substitui) o bloco de uma aba/mês em uma transação (função gravar_bloco). */
export async function gravarBloco(sb: SupabaseClient, menu: string, aba: string, mes: string, t: Tabela, apagarOutros = false): Promise<void> {
  const { error } = await sb.rpc("gravar_bloco", {
    p_menu: menu, p_aba: aba, p_mes: mes, p_colunas: t.colunas, p_linhas: t.linhas.length, p_conteudo: codificarBloco(t.linhas), p_apagar_outros: apagarOutros,
  });
  if (error) throw new Error(`gravar bloco ${menu}/${aba}/${mes}: ${error.message}`);
}

export async function blocosExistentes(sb: SupabaseClient, menu: string): Promise<Set<string>> {
  const { data, error } = await sb.from("dados_blocos").select("aba, mes").eq("menu", menu);
  if (error) throw new Error(`listar blocos de ${menu}: ${error.message}`);
  return new Set((data ?? []).map((r) => `${r.aba}|${r.mes}`));
}
