-- Aba "CRM Ressonância": funil da Ressonância Magnética (procura -> orçamento -> agendamento -> comparecimento -> realização)
-- lançado à mão pela equipe, para achar os gargalos antes de investir em captação. Sem nome, CPF ou dado clínico do paciente.
--
-- Duas permissões novas em profiles.permissions, as duas nascem DESLIGADAS:
--   crm_rm_preencher = lança e atualiza o que ela mesma lançou
--   crm_rm           = vê tudo (indicadores e listas), atualiza qualquer registro
-- Administrador tem as duas sempre.

create or replace function public.crm_rm_toca_atualizado()
returns trigger
language plpgsql
as $$
begin
  new.atualizado_em := now();
  return new;
end;
$$;

-- Uma linha por solicitação de exame recebida (aba "CRM - Contatos")
create table if not exists public.crm_rm_contato (
  id                bigint generated always as identity primary key,
  data_contato      date not null,
  canal             text not null check (canal in ('WhatsApp', 'Telefone', 'Site', 'Google', 'Instagram', 'Indicação médica', 'Presencial', 'Outro')),
  tipo_paciente     text not null check (tipo_paciente in ('Novo paciente', 'Paciente já atendido')),
  exame             text not null check (exame in ('Crânio / encéfalo', 'Coluna cervical', 'Coluna torácica', 'Coluna lombar', 'Joelho', 'Ombro', 'Quadril / bacia', 'Pé / tornozelo', 'Mão / punho', 'Abdome', 'Pelve', 'Mama', 'Angiorressonância', 'Outro')),
  forma_pagamento   text not null check (forma_pagamento in ('Particular', 'Convênio')),
  convenio          text check (convenio is null or char_length(convenio) <= 60),
  valor_informado   numeric(10, 2) check (valor_informado is null or valor_informado >= 0),
  situacao          text not null default 'Novo contato' check (situacao in ('Novo contato', 'Orçamento enviado', 'Aguardando resposta', 'Aguardando autorização', 'Agendado', 'Não agendou', 'Desistiu')),
  motivo_perda      text check (motivo_perda in ('Preço', 'Convênio não atendido', 'Sem vaga na data desejada', 'Demora na resposta', 'Autorização negada', 'Preparo / contraindicação', 'Preferiu outra clínica', 'Não respondeu', 'Outro')),
  data_ultimo_contato date,
  proxima_acao      text check (proxima_acao in ('Ligar', 'Enviar WhatsApp', 'Reenviar orçamento', 'Verificar vaga', 'Acompanhar autorização', 'Sem ação')),
  data_retorno      date,
  responsavel       text check (responsavel is null or char_length(responsavel) <= 60),
  observacoes       text check (observacoes is null or char_length(observacoes) <= 500),
  criado_por        uuid default auth.uid() references auth.users (id) on delete set null,
  criado_em         timestamptz not null default now(),
  atualizado_em     timestamptz not null default now(),
  -- true = linha de demonstração (apague com: delete from public.crm_rm_contato where exemplo)
  exemplo           boolean not null default false,
  -- perdeu = tem motivo; não perdeu = não tem
  check ((situacao in ('Não agendou', 'Desistiu')) = (motivo_perda is not null)),
  check (data_retorno is null or data_retorno >= data_contato),
  check (data_ultimo_contato is null or data_ultimo_contato >= data_contato)
);

-- Uma linha por horário reservado (aba "Agenda - RM"); reagendamento NÃO é contato novo
create table if not exists public.crm_rm_agenda (
  id                bigint generated always as identity primary key,
  contato_id        bigint references public.crm_rm_contato (id) on delete set null,
  data_exame        date not null,
  horario           time,
  forma_pagamento   text not null check (forma_pagamento in ('Particular', 'Convênio')),
  exame             text not null check (exame in ('Crânio / encéfalo', 'Coluna cervical', 'Coluna torácica', 'Coluna lombar', 'Joelho', 'Ombro', 'Quadril / bacia', 'Pé / tornozelo', 'Mão / punho', 'Abdome', 'Pelve', 'Mama', 'Angiorressonância', 'Outro')),
  status            text not null default 'Agendado' check (status in ('Agendado', 'Realizado', 'Faltou', 'Cancelado', 'Reagendado')),
  confirmacao       text not null default 'Não contatado' check (confirmacao in ('Confirmou', 'Não respondeu', 'Solicitou reagendamento', 'Não contatado')),
  motivo_falta      text check (motivo_falta in ('Esqueceu', 'Problema de transporte', 'Preparo inadequado', 'Autorização pendente', 'Doença / imprevisto', 'Outro')),
  vaga_recuperada   text not null default 'Não se aplica' check (vaga_recuperada in ('Sim', 'Não', 'Não se aplica')),
  valor_previsto    numeric(10, 2) check (valor_previsto is null or valor_previsto >= 0),
  valor_realizado   numeric(10, 2) check (valor_realizado is null or valor_realizado >= 0),
  horas_paradas     numeric(4, 1) check (horas_paradas is null or horas_paradas between 0 and 24),
  motivo_operacional text check (motivo_operacional in ('Equipamento parado', 'Bobina indisponível', 'Manutenção', 'Falta de profissional', 'Atraso no preparo', 'Outro')),
  criado_por        uuid default auth.uid() references auth.users (id) on delete set null,
  criado_em         timestamptz not null default now(),
  atualizado_em     timestamptz not null default now(),
  exemplo           boolean not null default false,
  check (valor_realizado is null or status = 'Realizado'),
  check (motivo_falta is null or status in ('Faltou', 'Cancelado', 'Reagendado')),
  check (vaga_recuperada = 'Não se aplica' or status in ('Faltou', 'Cancelado', 'Reagendado'))
);

