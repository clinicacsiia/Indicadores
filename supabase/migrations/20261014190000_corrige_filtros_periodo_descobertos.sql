-- Filtros de período descobertos pela conferência da Edge Function (nomes vindos da resposta do
-- Klingo). #275, #319 e #52 usam "periodo" e não "periodo0": com o nome errado o Klingo ignorava o
-- pedido e devolvia as mesmas linhas todos os dias.
update public.dim_relatorio
set filtro_periodo = 'periodo', falhas_seguidas = 0, pausado_ate = null
where klingo_id in ('47', '52', '275', '319', '370', '681', '843', '7128');

update public.dim_relatorio
set falhas_seguidas = 0, pausado_ate = null
where klingo_id in ('18', '235', '243', '260', '13434');

-- #7 tem dois filtros de data (data_marcacao e data_atendimento); escolher qual separa os dias é decisão humana.
update public.dim_relatorio
set ativo = false,
    observacoes = 'Tem dois filtros de data (data_marcacao e data_atendimento) e não dá para escolher sozinho qual separa os dias. Defina filtro_periodo e volte ativo = true.'
where klingo_id = '7';
