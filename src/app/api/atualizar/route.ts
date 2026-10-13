import { after } from "next/server";
import { ATUALIZA_JUNTO, ehMenu, NOME_DO_MENU, type MenuId } from "@/klingo/config";
import { enfileirarAtualizacao } from "@/klingo/motor";
import { auditar } from "@/lib/auditoria";
import { processarEEncadear, versaoDosDados } from "@/lib/atualizacao";
import { lerConfiguracoes } from "@/lib/configuracoes";
import { hashDeOrigem, ipDe, lerJson, validarPost } from "@/lib/seguranca";
import { obterSessao, podeVerMenu } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";

export const maxDuration = 60;
export const dynamic = "force-dynamic";

/**
 * "Atualizar agora": só uma atualização por vez no sistema inteiro (trava com prazo); quem não é admin só atualiza se os dados do menu têm
 * mais de 5 min (senão a tela explica e o Klingo não é consultado); admin sempre pode. Exige X-Painel: 1 (anti-CSRF), sessão e permissão.
 */
export async function POST(req: Request) {
  const recusa = validarPost(req);
  if (recusa) return recusa;
  const sessao = await obterSessao();
  if (!sessao) return Response.json({ erro: "Entre para continuar." }, { status: 401 });
  const corpo = await lerJson<{ menu?: string }>(req);
  const menu = corpo?.menu;
  if (!ehMenu(menu) || !podeVerMenu(sessao, menu)) return Response.json({ erro: "Sem acesso a este painel." }, { status: 403 });
  const db = admin();
  const nome = NOME_DO_MENU[menu];

  if (!sessao.admin) {
    const min = (await lerConfiguracoes()).intervalo_minimo_atualizar_agora_minutos;
    const { atualizadoEm } = await versaoDosDados(menu);
    const idade = atualizadoEm ? (Date.now() - Date.parse(atualizadoEm)) / 60000 : Infinity;
    if (idade < min) {
      const mensagem = `Os dados de ${nome} foram atualizados há ${Math.max(1, Math.round(idade))} min e já estão em dia. Não consultei o Klingo (só é possível pedir de novo depois de ${min} min).`;
      await db.from("historico_atualizacoes").insert({ modulo_id: menu, status: "ja_em_dia", mensagem, usuario: sessao.usuario });
      return Response.json({ atualizou: false, status: "ja_em_dia", mensagem });
    }
  }

  const { data: trava, error } = await db.rpc("adquirir_trava", { p_modulo: menu, p_usuario: sessao.usuario, p_minutos: 15 });
  if (error) return Response.json({ erro: "Não foi possível iniciar a atualização agora." }, { status: 500 });
  if (!trava.ok) {
    const quem = ehMenu(trava.modulo) ? NOME_DO_MENU[trava.modulo as MenuId] : "outro painel";
    return Response.json({ atualizou: false, status: "ocupado", mensagem: `Já há uma atualização em andamento: ${quem} (por ${trava.usuario ?? "alguém"}). Aguarde terminar.` });
  }
  try {
    const r = await enfileirarAtualizacao({ sb: db }, [menu], sessao.usuario);
    await auditar("atualizar", sessao.usuario, { menu, menus: r.menus, itens: r.itens }, hashDeOrigem(ipDe(req)));
  } catch (e) {
    await db.rpc("liberar_trava");
    console.error("falha ao enfileirar", (e as Error).message);
    return Response.json({ erro: "Não foi possível iniciar a atualização agora." }, { status: 500 });
  }
  const origem = new URL(req.url).origin;
  after(async () => { try { await processarEEncadear(origem); } catch (e) { console.error("falha no processamento", (e as Error).message); } });
  const junto = (ATUALIZA_JUNTO[menu] ?? []).map((m) => NOME_DO_MENU[m]);
  return Response.json({ atualizou: true, status: "iniciada", mensagem: `Atualizando ${nome}${junto.length ? ` (e também ${junto.join(" e ")})` : ""}… este painel recarrega sozinho quando terminar.` });
}
