-- Painéis que cada usuário marcou para aparecer já embutidos na tela de Início,
-- para visualização rápida sem precisar abrir o painel completo pelo menu.
create table if not exists public.painel_favoritos (
  user_id uuid not null references auth.users (id) on delete cascade,
  painel_id text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, painel_id)
);

comment on table public.painel_favoritos is 'Favoritos da tela de Início, por usuário. painel_id é o id do painel em modulos.json/PAINEIS; a permissão real de ver aquele painel continua sendo checada em profiles.permissions (podeVerPainel), esta tabela só guarda a preferência de exibição.';

alter table public.painel_favoritos enable row level security;

-- Cada usuário só vê e altera os próprios favoritos.
create policy "painel_favoritos_select_own"
  on public.painel_favoritos
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "painel_favoritos_insert_own"
  on public.painel_favoritos
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "painel_favoritos_delete_own"
  on public.painel_favoritos
  for delete
  to authenticated
  using (user_id = auth.uid());
