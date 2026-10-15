-- Aba "Avisos": correção de uma justificativa postada no aviso errado, com registro no histórico.
--
-- Em 14/10/2026, 22:03, o administrador (csiadmin) justificou o aviso "Quase nada de convênio aparece como recebido" (Setembro/2026) com a nota da
-- atualização PR#36 ("Prazo por convênio aprendido do histórico..."), que era do aviso "Faturas esperando envio há mais de 7 dias". Agora:
--   * o aviso de convênio recebido volta a ficar ABERTO, sem a justificativa (o selo "Reaberto 1×" de antes continua: ele vem da justificativa do dia 14);
--   * a nota passa para o histórico de "Faturas esperando envio" (a justificativa e a data prevista de 20/10/2026 de quem justificou antes ficam como estão);
--   * nos dois históricos entra um evento "correcao" explicando o que foi feito (a linha original do histórico não é apagada).
-- Ganha também o tipo de evento 'correcao'. Roda uma vez: só mexe se o aviso ainda estiver com a justificativa errada.

alter table public.aviso_evento drop constraint if exists aviso_evento_tipo_check;
alter table public.aviso_evento add constraint aviso_evento_tipo_check
  check (tipo in ('detectado', 'sumiu', 'justificado', 'confirmado', 'reapareceu', 'nao_corrigido', 'piorou', 'reaberto', 'informado', 'prazo_vencido', 'atualizacao', 'correcao'));

with errado as (
  select id, painel, justificativa, justificado_por, justificado_em
  from public.aviso
  where painel = 'faturamento' and chave = '2026-09|fat_pouco_recebido' and status = 'justificado'
    and justificado_por = 'csiadmin@csi.local' and justificativa like 'Resolvido na atualização PR#36%'
  for update
),
reaberto as (
  update public.aviso a
     set status = 'aberto', justificativa = null, justificado_por = null, justificado_em = null, justificado_versao = null, justificado_nivel = null,
         justificado_itens = null, previsto_para = null, justificativa_vale = false, em_informacao = false
  from errado e
  where a.id = e.id
  returning a.id, a.painel, a.itens_total, e.justificativa as texto, e.justificado_por as usuario, e.justificado_em as quando
),
no_errado as (
  insert into public.aviso_evento (aviso_id, painel, tipo, usuario, detalhe, itens_total)
  select id, painel, 'correcao', usuario,
         'Correção: a justificativa de ' || to_char(quando at time zone 'America/Sao_Paulo', 'DD/MM/YYYY, HH24:MI')
         || ' (nota da atualização PR#36) foi postada neste aviso por engano e era de “Faturas esperando envio há mais de 7 dias”. '
         || 'Ela foi retirada daqui e movida para lá; este aviso volta a ficar aberto para ser justificado.', itens_total
  from reaberto
  returning 1
)
insert into public.aviso_evento (aviso_id, painel, tipo, usuario, detalhe, itens_total)
select dest.id, dest.painel, 'correcao', r.usuario,
       'Correção: a nota abaixo, da atualização PR#36, foi escrita em ' || to_char(r.quando at time zone 'America/Sao_Paulo', 'DD/MM/YYYY, HH24:MI')
       || ' no aviso “Quase nada de convênio aparece como recebido” por engano e foi movida para cá. A justificativa e a data prevista de quem fechou este aviso continuam valendo.'
       || E'\n' || r.texto,
       dest.itens_total
from reaberto r
join public.aviso dest on dest.painel = 'faturamento' and dest.chave = '|fat_espera_envio';
