-- O site ficava lento e a agenda do CRM Ressonância voltava a falhar ("canceling statement due to statement timeout") mesmo depois de
-- 20261024140000: a função sozinha leva ~0,3 s, mas passava de 8 s quando o banco estava ocupado com a coleta do Klingo.
--
-- Quem mais ocupava o banco era `proximos_trabalhos`, chamada pela coleta automática (cron a cada 5 min): ~5 s e 472 mil blocos lidos
-- por chamada, porque cada "not exists" em `sync_relatorio_runs` (~97 mil linhas) filtra por (relatorio_id, periodo, status) e o único
-- índice era (relatorio_id, started_at): para cada par relatório/dia ela relia todas as execuções daquele relatório.
-- Com este índice: ~0,2 s e 46 mil blocos. `status_coleta_relatorios` (tela Início, refeita a cada 10–60 s) e
-- `v_relatorio_linha_vigente` (o "último sucesso" de cada período) também passam a usá-lo.
create index if not exists sync_relatorio_runs_rel_periodo_status_idx
  on public.sync_relatorio_runs (relatorio_id, periodo, status, finished_at desc);

analyze public.sync_relatorio_runs;
