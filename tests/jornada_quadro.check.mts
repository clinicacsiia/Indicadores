import assert from "node:assert/strict";
import { noPeriodo, somarDias, filtrarCards, agruparExames, FILTROS_PADRAO, linkWhatsApp, tempoNaColuna, semAcento, hojeBrasilia, podeVerJornada, diaCurto, destinosPermitidos, cartaoMovido, erroDeMover, iniciais, compararCartoes, rotuloVencimento } from "../lib/jornada.ts";
import { tokenValido, textoDoMotivo, diaPorExtenso, urlDoPortal, mensagemDoLink, linkWhatsAppComTexto } from "../lib/portal.ts";
import { duracaoCurta, estadoDoRelatorio, estadoGeral, segundosAte } from "../lib/coleta-ritmo.ts";

assert.equal(somarDias("2026-11-30", 1), "2026-12-01");
assert.equal(somarDias("2026-03-01", -1), "2026-02-28");
const hoje = "2026-11-04";
assert.ok(noPeriodo("2026-11-04", "hoje", hoje) && !noPeriodo("2026-11-05", "hoje", hoje));
assert.ok(noPeriodo("2026-11-03", "ontem", hoje) && noPeriodo("2026-11-05", "amanha", hoje));
assert.ok(noPeriodo("2026-11-10", "7dias", hoje) && !noPeriodo("2026-11-11", "7dias", hoje) && !noPeriodo("2026-11-03", "7dias", hoje));
assert.ok(noPeriodo("1999-01-01", "tudo", hoje));
assert.equal(hojeBrasilia(new Date("2026-11-05T01:30:00Z")), "2026-11-04"); // 22:30 em Brasília ainda é dia 4
assert.equal(semAcento("João"), "joao");
assert.equal(linkWhatsApp("(11) 98888-7777"), "https://wa.me/5511988887777");
assert.equal(linkWhatsApp("5511988887777"), "https://wa.me/5511988887777");
assert.equal(linkWhatsApp("123"), null);
assert.equal(tempoNaColuna(35), "35 min"); assert.equal(tempoNaColuna(125), "2 h 05"); assert.equal(tempoNaColuna(1500), "1 d 1 h");
assert.equal(diaCurto("2026-11-03"), "03/11");
assert.ok(podeVerJornada({ role: "admin", permissions: {} }) && podeVerJornada({ role: "viewer", permissions: { jornada: true } }) && !podeVerJornada({ role: "viewer", permissions: {} }) && !podeVerJornada(null));

const card = (id: number, over: object = {}) => ({ id, paciente_chave: "100" + id, paciente_nome: "Maria da Conceição", data_ref: hoje, unidade: "CSI 1", coluna: "a_confirmar", coluna_nome: "A confirmar", etapa: "agendamento", origem: "klingo", ordem: 4, coluna_desde: "", responsavel: null, prioridade: 0, versao: 1, n_exames: 1, n_ativos: 1, n_mensagens: 0, vazio: false, atrasado: false, minutos_na_coluna: 5, n_tarefas_abertas: 0, n_tarefas_vencidas: 0, portal_confirmou_em: null, ...over }) as any;
const ex = (card_id: number, over: object = {}) => ({ card_id, marcacao_id: "M" + card_id, atendimento_id: null, procedimento: "RM JOELHO", operadora: "AMIL", agendado_para: "2026-11-04T13:30:00Z", status: "agendado", confirm_status: null, cancelamento_motivo: null, ...over }) as any;
const cards = [card(1), card(2, { unidade: "CSI 2", paciente_nome: "José" }), card(3, { vazio: true }), card(4, { atrasado: true }), card(5, { data_ref: "2026-11-20" })];
const mapa = agruparExames([ex(1), ex(2, { operadora: "SUS", procedimento: "US ABDOME" }), ex(3), ex(4), ex(5)]);
const f = (o: object) => filtrarCards(cards, mapa, { ...FILTROS_PADRAO, periodo: "hoje", ...o }, hoje).map((c) => c.id);
assert.deepEqual(f({}), [1, 2, 4]);                       // o vazio (3) fica oculto
assert.deepEqual(f({ mostrarVazios: true }), [1, 2, 3, 4]);
assert.deepEqual(f({ unidade: "CSI 2" }), [2]);
assert.deepEqual(f({ operadora: "SUS" }), [2]);
assert.deepEqual(f({ busca: "conceicao" }), [1, 4]);      // sem acento, sem maiúscula
assert.deepEqual(f({ busca: "us abdome" }), [2]);          // por exame
assert.deepEqual(f({ busca: "1002" }), [2]);               // por prontuário
assert.deepEqual(f({ busca: "M4" }), [4]);                 // por nº da marcação
assert.deepEqual(f({ soAtrasados: true }), [4]);
assert.deepEqual(f({ periodo: "30dias" }), [1, 2, 4, 5]);

