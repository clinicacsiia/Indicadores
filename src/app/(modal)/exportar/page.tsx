import { menusDoUsuario, exigirSessao } from "@/lib/sessao";
import responsaveis from "../../../../painel_py/Atendimento/responsaveis.json";
import ExportarClient from "./ExportarClient";

export const dynamic = "force-dynamic";

export default async function Exportar() {
  const menus = await menusDoUsuario(await exigirSessao());
  const nomes = Object.fromEntries(responsaveis.responsaveis.map((r) => [r.id, `${r.nome} (${r.area})`]));
  const itens = menus.flatMap((m) => [
    { chave: m.id, modulo: m.id, visao: "", nome: m.nome, grupo: "Painéis" },
    ...m.visoes_pdf.map((v) => ({ chave: `${m.id}:${v}`, modulo: m.id, visao: v, nome: `${m.nome} · ${nomes[v] ?? v}`, grupo: "Por responsável" })),
  ]);
  return <ExportarClient itens={itens} />;
}
