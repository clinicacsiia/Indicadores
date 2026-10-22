-- Testa a migration 20261022110000_crm_ressonancia.sql num Postgres vazio (sem Supabase): papéis e auth.uid() são simulados aqui.
--
--   createdb crm_rm_teste && psql -v ON_ERROR_STOP=1 -d crm_rm_teste -f supabase/tests/crm_rm.sql    (na raiz do repositório)
--
-- Termina com `raise exception` se algo não for o esperado; chegando ao fim, imprime "CRM RM OK".
\set ON_ERROR_STOP on

do $$ begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create table auth.users (id uuid primary key);
create table public.profiles (id uuid primary key, email text, role text not null default 'viewer', permissions jsonb not null default '{}'::jsonb, status text not null default 'ativo');
grant usage on schema public, auth to anon, authenticated;
grant select on public.profiles to authenticated;

create function public.is_admin() returns boolean language sql security definer set search_path = '' stable
  as $$ select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin') $$;
create function public.can_view_painel(p_painel text) returns boolean language sql security definer set search_path = '' stable
  as $$ select exists (select 1 from public.profiles where id = auth.uid() and (role = 'admin' or coalesce(permissions -> p_painel = 'true'::jsonb, false))) $$;
grant execute on function public.is_admin(), public.can_view_painel(text) to authenticated;

\i supabase/migrations/20261022110000_crm_ressonancia.sql

insert into auth.users values
  ('00000000-0000-0000-0000-00000000000a'), ('00000000-0000-0000-0000-00000000000b'), ('00000000-0000-0000-0000-00000000000c'),
  ('00000000-0000-0000-0000-00000000000d'), ('00000000-0000-0000-0000-00000000000e'), ('00000000-0000-0000-0000-00000000000f');
insert into public.profiles (id, email, role, permissions) values
  ('00000000-0000-0000-0000-00000000000a', 'adm@csi.local',  'admin',  '{}'),
  ('00000000-0000-0000-0000-00000000000b', 'ana@csi.local',  'viewer', '{"crm_rm_preencher": true}'),
  ('00000000-0000-0000-0000-00000000000c', 'bia@csi.local',  'viewer', '{"crm_rm": true}'),
  ('00000000-0000-0000-0000-00000000000d', 'caio@csi.local', 'viewer', '{}'),
  ('00000000-0000-0000-0000-00000000000e', 'duda@csi.local', 'viewer', '{"crm_rm_preencher": false, "crm_rm": false}'),
  ('00000000-0000-0000-0000-00000000000f', 'edu@csi.local',  'viewer', '{"crm_rm_preencher": true}');

create function pg_temp.como(u text) returns void language plpgsql as $$
begin perform set_config('request.jwt.claim.sub', u, false); execute 'set role authenticated'; end $$;
create function pg_temp.deve_falhar(sql text, esperado text) returns void language plpgsql as $$
begin
  begin execute sql;
  exception when others then
    if sqlerrm like '%' || esperado || '%' then return; end if;
    raise exception 'falhou por outro motivo (%): %', esperado, sqlerrm;
  end;
  raise exception 'deveria falhar (%): %', esperado, sql;
end $$;
create function pg_temp.conta(sql text) returns bigint language plpgsql as $$
declare n bigint; begin execute sql into n; return n; end $$;
create function pg_temp.afeta(sql text) returns bigint language plpgsql as $$
declare n bigint; begin execute sql; get diagnostics n = row_count; return n; end $$;
create function pg_temp.espera(obtido bigint, esperado bigint, quem text) returns void language plpgsql as $$
begin if obtido is distinct from esperado then raise exception '%: esperava %, veio %', quem, esperado, obtido; end if; end $$;

-- Ana (só preenche) lança contato e horário; vê só o que lançou
select pg_temp.como('00000000-0000-0000-0000-00000000000b');
insert into public.crm_rm_contato (data_contato, canal, tipo_paciente, exame, forma_pagamento, valor_informado, situacao, criado_por)
  values (current_date, 'WhatsApp', 'Novo paciente', 'Joelho', 'Particular', 650, 'Orçamento enviado', auth.uid());
insert into public.crm_rm_agenda (contato_id, data_exame, horario, forma_pagamento, exame, valor_previsto, criado_por)
  values ((select id from public.crm_rm_contato), current_date + 2, '08:30', 'Particular', 'Joelho', 650, auth.uid());
