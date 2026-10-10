-- Três melhorias pedidas sobre o data warehouse de relatórios:
--
-- 1) Evitar duplicata de informação quando dois relatórios do Klingo têm o
--    mesmo nome (geralmente uma versão antiga e uma mais nova, com IDs
--    diferentes): a regra passa a ser "o número mais alto vence". Isso é
--    reforçado em duas camadas: um índice único que nunca deixa dois
--    relatórios com o mesmo nome ficarem ativos ao mesmo tempo, e a coluna
--    `supersedido_por`, que aponta o relatório antigo pro novo (a Edge
--    Function também passa a pular qualquer relatório superseded, mesmo que
--    `ativo` tenha sido marcado true por engano).
-- 2) ETL mais robusto: isso aqui é só o lado do schema (o retry/validação
--    fica na Edge Function); o índice único acima também é uma rede de
--    segurança contra duplicata a nível de banco, não só de aplicação.
-- 3) Mapear em qual relatório está cada informação: `dim_relatorio_coluna`
--    guarda, por relatório, quais chaves de coluna (col1, col2...) já foram
--    observadas e que tipo de valor cada uma costuma ter. O rótulo humano
--    (o que a coluna realmente significa) fica em branco de propósito — a
--    Edge Function nunca escreve nele, só o preenche quem for conferir o
--    relatório no Klingo e rodar um `update`. Isso evita a função "chutar"
--    um nome errado pra coluna.

alter table public.dim_relatorio
  add column if not exists supersedido_por uuid references public.dim_relatorio (id);

comment on column public.dim_relatorio.supersedido_por is 'Aponta para o relatório que substitui este (mesmo nome, klingo_id mais novo). Quando preenchido, a Edge Function pula este relatório mesmo que ativo=true.';

-- Nunca dois relatórios com o mesmo nome ativos ao mesmo tempo — é a rede de
-- segurança que impede duplicar a mesma informação sob dois klingo_id
-- diferentes.
create unique index if not exists dim_relatorio_nome_ativo_uq
  on public.dim_relatorio (nome)
  where ativo;

-- Caso já identificado nas screenshots: "Faturas Emitidas" existe como
-- #13149 e #12756. 13149 > 12756, então 13149 é o vigente; 12756 fica
-- marcado como superseded e nunca mais pode ser ativado por engano (o
-- índice único acima barraria de qualquer forma, mas isso deixa explícito
-- o porquê).
update public.dim_relatorio
set supersedido_por = (select id from public.dim_relatorio where klingo_id = '13149'),
    observacoes = 'Superseded pelo #13149 (mesmo nome, ID mais novo) — regra "número mais alto vence" pra evitar duplicar a mesma informação sob dois IDs.'
where klingo_id = '12756';

-- Dicionário de colunas: o que já se sabe sobre cada "colN" de cada
-- relatório. Preenchido automaticamente (coluna_key, tipo_observado) pela
-- Edge Function a cada sync; rotulo é manual.
create table if not exists public.dim_relatorio_coluna (
  id uuid primary key default gen_random_uuid(),
  relatorio_id uuid not null references public.dim_relatorio (id) on delete cascade,
  coluna_key text not null,
  rotulo text,
  tipo_observado text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (relatorio_id, coluna_key)
);

comment on table public.dim_relatorio_coluna is 'Dicionário de colunas por relatório: quais chaves (col1, col2...) já foram observadas e que tipo de valor costumam ter. rotulo é preenchido manualmente por quem confere o relatório no Klingo — a Edge Function nunca escreve nele, só em coluna_key/tipo_observado/last_seen_at.';
comment on column public.dim_relatorio_coluna.rotulo is 'O que a coluna significa de fato (ex.: "nome do convênio"). Preencher manualmente via SQL Editor depois de conferir o relatório no Klingo.';
comment on column public.dim_relatorio_coluna.tipo_observado is 'Tipo do último valor não nulo visto nessa coluna (string, number, boolean, null, object, array) — pista automática, não substitui o rotulo.';

alter table public.dim_relatorio_coluna enable row level security;

create policy "dim_relatorio_coluna_select_authenticated"
  on public.dim_relatorio_coluna
  for select
  to authenticated
  using (true);

-- Mesmo padrão das outras tabelas: sem policy de insert/update/delete pra
-- authenticated/anon. A Edge Function grava via service_role; o rotulo
-- manual também é preenchido via SQL Editor (role postgres, ignora RLS).
