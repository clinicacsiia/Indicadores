-- Painéis em Python (Faturamento, Financeiro, Despesas, Indicadores, Cesta,
-- Suprimentos, Atendimento) rodando na Vercel com os dados no Supabase.
--
-- No programa local esses painéis guardavam tudo em arquivos Excel (uma
-- planilha por painel) e num banco SQLite (marcações de "resolvido", histórico
-- de atualizações). Aqui o lugar desses arquivos passa a ser o Supabase.
--
-- SEGURANÇA: estas tabelas guardam as linhas dos relatórios do Klingo como
-- vieram (podem ter nome de paciente, CPF etc. — ver "ATENÇÃO LGPD" no README).
-- Por isso o RLS fica ligado SEM nenhuma policy e o acesso é revogado de anon e
-- authenticated: o navegador nunca lê nem escreve aqui. Só as funções Python da
-- Vercel (`api/*.py`), usando a service_role no servidor, depois de conferir o
-- login e a permissão do usuário (profiles.role = 'admin' ou
-- profiles.permissions.<id do painel> = true; painéis novos nascem bloqueados,
-- por terem dado financeiro e, em alguns, identificação de paciente).

-- ---------------------------------------------------------------- dados dos relatórios
-- Uma "aba" (= antiga aba da planilha) de um painel, por mês, em lotes de linhas.
-- O mês inteiro é SUBSTITUÍDO a cada atualização (igual ao Excel): as linhas novas
-- entram com uma `versao` nova e só depois painel_publicar_mes troca o ponteiro
-- e apaga a versão velha, então quem lê nunca vê um mês pela metade.
create table if not exists public.painel_dados (
  painel   text   not null,
  aba      text   not null,
  mes      text   not null check (mes ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  versao   text   not null,
  lote     int    not null,
  linhas   json   not null,   -- json (não jsonb): preserva a ordem das colunas do relatório
  n_linhas int    not null,
  primary key (painel, aba, mes, versao, lote)
);

create table if not exists public.painel_mes (
  painel        text        not null,
  aba           text        not null,
  mes           text        not null,
  versao        text        not null,
  n_linhas      int         not null default 0,
  atualizado_em timestamptz not null default now(),
  primary key (painel, aba, mes)
);

comment on table public.painel_dados is 'Linhas dos relatórios do Klingo usadas pelos painéis em Python (lotes por painel/aba/mês/versão). Acesso só pela service_role.';
comment on table public.painel_mes is 'Qual versão de cada painel/aba/mês está valendo e quando foi atualizada (equivale à data do arquivo Excel).';

-- Só o que está valendo (versão apontada em painel_mes).
create or replace view public.painel_dados_ativos with (security_invoker = true) as
  select d.painel, d.aba, d.mes, d.lote, d.linhas, m.atualizado_em
  from public.painel_dados d
  join public.painel_mes m
    on m.painel = d.painel and m.aba = d.aba and m.mes = d.mes and m.versao = d.versao;

-- Troca atômica do mês. `p_exclusivo` = relatório sem filtro de data (vem inteiro
-- a cada baixa): tudo que existia de outros meses nessa aba sai.
create or replace function public.painel_publicar_mes(
  p_painel text, p_aba text, p_mes text, p_versao text, p_n_linhas int, p_exclusivo boolean default false
)
returns void
language plpgsql
set search_path = ''
as $$
begin
  if p_n_linhas > 0 and not exists (
    select 1 from public.painel_dados
    where painel = p_painel and aba = p_aba and mes = p_mes and versao = p_versao
  ) then
    raise exception 'Nenhum lote gravado para % / % / % (versão %)', p_painel, p_aba, p_mes, p_versao;
  end if;

  insert into public.painel_mes (painel, aba, mes, versao, n_linhas, atualizado_em)
  values (p_painel, p_aba, p_mes, p_versao, p_n_linhas, now())
  on conflict (painel, aba, mes)
  do update set versao = excluded.versao, n_linhas = excluded.n_linhas, atualizado_em = excluded.atualizado_em;

  delete from public.painel_dados
  where painel = p_painel and aba = p_aba and mes = p_mes and versao <> p_versao;

  if p_exclusivo then
    delete from public.painel_dados where painel = p_painel and aba = p_aba and mes <> p_mes;
    delete from public.painel_mes   where painel = p_painel and aba = p_aba and mes <> p_mes;
  end if;
end;
$$;

-- ---------------------------------------------------------------- páginas prontas
-- A conta de um painel (Cesta chega a levar mais de 1 min) é feita quando os dados
-- mudam; a tela só entrega o HTML pronto. `chave` = 'padrao' ou 'AAAA-MM..AAAA-MM'
-- (período de vários meses). `dados_versao` = versão dos dados usada; `dia` = dia
-- em que foi calculada (o painel depende da data de hoje).
create table if not exists public.painel_pagina (
  painel       text        not null,
  chave        text        not null,
  html         text        not null,
  dados_versao bigint      not null,
  dia          date        not null,
  gerado_em    timestamptz not null default now(),
  primary key (painel, chave)
);

-- ---------------------------------------------------------------- marcações e histórico
-- "Marcar como resolvido" dos alertas (valem para todos os usuários do painel).
create table if not exists public.painel_pendencia (
  painel  text        not null,
  chave   text        not null,
  titulo  text        not null default '',
  usuario text        not null default '',
  versao  bigint      not null default 0,
  quando  timestamptz not null default now(),
  primary key (painel, chave)
);

-- Quem atualizou o quê, quando e com que resultado.
create table if not exists public.painel_atualizacao (
  id               bigint generated always as identity primary key,
  painel           text             not null,
  usuario          text             not null default '',
  status           text             not null,
  mensagem         text             not null default '',
  duracao_segundos double precision not null default 0,
  criado_em        timestamptz      not null default now()
);

-- Custos de itens que a clínica informa à mão (antiga planilha "Custos dos
-- Itens.xlsx" do painel de Suprimentos). Preenchida pelo Table Editor do Supabase.
create table if not exists public.painel_custo_item (
  item          text primary key,
  custo         numeric(14, 4) check (custo is null or custo >= 0),
  observacao    text,
  atualizado_em timestamptz not null default now()
);

-- ---------------------------------------------------------------- travas
-- RLS ligado e nenhuma policy = negado para anon/authenticated. A service_role
-- (só no servidor) ignora RLS. Os revokes são a segunda camada.
alter table public.painel_dados      enable row level security;
alter table public.painel_mes        enable row level security;
alter table public.painel_pagina     enable row level security;
alter table public.painel_pendencia  enable row level security;
alter table public.painel_atualizacao enable row level security;
alter table public.painel_custo_item enable row level security;

revoke all on public.painel_dados, public.painel_mes, public.painel_pagina,
              public.painel_pendencia, public.painel_atualizacao, public.painel_custo_item,
              public.painel_dados_ativos
  from public, anon, authenticated;

revoke execute on function public.painel_publicar_mes(text, text, text, text, int, boolean) from public, anon, authenticated;
grant  execute on function public.painel_publicar_mes(text, text, text, text, int, boolean) to service_role;
grant  all on public.painel_dados, public.painel_mes, public.painel_pagina,
              public.painel_pendencia, public.painel_atualizacao, public.painel_custo_item,
              public.painel_dados_ativos
  to service_role;
