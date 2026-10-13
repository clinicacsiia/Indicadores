-- Metas: cada linha devolvida por metas_atendimentos_mes() passa a trazer o dia do
-- atendimento ("dia"), para o site montar o gráfico dia a dia (ritmo do mês) e a
-- comparação com o mesmo ponto do mês anterior, como no painel local.
-- Mesmas regras de antes; só o agrupamento ganhou o dia.

create or replace function public.metas_atendimentos_mes(p_mes text)
returns jsonb
language plpgsql
security definer
set search_path = ''
stable
as $$
declare
  v_rel uuid;
  v_de date;
  v_ate date;
  v_id text;
  v_unidade text;
  v_classes text;
  v_esp text;
  v_proc text;
  v_oper text;
  v_linhas jsonb;
  v_sync timestamptz;
  v_dia date;
  v_dias integer;
begin
  if not public.can_view_metas() then
    raise exception 'Sem permissão para ver Metas' using errcode = '42501';
  end if;
  if p_mes is null or p_mes !~ '^\d{4}-(0[1-9]|1[0-2])$' then
    raise exception 'Mês inválido: use AAAA-MM' using errcode = '22023';
  end if;

  v_de := (p_mes || '-01')::date;
  v_ate := (v_de + interval '1 month')::date;

  select id into v_rel from public.dim_relatorio where klingo_id = '13339';
  if v_rel is null then
    return jsonb_build_object('mapeado', false);
  end if;

  select
    max(coluna_key) filter (where titulo_klingo = 'Exames Realizados'),
    max(coluna_key) filter (where titulo_klingo = 'Unidade'),
    max(coluna_key) filter (where titulo_klingo = 'Procedimento - Classes'),
    max(coluna_key) filter (where titulo_klingo = 'Especialidade'),
    max(coluna_key) filter (where titulo_klingo = 'Procedimento'),
    max(coluna_key) filter (where titulo_klingo in ('Operadora', 'Convênio'))
  into v_id, v_unidade, v_classes, v_esp, v_proc, v_oper
  from public.dim_relatorio_coluna
  where relatorio_id = v_rel;

  -- Convênio é opcional; as demais colunas as regras das metas exigem.
  if v_id is null or v_unidade is null or v_classes is null or v_esp is null or v_proc is null then
    return jsonb_build_object('mapeado', false);
  end if;

  with ultimo_sync as (
    select periodo, max(started_at) as inicio
    from public.sync_relatorio_runs
    where relatorio_id = v_rel
      and status = 'success'
      and periodo >= v_de and periodo < v_ate
    group by periodo
  ),
  vigentes as (
    select distinct on (f.linha ->> v_id)
      f.periodo as dia,
      f.linha ->> v_unidade as unidade,
      f.linha ->> v_classes as classes,
      f.linha ->> v_esp as especialidade,
      f.linha ->> v_proc as procedimento,
      case when v_oper is null then null else f.linha ->> v_oper end as operadora
    from public.fact_relatorio_linha f
    left join ultimo_sync u on u.periodo = f.periodo
    where f.relatorio_id = v_rel
      and f.periodo >= v_de and f.periodo < v_ate
      and (f.linha ->> v_id) is not null
      and (u.inicio is null or f.last_seen_at >= u.inicio)
    order by f.linha ->> v_id, f.last_seen_at desc
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'dia', dia,
           'unidade', unidade,
           'classes', classes,
           'especialidade', especialidade,
           'procedimento', procedimento,
           'operadora', operadora,
           'qtd', qtd
         )), '[]'::jsonb)
  into v_linhas
  from (
    select dia, unidade, classes, especialidade, procedimento, operadora, count(*) as qtd
    from vigentes
    group by dia, unidade, classes, especialidade, procedimento, operadora
  ) t;

  select max(finished_at), max(periodo), count(distinct periodo)
  into v_sync, v_dia, v_dias
  from public.sync_relatorio_runs
  where relatorio_id = v_rel
    and status = 'success'
    and periodo >= v_de and periodo < v_ate;

  return jsonb_build_object(
    'mapeado', true,
    'convenio', v_oper is not null,
    'linhas', v_linhas,
    'ultimo_sync', v_sync,
    'ultimo_dia', v_dia,
    'dias_sincronizados', coalesce(v_dias, 0)
  );
end;
$$;

revoke execute on function public.metas_atendimentos_mes(text) from public, anon;
grant execute on function public.metas_atendimentos_mes(text) to authenticated;
