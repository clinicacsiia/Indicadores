-- Indicadores CSI (site): esquema novo. Substitui o esquema do primeiro app (profiles, indicadores, dim_relatorio, fact_relatorio_linha...).
-- Regras gerais: RLS ligada em TODAS as tabelas; o navegador nunca le tabela de dados. So as rotas do servidor (service role) leem/gravam,
-- depois de checar sessao e permissao do menu. As unicas politicas abertas ao usuario logado sao as de leitura de dados nao sensiveis
-- (perfil proprio, lista de menus e versao dos dados, esta ultima para o Realtime avisar "atualizacao terminou").

-- ---------------------------------------------------------------- 0. limpeza do esquema antigo
do $$ begin
  begin perform cron.unschedule(jobname) from cron.job where jobname in ('sync-indicadores', 'sync-relatorios-dw', 'sync_indicadores', 'sync_relatorios_dw'); exception when others then null; end;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
drop function if exists public.handle_new_user() cascade;
drop view if exists public.v_etl_pendencias cascade;
drop table if exists public.etl_alertas cascade;
drop table if exists public.sync_relatorio_runs cascade;
drop table if exists public.sync_runs cascade;
drop table if exists public.fact_relatorio_linha cascade;
drop table if exists public.dim_relatorio_coluna cascade;
drop table if exists public.dim_relatorio cascade;
drop table if exists public.indicadores cascade;
drop table if exists public.profiles cascade;
drop function if exists public.is_admin() cascade;
drop function if exists public.can_view_relatorios() cascade;
drop function if exists public.set_updated_at() cascade;
drop function if exists public.registrar_alerta(text, text, text, text, uuid, uuid, date, jsonb, boolean) cascade;
drop function if exists public.analisar_duplicata_nome(uuid) cascade;
drop function if exists public.analisar_sobreposicao_dados(uuid, date) cascade;
drop function if exists public.dim_relatorio_analisar_nome() cascade;

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- ---------------------------------------------------------------- 1. utilitarios
create or replace function public.tocar_atualizado_em() returns trigger language plpgsql as $$
begin new.atualizado_em := now(); return new; end $$;

-- ---------------------------------------------------------------- 2. perfis (1:1 com auth.users)
-- O Supabase Auth guarda a senha (hash/sal); aqui ficam so o nome de exibicao e as permissoes.
create table public.perfis (
  id uuid primary key references auth.users (id) on delete cascade,
  usuario text not null,
  admin boolean not null default false,
  relatorios text[] not null default '{}',              -- ids de menu liberados; '*' = todos
  sessoes_validas_desde timestamptz not null default now(),   -- trocar/redefinir a senha derruba as sessoes mais antigas que isto
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint perfis_usuario_formato check (usuario ~ '^[A-Za-z0-9._-]{2,32}$')
);
create unique index perfis_usuario_uq on public.perfis (lower(usuario));
create trigger perfis_tocar before update on public.perfis for each row execute function public.tocar_atualizado_em();
alter table public.perfis enable row level security;
create policy perfis_le_o_proprio on public.perfis for select to authenticated using (id = auth.uid());

create or replace function public.eh_admin() returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select admin from public.perfis where id = auth.uid()), false)
$$;

-- ---------------------------------------------------------------- 3. pedidos de cadastro
-- A senha escolhida NAO fica aqui: o usuario e criado no Supabase Auth ja bloqueado (banido) e so e liberado quando um admin aprova.
create table public.solicitacoes_cadastro (
  id uuid primary key default gen_random_uuid(),
  usuario text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  mensagem text not null default '' check (char_length(mensagem) <= 200),
  origem text,                                           -- hash do IP (limite de pedidos por hora)
  solicitado_em timestamptz not null default now()
);
create unique index solicitacoes_usuario_uq on public.solicitacoes_cadastro (lower(usuario));
create index solicitacoes_origem_idx on public.solicitacoes_cadastro (origem, solicitado_em);
alter table public.solicitacoes_cadastro enable row level security;

-- ---------------------------------------------------------------- 4. bloqueios de login (5 erros por usuario / 12 por IP)
create table public.tentativas_acesso (
  id bigserial primary key,
  tipo text not null check (tipo in ('usuario', 'ip')),
  chave text not null,                                   -- nome do usuario (minusculo) ou hash do IP
  quando timestamptz not null default now()
);
create index tentativas_acesso_idx on public.tentativas_acesso (tipo, chave, quando desc);
alter table public.tentativas_acesso enable row level security;

