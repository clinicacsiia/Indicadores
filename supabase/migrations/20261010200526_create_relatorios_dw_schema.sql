-- Camada "data warehouse" genérica: em vez de uma função por relatório (como
-- sync-indicadores, que só lê o 13397 e grava 4 agregados por dia), este
-- esquema permite cadastrar qualquer relatório do Klingo e gravar as linhas
-- cruas que ele retorna, sem precisar criar tabela nova a cada relatório.
--
-- ATENÇÃO LGPD: diferente de `indicadores` (que só guarda agregados sem
-- identificar paciente), `fact_relatorio_linha` grava a linha do relatório
-- como veio do Klingo — e vários relatórios desta clínica trazem dado
-- identificável (nome de paciente, CPF, etc. conforme o relatório). O select
-- continua restrito a `authenticated` (mesma postura de antes), mas isso é
-- decisão consciente de produto: avalie RLS adicional por coluna/linha ou
-- mascaramento antes de expor esses dados a mais gente além do painel atual.

-- Cadastro dos relatórios do Klingo que participam da sincronização.
-- Adicionar um relatório novo = inserir uma linha aqui (ativo = false até
-- validar que ele aceita o parâmetro de período padrão), não escrever código.
create table if not exists public.dim_relatorio (
  id uuid primary key default gen_random_uuid(),
  klingo_id text not null unique,
  nome text not null,
  categoria text,
  ativo boolean not null default false,
  periodicidade text,
  observacoes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.dim_relatorio is 'Dimensão: catálogo de relatórios do Klingo elegíveis para sincronização. ativo=false até confirmar que o relatório aceita o parâmetro de período usado pela Edge Function.';
comment on column public.dim_relatorio.klingo_id is 'ID do relatório no Klingo (parâmetro ?id= da API /info/relatorio).';
comment on column public.dim_relatorio.periodicidade is 'Texto livre (ex.: diario, mensal, pontual) — informativo, só para orientar quem for ativar o relatório.';

-- Fato: uma linha por linha de relatório efetivamente observada, deduplicada
-- por conteúdo. Reexecutar o sync para o mesmo relatório/dia é idempotente:
-- linha igual não gera nova linha (só atualiza last_seen_at); linha que
-- mudou de conteúdo vira uma nova linha com hash novo. Nada é apagado, então
-- isto funciona como histórico (estilo slowly-changing-dimension) em vez de
-- um retrato único que é sobrescrito a cada sync.
create table if not exists public.fact_relatorio_linha (
  id uuid primary key default gen_random_uuid(),
  relatorio_id uuid not null references public.dim_relatorio (id) on delete cascade,
  periodo date not null,
  linha jsonb not null,
  linha_hash text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (relatorio_id, periodo, linha_hash)
);

comment on table public.fact_relatorio_linha is 'Fato: linhas cruas dos relatórios do Klingo, deduplicadas por hash de conteúdo. Escrita somente via service_role (Edge Function de sync).';
comment on column public.fact_relatorio_linha.linha_hash is 'sha256 hex do JSON canônico da linha (chaves ordenadas). Usado para detectar o que realmente mudou sem comparar jsonb inteiro.';

create index if not exists fact_relatorio_linha_relatorio_periodo_idx
  on public.fact_relatorio_linha (relatorio_id, periodo);

-- Auditoria por relatório/dia sincronizado (equivalente a sync_runs, mas
-- granular o suficiente pra um relatório falhar sem derrubar os outros).
create table if not exists public.sync_relatorio_runs (
  id uuid primary key default gen_random_uuid(),
  relatorio_id uuid references public.dim_relatorio (id) on delete set null,
  periodo date,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'error')),
  linhas_sincronizadas integer not null default 0,
  error_message text
);

comment on table public.sync_relatorio_runs is 'Auditoria por relatório/dia das execuções do sync genérico de relatórios (sync-relatorios-dw).';

