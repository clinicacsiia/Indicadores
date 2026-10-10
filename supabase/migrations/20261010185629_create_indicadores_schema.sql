-- Tabela de valores de indicadores sincronizados da API externa
create table if not exists public.indicadores (
  id uuid primary key default gen_random_uuid(),
  codigo text not null,
  nome text not null,
  valor numeric not null,
  unidade text,
  periodo date not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (codigo, periodo)
);

comment on table public.indicadores is 'Valores de indicadores sincronizados periodicamente da API externa. Escrita somente via service_role (Edge Function de sync).';

-- Log de execuções de sincronização, para auditoria e diagnóstico de falhas
create table if not exists public.sync_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'error')),
  records_synced integer not null default 0,
  error_message text
);

comment on table public.sync_runs is 'Auditoria das execuções do job de sincronização com a API externa.';

-- RLS habilitado por padrão em toda tabela nova: nada é lido ou escrito sem uma policy explícita
alter table public.indicadores enable row level security;
alter table public.sync_runs enable row level security;

-- Apenas usuários autenticados (login no site) podem ler indicadores
create policy "indicadores_select_authenticated"
  on public.indicadores
  for select
  to authenticated
  using (true);

-- Apenas usuários autenticados podem ler o histórico de sincronização
create policy "sync_runs_select_authenticated"
  on public.sync_runs
  for select
  to authenticated
  using (true);

-- Nenhuma policy de insert/update/delete é criada para "authenticated" ou "anon":
-- isso bloqueia qualquer escrita feita pelo navegador. Só a service_role
-- (usada exclusivamente dentro da Edge Function de sync, nunca no front-end)
-- consegue escrever, pois ela ignora RLS por padrão no Postgres do Supabase.

-- Mantém updated_at correto em cada atualização
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger indicadores_set_updated_at
  before update on public.indicadores
  for each row
  execute function public.set_updated_at();
