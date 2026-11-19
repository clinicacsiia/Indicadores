-- Coleta parada de 15/11 (08:25) até 19/11: o banco chegou a 478 MB e o freio de proximos_trabalhos (470 MB) parou tudo.
-- O selo "Atualizado em ..." das Metas (e dos outros painéis) congelava porque nenhum dado novo entrava.
--
-- Causa: inchaço (linhas mortas). Cada coleta substitui o mês/dia inteiro (apaga e regrava), e o autovacuum padrão
-- (20% da tabela) só passa depois de ~85 mil linhas mortas em fact_relatorio_linha. Em poucas horas de coleta o arquivo
-- crescia ~74 MB, e o VACUUM FULL só rodava aos domingos. Em 19/11 o VACUUM FULL manual devolveu esses 74 MB (478 -> 404 MB).
--
-- 1. Autovacuum bem mais frequente nas tabelas que mais regravam: o espaço morto é reaproveitado em vez de o arquivo crescer.
-- 2. Compactação (VACUUM FULL) todo dia às 03:00 (Brasília), não só aos domingos. Leva de 4 a 34 s por tabela nesse tamanho.
--    cron.schedule com o mesmo nome apenas troca o horário do job existente.
-- Não apaga nenhum dado.

alter table public.fact_relatorio_linha set (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_vacuum_cost_limit = 2000
);

alter table public.sync_relatorio_runs set (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_vacuum_cost_limit = 2000
);

alter table public.painel_dados set (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_vacuum_threshold = 50
);

alter table public.painel_pagina set (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_vacuum_threshold = 10
);

select cron.schedule('compactar-sync-relatorio-runs',   '0 6 * * *',  $cmd$ vacuum full public.sync_relatorio_runs $cmd$);
select cron.schedule('compactar-fact-relatorio-linha',  '10 6 * * *', $cmd$ vacuum full public.fact_relatorio_linha $cmd$);
select cron.schedule('compactar-painel-dados',          '20 6 * * *', $cmd$ vacuum full public.painel_dados $cmd$);