-- regras da tabela: perdeu exige motivo; motivo sem perda é erro; valor realizado só em exame realizado; retorno não pode ser antes do contato
select pg_temp.deve_falhar($q$update public.crm_rm_contato set situacao = 'Não agendou'$q$, 'crm_rm_contato_check');
select pg_temp.deve_falhar($q$update public.crm_rm_contato set motivo_perda = 'Preço'$q$, 'crm_rm_contato_check');
select pg_temp.deve_falhar($q$update public.crm_rm_agenda set valor_realizado = 650$q$, 'crm_rm_agenda_check');
select pg_temp.deve_falhar($q$update public.crm_rm_agenda set status = 'Realizado', motivo_falta = 'Esqueceu'$q$, 'crm_rm_agenda_check');
select pg_temp.deve_falhar($q$update public.crm_rm_contato set data_retorno = current_date - 5$q$, 'crm_rm_contato_check');
-- atualiza o próprio registro (o funil anda)
select pg_temp.espera(pg_temp.afeta($q$update public.crm_rm_contato set situacao = 'Não agendou', motivo_perda = 'Preço'$q$), 1, 'Ana atualizando o próprio');
select pg_temp.espera(pg_temp.afeta($q$update public.crm_rm_contato set situacao = 'Agendado', motivo_perda = null$q$), 1, 'Ana voltando para agendado');
-- não pode lançar em nome de outra pessoa, nem como exemplo, nem com data futura
select pg_temp.deve_falhar($q$insert into public.crm_rm_contato (data_contato, canal, tipo_paciente, exame, forma_pagamento, criado_por) values (current_date, 'Site', 'Novo paciente', 'Joelho', 'Particular', '00000000-0000-0000-0000-00000000000c')$q$, 'row-level security');
select pg_temp.deve_falhar($q$insert into public.crm_rm_contato (data_contato, canal, tipo_paciente, exame, forma_pagamento, criado_por, exemplo) values (current_date, 'Site', 'Novo paciente', 'Joelho', 'Particular', auth.uid(), true)$q$, 'permission denied');
select pg_temp.deve_falhar($q$insert into public.crm_rm_contato (data_contato, canal, tipo_paciente, exame, forma_pagamento, criado_por) values (current_date + 2, 'Site', 'Novo paciente', 'Joelho', 'Particular', auth.uid())$q$, 'row-level security');
-- não troca a autoria nem apaga
select pg_temp.deve_falhar($q$update public.crm_rm_contato set criado_por = '00000000-0000-0000-0000-00000000000c'$q$, 'permission denied');
select pg_temp.espera(pg_temp.afeta('delete from public.crm_rm_contato'), 0, 'Ana apagando');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_contato'), 1, 'Ana vê o que lançou');
reset role;

-- Edu (também preenche) não vê nem mexe no que a Ana lançou, nem liga o horário dele ao contato dela
select pg_temp.como('00000000-0000-0000-0000-00000000000f');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_contato'), 0, 'Edu vendo o da Ana');
select pg_temp.espera(pg_temp.afeta($q$update public.crm_rm_contato set situacao = 'Desistiu', motivo_perda = 'Outro'$q$), 0, 'Edu mexendo no da Ana');
select pg_temp.deve_falhar($q$insert into public.crm_rm_agenda (contato_id, data_exame, forma_pagamento, exame, criado_por) values ((select id from public.crm_rm_contato union all select 1 limit 1), current_date, 'Particular', 'Joelho', auth.uid())$q$, 'row-level security');
reset role;

-- Bia (só vê) não lança, mas lê e atualiza tudo; o painel de indicadores vem desses dados
select pg_temp.como('00000000-0000-0000-0000-00000000000c');
select pg_temp.deve_falhar($q$insert into public.crm_rm_contato (data_contato, canal, tipo_paciente, exame, forma_pagamento, criado_por) values (current_date, 'Site', 'Novo paciente', 'Joelho', 'Particular', auth.uid())$q$, 'row-level security');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_contato'), 1, 'Bia lê contatos');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_agenda'), 1, 'Bia lê agenda');
select pg_temp.espera(pg_temp.afeta($q$update public.crm_rm_agenda set status = 'Realizado', valor_realizado = 650$q$), 1, 'Bia atualizando');
select pg_temp.espera(pg_temp.afeta('delete from public.crm_rm_agenda'), 0, 'Bia apagando');
reset role;

-- Caio (nada) e Duda (permissões falsas) não leem nem lançam
select pg_temp.como('00000000-0000-0000-0000-00000000000d');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_contato'), 0, 'Caio lendo');
select pg_temp.deve_falhar($q$insert into public.crm_rm_contato (data_contato, canal, tipo_paciente, exame, forma_pagamento, criado_por) values (current_date, 'Site', 'Novo paciente', 'Joelho', 'Particular', auth.uid())$q$, 'row-level security');
reset role;
select pg_temp.como('00000000-0000-0000-0000-00000000000e');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_agenda'), 0, 'Duda lendo');
select pg_temp.deve_falhar($q$insert into public.crm_rm_agenda (data_exame, forma_pagamento, exame, criado_por) values (current_date, 'Particular', 'Joelho', auth.uid())$q$, 'row-level security');
reset role;

-- Sem login (anon)
set role anon;
select pg_temp.deve_falhar('select count(*) from public.crm_rm_contato', 'permission denied');
reset role;

-- Administrador lança, lê tudo e apaga (o horário é apagado junto: ON DELETE SET NULL não apaga a agenda, mas a agenda também é apagada aqui)
select pg_temp.como('00000000-0000-0000-0000-00000000000a');
select pg_temp.espera(pg_temp.conta('select count(*) from public.crm_rm_contato'), 1, 'Admin lê tudo');
select pg_temp.espera(pg_temp.afeta('delete from public.crm_rm_agenda'), 1, 'Admin apaga agenda');
select pg_temp.espera(pg_temp.afeta('delete from public.crm_rm_contato'), 1, 'Admin apaga contato');
reset role;

select 'CRM RM OK' as resultado;
