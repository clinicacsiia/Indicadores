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

comment on table public.profiles is 'O que cada usuário autenticado pode ver no painel. role=admin libera a tela de Configurações; permissions.relatorios=false bloqueia a leitura dos indicadores.';

alter table public.profiles enable row level security;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row
  execute function public.set_updated_at();

-- security definer + search_path vazio: evita recursão de RLS (a policy de
-- select em profiles não pode depender de uma query que passe pela própria
-- policy) e evita sequestro da função por um schema malicioso.
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

-- Admin sempre vê Relatórios; viewer só se permissions.relatorios não for false.
create or replace function public.can_view_relatorios()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin' or coalesce((permissions ->> 'relatorios')::boolean, true))
  );
$$;

-- Cria o perfil automaticamente quando um usuário é criado no Supabase Auth.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

-- Funções security definer não devem ser chamáveis como RPC por anon/público.
-- is_admin e can_view_relatorios só precisam rodar para "authenticated" (RLS).
revoke execute on function public.is_admin() from public, anon;
revoke execute on function public.can_view_relatorios() from public, anon;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
grant execute on function public.is_admin() to authenticated;
grant execute on function public.can_view_relatorios() to authenticated;

create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function public.handle_new_user();

-- Usuários que já existiam antes desta migration (nascem como viewer)
insert into public.profiles (id, email)
select id, email from auth.users
on conflict (id) do nothing;

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