// tarefas
const comTarefa = [card(1, { n_tarefas_abertas: 2 }), card(2), card(3, { n_tarefas_abertas: 1, n_tarefas_vencidas: 1 })];
assert.deepEqual(filtrarCards(comTarefa, mapa, { ...FILTROS_PADRAO, periodo: "hoje", soComTarefa: true }, hoje).map((c) => c.id), [1, 3]);
assert.ok(compararCartoes(card(1, { prioridade: 3 }), card(2), "a", "a") < 0);                        // prioridade 3 vem antes
assert.ok(compararCartoes(card(1), card(2), "2026-11-04T10", "2026-11-04T09") > 0);                    // mesma prioridade: o mais cedo primeiro
const ag = Date.parse("2026-11-04T15:00:00Z");                                                         // 12:00 em Brasília
assert.deepEqual(rotuloVencimento("2026-11-04T19:00:00Z", ag), { texto: "vence 16:00", vencida: false });
assert.deepEqual(rotuloVencimento("2026-11-05T12:00:00Z", ag), { texto: "vence amanhã 09:00", vencida: false });
assert.deepEqual(rotuloVencimento("2026-11-04T13:00:00Z", ag), { texto: "venceu há 2 h 00", vencida: true });
assert.deepEqual(rotuloVencimento("2026-11-09T12:00:00Z", ag), { texto: "vence 09/11 09:00", vencida: false });
assert.deepEqual(rotuloVencimento(null, ag), { texto: "", vencida: false });

// responsável
const comResp = [card(1, { responsavel: "u1" }), card(2, { responsavel: "u2" }), card(3), card(4, { responsavel: "u1" })];
const fr = (r: string) => filtrarCards(comResp, mapa, { ...FILTROS_PADRAO, periodo: "hoje", responsavel: r }, hoje, "u1").map((c) => c.id);
assert.deepEqual(fr(""), [1, 2, 3, 4]);
assert.deepEqual(fr("meus"), [1, 4]);
assert.deepEqual(fr("sem"), [3]);
assert.deepEqual(fr("u2"), [2]);

// mover à mão
const colunas = [
  { id: "confirmado", nome: "Confirmado", ordem: 5, etapa: "agendamento", origem: "klingo", sla_min: null },
  { id: "chegou", nome: "Chegou", ordem: 6, etapa: "depois", origem: "manual", sla_min: 30 },
  { id: "em_atendimento", nome: "Em atendimento", ordem: 7, etapa: "depois", origem: "klingo", sla_min: 120 },
  { id: "finalizado", nome: "Finalizado", ordem: 8, etapa: "depois", origem: "manual", sla_min: 30 },
] as any;
const trans = [{ de: "confirmado", para: "chegou" }, { de: "chegou", para: "finalizado" }, { de: "chegou", para: "em_atendimento" }];
assert.deepEqual(destinosPermitidos("confirmado", trans, colunas).map((c: any) => c.id), ["chegou"]);
assert.deepEqual(destinosPermitidos("chegou", trans, colunas).map((c: any) => c.id), ["finalizado"]);   // nunca para coluna do Klingo
assert.deepEqual(destinosPermitidos("finalizado", trans, colunas), []);
const mv = cartaoMovido(card(9, { coluna: "confirmado", atrasado: true, minutos_na_coluna: 50, versao: 3 }), colunas[1]);
assert.equal(mv.coluna, "chegou"); assert.equal(mv.versao, 4); assert.equal(mv.atrasado, false); assert.equal(mv.minutos_na_coluna, 0); assert.equal(mv.origem, "manual");
assert.equal(erroDeMover("CONFLITO: o card foi alterado por outra pessoa. Atualize a tela e tente de novo.").conflito, true);
assert.equal(erroDeMover("Movimento não permitido: de x para y.").conflito, false);
assert.equal(iniciais("Maria da Conceição"), "MC"); assert.equal(iniciais("ana"), "A"); assert.equal(iniciais(""), "?"); assert.equal(iniciais(null), "?");

