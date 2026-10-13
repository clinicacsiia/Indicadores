-- "Atualizar tudo" passa a sincronizar TODOS os relatórios do catálogo
-- (dim_relatorio), não só os liberados (ativo = true). A tela Início, que mostra o
-- quanto cada um está sincronizado, acompanha: lista todo relatório que não foi
-- marcado como supersedido por uma pessoa. O resto da lógica é a mesma da migration
-- 20261013140000_status_sincronizacao_relatorios.sql.
create or replace function public.status_sincronizacao_relatorios()
returns table (
  klingo_id text,
  nome text,
  categoria text,
  periodicidade text,
  ultimo_periodo date,
  ultimo_sync timestamptz,
  dias_sincronizados integer,
  dias_esperados integer,
  pct numeric
)
language sql
security invoker
stable
set search_path = ''
as $$
  with hoje as (
    select (now() at time zone 'America/Sao_Paulo')::date as d
  ),
  ativos as (
    select id, klingo_id, nome, categoria, periodicidade
    from public.dim_relatorio
    where supersedido_por is null
  ),
  sucesso_geral as (
    select relatorio_id, max(periodo) as ultimo_periodo, max(finished_at) as ultimo_sync
    from public.sync_relatorio_runs
    where status = 'success'
    group by relatorio_id
  ),
  janela as (
    select
      a.id,
      case when a.periodicidade = 'mensal' then date_trunc('month', h.d)::date else h.d - 29 end as inicio,
      h.d as fim
    from ativos a, hoje h
    where a.periodicidade is distinct from 'pontual'
  ),
  dias_ok as (
    select j.id, count(distinct s.periodo) as qtd
    from janela j
    left join public.sync_relatorio_runs s
      on s.relatorio_id = j.id and s.status = 'success' and s.periodo between j.inicio and j.fim
    group by j.id
  )
  select
    a.klingo_id,
    a.nome,
    a.categoria,
    a.periodicidade,
    g.ultimo_periodo,
    g.ultimo_sync,
    case when a.periodicidade = 'pontual' then (case when g.ultimo_periodo is not null then 1 else 0 end)
         else coalesce(d.qtd, 0) end as dias_sincronizados,
    case when a.periodicidade = 'pontual' then 1
         else (j.fim - j.inicio + 1) end as dias_esperados,
    case when a.periodicidade = 'pontual' then (case when g.ultimo_periodo is not null then 100 else 0 end)
         else round(100.0 * coalesce(d.qtd, 0) / greatest(j.fim - j.inicio + 1, 1)) end as pct
  from ativos a
  left join sucesso_geral g on g.relatorio_id = a.id
  left join janela j on j.id = a.id
  left join dias_ok d on d.id = a.id
  order by a.categoria, a.nome;
$$;

comment on function public.status_sincronizacao_relatorios() is 'Status de sincronização (% e última data) de cada relatório do catálogo que não foi supersedido (qualquer ativo). Alimenta a tela Início e o botão "Atualizar tudo". As tabelas-base (dim_relatorio, sync_relatorio_runs) já têm select liberado a authenticated, então security invoker basta.';

revoke execute on function public.status_sincronizacao_relatorios() from public, anon;
grant execute on function public.status_sincronizacao_relatorios() to authenticated;
