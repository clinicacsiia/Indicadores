-- Coleta por mês para os relatórios dos painéis em Python (ver 20261014200000_coleta_mensal_colunas.sql).
-- Roda DEPOIS de a Edge Function com o modo mensal estar publicada (versão 13 ou mais nova).

-- 1. proximos_trabalhos agora devolve também pares (relatório, mês): periodo = dia 1 do mês. A consulta
-- do mês inteiro (e, se o Klingo cortar o resultado, dividida ao meio) é feita pela Edge Function.
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

-- 2. Relatórios dos painéis em Python: coletados por mês, como o painel pedia (primeiro mês, meses à frente
-- e meses revisados vêm dos relatorios.json de cada painel).
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 2 where klingo_id = '26';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '798';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 2 where klingo_id = '13280';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 2 where klingo_id = '13284';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 2 where klingo_id = '13285';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '13295';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 6, revisar_meses = null where klingo_id = '13297';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 3, revisar_meses = null where klingo_id = '13328';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '13329';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-06-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '13355';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '13375';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-02-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '13385';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-02-01', meses_a_frente = 0, revisar_meses = null where klingo_id = '13387';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 2 where klingo_id = '13402';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 1 where klingo_id = '13404';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-06-01', meses_a_frente = 6, revisar_meses = null where klingo_id = '13505';
update public.dim_relatorio set granularidade = 'mes', primeiro_mes = '2026-06-01', meses_a_frente = 6, revisar_meses = null where klingo_id = '13509';
