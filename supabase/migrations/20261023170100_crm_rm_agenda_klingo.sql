-- Agenda da Ressonância vinda do Klingo (relatório #13825, uma linha por marcação), para a aba "CRM Ressonância".
-- A tabela com as linhas do Klingo é só do administrador; esta função entrega a agenda a quem tem acesso ao CRM
-- (administrador, "crm_rm" ou "crm_rm_preencher"). Fora disso devolve zero linhas, sem erro.
--
-- Colunas do relatório: col0 Id da Marcação, col1 Id do Atendimento (só existe quando o paciente foi atendido), col2 Prontuário,
-- col3 Data Agendado Em, col4 Data Agendado Para (a do exame), col5 Procedimento, col6 Operadora, col7 Responsável (quem marcou),
-- col8 Valor, col9 Observação, col10 Confirm Status, col11 Cancelamento - Motivo, col12 Status (Aberta/Cancelada),
-- col13 Atendido (S/N), col14 Unidade, col15 Paciente - Nome, col16 Paciente - Celular, col17 Paciente - Telefone.
--
-- Uma marcação pode estar em mais de uma linha do banco (coleta do dia e do mês, ou o status que mudou): vale a mais recente.
-- É só Ressonância: o procedimento tem de estar no catálogo `crm_rm_exame` (ou começar com RM/ANGIO-RM/COLANGIO, para exame novo
-- que ainda não entrou no catálogo); tomografia, pacote (PCTE) e contraste ficam de fora. Nomes comparados sem acento e sem
-- diferença de maiúscula ("AMOR SAÚDE" no relatório × "AMOR SAUDE" no catálogo).
create or replace function public.crm_rm_agenda_klingo(p_de date, p_ate date)
returns table (
  codigo_marcacao text,
  id_atendimento text,
  prontuario text,
  agendado_em timestamp,
  data_exame date,
  horario text,
  exame text,
  convenio text,
  forma_pagamento text,
  responsavel text,
  valor numeric,
  confirm_status text,
  cancelada boolean,
  atendido boolean,
  motivo_cancelamento text,
  observacao text,
  paciente text,
  celular text,
  telefone text,
  unidade text,
  atualizado_em timestamptz
)
language sql
security definer
set search_path = ''
stable
as $$
  with vigente as (
    select distinct on (v.linha->>'col0') v.linha as l, v.last_seen_at
    from public.v_relatorio_linha_vigente v
    join public.dim_relatorio r on r.id = v.relatorio_id
    where r.klingo_id = '13825'
      and coalesce(v.linha->>'col0', '') <> ''
      and coalesce(v.linha->>'col4', '') ~ '^\d{4}-\d{2}-\d{2}'
    order by v.linha->>'col0', v.last_seen_at desc
  ),
  base as (
    select l, last_seen_at,
           (l->>'col4')::timestamp as quando,
           translate(upper(coalesce(l->>'col5', '')), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC') as proc_norm,
           translate(upper(coalesce(l->>'col6', '')), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC') as conv_norm
    from vigente
  )
  select b.l->>'col0',
         nullif(b.l->>'col1', ''),
         nullif(b.l->>'col2', ''),
         case when coalesce(b.l->>'col3', '') ~ '^\d{4}-\d{2}-\d{2}' then (b.l->>'col3')::timestamp end,
         b.quando::date,
         to_char(b.quando, 'HH24:MI'),
         coalesce(e.nome, b.l->>'col5'),
         coalesce(c.nome, nullif(b.l->>'col6', '')),
         coalesce(c.tipo, case when b.conv_norm = 'PARTICULAR' then 'Particular' else 'Convênio' end),
         nullif(b.l->>'col7', ''),
         case when coalesce(b.l->>'col8', '') ~ '^[0-9]+(\.[0-9]+)?$' then (b.l->>'col8')::numeric end,
         nullif(b.l->>'col10', ''),
         b.l->>'col12' = 'Cancelada',
         b.l->>'col13' = 'S',
         nullif(b.l->>'col11', ''),
         nullif(b.l->>'col9', ''),
         nullif(b.l->>'col15', ''),
         nullif(b.l->>'col16', ''),
         nullif(b.l->>'col17', ''),
         nullif(b.l->>'col14', ''),
         b.last_seen_at
  from base b
  left join public.crm_rm_exame e on translate(upper(e.nome), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC') = b.proc_norm
  left join public.crm_rm_convenio c on translate(upper(c.nome), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC') = b.conv_norm
  where b.quando::date between p_de and p_ate
    and (public.can_view_painel('crm_rm') or public.pode_preencher_crm_rm())
    and b.proc_norm !~ '^(PCTE|CONTRASTE)'
    and (e.id is not null or b.proc_norm ~ '^(RM |ANGIO-?RM|COLANGIO)')
  order by b.quando, b.l->>'col0';
$$;

revoke execute on function public.crm_rm_agenda_klingo(date, date) from public, anon;
grant execute on function public.crm_rm_agenda_klingo(date, date) to authenticated;
