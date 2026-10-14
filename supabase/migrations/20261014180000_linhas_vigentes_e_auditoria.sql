-- 1. Linhas vigentes. fact_relatorio_linha guarda o histórico (linha que mudou vira registro novo,
-- nada é apagado), então um mesmo dia pode ter versões antigas e novas lado a lado. Somar a tabela
-- crua conta em dobro. Esta visão devolve só o que a ÚLTIMA coleta bem-sucedida de cada relatório/dia
-- viu: é por ela que telas e contas devem ler. (Mesma regra que metas_atendimentos_mes já usa.)
-- Atenção: "repeticoes" é a contagem de linhas idênticas devolvidas pelo Klingo no mesmo dia; para
-- contar registros como o painel em Python (que deduplica pela chave), use 1 linha por registro.
create or replace view public.v_relatorio_linha_vigente
with (security_invoker = true)
as
with ultimo as (
  select relatorio_id, periodo, max(started_at) as inicio
  from public.sync_relatorio_runs
  where status = 'success'
  group by relatorio_id, periodo
)
select f.*
from public.fact_relatorio_linha f
left join ultimo u on u.relatorio_id = f.relatorio_id and u.periodo = f.periodo
where u.inicio is null or f.last_seen_at >= u.inicio;

comment on view public.v_relatorio_linha_vigente is 'Linhas vistas pela última coleta bem-sucedida de cada relatório/dia (sem versões antigas). Use esta visão, não fact_relatorio_linha, para somar valores.';

-- 2. Auditoria diária: relatório cujas linhas se repetem em vários dias vira alerta aberto em
-- v_etl_pendencias (tipo possivel_duplicata_dados). Quem decide o que fazer é uma pessoa.
create or replace function public.auditar_qualidade_relatorios()
returns integer
language plpgsql
set search_path = ''
as $$
declare
  v record;
  n integer := 0;
begin
  for v in
    select r.id, q.klingo_id, q.nome, q.dias_com_dados, q.vezes_que_cada_linha_aparece
    from public.v_qualidade_relatorios q
    join public.dim_relatorio r on r.klingo_id = q.klingo_id
    where q.situacao like 'SUSPEITO%'
  loop
    perform public.registrar_alerta(
      'possivel_duplicata_dados', 'aviso', 'periodo_suspeito:' || v.id,
      '"' || v.nome || '" (#' || v.klingo_id || ') repete as mesmas linhas em ' || v.dias_com_dados
        || ' dias (cada linha aparece ' || v.vezes_que_cada_linha_aparece
        || ' vezes): o filtro de período provavelmente é ignorado pelo Klingo. Não some este relatório por período antes de conferir.',
      v.id, null, (now() at time zone 'America/Sao_Paulo')::date,
      jsonb_build_object('dias', v.dias_com_dados, 'vezes', v.vezes_que_cada_linha_aparece), false
    );
    n := n + 1;
  end loop;
  return n;
end;
$$;

revoke execute on function public.auditar_qualidade_relatorios() from public, anon, authenticated;
grant execute on function public.auditar_qualidade_relatorios() to service_role;

select cron.schedule('auditoria-qualidade-relatorios', '0 9 * * *', $cmd$ select public.auditar_qualidade_relatorios(); $cmd$);
