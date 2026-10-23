-- Relatório #13825 do Klingo ("Agendamentos - Visão Consolidada por Marcação"): fonte da agenda da aba "CRM Ressonância".
-- Entra em modo de descoberta (janela_dias = 1, só o dia de hoje): a primeira coleta registra as colunas em dim_relatorio_coluna
-- e, se o filtro de período 'periodo0' não existir nele, o erro da coleta lista os filtros de data que o relatório tem.
-- Depois de conferir as colunas: ajustar filtro_periodo, definir colunas_essenciais (sem nome/telefone do paciente) e liberar janela_dias.
insert into public.dim_relatorio (klingo_id, nome, categoria, ativo, observacoes, filtro_periodo, granularidade, janela_dias)
values ('13825', 'Agendamentos - Visão Consolidada por Marcação', 'Marcação', true,
        'Agenda do CRM Ressonância. Em descoberta (23/10): conferir colunas e filtro de período antes de liberar o histórico.',
        'periodo0', 'dia', 1)
on conflict (klingo_id) do update
  set nome = excluded.nome, categoria = excluded.categoria, ativo = true, granularidade = 'dia',
      filtro_periodo = coalesce(public.dim_relatorio.filtro_periodo, excluded.filtro_periodo);
