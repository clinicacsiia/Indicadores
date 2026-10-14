-- Tela Início: o que está sendo coletado, medido do jeito que cada relatório é de fato coletado.
--
-- A status_sincronizacao_relatorios() só sabia contar DIAS (janela_dias). Para os relatórios de coleta MENSAL
-- (dim_relatorio.granularidade = 'mes') ela olhava só se "hoje" tinha rodado e mostrava 100% mesmo com meses faltando
-- (ex.: Despesas Detalhadas, 8 de 11 meses), e o "atualizado até" podia cair num mês futuro (meses_a_frente). Também
-- não dizia nada sobre relatório pausado ou falhando. Esta versão (nome novo, para a tela antiga continuar funcionando
-- durante o deploy) conta na unidade certa e traz o estado de pausa/falha.
--
--   unidade 'dia'   -> dias com coleta bem-sucedida nos últimos janela_dias dias
--   unidade 'mes'   -> meses (periodo = dia 1) de primeiro_mes até o mês atual + meses_a_frente
--   unidade 'unico' -> relatório pontual: coletado alguma vez ou não
create or replace function public.status_coleta_relatorios()
returns table (
  klingo_id text,
  nome text,
  categoria text,
  unidade text,
  ultimo_periodo date,          -- último período coletado que não é futuro
  ultimo_sync timestamptz,
  sincronizados integer,        -- dias, meses ou 1/0, conforme a unidade
  esperados integer,
  pct numeric,
  pausado_ate timestamptz,      -- só quando ainda vale (no futuro)
  falhas_seguidas integer,
  erros_24h integer,
  ultimo_erro text
)
language sql
security invoker
stable
set search_path = ''
as $$
  with hoje as (
    select (now() at time zone 'America/Sao_Paulo')::date as d
  ),
  alvo as (
    select
      r.id, r.klingo_id, r.nome, r.categoria, r.pausado_ate, r.falhas_seguidas,
      case when r.periodicidade = 'pontual' then 'unico'
           when r.granularidade = 'mes' then 'mes'
           else 'dia' end as unidade,
      case when r.granularidade = 'mes' then date_trunc('month', coalesce(r.primeiro_mes, h.d))::date
           else h.d - (greatest(coalesce(r.janela_dias, 1), 1) - 1) end as inicio,
      case when r.granularidade = 'mes'
           then (date_trunc('month', h.d) + make_interval(months => coalesce(r.meses_a_frente, 0)))::date
           else h.d end as fim,
      h.d as hoje
    from public.dim_relatorio r
    cross join hoje h
    where r.ativo = true and r.supersedido_por is null
  ),
  sucesso as (
    select s.relatorio_id,
           max(s.periodo) filter (where s.periodo <= (select d from hoje)) as ultimo_periodo,
           max(s.finished_at) as ultimo_sync
    from public.sync_relatorio_runs s
    where s.status = 'success'
    group by s.relatorio_id
  ),
  contagem as (
    select a.id,
           count(distinct s.periodo) as qtd
    from alvo a
    left join public.sync_relatorio_runs s
      on s.relatorio_id = a.id and s.status = 'success'
     and s.periodo between a.inicio and a.fim
     and (a.unidade <> 'mes' or s.periodo = date_trunc('month', s.periodo)::date)   -- mensal: só o dia 1 representa o mês
    where a.unidade <> 'unico'
    group by a.id
  ),
  erros as (
    select s.relatorio_id,
           count(*) filter (where s.started_at > now() - interval '24 hours') as erros_24h,
           (array_agg(left(s.error_message, 200) order by s.started_at desc))[1] as ultimo_erro
    from public.sync_relatorio_runs s
    where s.status <> 'success' and s.started_at > now() - interval '7 days'
    group by s.relatorio_id
  )
  select
    a.klingo_id,
    a.nome,
    a.categoria,
    a.unidade,
    g.ultimo_periodo,
    g.ultimo_sync,
    case a.unidade
      when 'unico' then (case when g.ultimo_sync is not null then 1 else 0 end)
      else coalesce(c.qtd, 0)::integer end as sincronizados,
    case a.unidade
      when 'unico' then 1
      when 'mes' then (((extract(year from a.fim) - extract(year from a.inicio)) * 12
                        + extract(month from a.fim) - extract(month from a.inicio))::integer + 1)
      else (a.fim - a.inicio + 1) end as esperados,
    case a.unidade
      when 'unico' then (case when g.ultimo_sync is not null then 100 else 0 end)
      else round(100.0 * coalesce(c.qtd, 0) / greatest(
             case a.unidade when 'mes' then (((extract(year from a.fim) - extract(year from a.inicio)) * 12
                                              + extract(month from a.fim) - extract(month from a.inicio))::integer + 1)
                            else (a.fim - a.inicio + 1) end, 1)) end as pct,
    case when a.pausado_ate > now() then a.pausado_ate end as pausado_ate,
    coalesce(a.falhas_seguidas, 0) as falhas_seguidas,
    coalesce(e.erros_24h, 0)::integer as erros_24h,
    e.ultimo_erro
  from alvo a
  left join sucesso g on g.relatorio_id = a.id
  left join contagem c on c.id = a.id
  left join erros e on e.relatorio_id = a.id
  order by a.categoria, a.nome;
$$;

comment on function public.status_coleta_relatorios() is 'Status da coleta de cada relatório ativo para a tela Início: dias (diários), meses (mensais) ou 1/0 (pontuais), mais pausa/falhas. As tabelas-base (dim_relatorio, sync_relatorio_runs) já têm select liberado a authenticated, então security invoker basta.';

revoke execute on function public.status_coleta_relatorios() from public, anon;
grant execute on function public.status_coleta_relatorios() to authenticated;

-- Painéis em Python sendo renovados agora (a tabela painel_renovacao é só da service_role): a tela Início mostra "atualizando agora".
-- Só devolve os painéis que quem pergunta pode ver (mesma regra do resto do site) e ignora trava que já venceu (6 min).
create or replace function public.paineis_renovando()
returns table (painel text, decorrido_s integer, previsto_s integer)
language sql
security definer
stable
set search_path = ''
as $$
  select r.painel,
         greatest(extract(epoch from (now() - r.iniciado_em))::integer, 0),
         r.previsto_s
  from public.painel_renovacao r
  where r.iniciado_em > now() - interval '6 minutes'
    and public.can_view_painel(r.painel)
  order by r.iniciado_em;
$$;

comment on function public.paineis_renovando() is 'Painéis em Python com renovação em andamento (painel, segundos decorridos, previsto), só os que o usuário pode ver. Alimenta o aviso "atualizando agora" da tela Início.';

revoke execute on function public.paineis_renovando() from public, anon;
grant execute on function public.paineis_renovando() to authenticated;
