-- #13404 (Fluxo na Recepção) tem meses de 32 mil linhas: a Edge Function morria ao processar um mês inteiro (limite de CPU por chamada).
-- Passa a ser coletado dia a dia (~1 000 linhas por pedido); a coleta mensal dele é descartada (nada é apagado) para o banco refazer os dias.
-- Além disso, coleta que morre no meio 2 vezes em 3 h espera, em vez de derrubar o lote inteiro a cada 5 minutos.
update public.sync_relatorio_runs
set status = 'error', error_message = 'troca de granularidade: coleta mensal descartada'
where relatorio_id = (select id from public.dim_relatorio where klingo_id = '13404')
  and status in ('success', 'running')
  and periodo = date_trunc('month', periodo)::date;

update public.dim_relatorio set granularidade = 'dia', janela_dias = 90 where klingo_id = '13404';

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
    where r.granularidade is distinct from 'mes'
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
  todos as (
    select * from pend_dia
    union all
    select * from pend_mes
  )
  select id, klingo_id, periodo, count(*) over ()
  from todos
  order by atual desc, periodo desc, klingo_id
  limit greatest(least(p_limite, 100), 1);
$$;
