-- Ritmo da coleta: o dia de hoje de cada relatório é refeito no máximo a cada 5 horas
-- (p_frescor_minutos = 300). O botão "Atualizar tudo" pede um frescor menor (10 min) e por isso
-- refaz tudo que tiver mais de 10 minutos, para qualquer pessoa logada. Dias passados já
-- completos nunca são refeitos. O pg_cron só "puxa" o lote a cada 5 minutos: se nada está
-- vencido, a Edge Function responde na hora sem tocar no Klingo.
drop function if exists public.proximos_trabalhos(integer);

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
    select id, klingo_id, periodicidade, janela_dias
    from public.dim_relatorio
    where ativo and supersedido_por is null and (pausado_ate is null or pausado_ate <= now())
  ),
  pares as (
    select r.id, r.klingo_id, r.periodicidade, g::date as periodo, h.d as hoje
    from rel r
    cross join hoje h
    cross join lateral generate_series(
      (case when r.periodicidade = 'pontual' then h.d else h.d - (r.janela_dias - 1) end)::timestamp,
      h.d::timestamp,
      interval '1 day'
    ) g
  ),
  pendentes as (
    select p.*
    from pares p
    where
      case when p.periodicidade = 'pontual'
        then not exists (
          select 1 from public.sync_relatorio_runs s where s.relatorio_id = p.id and s.status = 'success'
        )
        else not exists (
          select 1 from public.sync_relatorio_runs s
          where s.relatorio_id = p.id and s.periodo = p.periodo and s.status = 'success'
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
  )
  select id, klingo_id, periodo, count(*) over ()
  from pendentes
  order by (periodo = hoje) desc, periodo desc, klingo_id
  limit greatest(least(p_limite, 100), 1);
$$;

revoke execute on function public.proximos_trabalhos(integer, integer) from public, anon, authenticated;
grant execute on function public.proximos_trabalhos(integer, integer) to service_role;