create index if not exists sync_relatorio_runs_relatorio_idx
  on public.sync_relatorio_runs (relatorio_id, started_at desc);

alter table public.dim_relatorio enable row level security;
alter table public.fact_relatorio_linha enable row level security;
alter table public.sync_relatorio_runs enable row level security;

create policy "dim_relatorio_select_authenticated"
  on public.dim_relatorio
  for select
  to authenticated
  using (true);

create policy "fact_relatorio_linha_select_authenticated"
  on public.fact_relatorio_linha
  for select
  to authenticated
  using (true);

create policy "sync_relatorio_runs_select_authenticated"
  on public.sync_relatorio_runs
  for select
  to authenticated
  using (true);

-- Nenhuma policy de insert/update/delete para authenticated/anon, mesmo
-- motivo das tabelas existentes: só a service_role (dentro da Edge Function)
-- escreve, pois ela ignora RLS.

create trigger dim_relatorio_set_updated_at
  before update on public.dim_relatorio
  for each row
  execute function public.set_updated_at();

-- Catálogo inicial dos relatórios já identificados no painel do Klingo desta
-- clínica (capturado em 10/10/2026 — o painel listava 101 relatórios ao
-- todo; os que faltam podem ser adicionados depois com o mesmo insert).
-- Todos entram inativos, exceto o 13397 (já validado pela sync-indicadores
-- original, que usa o mesmo formato de parâmetro de período).
insert into public.dim_relatorio (klingo_id, nome, categoria, ativo, observacoes)
values
  ('13397', 'AGENDADOS X REALIZADOS', 'Marcação', true, 'Já sincronizado via sync-indicadores (agregados); aqui também grava linha a linha.'),

  ('235', 'COMPRAS - Valor Total de Entrada por Período', 'Suprimentos', false, null),
  ('243', 'Relatório Consolidado de Estoque por Setor Solicitante', 'Suprimentos', false, null),
  ('13222', 'Suprimentos - Compras por Fornecedor (Notas Fiscais) - Mensal', 'Suprimentos', false, 'Mensal'),
  ('13385', 'Suprimentos - Movimentações', 'Suprimentos', false, null),
  ('13387', 'Suprimentos - Solicitações', 'Suprimentos', false, null),

  ('13510', 'CONSOLIDADO ANALÍTICO', 'Faturamento', false, null),
  ('21', 'Espelho Sintético', 'Faturamento', false, null),
  ('13328', 'Fatura - Faturas Não Baixadas - Mensal', 'Faturamento', false, 'Mensal'),
  ('13375', 'Faturamento - Glosas e Recursos', 'Faturamento', false, null),
  ('13374', 'Faturamento - Guias com Situação', 'Faturamento', false, null),
  ('13329', 'Guias - Controle de Produção do Faturamento por Convênio - Mensal', 'Faturamento', false, 'Mensal'),

  ('798', 'FINANCEIRO - ACOMPANHAMENTO DE LANÇAMENTO', 'Financeiro', false, null),
  ('13376', 'Financeiro - Conciliação de Créditos', 'Financeiro', false, null),
  ('13509', 'Financeiro - Despesas Detalhadas por Lançamento (Valor Líquido) - Mensal', 'Financeiro', false, 'Mensal'),
  ('13505', 'Financeiro - Evolução das Despesas por Categoria e Mês - Mensal', 'Financeiro', false, 'Mensal'),
  ('13295', 'Identificações de Créditos de Fatura - Recebimento por Convênio com Glosa, Impostos e Líquido - Mensal', 'Financeiro', false, 'Mensal'),
  ('26', 'RECEITA PRODUZIDA POR CENTRO DE RESULTADO', 'Financeiro', false, null),
  ('13297', 'Recebimento Particular (Múltiplo) - Recebimentos Particulares com Taxa e Líquido - Mensal', 'Financeiro', false, 'Mensal'),
  ('370', 'Repasse de Honorário Médico - OPME (em construção)', 'Financeiro', false, 'Relatório ainda em construção no Klingo.'),

  ('275', 'Acompanhamento de Retorno de Pacientes', 'Atendimentos', false, null),
  ('52', 'EXTRATO ANALÍTICO DE PRODUTIVIDADE POR CONVÊNIO', 'Atendimentos', false, null),
  ('319', 'RELATÓRIO DE PRODUÇÃO MÉDICA', 'Atendimentos', false, null),

  ('12712', 'Arquivos', 'Geral', false, 'Pode não aceitar filtro de período por dia — validar antes de ativar.'),
  ('12757', 'Atendimento por Serviço x Solicitante', 'Geral', false, null),
  ('13339', 'Atendimentos - Acompanhamento de Metas por Unidade e Procedimento - Mensal', 'Geral', false, 'Mensal'),
  ('13280', 'Atendimentos - Base Cesta de Exames - Mensal', 'Geral', false, 'Mensal'),
  ('13256', 'Atendimentos - Conferência Cadastro de Paciente x Envio PACS por Exame - Pontual', 'Geral', false, 'Pontual'),
  ('13284', 'Atendimentos - Exames por Faixa Etária e Sexo - Mensal', 'Geral', false, 'Mensal'),
  ('13285', 'Atendimentos - Procedimentos por Faixa Etária e Sexo - Mensal', 'Geral', false, 'Mensal'),
  ('6881', 'CADASTROS - MEDICAMENTOS X CODIGOS COBRANÇA', 'Geral', false, 'Pode não aceitar filtro de período por dia — validar antes de ativar.'),
  ('13355', 'Faturamento Consulta - Fatura', 'Geral', false, null),
  ('13149', 'Faturas Emitidas', 'Geral', false, null),
  ('12756', 'Faturas Emitidas', 'Geral', false, 'Mesmo nome do #13149 no painel, ID diferente — conferir qual é o atual antes de ativar.'),
  ('13302', 'Produção - Honorário Médico Mensal', 'Geral', false, 'Mensal'),
  ('13434', 'Teste retorno do pasciente', 'Geral', false, 'Nome sugere relatório de teste — confirmar se é pra produção antes de ativar.'),
  ('13437', 'Verificação de ID', 'Geral', false, 'Pode não aceitar filtro de período por dia — validar antes de ativar.'),

  ('12640', 'AGENDAMENTOS REALIZADOS POR ATENDENTE', 'Marcação', false, null),
  ('7', 'AGENDAS MARCADAS', 'Marcação', false, null),
  ('7128', 'ATENDIMENTO REALIZADO - CDM (COLABORADORA)', 'Marcação', false, null),
  ('13404', 'Atendimentos - Tempos de Espera e Fluxo na Recepção - Mensal', 'Marcação', false, 'Mensal'),
  ('13402', 'Atendimentos - Visão Gerencial de Produtividade, Espera e Receita - Mensal', 'Marcação', false, 'Mensal'),
  ('843', 'CAMPANHA - MEDICOS COM AGENDA', 'Marcação', false, null),
  ('19', 'CONFIRMAÇÃO DE AGENDA', 'Marcação', false, 'Pode não aceitar filtro de período por dia — validar antes de ativar.'),
  ('260', 'Confirmação de Agenda Programada', 'Marcação', false, null),
  ('47', 'MARCAÇÕES BLOQUEADAS E CANCELADAS', 'Marcação', false, null),
  ('18', 'PRODUTIVIDADE X EFETIVIDADE', 'Marcação', false, null),
  ('12624', 'RANKING DE AGENDAMENTOS', 'Marcação', false, null),
  ('12625', 'RANKING DE AGENDAMENTOS CONVERTIDOS', 'Marcação', false, null),
  ('681', 'Retorno Programado', 'Marcação', false, null)
on conflict (klingo_id) do nothing;
