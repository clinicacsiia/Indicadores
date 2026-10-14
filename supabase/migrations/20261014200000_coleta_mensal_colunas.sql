-- Granularidade da coleta. Os painéis em Python pedem cada relatório por MÊS inteiro (e alguns por meses
-- futuros, como contas a pagar/receber até 6 meses à frente, ou histórico mais longo que 90 dias). Para o
-- banco entregar exatamente o que o painel recebia do Klingo, o relatório pode ser coletado por mês:
--   granularidade 'dia' (padrão): um pedido por dia, dentro de janela_dias.
--   granularidade 'mes': um pedido por mês, de primeiro_mes até o mês atual + meses_a_frente; o mês é guardado
--     com periodo = dia 1. Meses dos últimos revisar_meses (padrão 2) são refeitos a cada coleta vencida;
--     os mais antigos uma vez só (revisar_meses preenchido) ou 1 vez por dia (revisar_meses vazio).
alter table public.dim_relatorio
  add column if not exists granularidade text not null default 'dia',
  add column if not exists primeiro_mes date,
  add column if not exists meses_a_frente integer not null default 0,
  add column if not exists revisar_meses integer;

comment on column public.dim_relatorio.granularidade is 'dia (um pedido por dia) ou mes (um pedido por mês, como os painéis em Python).';
comment on column public.dim_relatorio.primeiro_mes is 'Primeiro mês coletado (dia 1) quando a granularidade é mês.';
comment on column public.dim_relatorio.meses_a_frente is 'Quantos meses futuros também são coletados (relatórios por vencimento).';
comment on column public.dim_relatorio.revisar_meses is 'Meses recentes sempre refeitos; NULL = refaz os antigos 1 vez por dia.';
