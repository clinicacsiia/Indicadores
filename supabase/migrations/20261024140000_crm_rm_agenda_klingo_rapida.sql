-- A aba "CRM Ressonância" não carregava a agenda: `crm_rm_agenda_klingo` levava de 9 a 20 s e o papel `authenticated` do Supabase
-- cancela qualquer consulta que passe de 8 s (`statement_timeout`), então a tela mostrava "Não foi possível carregar os registros".
--
-- Causa: a função achava o relatório por um join com `dim_relatorio` (`r.klingo_id = '13825'`). Com o join, o planejador varria a
-- `fact_relatorio_linha` inteira (~190 mil linhas, de todos os relatórios) e lia o JSON de cada uma só para descartar o que não era do #13825.
-- Buscando o id do relatório antes (subconsulta escalar), ele usa o índice (relatorio_id, periodo) e lê só as ~15 mil linhas do #13825:
-- no mesmo banco, 9,4 s caem para ~1,1 s. O resultado é o mesmo; só mudou o jeito de achar o relatório.
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
    where v.relatorio_id = (select r.id from public.dim_relatorio r where r.klingo_id = '13825')
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

-- Quando o Klingo foi lido pela última vez para a agenda (fim da última coleta do #13825 que deu certo), para a tela mostrar a data.
-- Não depende de a agenda ter linhas: se a coleta rodou e não trouxe nada, a data continua aparecendo.
-- Mesma regra de acesso da agenda; para quem não tem acesso ao CRM devolve nulo, sem erro.
create or replace function public.crm_rm_agenda_atualizada_em()
returns timestamptz
language sql
security definer
set search_path = ''
stable
as $$
  select max(s.finished_at)
  from public.sync_relatorio_runs s
  where s.relatorio_id = (select r.id from public.dim_relatorio r where r.klingo_id = '13825')
    and s.status = 'success'
    and (public.can_view_painel('crm_rm') or public.pode_preencher_crm_rm());
$$;

revoke execute on function public.crm_rm_agenda_atualizada_em() from public, anon;
grant execute on function public.crm_rm_agenda_atualizada_em() to authenticated;
