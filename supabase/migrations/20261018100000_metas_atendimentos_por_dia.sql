-- Aba "Metas": atendimentos contados DIA A DIA, para o gráfico de linha da comparação "com SUS × só pagante".
--
-- metas_atendimentos_periodo(de, ate) devolve o período inteiro somado. Esta função devolve as mesmas linhas, com a mesma regra
-- (cada atendimento conta uma vez, pela versão mais recente; só entra o que foi visto na última coleta bem-sucedida do dia; mesma
-- permissão "Pode ver Metas"), mas separadas por dia (`dia`), para o site desenhar a evolução acumulada e a participação do pagante.
-- Só leitura; não muda nenhuma tabela.
create or replace function public.metas_atendimentos_por_dia(p_de date, p_ate date)
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
      f.periodo as dia,
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

  return jsonb_build_object(
    'mapeado', true,
    'convenio', v_oper is not null,
    'linhas', v_linhas
  );
end;
$$;

revoke execute on function public.metas_atendimentos_por_dia(date, date) from public, anon;
grant execute on function public.metas_atendimentos_por_dia(date, date) to authenticated;