-- ---------------------------------------------------------------- 5. menus e configuracao
create table public.modulos (
  id text primary key,
  nome text not null,
  descricao text not null default '',
  tipo text not null check (tipo in ('metas', 'relatorios')),
  ativo boolean not null default true,
  ordem int not null,
  visoes_pdf text[] not null default '{}'               -- Atendimento: juliana, carla, luzia
);
alter table public.modulos enable row level security;
create policy modulos_le_logado on public.modulos for select to authenticated using (true);

create table public.configuracoes (
  chave text primary key,
  valor text not null,
  atualizado_em timestamptz not null default now()
);
alter table public.configuracoes enable row level security;
create trigger configuracoes_tocar before update on public.configuracoes for each row execute function public.tocar_atualizado_em();

-- ---------------------------------------------------------------- 6. atualizacoes
create table public.historico_atualizacoes (
  id bigserial primary key,
  modulo_id text not null,
  status text not null,                                  -- ok, aviso, erro, token_invalido, ja_em_dia...
  mensagem text not null default '',
  duracao_segundos numeric(10, 2) not null default 0,
  data_hora timestamptz not null default now(),
  usuario text not null default 'automático'
);
create index historico_atualizacoes_idx on public.historico_atualizacoes (data_hora desc);
alter table public.historico_atualizacoes enable row level security;

create table public.atualizacao_trava (                   -- uma atualizacao por vez no sistema inteiro, com prazo para nunca ficar presa
  id int primary key default 1 check (id = 1),
  em_andamento boolean not null default false,
  modulo text,
  usuario text,
  inicio timestamptz,
  expira_em timestamptz
);
insert into public.atualizacao_trava (id) values (1);
alter table public.atualizacao_trava enable row level security;

create table public.fila_sincronizacao (
  id bigserial primary key,
  lote uuid not null,
  menu text not null,
  tipo text not null default 'baixar' check (tipo in ('baixar', 'aquecer')),
  relatorio_id int,
  aba text,
  mes text,                                              -- AAAA-MM; nulo em relatorio sem filtro de data
  estado text not null default 'pendente' check (estado in ('pendente', 'executando', 'ok', 'erro', 'pulado')),
  tentativas int not null default 0,
  erro text,
  usuario text not null default 'automático',
  criado_em timestamptz not null default now(),
  iniciado_em timestamptz,
  finalizado_em timestamptz
);
create index fila_sincronizacao_estado_idx on public.fila_sincronizacao (estado, id);
create index fila_sincronizacao_lote_idx on public.fila_sincronizacao (lote);
alter table public.fila_sincronizacao enable row level security;

-- ---------------------------------------------------------------- 7. dados do Klingo
-- Uma linha por (menu, aba, mes): as linhas do relatorio em JSON + gzip + base64, com os titulos originais das colunas do Klingo.
-- (Decisao de arquitetura em docs/ARQUITETURA.md: o painel le o mes inteiro de uma vez; ~45 mil linhas vem em poucos blocos.)
create table public.dados_blocos (
  menu text not null,
  aba text not null,
  mes text not null check (mes ~ '^\d{4}-\d{2}$'),       -- "Mês (filtro)"
  colunas jsonb not null,
  linhas int not null default 0,
  conteudo text not null,
  atualizado_em timestamptz not null default now(),
  primary key (menu, aba, mes)
);
alter table public.dados_blocos enable row level security;

create table public.dados_versao (                        -- muda quando o menu recebe dados novos (chave do cache e "idade dos dados")
  menu text primary key,
  versao bigint not null default 1,
  atualizado_em timestamptz not null default now()
);
alter table public.dados_versao enable row level security;
create policy dados_versao_le_logado on public.dados_versao for select to authenticated using (true);
do $$ begin
  alter publication supabase_realtime add table public.dados_versao;
exception when others then null;
end $$;

create or replace function public.subir_versao(p_menu text) returns bigint language plpgsql security definer set search_path = public as $$
declare v bigint;
begin
  insert into public.dados_versao (menu, versao, atualizado_em) values (p_menu, 1, now())
  on conflict (menu) do update set versao = public.dados_versao.versao + 1, atualizado_em = now()
  returning versao into v;
  return v;
end $$;
revoke all on function public.subir_versao(text) from public, anon, authenticated;

create table public.painel_cache (                        -- pagina pronta de cada (menu, periodo): vale enquanto os dados e o dia nao mudam
  menu text not null,
  periodo text not null default '',
  chave_versao text not null,
  conteudo text not null,                                -- HTML em gzip + base64
  gerado_em timestamptz not null default now(),
  primary key (menu, periodo)
);
alter table public.painel_cache enable row level security;

