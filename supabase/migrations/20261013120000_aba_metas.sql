-- Aba "Metas": acompanhamento das metas mensais por unidade/procedimento, a
-- partir do relatório #13339 do Klingo ("Atendimentos - Acompanhamento de
-- Metas por Unidade e Procedimento - Mensal"), que já é sincronizado para
-- fact_relatorio_linha pela Edge Function sync-relatorios-dw.
--
-- O que muda aqui:
-- 1) dim_relatorio_coluna.titulo_klingo — título que o próprio Klingo dá a cada
--    coluna ("Unidade", "Procedimento"…). A Edge Function passa a gravá-lo a
--    cada sync. É separado de `rotulo` de propósito: `rotulo` continua sendo
--    preenchido só por uma pessoa; `titulo_klingo` é o dado cru do Klingo.
-- 2) can_view_metas() — permissão "Pode ver Metas" (permissions.metas),
--    no mesmo molde de can_view_relatorios().
-- 3) metas_atendimentos_mes(mês) — devolve os atendimentos do mês já contados
--    por unidade/classe/especialidade/procedimento/convênio. As regras das
--    metas (metas.json) ficam no app; o banco só entrega a contagem.

alter table public.dim_relatorio_coluna
  add column if not exists titulo_klingo text;

comment on column public.dim_relatorio_coluna.titulo_klingo is 'Título da coluna como o Klingo devolve (result.columns[].title). Gravado automaticamente pelo sync; ao contrário de `rotulo`, não é decisão humana.';

-- Admin sempre vê Metas; viewer só se permissions.metas não for false.
create or replace function public.can_view_metas()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin' or coalesce((permissions ->> 'metas')::boolean, true))
  );
$$;

revoke execute on function public.can_view_metas() from public, anon;
grant execute on function public.can_view_metas() to authenticated;

-- Atendimentos de um mês ("AAAA-MM") do relatório #13339.
--
-- Por que uma função e não um select direto em fact_relatorio_linha: a tabela
-- guarda histórico (linha que mudou de conteúdo vira outra linha, nada é
-- apagado), então contar linhas cruas contaria o mesmo atendimento duas vezes
-- ou manteria um atendimento que o Klingo já removeu. Aqui valem as regras:
--   * cada atendimento ("Exames Realizados" = ID) conta uma vez, pela versão
--     vista mais recentemente;
--   * se um dia teve sync bem-sucedido, só entram linhas vistas naquele sync
--     (o que sumiu do Klingo depois deixa de contar);
--   * linha sem ID não entra (o extrator local também recusa).
-- Também aplica a permissão "Pode ver Metas" (security definer ignora RLS).
--
-- Retorno (jsonb): mapeado=false enquanto o sync ainda não gravou os títulos
-- das colunas; senão { mapeado, convenio, linhas[], ultimo_sync, ultimo_dia,
-- dias_sincronizados }.
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

update public.dim_relatorio
set observacoes = 'Alimenta a aba Metas do site (regras em "Acompanhamento de META/metas.json"). Atualizar pelo botão "Atualizar" da aba Metas: um mês por vez.'
where klingo_id = '13339';
