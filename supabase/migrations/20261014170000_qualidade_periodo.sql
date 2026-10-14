-- Trava contra o erro "filtro de período ignorado": o Klingo devolve o dia de hoje (ou a tabela
-- inteira) para qualquer dia pedido quando o nome do filtro está errado, e os valores deixam de
-- bater. Agora um relatório só recebe histórico (mais de 1 dia) depois que uma coleta comprovou,
-- na própria resposta do Klingo, que o filtro de período foi aplicado (periodo_validado_em).

-- 1. Filtros descobertos pela conferência da Edge Function (os nomes vieram da resposta do Klingo).
update public.dim_relatorio set filtro_periodo = 'para' where klingo_id = '18';
update public.dim_relatorio set filtro_periodo = 'periodo' where klingo_id in ('235', '243', '260');
update public.dim_relatorio set filtro_periodo = null where klingo_id = '13434'; -- só tem parm0, sem filtro de data

alter table public.dim_relatorio add column if not exists periodo_validado_em timestamptz;
comment on column public.dim_relatorio.periodo_validado_em is 'Última vez em que o Klingo confirmou, na resposta, ter aplicado o filtro de período. Sem isso o relatório fica limitado ao dia de hoje.';

create or replace function public.registrar_periodo_validado(p_relatorio_id uuid)
returns void
language sql
security invoker
set search_path = ''
as $$
  update public.dim_relatorio set periodo_validado_em = now() where id = p_relatorio_id;
$$;

revoke execute on function public.registrar_periodo_validado(uuid) from public, anon, authenticated;
grant execute on function public.registrar_periodo_validado(uuid) to service_role;

-- 2. proximos_trabalhos: janela efetiva = 1 dia enquanto o filtro não foi comprovado (ou se o
-- relatório não tem filtro de data, caso em que ele vem inteiro e só vale como foto do dia). O dia
-- de hoje de um relatório ainda não comprovado é refeito já, para comprovar logo.
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
    select id, klingo_id, periodicidade,
      case when filtro_periodo is null or periodo_validado_em is null then 1 else janela_dias end as janela,
      (filtro_periodo is not null and periodo_validado_em is null) as a_comprovar
    from public.dim_relatorio
    where ativo and supersedido_por is null and (pausado_ate is null or pausado_ate <= now())
  ),
  pares as (
    select r.id, r.klingo_id, r.periodicidade, r.a_comprovar, g::date as periodo, h.d as hoje
    from rel r
    cross join hoje h
    cross join lateral generate_series(
      (case when r.periodicidade = 'pontual' then h.d else h.d - (r.janela - 1) end)::timestamp,
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
  )
  select id, klingo_id, periodo, count(*) over ()
  from pendentes
  order by (periodo = hoje) desc, periodo desc, klingo_id
  limit greatest(least(p_limite, 100), 1);
$$;

-- 3. Auditoria: um relatório cujas linhas se repetem em vários dias quase sempre tem o filtro de
-- período ignorado (cada linha aparece em ~todos os dias). Consulta: select * from v_qualidade_relatorios;
create or replace view public.v_qualidade_relatorios
with (security_invoker = true)
as
select
  r.klingo_id,
  r.nome,
  r.filtro_periodo,
  r.periodo_validado_em,
  r.janela_dias,
  count(distinct f.periodo) as dias_com_dados,
  count(*) as linhas_gravadas,
  count(distinct f.linha_hash) as linhas_distintas,
  round(count(*)::numeric / nullif(count(distinct f.linha_hash), 0), 1) as vezes_que_cada_linha_aparece,
  coalesce(sum(f.repeticoes - 1), 0) as duplicatas_exatas_no_klingo,
  case
    when r.filtro_periodo is not null and count(distinct f.periodo) >= 3
         and count(*)::numeric / nullif(count(distinct f.linha_hash), 0) >= 2
      then 'SUSPEITO: as mesmas linhas se repetem em vários dias (filtro de período ignorado?)'
    when r.filtro_periodo is not null and r.periodo_validado_em is null then 'filtro de período ainda não comprovado'
    else 'ok'
  end as situacao
from public.dim_relatorio r
join public.fact_relatorio_linha f on f.relatorio_id = r.id
group by r.id, r.klingo_id, r.nome, r.filtro_periodo, r.periodo_validado_em, r.janela_dias
order by r.klingo_id::int;

comment on view public.v_qualidade_relatorios is 'Auditoria por relatório: repetição de linhas entre dias (sinal de filtro de período ignorado) e duplicatas exatas devolvidas pelo Klingo. Só administradores leem fact_relatorio_linha, então só eles veem linhas aqui.';
