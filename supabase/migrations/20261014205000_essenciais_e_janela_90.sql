-- 1. Colunas essenciais: nos relatórios que os painéis em Python NÃO usam, a coleta deixa de gravar o que identifica o paciente
-- (nome, telefone, matrícula, prontuário, CID e observações livres). Ficam os códigos/IDs (para contar pacientes distintos) e tudo
-- que serve para somar, cruzar e analisar. Relatórios dos painéis (colunas_essenciais vazio) continuam gravando todas as colunas.
-- Dados antigos já gravados com essas colunas NÃO foram apagados (decisão de uma pessoa): ver o README.
update public.dim_relatorio set colunas_essenciais = array['col0','col1','col5','col6','col7','col8','col9','col10','col11','col12'] where klingo_id = '12757';       -- sem Paciente, Pront e CID
update public.dim_relatorio set colunas_essenciais = array['col0','col1','col3','col4','col5','col6','col7','col8','col9','col10'] where klingo_id = '13256';        -- sem Paciente - Nome Completo
update public.dim_relatorio set colunas_essenciais = array['col0','col1','col3'] where klingo_id = '13434';                                                         -- sem Paciente - Nome
update public.dim_relatorio set colunas_essenciais = array['col1','col3','col4','col5','col6','col7','col8','col9'] where klingo_id = '13510';                      -- sem Nome do Paciente e Matrícula
update public.dim_relatorio set colunas_essenciais = array['ATENDIMENTO','MARCACAO','MARCADO','MEDICO','PROCEDIMENTO','Qtd','Status','Unidade'] where klingo_id = '18'; -- sem Paciente
update public.dim_relatorio set colunas_essenciais = array['Data_Atendimento','Hora','Medico','Procedimento','qtd','Status','Unidade','Usuario'] where klingo_id = '19'; -- sem Paciente e contato
update public.dim_relatorio set colunas_essenciais = array['Atendimento','Dias','Id_pessoa','idade','Medico','Meses','Operadora','Procedimento','Sexo'] where klingo_id = '275'; -- sem Paciente, Celular e Telefone
update public.dim_relatorio set colunas_essenciais = array['Categoria','Data_Atend','Id_Atend','Medico','Operadora','Prestador','Procedimento','Qtd','Rateio','Unidade','Valor'] where klingo_id = '319'; -- sem Paciente
update public.dim_relatorio set colunas_essenciais = array['Data_Atendimento','Medico','Motivo','Operadora','Procedimento','Status','Unidade','Usuario'] where klingo_id = '47';   -- sem Paciente
update public.dim_relatorio set colunas_essenciais = array['Atendimento','Categoria','id_atendimento','nome_procedimento','operadora','plano','Quantidade','Unidade','Valor'] where klingo_id = '52'; -- sem Paciente
update public.dim_relatorio set colunas_essenciais = array['Atend','data_atend','dt_retorno','medico','st_procedimento'] where klingo_id = '681';                      -- sem Paciente, Telefone e Observações

-- 2. #52, #275 e #319 devolviam as mesmas linhas todos os dias (filtro de período ignorado, corrigido para "periodo"). As coletas
-- antigas deles passam a "erro" (nada é apagado) para o banco refazer os dias com o filtro certo; a visão de linhas vigentes mostra
-- só o que a coleta nova viu.
update public.sync_relatorio_runs
set status = 'error', error_message = 'coleta antiga descartada: filtro de período ignorado'
where status = 'success'
  and relatorio_id in (select id from public.dim_relatorio where klingo_id in ('52', '275', '319'));

-- 3. Janela de 90 dias para os relatórios por dia que têm filtro de período. Quem ainda não teve o filtro comprovado segue limitado
-- ao dia de hoje (proximos_trabalhos) até a primeira coleta confirmar o período.
update public.dim_relatorio
set janela_dias = 90
where granularidade is distinct from 'mes'
  and filtro_periodo is not null
  and periodicidade is distinct from 'pontual'
  and supersedido_por is null
  and ativo
  and klingo_id <> '21';   -- o Klingo recusa este relatório
