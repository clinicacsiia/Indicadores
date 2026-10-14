-- Aba "Metas": filtro por período livre (datas exatas) além do filtro por mês.
--
-- metas_atendimentos_periodo(de, ate) faz o mesmo que metas_atendimentos_mes(mês) — mesmas regras de
-- contagem (cada atendimento conta uma vez, pela versão mais recente; só entra o que foi visto no último
-- sync do dia; mesma permissão "Pode ver Metas") —, mas para os dias de `p_de` a `p_ate`, inclusive.
-- O site usa esta função quando o período escolhido não é um mês inteiro; mês inteiro continua usando
-- metas_atendimentos_mes.
create or replace function public.metas_atendimentos_periodo(p_de date, p_ate date)
returns jsonb
language plpgsql
security definer
set search_path = ''
stable
as $$
declare
  v_rel uuid;
  v_fim date;
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
  if p_de is null or p_ate is null or p_ate < p_de or p_ate - p_de > 400 then
    raise exception 'Período inválido: informe De e Até (no máximo 400 dias)' using errcode = '22023';
  end if;

  v_fim := p_ate + 1;

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

  if v_id is null or v_unidade is null or v_classes is null or v_esp is null or v_proc is null then
    return jsonb_build_object('mapeado', false);
  end if;

  with ultimo_sync as (
    select periodo, max(started_at) as inicio
    from public.sync_relatorio_runs
    where relatorio_id = v_rel
      and status = 'success'
      and periodo >= p_de and periodo < v_fim
    group by periodo
  ),
  vigentes as (
    select distinct on (f.linha ->> v_id)
      f.linha ->> v_unidade as unidade,
      f.linha ->> v_classes as classes,
      f.linha ->> v_esp as especialidade,
      f.linha ->> v_proc as procedimento,
      case when v_oper is null then null else f.linha ->> v_oper end as operadora
    from public.fact_relatorio_linha f
    left join ultimo_sync u on u.periodo = f.periodo
    where f.relatorio_id = v_rel
      and f.periodo >= p_de and f.periodo < v_fim
      and (f.linha ->> v_id) is not null
      and (u.inicio is null or f.last_seen_at >= u.inicio)
    order by f.linha ->> v_id, f.last_seen_at desc
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'unidade', unidade,
           'classes', classes,
           'especialidade', especialidade,
           'procedimento', procedimento,
           'operadora', operadora,
           'qtd', qtd
         )), '[]'::jsonb)
  into v_linhas
  from (
    select unidade, classes, especialidade, procedimento, operadora, count(*) as qtd
    from vigentes
    group by unidade, classes, especialidade, procedimento, operadora
  ) t;

  select max(finished_at), max(periodo), count(distinct periodo)
  into v_sync, v_dia, v_dias
  from public.sync_relatorio_runs
  where relatorio_id = v_rel
    and status = 'success'
    and periodo >= p_de and periodo < v_fim;

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

revoke execute on function public.metas_atendimentos_periodo(date, date) from public, anon;
grant execute on function public.metas_atendimentos_periodo(date, date) to authenticated;
