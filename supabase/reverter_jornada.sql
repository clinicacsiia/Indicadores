-- Remove do Supabase do Indicadores tudo o que foi criado em 01/11/2026 para a "Jornada" (que foi feita aqui por engano e pertence ao projeto webchat).
-- RODE NO SQL EDITOR DO SUPABASE (projeto syhcvonwthtqalpjcmtj): o MCP não executa comandos que apagam (ver CLAUDE.md).
-- O código e as migrations continuam no histórico do Git (commits d1e416f a 3abc47f) e serviram de base para levar a Jornada ao webchat.
--
-- Conferido em 01/11/2026 por uma "prova seca": só pega 19 tabelas, 1 visão e 40 funções criadas hoje; nenhuma tabela ou função anterior tem esses nomes.
-- Já foi feito antes, pelo MCP: os 4 crons foram desligados, proximos_trabalhos voltou à versão original, o gatilho sync_relatorio_runs_ritmo foi desabilitado
-- e a Edge Function sync-relatorios-dw voltou ao código original (v17). Este script termina o serviço. Não mexe em dim_relatorio, fact_relatorio_linha nem sync_relatorio_runs.

-- 1) PROVA SECA: o que será apagado (rode só este SELECT primeiro e confira)
select 'tabela' as tipo, relname::text as nome from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r', 'p')
  and (relname like 'jornada\_%' or relname in ('coleta_ritmo', 'coleta_ritmo_config', 'portal_tentativa'))
union all select 'visao', relname::text from pg_class where relnamespace = 'public'::regnamespace and relkind = 'v' and relname = 'v_jornada_quadro'
union all select 'funcao', p.oid::regprocedure::text from pg_proc p where p.pronamespace = 'public'::regnamespace
  and (p.proname like 'jornada\_%' or p.proname in ('portal_resolver', 'portal_bloqueado', 'portal_ver', 'portal_confirmar', 'portal_remarcar', 'portal_enviar_mensagem',
       'coleta_em_expediente', 'coleta_proximo_expediente', 'coleta_ritmo_proximo', 'coleta_ritmo_registrar', 'acordar_coleta', 'status_ritmo_coleta', 'proximos_trabalhos_ritmo'))
order by 1, 2;

-- 2) APAGAR
do $$
declare
  r record;
begin
  -- crons (se algum ainda existir)
  perform cron.unschedule(jobname) from cron.job where jobname in ('coleta-ritmo-1min', 'jornada-sincronizar', 'jornada-regras', 'jornada-pendencias-diaria');

  -- gatilho e política que ficaram penduradas em objetos que não são nossos
  drop trigger if exists sync_relatorio_runs_ritmo on public.sync_relatorio_runs;
  if to_regclass('realtime.messages') is not null then
    drop policy if exists "jornada_canais_leitura" on realtime.messages;
  end if;

  -- avisos da Jornada na aba Avisos (o histórico deles cai junto)
  delete from public.aviso where escopo = 'jornada';

  drop view if exists public.v_jornada_quadro;

  for r in select relname from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r', 'p')
           and (relname like 'jornada\_%' or relname in ('coleta_ritmo', 'coleta_ritmo_config', 'portal_tentativa')) loop
    execute format('drop table if exists public.%I cascade', r.relname);
  end loop;

  for r in select p.oid::regprocedure as f from pg_proc p where p.pronamespace = 'public'::regnamespace
           and (p.proname like 'jornada\_%' or p.proname in ('portal_resolver', 'portal_bloqueado', 'portal_ver', 'portal_confirmar', 'portal_remarcar', 'portal_enviar_mensagem',
                'coleta_em_expediente', 'coleta_proximo_expediente', 'coleta_ritmo_proximo', 'coleta_ritmo_registrar', 'acordar_coleta', 'status_ritmo_coleta', 'proximos_trabalhos_ritmo')) loop
    execute format('drop function if exists %s cascade', r.f);
  end loop;
end $$;

-- 3) CONFERIR: tudo deve voltar vazio (0 linhas)
select relname from pg_class where relnamespace = 'public'::regnamespace and (relname like 'jornada\_%' or relname like 'coleta\_ritmo%' or relname = 'portal_tentativa' or relname = 'v_jornada_quadro')
union all select proname from pg_proc where pronamespace = 'public'::regnamespace and (proname like 'jornada\_%' or proname like 'portal\_%' or proname in ('acordar_coleta', 'status_ritmo_coleta', 'proximos_trabalhos_ritmo'));
