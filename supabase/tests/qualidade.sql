-- Testa a migration 20261022100000_aba_qualidade.sql num Postgres vazio (sem Supabase): papéis e auth.uid() são simulados aqui.
--
--   createdb qualidade_teste && psql -v ON_ERROR_STOP=1 -d qualidade_teste -f supabase/tests/qualidade.sql    (na raiz do repositório)
--
-- Termina com `raise exception` se algo não for o esperado; chegando ao fim, imprime "QUALIDADE OK".
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

\i supabase/migrations/20261022100000_aba_qualidade.sql

insert into auth.users values
  ('00000000-0000-0000-0000-00000000000a'), ('00000000-0000-0000-0000-00000000000b'),
  ('00000000-0000-0000-0000-00000000000c'), ('00000000-0000-0000-0000-00000000000d'), ('00000000-0000-0000-0000-00000000000e');
insert into public.profiles (id, email, role, permissions) values
  ('00000000-0000-0000-0000-00000000000a', 'adm@csi.local',  'admin',  '{}'),
  ('00000000-0000-0000-0000-00000000000b', 'ana@csi.local',  'viewer', '{"qualidade_preencher": true}'),
  ('00000000-0000-0000-0000-00000000000c', 'bia@csi.local',  'viewer', '{"qualidade": true}'),
  ('00000000-0000-0000-0000-00000000000d', 'caio@csi.local', 'viewer', '{}'),
  ('00000000-0000-0000-0000-00000000000e', 'duda@csi.local', 'viewer', '{"qualidade_preencher": false, "qualidade": false}');

create function pg_temp.como(u text) returns void language plpgsql as $$
begin
  perform set_config('request.jwt.claim.sub', u, false);
  execute 'set role authenticated';
end $$;

create function pg_temp.deve_falhar(sql text, esperado text) returns void language plpgsql as $$
begin
  begin
    execute sql;
  exception when others then
    if sqlerrm like '%' || esperado || '%' then return; end if;
    raise exception 'falhou por outro motivo (%): %', esperado, sqlerrm;
  end;
  raise exception 'deveria falhar (%): %', esperado, sql;
end $$;

-- Ana (só preenche) lança e vê só o que lançou
select pg_temp.como('00000000-0000-0000-0000-00000000000b');
insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, gravidade, descricao, criado_por)
  values (current_date, 'CSI 1', 'Recepção', 'reclamacao', 'media', 'Paciente esperou mais de uma hora na recepção.', auth.uid());
-- não pode lançar em nome de outra pessoa, nem como "exemplo", nem já resolvida, nem no futuro
select pg_temp.deve_falhar($q$insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por) values (current_date, 'CSI 1', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', '00000000-0000-0000-0000-00000000000c')$q$, 'row-level security');
select pg_temp.deve_falhar($q$insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por, exemplo) values (current_date, 'CSI 1', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', auth.uid(), true)$q$, 'permission denied');
select pg_temp.deve_falhar($q$insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por) values (current_date + 3, 'CSI 1', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', auth.uid())$q$, 'row-level security');

create function pg_temp.conta(sql text) returns bigint language plpgsql as $$
declare n bigint; begin execute sql into n; return n; end $$;
create function pg_temp.afeta(sql text) returns bigint language plpgsql as $$
declare n bigint; begin execute sql; get diagnostics n = row_count; return n; end $$;
create function pg_temp.espera(obtido bigint, esperado bigint, quem text) returns void language plpgsql as $$
begin if obtido is distinct from esperado then raise exception '%: esperava %, veio %', quem, esperado, obtido; end if; end $$;

select pg_temp.espera(pg_temp.conta('select count(*) from public.ocorrencia'), 1, 'Ana vê o que lançou');
-- não pode resolver nem apagar (preencher não é ver o indicador)
select pg_temp.espera(pg_temp.afeta($q$update public.ocorrencia set status = 'resolvida', resolvida_em = current_date$q$), 0, 'Ana resolvendo');
select pg_temp.espera(pg_temp.afeta('delete from public.ocorrencia'), 0, 'Ana apagando');
reset role;

-- Bia (só vê) não lança, mas lê tudo e resolve
select pg_temp.como('00000000-0000-0000-0000-00000000000c');
select pg_temp.deve_falhar($q$insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por) values (current_date, 'CSI 1', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', auth.uid())$q$, 'row-level security');
select pg_temp.espera(pg_temp.conta('select count(*) from public.ocorrencia'), 1, 'Bia lê tudo');
select pg_temp.deve_falhar($q$update public.ocorrencia set descricao = 'trocando o texto de outra pessoa'$q$, 'permission denied');
select pg_temp.deve_falhar($q$update public.ocorrencia set status = 'resolvida'$q$, 'ocorrencia_check');   -- resolvida exige a data
select pg_temp.espera(pg_temp.afeta($q$update public.ocorrencia set status = 'resolvida', resolvida_em = current_date$q$), 1, 'Bia resolvendo');
select pg_temp.espera(pg_temp.afeta('delete from public.ocorrencia'), 0, 'Bia apagando');
reset role;

-- Caio (sem nada) e Duda (permissões falsas) não leem, não lançam
select pg_temp.como('00000000-0000-0000-0000-00000000000d');
select pg_temp.espera(pg_temp.conta('select count(*) from public.ocorrencia'), 0, 'Caio lendo');
select pg_temp.deve_falhar($q$insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por) values (current_date, 'CSI 1', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', auth.uid())$q$, 'row-level security');
reset role;
select pg_temp.como('00000000-0000-0000-0000-00000000000e');
select pg_temp.espera(pg_temp.conta('select count(*) from public.ocorrencia'), 0, 'Duda lendo');
select pg_temp.deve_falhar($q$insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por) values (current_date, 'CSI 1', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', auth.uid())$q$, 'row-level security');
reset role;

-- Sem login (anon) não toca em nada
set role anon;
select pg_temp.deve_falhar('select count(*) from public.ocorrencia', 'permission denied');
reset role;

-- Administrador lança, lê tudo e apaga; elogio não pode ficar "resolvido"
select pg_temp.como('00000000-0000-0000-0000-00000000000a');
insert into public.ocorrencia (data_ocorrencia, unidade, setor, tipo, descricao, criado_por)
  values (current_date, 'CSI 2', 'Coleta', 'elogio', 'Atendimento muito bom na coleta.', auth.uid());
select pg_temp.deve_falhar($q$update public.ocorrencia set status = 'resolvida', resolvida_em = current_date where tipo = 'elogio'$q$, 'ocorrencia_check');
select pg_temp.espera(pg_temp.conta('select count(*) from public.ocorrencia'), 2, 'Admin lê tudo');
select pg_temp.espera(pg_temp.afeta('delete from public.ocorrencia'), 2, 'Admin apaga');
reset role;

select 'QUALIDADE OK' as resultado;
