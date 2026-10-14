-- Gráficos que cada usuário escolheu para aparecer na tela de Início: não a página inteira do painel, só o bloco específico
-- (um gráfico, o conjunto de números principais ou uma tabela), identificado pela aba do painel (Resumo, Análise, ...) e pelo título.
-- `chave` é o título normalizado pelo painel_base.js (sem mês/ano e sem números): é ela que acha o bloco de novo quando o mês muda;
-- `titulo` é só o texto mostrado no cartão.
create table if not exists public.painel_favoritos_itens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  painel_id text not null,
  aba text not null check (char_length(aba) between 1 and 60),
  chave text not null check (char_length(chave) between 1 and 200),
  titulo text not null check (char_length(titulo) between 1 and 200),
  created_at timestamptz not null default now(),
  unique (user_id, painel_id, aba, chave)
);

comment on table public.painel_favoritos_itens is 'Gráficos favoritos da tela de Início, por usuário. painel_id é o id do painel em modulos.json; a permissão de ver aquele painel continua sendo checada em profiles.permissions (podeVerPainel), esta tabela só guarda a preferência de exibição. Substitui painel_favoritos (painel inteiro), que deixou de ser usada.';

alter table public.painel_favoritos_itens enable row level security;

-- Cada usuário só vê e altera os próprios favoritos.
create policy "painel_favoritos_itens_select_own"
  on public.painel_favoritos_itens
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "painel_favoritos_itens_insert_own"
  on public.painel_favoritos_itens
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "painel_favoritos_itens_delete_own"
  on public.painel_favoritos_itens
  for delete
  to authenticated
  using (user_id = auth.uid());