create table public.custos_itens (                        -- Suprimentos: o administrador digita o custo; o painel preenche o resto
  item text primary key,
  grupo text,
  unidade text,
  embalagem text,
  fator numeric,
  custo_klingo numeric,
  custo numeric check (custo is null or custo >= 0),
  observacao text,
  atualizado_em timestamptz not null default now()
);
create trigger custos_itens_tocar before update on public.custos_itens for each row execute function public.tocar_atualizado_em();
alter table public.custos_itens enable row level security;

-- ---------------------------------------------------------------- 8. guia dos alertas e auditoria
create table public.pendencias_resolvidas (
  painel text not null,
  chave text not null,                                   -- escopo|id do alerta
  titulo text not null,
  usuario text not null,
  quando timestamptz not null default now(),
  versao bigint not null,                                -- versao dos dados no momento da marcacao
  primary key (painel, chave)
);
alter table public.pendencias_resolvidas enable row level security;

create table public.auditoria (
  id bigserial primary key,
  quando timestamptz not null default now(),
  usuario text,
  acao text not null,                                    -- entrou, senha_errada, atualizar, usuario_criado, pendencia_resolvida...
  detalhe jsonb not null default '{}',
  origem text                                            -- hash do IP
);
create index auditoria_quando_idx on public.auditoria (quando desc);
alter table public.auditoria enable row level security;

-- ---------------------------------------------------------------- 9. sementes
insert into public.modulos (id, nome, descricao, tipo, ativo, ordem, visoes_pdf) values
  ('metas', 'Metas', 'Acompanhamento de metas por unidade e procedimento', 'metas', true, 1, '{}'),
  ('faturamento', 'Faturamento', 'Receita produzida, faturas e convênios', 'relatorios', true, 2, '{}'),
  ('financeiro', 'Financeiro', 'A pagar, a receber e fluxo de caixa', 'relatorios', true, 3, '{}'),
  ('despesas', 'Despesas', 'Despesas por competência, previsão e repasse médico', 'relatorios', true, 4, '{}'),
  ('indicadores', 'Indicadores', 'Indicadores de produção, financeiro e glosas', 'relatorios', true, 5, '{}'),
  ('cesta', 'Cesta', 'Cesta de exames, combos e oportunidades', 'relatorios', true, 6, '{}'),
  ('suprimentos', 'Suprimentos', 'Estoque, pedidos e custos', 'relatorios', true, 7, '{}'),
  ('atendimento', 'Atendimento', 'Esperas, duração, fluxo na recepção e produtividade', 'relatorios', true, 8, '{juliana,carla,luzia}')
on conflict (id) do nothing;

insert into public.configuracoes (chave, valor) values
  ('intervalo_minimo_minutos', '30'),
  ('verificacao_automatica_minutos', '30'),
  ('intervalo_minimo_atualizar_agora_minutos', '5')
on conflict (chave) do nothing;

-- ---------------------------------------------------------------- 10. agendamento (pg_cron + pg_net chamando o site)
-- Rode UMA vez, depois do primeiro deploy:  select public.agendar_sincronizacao('https://SEU-SITE.vercel.app', 'MESMO-VALOR-DO-CRON_SECRET');
-- O segredo fica no Vault do Supabase (nunca no Git).
create or replace function public.agendar_sincronizacao(p_url text, p_segredo text) returns void language plpgsql security definer set search_path = public as $$
declare v_id uuid;
begin
  if p_url !~ '^https://' then raise exception 'use a URL https do site'; end if;
  select id into v_id from vault.secrets where name = 'csi_cron_secret';
  if v_id is null then perform vault.create_secret(p_segredo, 'csi_cron_secret', 'Segredo das rotas /api/cron do site');
  else perform vault.update_secret(v_id, p_segredo); end if;
  begin perform cron.unschedule('csi-verificar'); exception when others then null; end;
  begin perform cron.unschedule('csi-processar-fila'); exception when others then null; end;
  perform cron.schedule('csi-verificar', '*/30 * * * *', format($c$select net.http_post(url := %L, headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'csi_cron_secret'), 'Content-Type', 'application/json'), body := '{}'::jsonb, timeout_milliseconds := 55000)$c$, rtrim(p_url, '/') || '/api/cron/verificar'));
  perform cron.schedule('csi-processar-fila', '* * * * *', format($c$select net.http_post(url := %L, headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'csi_cron_secret'), 'Content-Type', 'application/json'), body := '{}'::jsonb, timeout_milliseconds := 55000)$c$, rtrim(p_url, '/') || '/api/cron/processar'));
end $$;
revoke all on function public.agendar_sincronizacao(text, text) from public, anon, authenticated;
