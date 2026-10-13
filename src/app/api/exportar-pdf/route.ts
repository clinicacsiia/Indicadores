import { ehMenu, NOME_DO_MENU, type MenuId } from "@/klingo/config";
import { hojeSalvador, textoPeriodo } from "@/klingo/datas";
import { ambiente } from "@/lib/ambiente";
import { auditar } from "@/lib/auditoria";
import { abrirNavegador, htmlParaPdf } from "@/lib/pdf";
import { juntarPdfs, type ParteDoPdf } from "@/lib/pdf-juntar";
import { lerJson, validarPost } from "@/lib/seguranca";
import { menusDoUsuario, obterSessao } from "@/lib/sessao";
import responsaveis from "../../../../painel_py/Atendimento/responsaveis.json";

export const maxDuration = 300;
export const dynamic = "force-dynamic";

const AAAA_MM = /^\d{4}-(0[1-9]|1[0-2])$/;

/**
 * POST /api/exportar-pdf  {"itens":[{"modulo":"faturamento"},{"modulo":"atendimento","visao":"carla"}], "de":"2026-09", "ate":"2026-10"}
 * Sem corpo: tudo que o usuário pode ver. A4 paisagem, margens de 8 mm, fonte mínima 12 pt, rodapé em todas as folhas, um marcador por painel.
 * Gera um painel por vez (o navegador é aberto uma vez); a tela do Exportar pede um item por chamada para respeitar o tempo da função.
 */
export async function POST(req: Request) {
  const recusa = validarPost(req);
  if (recusa) return recusa;
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const c = (await lerJson<{ itens?: { modulo?: string; visao?: string }[]; de?: string; ate?: string }>(req)) ?? {};
  const permitidos = await menusDoUsuario(sessao);
  const hoje = hojeSalvador();
  const de = c.de && AAAA_MM.test(c.de) ? c.de : hoje.ym, ate = c.ate && AAAA_MM.test(c.ate) ? c.ate : de;
  const [ini, fim] = de <= ate ? [de, ate] : [ate, de];

  type Pedido = { modulo?: string; visao?: string };
  const pedido: Pedido[] = (c.itens && c.itens.length ? c.itens : permitidos.flatMap((m): Pedido[] => [{ modulo: m.id }, ...m.visoes_pdf.map((v) => ({ modulo: m.id, visao: v }))])).slice(0, 40);
  for (const it of pedido) {
    const m = permitidos.find((p) => p.id === it.modulo);
    if (!ehMenu(it.modulo) || !m) return Response.json({ erro: "Sem acesso a um dos painéis pedidos." }, { status: 403 });
    if (it.visao && !m.visoes_pdf.includes(it.visao)) return Response.json({ erro: "Visão inválida." }, { status: 400 });
  }

  const quando = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Bahia", dateStyle: "short", timeStyle: "short" }).format(new Date());
  const periodo = textoPeriodo(ini, fim, hoje.iso);
  const partes: ParteDoPdf[] = [];
  const navegador = await abrirNavegador();
  try {
    for (const it of pedido) {
      const menu = it.modulo as MenuId;
      const url = new URL("/api/py/painel", new URL(req.url).origin);
      url.searchParams.set("menu", menu); url.searchParams.set("de", ini); url.searchParams.set("ate", fim);
      const cab: Record<string, string> = { "x-interno": ambiente.cronSecret };
      if (process.env.VERCEL_AUTOMATION_BYPASS_SECRET) cab["x-vercel-protection-bypass"] = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
      const r = await fetch(url, { headers: cab, cache: "no-store" });
      if (!r.ok) return Response.json({ erro: `Não foi possível montar o painel ${NOME_DO_MENU[menu]}.` }, { status: 502 });
      const resp = it.visao ? responsaveis.responsaveis.find((x) => x.id === it.visao) : null;
      const nome = resp ? `${NOME_DO_MENU[menu]} · ${resp.nome} (${resp.area})` : NOME_DO_MENU[menu];
      const q = new URLSearchParams({ de: ini, ate: fim, visao: it.visao ?? "todos" }).toString();
      partes.push({ titulo: nome, bytes: await htmlParaPdf(navegador, await r.text(), q, { titulo: "Clínica CSI", painel: nome, periodo, quando }) });
    }
  } finally {
    await navegador.close();
  }
  await auditar("exportar_pdf", sessao.usuario, { itens: pedido.length, de: ini, ate: fim });
  const pdf = partes.length === 1 ? partes[0].bytes : await juntarPdfs(partes);
  return new Response(Buffer.from(pdf), { headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="indicadores-csi.pdf"', "Cache-Control": "no-store" } });
}
