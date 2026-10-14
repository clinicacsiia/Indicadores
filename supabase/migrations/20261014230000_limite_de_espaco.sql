-- Contenção de espaço (plano gratuito do Supabase = 500 MB; o banco já estava em 184 MB e a coleta ainda ia crescer).
--
-- 1. Relatórios SEM filtro de data (#13374 guias, #13376 baixas, #13434): vinham inteiros e eram guardados uma cópia por DIA
--    (~8 MB/dia só o #13374). Agora a granularidade é 'snapshot': uma consulta a cada 5 h, sempre no mesmo periodo (2000-01-01),
--    então a deduplicação por hash só acrescenta o que MUDOU. As cópias diárias antigas saem na poda abaixo.
-- 2. #13404 só é usado pelo painel desde setembro: janela de 46 dias em vez de 90.
-- 3. Poda diária (pg_cron): relatórios por dia saem da tabela depois de janela_dias + 3 dias, exceto os marcados reter_sempre
--    (#13339 Metas e #13397, lidos pelo site por mês). Linhas de relatório mensal não são podadas.
-- 4. Freio de emergência em proximos_trabalhos: acima de 470 MB a coleta para sozinha.

alter table public.dim_relatorio add column if not exists reter_sempre boolean not null default false;
comment on column public.dim_relatorio.reter_sempre is 'true = a poda diária não apaga as linhas deste relatório (o site lê o histórico dele por mês).';

update public.dim_relatorio set reter_sempre = true where klingo_id in ('13339', '13397');
update public.dim_relatorio set granularidade = 'snapshot' where klingo_id in ('13374', '13376', '13434');
update public.dim_relatorio set janela_dias = 46 where klingo_id = '13404';

create or replace function public.proximos_trabalhos(p_limite integer default 30, p_frescor_minutos integer default 300)
returns table (relatorio_id uuid, klingo_id text, periodo date, restantes bigint)
language sql
security invoker
stable
set search_path = ''
as $$
  with hoje as (
    select (now() at time zone 'America/Sao_Paulo')::date as d
  ),
  rel as (
    select id, klingo_id, periodicidade, granularidade, primeiro_mes, meses_a_frente, revisar_meses,
      case when filtro_periodo is null or periodo_validado_em is null then 1 else janela_dias end as janela,
      (filtro_periodo is not null and periodo_validado_em is null) as a_comprovar
    from public.dim_relatorio
    where ativo and supersedido_por is null and (pausado_ate is null or pausado_ate <= now())
      -- freio de emergência: perto do limite do plano (500 MB) a coleta para para não deixar o banco só-leitura
      and pg_database_size(current_database()) < 470000000
  ),
  pares_dia as (
    select r.id, r.klingo_id, r.periodicidade, r.a_comprovar, g::date as periodo, h.d as hoje
    from rel r
    cross join hoje h
    cross join lateral generate_series(
      (case when r.periodicidade = 'pontual' then h.d else h.d - (r.janela - 1) end)::timestamp,
      h.d::timestamp,
      interval '1 day'
    ) g
    where coalesce(r.granularidade, 'dia') = 'dia'
  ),
  pend_dia as (
    select p.id, p.klingo_id, p.periodo, (p.periodo = p.hoje) as atual
    from pares_dia p
    where
      case when p.periodicidade = 'pontual'
        then not exists (
          select 1 from public.sync_relatorio_runs s where s.relatorio_id = p.id and s.status = 'success'
        )
        else not exists (
          select 1 from public.sync_relatorio_runs s
          where s.relatorio_id = p.id and s.periodo = p.periodo and s.status = 'success'
            and not (p.a_comprovar and p.periodo = p.hoje)
            and (s.finished_at at time zone 'America/Sao_Paulo')::date > p.periodo
            and (p.periodo < p.hoje
                 or s.finished_at > now() - make_interval(mins => greatest(p_frescor_minutos, 1)))
        )
      end
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = p.id and s.periodo = p.periodo
          and ((s.status = 'running' and s.started_at > now() - interval '5 minutes')
            or (s.status = 'error' and s.started_at > now() - interval '30 minutes'))
      )
      -- coleta que morreu no meio (ficou "running" e nunca terminou) 2 vezes em 3 h: espera, para nao derrubar o lote todo de novo
      and (select count(*) from public.sync_relatorio_runs s
           where s.relatorio_id = p.id and s.periodo = p.periodo and s.status = 'running'
             and s.started_at < now() - interval '5 minutes' and s.started_at > now() - interval '3 hours') < 2
  ),
  pares_mes as (
    select r.id, r.klingo_id, r.revisar_meses, r.a_comprovar, g::date as periodo, h.d as hoje
    from rel r
    cross join hoje h
    cross join lateral generate_series(
      (case when r.a_comprovar or r.primeiro_mes is null then date_trunc('month', h.d::timestamp) else r.primeiro_mes::timestamp end),
      date_trunc('month', h.d::timestamp) + make_interval(months => r.meses_a_frente),
      interval '1 month'
    ) g
    where r.granularidade = 'mes'
  ),
  pend_mes as (
    select m.id, m.klingo_id, m.periodo, (m.periodo = date_trunc('month', m.hoje::timestamp)::date) as atual
    from pares_mes m
    where not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = m.id and s.periodo = m.periodo and s.status = 'success'
          and not (m.a_comprovar and m.periodo = date_trunc('month', m.hoje::timestamp)::date)
          and (
            case when m.periodo >= (date_trunc('month', m.hoje::timestamp) - make_interval(months => coalesce(m.revisar_meses, 2)))::date
              -- mês recente ou futuro: refeito quando o frescor vence
              then s.finished_at > now() - make_interval(mins => greatest(p_frescor_minutos, 1))
              -- mês antigo: uma vez só (revisar_meses definido) ou 1 vez por dia (revisar_meses vazio)
              else (m.revisar_meses is not null or s.finished_at > now() - interval '24 hours')
            end
          )
      )
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = m.id and s.periodo = m.periodo
          and ((s.status = 'running' and s.started_at > now() - interval '5 minutes')
            or (s.status = 'error' and s.started_at > now() - interval '30 minutes'))
      )
      and (select count(*) from public.sync_relatorio_runs s
           where s.relatorio_id = m.id and s.periodo = m.periodo and s.status = 'running'
             and s.started_at < now() - interval '5 minutes' and s.started_at > now() - interval '3 hours') < 2
  ),
  pend_snap as (
    select r.id, r.klingo_id, date '2000-01-01' as periodo, true as atual
    from rel r
    where r.granularidade = 'snapshot'
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = r.id and s.periodo = date '2000-01-01' and s.status = 'success'
          and s.finished_at > now() - make_interval(mins => greatest(p_frescor_minutos, 1))
      )
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = r.id and s.periodo = date '2000-01-01'
          and ((s.status = 'running' and s.started_at > now() - interval '5 minutes')
            or (s.status = 'error' and s.started_at > now() - interval '30 minutes'))
      )
      and (select count(*) from public.sync_relatorio_runs s
           where s.relatorio_id = r.id and s.periodo = date '2000-01-01' and s.status = 'running'
             and s.started_at < now() - interval '5 minutes' and s.started_at > now() - interval '3 hours') < 2
  ),
  todos as (
    select * from pend_dia
    union all
    select * from pend_mes
    union all
    select * from pend_snap
  )
  select id, klingo_id, periodo, count(*) over ()
  from todos
  order by atual desc, periodo desc, klingo_id
  limit greatest(least(p_limite, 100), 1);
