-- Limpeza semanal de espaço (plano gratuito do Supabase = 500 MB).
-- Em 11/11 a coleta ficou parada desde 05/11 porque o banco passou de 470 MB (freio de proximos_trabalhos):
-- ~107 MB eram linhas mortas (inchaço) das tabelas que mais recebem atualização. VACUUM FULL devolve esse espaço ao disco.
-- Roda aos domingos, de madrugada (horário de Brasília), um job por tabela porque o pg_cron só aceita VACUUM como comando único.
-- Não apaga dado nenhum: só recompacta as tabelas (o bloqueio dura segundos nesse tamanho).
select cron.schedule('compactar-sync-relatorio-runs', '0 6 * * 0',  $cmd$ vacuum full public.sync_relatorio_runs $cmd$);
select cron.schedule('compactar-fact-relatorio-linha', '10 6 * * 0', $cmd$ vacuum full public.fact_relatorio_linha $cmd$);
select cron.schedule('compactar-painel-dados',          '20 6 * * 0', $cmd$ vacuum full public.painel_dados $cmd$);
