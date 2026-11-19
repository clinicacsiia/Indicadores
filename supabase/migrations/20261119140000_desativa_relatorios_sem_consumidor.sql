-- Libera espaço no plano gratuito (500 MB): desativa os relatórios que a coleta buscava mas NENHUM painel, tela ou função lê.
-- Em 19/11 o banco estava em 436 MB (freio da coleta aos 470 MB) e crescendo ~25-30 MB por mês.
--
-- Como foi decidido: cada relatório do relatorios.json de cada painel, mais 13339 (Metas), 13397 (Início) e 13825 (agenda do CRM)
-- foram MANTIDOS. Os 27 abaixo não aparecem em nenhum painel nem em função do banco que leia fact_relatorio_linha
-- (o relatório 52 só era lido por funções do CRM Ressonância que não existem em produção). Os painéis em Python leem da
-- cópia própria (painel_dados), então nenhuma tela perde dado.
--
-- O que muda: ativo = false (a coleta para de buscá-los) e janela_dias = 1 nos relatórios por dia. A poda diária
-- (podar_linhas_antigas, 05:30 de Brasília) apaga as linhas com mais de janela_dias + 3 dias; ela já existia, então não
-- há DELETE novo. Em 19/11 foi chamada na hora: 122.487 linhas saíram e, depois do VACUUM FULL, o banco foi de 436 para 321 MB.
-- Sobram só os últimos ~4 dias de cada um (~7,5 mil linhas).
--
-- COMO VOLTAR a um relatório (exemplo: 319, Produção Médica; os relatórios por dia tinham janela_dias = 90):
--   update public.dim_relatorio set ativo = true, janela_dias = 90 where klingo_id = '319';
-- A coleta (a cada 5 min) busca os 90 dias de novo no Klingo, que continua tendo o dado. Isso ocupa espaço outra vez
-- (a lista com o tamanho de cada um está no README); acompanhe o tamanho do banco e o freio de 470 MB.
-- Relatórios que eram "pontual" (19, 6881, 12712, 13256, 13437) tinham janela_dias = 1: basta ativo = true.

update public.dim_relatorio
set ativo = false,
    janela_dias = case when granularidade = 'dia' and periodicidade is null then 1 else janela_dias end,
    observacoes = left(coalesce(nullif(observacoes, ''), '') || case when coalesce(observacoes, '') = '' then '' else ' | ' end
      || 'Desativado em 19/11/2026 para liberar espaço (nenhum painel lê). Para voltar: ativo=true e janela_dias=90 (se por dia).', 900)
where klingo_id in ('18','19','21','47','52','235','243','260','275','319','370','681','843','6881','7128',
                    '12624','12625','12640','12712','12757','13149','13222','13256','13302','13434','13437','13510')
  and ativo;
