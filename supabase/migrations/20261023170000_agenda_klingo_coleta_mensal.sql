-- Relatório #13825 ("Agendamentos - Visão Consolidada por Marcação"): coleta mensal, todas as colunas.
-- O filtro de período dele (periodo0, o único de data) é a data em que a marcação foi FEITA, então o status (cancelada,
-- atendido, confirmação) de uma marcação muda depois do dia em que ela entra. Coletar por mês e rever os últimos meses
-- (como o NPS) refaz esse status; a coleta por dia só olharia cada dia uma vez.
-- Sem colunas_essenciais: nome e telefone do paciente ficam guardados (tabela só do admin) porque a Agenda do CRM Ressonância
-- os usa para a confirmação do exame; quem lê é a função crm_rm_agenda_klingo(), só para quem tem acesso ao CRM.
--
-- Colunas do relatório (título que o Klingo dá): col0 Id da Marcação, col1 Id do Atendimento, col2 Prontuário,
-- col3 Data Agendado Em, col4 Data Agendado Para, col5 Procedimento, col6 Operadora, col7 Responsável, col8 Valor,
-- col9 Observação, col10 Confirm Status, col11 Cancelamento - Motivo, col12 Status, col13 Atendido, col14 Unidade,
-- col15 Paciente - Nome, col16 Paciente - Celular, col17 Paciente - Telefone.
update public.dim_relatorio
set granularidade = 'mes', primeiro_mes = '2026-09-01', meses_a_frente = 0, revisar_meses = 2, janela_dias = 90,
    falhas_seguidas = 0, pausado_ate = null
where klingo_id = '13825';