comment on table public.crm_rm_contato is 'Aba CRM Ressonância: uma linha por solicitação de exame de RM (funil comercial). Sem dados de paciente. exemplo=true marca demonstração.';
comment on table public.crm_rm_agenda is 'Aba CRM Ressonância: uma linha por horário reservado na RM (comparecimento, falta, cancelamento, receita, ociosidade).';

create index if not exists crm_rm_contato_data_idx on public.crm_rm_contato (data_contato desc);
create index if not exists crm_rm_contato_criado_por_idx on public.crm_rm_contato (criado_por);
create index if not exists crm_rm_agenda_data_idx on public.crm_rm_agenda (data_exame desc);
create index if not exists crm_rm_agenda_criado_por_idx on public.crm_rm_agenda (criado_por);
create index if not exists crm_rm_agenda_contato_idx on public.crm_rm_agenda (contato_id);

create trigger crm_rm_contato_atualizado before update on public.crm_rm_contato
  for each row execute function public.crm_rm_toca_atualizado();
create trigger crm_rm_agenda_atualizado before update on public.crm_rm_agenda
  for each row execute function public.crm_rm_toca_atualizado();

create or replace function public.pode_preencher_crm_rm()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin' or coalesce(permissions -> 'crm_rm_preencher' = 'true'::jsonb, false))
  );
$$;

revoke execute on function public.pode_preencher_crm_rm() from public, anon;
grant  execute on function public.pode_preencher_crm_rm() to authenticated;

alter table public.crm_rm_contato enable row level security;
alter table public.crm_rm_agenda  enable row level security;

-- Vê tudo quem tem "crm_rm"; quem só preenche vê apenas o que lançou.
create policy "crm_rm_contato_select" on public.crm_rm_contato for select to authenticated
  using (public.can_view_painel('crm_rm') or (criado_por = auth.uid() and public.pode_preencher_crm_rm()));
create policy "crm_rm_agenda_select" on public.crm_rm_agenda for select to authenticated
  using (public.can_view_painel('crm_rm') or (criado_por = auth.uid() and public.pode_preencher_crm_rm()));

create policy "crm_rm_contato_insert" on public.crm_rm_contato for insert to authenticated
  with check (
    criado_por = auth.uid() and exemplo = false and public.pode_preencher_crm_rm()
    and data_contato <= (now() at time zone 'America/Sao_Paulo')::date
  );
-- O horário só pode apontar para um contato que a pessoa enxerga (a RLS do contato vale dentro do exists).
create policy "crm_rm_agenda_insert" on public.crm_rm_agenda for insert to authenticated
  with check (
    criado_por = auth.uid() and exemplo = false and public.pode_preencher_crm_rm()
    and (contato_id is null or exists (select 1 from public.crm_rm_contato c where c.id = contato_id))
  );

create policy "crm_rm_contato_update" on public.crm_rm_contato for update to authenticated
  using (public.can_view_painel('crm_rm') or (criado_por = auth.uid() and public.pode_preencher_crm_rm()))
  with check (public.can_view_painel('crm_rm') or (criado_por = auth.uid() and public.pode_preencher_crm_rm()));
create policy "crm_rm_agenda_update" on public.crm_rm_agenda for update to authenticated
  using (public.can_view_painel('crm_rm') or (criado_por = auth.uid() and public.pode_preencher_crm_rm()))
  with check (public.can_view_painel('crm_rm') or (criado_por = auth.uid() and public.pode_preencher_crm_rm()));

create policy "crm_rm_contato_delete_admin" on public.crm_rm_contato for delete to authenticated using (public.is_admin());
create policy "crm_rm_agenda_delete_admin"  on public.crm_rm_agenda  for delete to authenticated using (public.is_admin());

revoke all on public.crm_rm_contato, public.crm_rm_agenda from public, anon, authenticated;
grant select on public.crm_rm_contato, public.crm_rm_agenda to authenticated;
grant insert (data_contato, canal, tipo_paciente, exame, forma_pagamento, convenio, valor_informado, situacao, motivo_perda,
              data_ultimo_contato, proxima_acao, data_retorno, responsavel, observacoes, criado_por)
  on public.crm_rm_contato to authenticated;
grant update (situacao, motivo_perda, valor_informado, data_ultimo_contato, proxima_acao, data_retorno, responsavel, observacoes)
  on public.crm_rm_contato to authenticated;
grant insert (contato_id, data_exame, horario, forma_pagamento, exame, status, confirmacao, motivo_falta, vaga_recuperada,
              valor_previsto, valor_realizado, horas_paradas, motivo_operacional, criado_por)
  on public.crm_rm_agenda to authenticated;
grant update (data_exame, horario, status, confirmacao, motivo_falta, vaga_recuperada, valor_previsto, valor_realizado, horas_paradas, motivo_operacional)
  on public.crm_rm_agenda to authenticated;
grant delete on public.crm_rm_contato, public.crm_rm_agenda to authenticated;
