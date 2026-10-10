-- Perfis de acesso: um registro por usuário autenticado, com o que ele pode ver.
-- Fica separado de auth.users (que só guarda credenciais) para nunca misturar
-- senha com permissão, e para o front-end nunca precisar saber senha de ninguém.
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  role text not null default 'viewer' check (role in ('admin', 'viewer')),
  permissions jsonb not null default '{"relatorios": true}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.profiles is 'O que cada usuário autenticado pode ver no painel. role=admin libera a tela de Configurações.';

alter table public.profiles enable row level security;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row
  execute function public.set_updated_at();

-- security definer + search_path vazio: evita recursão de RLS (a policy de
-- select em profiles não pode chamar uma query que também dependa da policy
-- de profiles) e evita que a função seja sequestrada por um schema malicioso.
create or replace function public.is_admin()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles where id = auth.uid() and role = 'admin'
  );
$$;

-- Todo usuário vê o próprio perfil (precisa saber o que ele mesmo pode ver)
create policy "profiles_select_own"
  on public.profiles
  for select
  to authenticated
  using (id = auth.uid());

-- Admin vê todos os perfis, para a tela de Configurações
create policy "profiles_select_admin"
  on public.profiles
  for select
  to authenticated
  using (public.is_admin());

-- Só admin altera perfil (o próprio usuário nunca pode se promover a admin)
create policy "profiles_update_admin"
  on public.profiles
  for update
  to authenticated
  using (public.is_admin())
  with check (public.is_admin());

-- Cria o perfil automaticamente quando um usuário é criado (painel do
-- Supabase ou Admin API). Primeiro usuário nasce como "viewer"; promover a
-- admin é um update manual via SQL Editor (ver README), nunca pelo app.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function public.handle_new_user();