$$;

create or replace function public.podar_linhas_antigas()
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v_dia bigint;
  v_snap bigint;
  v_hoje date := (now() at time zone 'America/Sao_Paulo')::date;
  v_bytes bigint := pg_database_size(current_database());
begin
  -- relatórios por dia: fora da janela (3 dias de folga)
  with del as (
    delete from public.fact_relatorio_linha f
    using public.dim_relatorio r
    where r.id = f.relatorio_id
      and r.granularidade = 'dia' and not r.reter_sempre
      and r.periodicidade is distinct from 'pontual' and r.filtro_periodo is not null
      and f.periodo < v_hoje - (r.janela_dias + 3)
    returning 1
  )
  select count(*) into v_dia from del;

  -- snapshot: cópias diárias antigas, só depois de existir o snapshot de periodo fixo
  with del as (
    delete from public.fact_relatorio_linha f
    using public.dim_relatorio r
    where r.id = f.relatorio_id
      and r.granularidade = 'snapshot'
      and f.periodo <> date '2000-01-01'
      and exists (select 1 from public.sync_relatorio_runs s
                  where s.relatorio_id = r.id and s.periodo = date '2000-01-01' and s.status = 'success')
    returning 1
  )
  select count(*) into v_snap from del;

  if v_bytes > 400000000 then
    perform public.registrar_alerta(
      'sync_erro', 'erro', 'espaco_banco',
      'O banco passou de 400 MB (limite do plano gratuito: 500 MB). A coleta para sozinha aos 470 MB. Reduza janela_dias dos relatórios por dia ou apague linhas antigas.',
      null, null, v_hoje, jsonb_build_object('bytes', v_bytes), false);
  end if;

  return jsonb_build_object('podadas_por_dia', v_dia, 'snapshots_antigos', v_snap, 'banco_mb', v_bytes / 1048576);
end;
$$;

revoke execute on function public.podar_linhas_antigas() from public, anon, authenticated;
grant execute on function public.podar_linhas_antigas() to service_role;

select cron.schedule('poda-linhas-antigas', '30 8 * * *', $cmd$ select public.podar_linhas_antigas(); $cmd$);
