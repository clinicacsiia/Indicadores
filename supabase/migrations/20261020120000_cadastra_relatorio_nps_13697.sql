-- Relatório #13697 do Klingo ("Relatorio NPS - Notas por Marcação", pasta NPS): alimenta a nova aba "NPS × Google".
-- Coleta mensal desde o início do Klingo (set/2026), como o #13402; o motor valida sozinho o filtro de período (periodo0 é o padrão)
-- e as colunas aparecem em dim_relatorio_coluna na primeira coleta.
insert into public.dim_relatorio (klingo_id, nome, categoria, ativo, observacoes, filtro_periodo, granularidade, primeiro_mes, meses_a_frente, revisar_meses)
values ('13697', 'Relatorio NPS - Notas por Marcação', 'NPS', true, 'Mensal', 'periodo0', 'mes', '2026-09-01', 0, 2)
on conflict (klingo_id) do update
  set nome = excluded.nome, categoria = excluded.categoria, ativo = true, granularidade = 'mes', primeiro_mes = '2026-09-01',
      meses_a_frente = 0, revisar_meses = 2, filtro_periodo = coalesce(public.dim_relatorio.filtro_periodo, 'periodo0');
