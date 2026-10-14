-- Coleta inteligente dos relatórios do Klingo.
--
-- Antes, "Atualizar tudo" era o navegador de quem clicou percorrendo o catálogo inteiro. Agora
-- o banco sabe o que falta (janela de dias por relatório) e a Edge Function sync-relatorios-dw
-- (modo "auto") busca só isso, em lotes pequenos, chamada por um agendamento a cada 5 minutos
-- e pelo botão do site. O site só lê o que já está no banco.
--
--  * janela_dias: quantos dias para trás o relatório é mantido (máx. 90). Relatório que nunca
--    foi sincronizado começa com 1 dia ("descoberta"): basta para ver quais colunas ele traz
--    e se aceita o filtro de período. Depois de conferir (e de definir colunas_essenciais),
--    suba para 90: update public.dim_relatorio set janela_dias = 90 where klingo_id = '...';
--  * colunas_essenciais: só essas colunas (col0, Paciente...) são gravadas em
--    fact_relatorio_linha. NULL = grava todas, como sempre foi.
--  * falhas_seguidas / pausado_ate: relatório que falha 3 vezes seguidas fica 6 h parado
--    para não martelar o Klingo; qualquer sucesso zera.

alter table public.dim_relatorio
  add column if not exists janela_dias integer not null default 90 check (janela_dias between 1 and 90),
  add column if not exists colunas_essenciais text[],
  add column if not exists falhas_seguidas integer not null default 0,
  add column if not exists pausado_ate timestamptz;

comment on column public.dim_relatorio.janela_dias is 'Dias (até hoje) que a coleta automática mantém em dia para este relatório. Máx. 90.';
comment on column public.dim_relatorio.colunas_essenciais is 'Se preenchido, só estas colunas da linha do Klingo são gravadas. NULL = todas.';
comment on column public.dim_relatorio.falhas_seguidas is 'Falhas de coleta seguidas; zera no primeiro sucesso.';
comment on column public.dim_relatorio.pausado_ate is 'Coleta automática pula o relatório até este instante (disjuntor após 3 falhas seguidas).';

-- Relatório que nunca teve sucesso começa só com o dia de hoje (descoberta de colunas).
update public.dim_relatorio r
set janela_dias = 1
where not exists (
  select 1 from public.sync_relatorio_runs s where s.relatorio_id = r.id and s.status = 'success'
);

-- Relatórios sem filtro de período (ou "pontuais"): buscados uma vez, não por dia.
update public.dim_relatorio
set periodicidade = 'pontual'
where periodicidade is null
  and (observacoes ilike 'Pontual%' or observacoes ilike 'Pode não aceitar filtro de período%');

-- Todos os relatórios não supersedidos passam a ser coletados.
update public.dim_relatorio set ativo = true where supersedido_por is null;

-- O que falta coletar agora: pares (relatório, dia) dentro da janela, do mais recente para o mais
-- antigo. Um dia só está completo se o sync terminou depois da meia-noite dele; o dia de hoje é
-- refeito no máximo a cada 60 minutos. Ficam de fora: relatório pausado, par com coleta em
-- andamento (últimos 5 min) e par que falhou nos últimos 30 min.
create or replace function public.proximos_trabalhos(p_limite integer default 30)
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
            and (p.periodo < p.hoje or s.finished_at > now() - interval '60 minutes')
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

revoke execute on function public.proximos_trabalhos(integer) from public, anon, authenticated;
grant execute on function public.proximos_trabalhos(integer) to service_role;

-- Disjuntor: chamado pela Edge Function depois de cada tentativa.
create or replace function public.registrar_resultado_coleta(p_relatorio_id uuid, p_ok boolean)
returns void
language sql
security invoker
set search_path = ''
as $$
  update public.dim_relatorio
  set falhas_seguidas = case when p_ok then 0 else falhas_seguidas + 1 end,
      pausado_ate = case
        when p_ok then null
        when falhas_seguidas + 1 >= 3 then now() + interval '6 hours'
        else pausado_ate
      end
  where id = p_relatorio_id;
$$;

revoke execute on function public.registrar_resultado_coleta(uuid, boolean) from public, anon, authenticated;
grant execute on function public.registrar_resultado_coleta(uuid, boolean) to service_role;

-- Tela Início: a % usa a janela de cada relatório (janela_dias) em vez de fixar 30 dias.
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
    select id, klingo_id, nome, categoria, periodicidade, janela_dias
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
    select a.id, h.d - (a.janela_dias - 1) as inicio, h.d as fim
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

revoke execute on function public.status_sincronizacao_relatorios() from public, anon;
grant execute on function public.status_sincronizacao_relatorios() to authenticated;
