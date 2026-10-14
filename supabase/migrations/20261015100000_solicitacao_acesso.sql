-- Solicitação de acesso: quem não tem usuário pede o acesso na tela de login e um administrador aprova.
--
-- O pedido já cria o usuário no Supabase Auth (com a senha que a pessoa escolheu), mas ele nasce BLOQUEADO
-- (ban_duration, feito pela server action com a service role): sem aprovação ele não consegue nem entrar.
-- Esta coluna só serve para a tela de Configurações separar quem está esperando de quem já tem acesso.
alter table public.profiles
  add column if not exists status text not null default 'ativo' check (status in ('ativo', 'pendente')),
  add column if not exists nome text,
  add column if not exists solicitado_em timestamptz;

comment on column public.profiles.status is 'pendente = pediu acesso na tela de login e aguarda um administrador aprovar (o usuário fica bloqueado no Auth até lá); ativo = acesso normal.';
comment on column public.profiles.nome is 'Nome informado por quem pediu acesso, para o administrador saber quem é. Vazio para usuários criados direto pelo administrador.';
comment on column public.profiles.solicitado_em is 'Quando o acesso foi solicitado (só para status pendente ou aprovado depois de solicitar).';

-- Usuário pendente nunca pode ser tratado como "ativo" pelas funções de permissão, mesmo que o bloqueio do Auth falhe.
create or replace function public.is_admin()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles where id = auth.uid() and role = 'admin' and status = 'ativo'
  );
$$;

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
      and status = 'ativo'
      and (role = 'admin' or coalesce((permissions ->> 'relatorios')::boolean, true))
  );
$$;
