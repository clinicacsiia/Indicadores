-- Tela inicial ("Início"): um card por relatório liberado para visualização
-- (dim_relatorio.ativo = true, sem supersedido_por) com o quanto já está
-- sincronizado. A janela de referência depende da periodicidade:
--   * mensal   -> dias do mês corrente (1 até hoje)
--   * pontual  -> não se repete: 100% se já sincronizou alguma vez, 0% se nunca
--   * qualquer outra (inclui null, "diario") -> últimos 30 dias
-- `dias_sincronizados`/`dias_esperados` alimentam tanto a % exibida quanto o
-- texto "faltam N dias"; `ultimo_periodo` é o último dia com sync bem-sucedido
-- em qualquer época (não só dentro da janela), usado pelo botão "Atualizar
-- tudo" para saber de onde recomeçar cada relatório.
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
    where ativo = true and supersedido_por is null
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

comment on function public.status_sincronizacao_relatorios() is 'Status de sincronização (% e última data) de cada relatório liberado para visualização (ativo=true, sem supersedido_por). Alimenta a tela Início. As tabelas-base (dim_relatorio, sync_relatorio_runs) já têm select liberado a authenticated, então security invoker basta.';

revoke execute on function public.status_sincronizacao_relatorios() from public, anon;
grant execute on function public.status_sincronizacao_relatorios() to authenticated;