// barra de atualização
const agora = Date.parse("2026-11-04T15:00:00Z");
const r = (o: object = {}) => ({ klingo_id: "13404", nome: "x", marcha: "ao_vivo", intervalo_min: 1, minimo_min: 1, ultima_leitura_em: "2026-11-04T14:59:30Z", proxima_leitura_em: "2026-11-04T15:00:30Z", ultimo_movimento_em: null, motivo_movimento: null, erros_seguidos: 0, em_expediente: true, agora: "", ...o }) as any;
assert.equal(estadoDoRelatorio(r(), agora), "ao_vivo");
assert.equal(estadoDoRelatorio(r({ proxima_leitura_em: "2026-11-04T14:55:00Z" }), agora), "atrasado");
assert.equal(estadoDoRelatorio(r({ proxima_leitura_em: "2026-11-04T14:58:00Z" }), agora), "ao_vivo");   // 2 min de folga ainda é normal
assert.equal(estadoDoRelatorio(r({ marcha: "dormindo", intervalo_min: 60, proxima_leitura_em: "2026-11-04T15:40:00Z" }), agora), "dormindo");
assert.equal(estadoDoRelatorio(r({ erros_seguidos: 2 }), agora), "erro");
assert.equal(estadoGeral([r({ marcha: "calmo", intervalo_min: 5, proxima_leitura_em: "2026-11-04T15:04:00Z" }), r({ erros_seguidos: 1 })], agora), "erro");
assert.equal(estadoGeral([r({ marcha: "dormindo", intervalo_min: 60, proxima_leitura_em: "2026-11-04T15:30:00Z" })], agora), "dormindo");
assert.equal(duracaoCurta(20), "20 s"); assert.equal(duracaoCurta(200), "3 min"); assert.equal(duracaoCurta(3900), "1 h 05");
assert.equal(segundosAte("2026-11-04T15:00:30Z", agora), 30);

// portal do paciente
assert.ok(tokenValido("a".repeat(64)) && tokenValido("0123456789abcdef".repeat(4)));
for (const ruim of ["", "abc", "a".repeat(63), "a".repeat(65), "A".repeat(64), "g".repeat(64), "../etc/passwd", " " + "a".repeat(63)]) assert.ok(!tokenValido(ruim), ruim);
assert.equal(urlDoPortal("https://csi.exemplo.com.br/", "abc"), "https://csi.exemplo.com.br/p/abc");
assert.equal(diaPorExtenso("2026-11-04"), "quarta-feira, 04/11");
assert.equal(mensagemDoLink("MARIA DA SILVA", "2026-11-04", "https://x/p/t"), "Olá, Maria! Aqui é a Clínica CSI. Para confirmar seu atendimento de 04/11 ou falar com a nossa equipe, acesse: https://x/p/t");
assert.ok(mensagemDoLink(null, "2026-11-04", "https://x/p/t").startsWith("Olá! Aqui"));
assert.ok(!mensagemDoLink("Maria", "2026-11-04", "u").toLowerCase().includes("exame"));                 // sem dado clínico na mensagem
const wa2 = linkWhatsAppComTexto("(11) 98888-7777", "Olá & tudo bem?");
assert.equal(wa2, "https://wa.me/5511988887777?text=Ol%C3%A1%20%26%20tudo%20bem%3F");
assert.equal(linkWhatsAppComTexto("123", "x"), null);
for (const m of ["desligado", "limite", "invalido", "indisponivel", "muitas", "tamanho", "qualquer"]) assert.ok(textoDoMotivo(m).length > 10 && !/erro|exception|sql/i.test(textoDoMotivo(m)), m);
console.log("JORNADA TS OK");
