-- Aba "Planilha" do painel de Despesas (a planilha mensal de despesas e a lista de fornecedores CSI / CSI 2 que a equipe consultava).
-- Quatro tabelas de apoio, todas editáveis no Table Editor do Supabase. O painel (servidor Python, service_role) é quem lê; o navegador nunca chega nelas.
--   despesa_item        o layout da planilha: grupo > item, na ordem em que aparecem
--   despesa_de_para     categoria do Klingo -> item da planilha (confirmado = false é o que ainda precisa de conferência)
--   despesa_historico   valor de cada item nos meses de ANTES do Klingo (o painel usa o Klingo a partir do início confiável)
--   despesa_fornecedor  nome do fornecedor na planilha, o fornecedor do Klingo que entra nele (e a categoria, quando precisa separar) e o % que fica na CSI
create table if not exists public.despesa_item (
  grupo       text not null,
  item        text not null,
  ordem_grupo int  not null,
  ordem_item  int  not null,
  primary key (grupo, item)
);

create table if not exists public.despesa_de_para (
  categoria_klingo text primary key,
  grupo            text not null,
  item             text not null,
  confirmado       boolean not null default false,
  observacao       text,
  foreign key (grupo, item) references public.despesa_item (grupo, item) on update cascade
);

create table if not exists public.despesa_historico (
  mes    date not null check (mes = date_trunc('month', mes)::date),
  grupo  text not null,
  item   text not null,
  valor  numeric(14, 2) not null,
  origem text,
  primary key (mes, grupo, item),
  foreign key (grupo, item) references public.despesa_item (grupo, item) on update cascade
);

create table if not exists public.despesa_fornecedor (
  id               bigint generated always as identity primary key,
  ordem            int not null,
  nome_planilha    text not null,
  fornecedor_klingo text,
  categoria_klingo text,
  pct_csi          numeric(5, 2) not null default 50 check (pct_csi between 0 and 100)
);
create unique index if not exists despesa_fornecedor_regra_uq
  on public.despesa_fornecedor (nome_planilha, coalesce(fornecedor_klingo, ''), coalesce(categoria_klingo, ''));

comment on table public.despesa_item is 'Layout da aba Planilha do painel de Despesas: grupo > item, na ordem da planilha original.';
comment on table public.despesa_de_para is 'Categoria do Klingo -> item da planilha. confirmado=false: correspondência deduzida, a equipe ainda precisa conferir.';
comment on table public.despesa_historico is 'Valores mensais por item de antes do Klingo (planilha FORNECEDORES - 09.2026, aba Planilha2). Do início confiável em diante o painel usa o Klingo.';
comment on table public.despesa_fornecedor is 'Lista de fornecedores da planilha, com o fornecedor (e categoria) do Klingo que entra em cada um e o % que fica na CSI (o resto vai para a CSI 2). Sem fornecedor_klingo = linha da planilha ainda sem origem no Klingo.';

alter table public.despesa_item       enable row level security;
alter table public.despesa_de_para    enable row level security;
alter table public.despesa_historico  enable row level security;
alter table public.despesa_fornecedor enable row level security;

revoke all on public.despesa_item, public.despesa_de_para, public.despesa_historico, public.despesa_fornecedor from public, anon, authenticated;
grant  all on public.despesa_item, public.despesa_de_para, public.despesa_historico, public.despesa_fornecedor to service_role;
