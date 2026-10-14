-- Cada relatório do Klingo tem seu próprio nome de filtro de período (a maioria "periodo0", mas o
-- #26 usa "periodo" e o #798 "PERIODO"). Com o nome errado o Klingo ignora o filtro e devolve o
-- período padrão (hoje) sem erro: o histórico de 90 dias viraria o dado de hoje repetido, com a
-- data errada. Agora a Edge Function usa o filtro cadastrado aqui e confere na resposta que o
-- período foi mesmo aplicado (mesma regra do painel em Python, extrair_laudo.validar_resposta).
-- filtro_periodo NULL = relatório sem filtro de data (vem inteiro; ex.: #13374 e #13376).
alter table public.dim_relatorio add column if not exists filtro_periodo text default 'periodo0';

comment on column public.dim_relatorio.filtro_periodo is 'Id do filtro de período do relatório no Klingo (sem os dois pontos). NULL = relatório sem filtro de data.';

update public.dim_relatorio set filtro_periodo = 'periodo' where klingo_id = '26';
update public.dim_relatorio set filtro_periodo = 'PERIODO' where klingo_id = '798';
update public.dim_relatorio set filtro_periodo = null where klingo_id in ('13374', '13376');

-- Estes quatro devolvem as mesmas linhas todos os dias (o filtro de período parece ser ignorado):
-- ficam só com o dia de hoje até a conferência da resposta dizer o contrário.
update public.dim_relatorio set janela_dias = 1 where klingo_id in ('275', '13434', '319', '52');
