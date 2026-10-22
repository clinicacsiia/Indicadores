-- Aba "Qualidade": ocorrências, reclamações e elogios lançados à mão (o Klingo não traz esse dado).
--
-- Duas permissões novas em profiles.permissions, as duas nascem DESLIGADAS (quem não foi marcado em Configurações não vê nem lança):
--   qualidade_preencher = pode lançar (e ver os próprios lançamentos)
--   qualidade           = pode ver o indicador inteiro e marcar uma ocorrência como resolvida
-- Administrador tem as duas sempre.

create table if not exists public.ocorrencia (
  id              bigint generated always as identity primary key,
  data_ocorrencia date not null,
  unidade         text not null check (unidade in ('CSI 1', 'CSI 2', 'CSI Pediatria')),
  setor           text not null check (setor in ('Recepção', 'Coleta', 'Imagem', 'Consultório', 'Faturamento', 'Estrutura e limpeza', 'Outro')),
  tipo            text not null check (tipo in ('reclamacao', 'elogio', 'ocorrencia')),
  gravidade       text not null default 'baixa' check (gravidade in ('baixa', 'media', 'alta')),
  descricao       text not null check (char_length(btrim(descricao)) between 10 and 1000),
  status          text not null default 'aberta' check (status in ('aberta', 'resolvida')),
  resolvida_em    date,
  criado_por      uuid default auth.uid() references auth.users (id) on delete set null,
  criado_em       timestamptz not null default now(),
  -- true = linha de demonstração (pode apagar com: delete from public.ocorrencia where exemplo)
  exemplo         boolean not null default false,
  check ((status = 'resolvida') = (resolvida_em is not null)),
  check (resolvida_em is null or resolvida_em >= data_ocorrencia),
  -- elogio não tem o que resolver
  check (tipo <> 'elogio' or status = 'aberta')
);

comment on table public.ocorrencia is 'Aba Qualidade: ocorrências, reclamações e elogios lançados pela equipe. Escrita só pelo formulário do site (RLS); exemplo=true marca dado de demonstração.';

create index if not exists ocorrencia_data_idx on public.ocorrencia (data_ocorrencia desc);
create index if not exists ocorrencia_criado_por_idx on public.ocorrencia (criado_por);

create or replace function public.pode_preencher_qualidade()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin' or coalesce(permissions -> 'qualidade_preencher' = 'true'::jsonb, false))
  );
$$;

revoke execute on function public.pode_preencher_qualidade() from public, anon;
grant  execute on function public.pode_preencher_qualidade() to authenticated;

alter table public.ocorrencia enable row level security;

-- Quem vê o indicador lê tudo; quem só preenche lê apenas o que lançou.
create policy "ocorrencia_select"
  on public.ocorrencia for select to authenticated
  using (public.can_view_painel('qualidade') or criado_por = auth.uid());

create policy "ocorrencia_insert"
  on public.ocorrencia for insert to authenticated
  with check (
    criado_por = auth.uid()
    and exemplo = false
    and status = 'aberta'
    and public.pode_preencher_qualidade()
    and data_ocorrencia <= (now() at time zone 'America/Sao_Paulo')::date
  );

-- Resolver: quem vê o indicador. Só as colunas status e resolvida_em podem mudar (grant por coluna abaixo).
create policy "ocorrencia_update"
  on public.ocorrencia for update to authenticated
  using (public.can_view_painel('qualidade'))
  with check (public.can_view_painel('qualidade'));

create policy "ocorrencia_delete_admin"
  on public.ocorrencia for delete to authenticated
  using (public.is_admin());

revoke all on public.ocorrencia from public, anon, authenticated;
grant select on public.ocorrencia to authenticated;
grant insert (data_ocorrencia, unidade, setor, tipo, gravidade, descricao, criado_por) on public.ocorrencia to authenticated;
grant update (status, resolvida_em) on public.ocorrencia to authenticated;
grant delete on public.ocorrencia to authenticated;
