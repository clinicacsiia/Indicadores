-- Limpeza do histórico da coleta, para o banco crescer mais devagar. RODE NO SQL EDITOR DO SUPABASE (o MCP não apaga linhas: ver CLAUDE.md).
-- Peça antes de rodar: apagar linhas antigas tira a "memória" do que o Klingo já mostrou (as versões antigas de cada linha). Os painéis e o quadro leem só a
-- última leitura de cada período (v_relatorio_linha_vigente), então não mudam. Relatórios com dim_relatorio.reter_sempre = true NUNCA são tocados.
--
-- Números de 01/11/2026 (banco em 424 MB; o freio da coleta está em 470 MB; ~1 MB de crescimento por dia):
--   versões antigas (substituídas há mais de 14 dias): ~35 mil linhas, ~16 MB de dados
--   execuções antigas da coleta: ~33,8 mil de 137,9 mil linhas, ~10 MB
-- O espaço apagado volta a ser usado por dados novos (o banco para de crescer por um bom tempo), mas o tamanho no painel só ENCOLHE com VACUUM FULL.
-- ATENÇÃO: NÃO rode VACUUM FULL em fact_relatorio_linha (precisa de uma cópia temporária de ~300 MB e passaria dos 500 MB do plano). No sync_relatorio_runs pode (43 MB).

-- 1) VER quanto sai, por relatório (não apaga nada)
with ultimo as (
  select relatorio_id, periodo, max(started_at) as ini from public.sync_relatorio_runs where status = 'success' group by 1, 2
)
select r.klingo_id, left(r.nome, 45) as relatorio, r.reter_sempre, count(*) as versoes_antigas, pg_size_pretty(sum(pg_column_size(f.linha) + 100)::bigint) as aprox
from public.fact_relatorio_linha f
join public.dim_relatorio r on r.id = f.relatorio_id
join ultimo u on u.relatorio_id = f.relatorio_id and u.periodo = f.periodo
where f.last_seen_at < u.ini and f.last_seen_at < now() - interval '14 days'
group by 1, 2, 3 order by sum(pg_column_size(f.linha)) desc;

-- 2) APAGAR as versões substituídas há mais de 14 dias (só de relatórios sem reter_sempre)
delete from public.fact_relatorio_linha f
using public.dim_relatorio r,
      (select relatorio_id, periodo, max(started_at) as ini from public.sync_relatorio_runs where status = 'success' group by 1, 2) u
where r.id = f.relatorio_id
  and not coalesce(r.reter_sempre, false)
  and u.relatorio_id = f.relatorio_id and u.periodo = f.periodo
  and f.last_seen_at < u.ini
  and f.last_seen_at < now() - interval '14 days';

-- 3) APAGAR execuções antigas da coleta (guarda a última de sucesso de cada período, que é o que define a leitura vigente)
delete from public.sync_relatorio_runs s
where s.started_at < now() - interval '14 days'
  and s.id not in (select distinct on (relatorio_id, periodo) id from public.sync_relatorio_runs where status = 'success' order by relatorio_id, periodo, started_at desc);

-- 4) Liberar o espaço para reuso (rápido, não trava) e, só na tabela pequena, devolver ao sistema (trava a tabela por segundos: faça fora do horário)
vacuum (analyze) public.fact_relatorio_linha;
vacuum (full, analyze) public.sync_relatorio_runs;

-- 5) Conferir
select pg_size_pretty(pg_database_size(current_database())) as banco, pg_size_pretty(pg_total_relation_size('public.fact_relatorio_linha')) as fact, pg_size_pretty(pg_total_relation_size('public.sync_relatorio_runs')) as runs;
