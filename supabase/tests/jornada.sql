-- Testa as migrations 20261101140000_jornada_modelo.sql, 20261101150000_jornada_pendencias.sql e 20261101160000_jornada_sincronizar.sql e 20261101170000_jornada_tempo_real.sql (quadro da Jornada: colunas,
-- regras do Klingo, movimentos à mão, chat, permissões, pendências, a leitura do #13825 que cria e move os cards e os avisos em tempo real) num Postgres vazio (sem Supabase): papéis, auth.uid() e as tabelas do data warehouse são simulados aqui.
--
--   createdb jornada_teste && psql -v ON_ERROR_STOP=1 -d jornada_teste -f supabase/tests/jornada.sql    (na raiz do repositório)
--
-- Cada cenário termina com `raise exception` se algo não for o esperado; chegando ao fim, imprime "JORNADA OK".
\set ON_ERROR_STOP on

do $$ begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create table public.profiles (id uuid primary key, email text, nome text, role text not null default 'viewer', permissions jsonb not null default '{}'::jsonb, status text not null default 'ativo');
create function public.is_admin() returns boolean language sql security definer set search_path = '' stable as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin') $$;
grant execute on function public.is_admin() to authenticated;
grant usage on schema public, auth to anon, authenticated, service_role;
grant select on public.profiles to authenticated;

create schema cron;
create table cron.agendados (nome text, agenda text, comando text);
create function cron.schedule(p_nome text, p_agenda text, p_comando text) returns bigint language sql as $$ insert into cron.agendados values (p_nome, p_agenda, p_comando) returning 1::bigint $$;


-- Realtime do Supabase: só registra o que seria enviado, e o canal só devolve o que a política deixa ler
create schema realtime;
create table realtime.messages (id bigserial primary key, topic text, event text, payload jsonb, private boolean);
alter table realtime.messages enable row level security;
create function realtime.send(payload jsonb, event text, topic text, private boolean default true) returns void language sql as $$ insert into realtime.messages (topic, event, payload, private) values (topic, event, payload, private) $$;
create function realtime.topic() returns text language sql stable as $$ select current_setting('realtime.topic', true) $$;
grant usage on schema realtime to authenticated;
grant select on realtime.messages to authenticated;

create table public.dim_relatorio (
  id uuid primary key default gen_random_uuid(), klingo_id text unique not null, nome text not null, ativo boolean not null default true,
  periodicidade text, granularidade text default 'dia', primeiro_mes date, meses_a_frente integer default 0, revisar_meses integer,
  filtro_periodo text, periodo_validado_em timestamptz, janela_dias integer default 1, supersedido_por uuid, pausado_ate timestamptz
);
create table public.dim_relatorio_coluna (id uuid primary key default gen_random_uuid(), relatorio_id uuid not null references public.dim_relatorio (id), coluna_key text, rotulo text, titulo_klingo text);
create table public.sync_relatorio_runs (
  id uuid primary key default gen_random_uuid(), relatorio_id uuid not null references public.dim_relatorio (id), periodo date not null,
  started_at timestamptz not null default now(), finished_at timestamptz, status text not null default 'running', linhas_sincronizadas integer, error_message text
);
create table public.fact_relatorio_linha (
  id uuid primary key default gen_random_uuid(), relatorio_id uuid not null references public.dim_relatorio (id), periodo date not null,
  linha jsonb, linha_hash text not null, first_seen_at timestamptz not null default now(), last_seen_at timestamptz not null default now(), repeticoes integer not null default 1,
  unique (relatorio_id, periodo, linha_hash)
);

\i supabase/migrations/20261014210000_avisos.sql
\i supabase/migrations/20261016120000_dados_financeiros.sql
\i supabase/migrations/20261017110000_aviso_informacao_e_previsao.sql

insert into public.dim_relatorio (klingo_id, nome, granularidade, filtro_periodo, periodo_validado_em) values
  ('13404', 'Fluxo na Recepção', 'dia', 'periodo0', now()), ('13825', 'Agendamentos', 'mes', 'periodo0', now()), ('13402', 'Visão Gerencial', 'mes', 'periodo0', now());

\i supabase/migrations/20261101120000_coleta_ritmo.sql
\i supabase/migrations/20261101140000_jornada_modelo.sql
\i supabase/migrations/20261101150000_jornada_pendencias.sql
\i supabase/migrations/20261101160000_jornada_sincronizar.sql
\i supabase/migrations/20261101170000_jornada_tempo_real.sql

-- gente: admin, quem tem a permissão da Jornada, quem não tem
insert into public.profiles (id, email, role, permissions, status) values
  ('00000000-0000-0000-0000-00000000000a', 'adm@csi.local',  'admin',  '{}', 'ativo'),
  ('00000000-0000-0000-0000-00000000000b', 'ana@csi.local',  'viewer', '{"jornada": true}', 'ativo'),
  ('00000000-0000-0000-0000-00000000000c', 'bia@csi.local',  'viewer', '{}', 'ativo');

-- ---------------------------------------------------------------- 1. colunas e transições
do $$
declare n integer;
begin
  select count(*) into n from public.jornada_coluna;
  if n <> 17 then raise exception 'esperava 17 colunas, achei %', n; end if;
  -- ninguém arrasta um card para uma coluna que é do Klingo
  if exists (select 1 from public.jornada_transicao t join public.jornada_coluna k on k.id = t.para where k.origem <> 'manual') then
    raise exception 'há transição manual para uma coluna do Klingo'; end if;
  -- e nenhuma transição manual sai de uma coluna de exceção do Klingo
  if exists (select 1 from public.jornada_transicao t join public.jornada_coluna k on k.id = t.de where k.etapa = 'excecao' and k.origem = 'klingo') then
    raise exception 'há transição manual saindo de uma exceção do Klingo'; end if;
  -- todo card manual consegue andar até Concluído
  if not exists (select 1 from public.jornada_transicao where para = 'concluido') then raise exception 'nada leva a Concluído'; end if;
end $$;

-- ---------------------------------------------------------------- 2. o que o Klingo pode fazer (matriz)
do $$
declare
  caso record;
begin
  for caso in
    select * from (values
      ('a_confirmar', 'confirmado', true), ('confirmado', 'a_confirmar', true),
      ('confirmado', 'em_atendimento', true), ('chegou', 'em_atendimento', true), ('a_confirmar', 'em_atendimento', true),
      ('finalizado', 'em_atendimento', false), ('laudo_pendente', 'confirmado', false), ('chegou', 'confirmado', false),
      ('confirmado', 'cancelado', true), ('a_confirmar', 'remarcado', true), ('chegou', 'cancelado', true),
      ('em_atendimento', 'cancelado', false), ('finalizado', 'cancelado', false), ('concluido', 'remarcado', false),
      ('confirmado', 'faltou', true), ('a_confirmar', 'faltou', true), ('chegou', 'faltou', false), ('em_atendimento', 'faltou', false),
      ('cancelado', 'a_confirmar', true), ('faltou', 'em_atendimento', true), ('remarcado', 'confirmado', true), ('perdido', 'a_confirmar', true),
      ('cancelado', 'faltou', false), ('faltou', 'cancelado', false),
      ('contato', 'a_confirmar', true), ('orcamento', 'confirmado', true), ('autorizacao', 'a_confirmar', true),
      ('confirmado', 'chegou', false), ('confirmado', 'finalizado', false), ('confirmado', 'perdido', false),   -- destino manual: nunca
      ('confirmado', 'confirmado', false), ('inexistente', 'confirmado', false), ('confirmado', 'inexistente', false)
    ) v (de, para, esperado)
  loop
    if public.jornada_klingo_pode_mover(caso.de, caso.para) is distinct from caso.esperado then
      raise exception 'Klingo % -> %: esperava %, deu %', caso.de, caso.para, caso.esperado, public.jornada_klingo_pode_mover(caso.de, caso.para);
    end if;
  end loop;
end $$;

-- cards de teste (inseridos como dono do banco, que ignora a RLS)
insert into public.jornada_paciente (prontuario, nome, celular) values ('P1', 'Paciente Um', '11999990001'), ('P2', 'Paciente Dois', '11999990002');
insert into public.jornada_card (paciente_chave, data_ref, unidade, coluna) values
  ('P1', current_date, 'CSI 2', 'confirmado'),        -- 1
  ('P2', current_date, 'CSI 2', 'a_confirmar'),       -- 2
  ('P3', current_date, 'CSI 1', 'cancelado'),         -- 3  (vazio: só exame cancelado)
  ('P4', current_date, 'CSI 1', 'confirmado'),        -- 4  (com exame ativo)
  ('manual:1', current_date, '', 'contato'),          -- 5  (card manual, sem exame)
  ('P6', current_date, 'CSI 2', 'chegou');            -- 6
insert into public.jornada_exame (card_id, marcacao_id, procedimento, status) values
  (3, 'M3', 'RM JOELHO', 'cancelado'), (4, 'M4', 'RX TORAX', 'confirmado'), (4, 'M4b', 'US ABDOME', 'cancelado'), (1, 'M1', 'RM CRANIO', 'confirmado');

-- ---------------------------------------------------------------- 3. aplicar o Klingo
do $$
declare r text; n integer;
begin
  if public.jornada_aplicar_klingo(1, 'confirmado') <> 'igual' then raise exception 'mesma coluna devia ser igual'; end if;
  if public.jornada_aplicar_klingo(1, 'em_atendimento', '{"marcacao":"M1"}') <> 'moveu' then raise exception 'confirmado -> em atendimento devia mover'; end if;
  if (select coluna from public.jornada_card where id = 1) <> 'em_atendimento' or (select versao from public.jornada_card where id = 1) <> 2 then raise exception 'card 1 devia estar em atendimento, versão 2'; end if;
  if not exists (select 1 from public.jornada_evento where card_id = 1 and tipo = 'movido' and origem = 'klingo' and de_coluna = 'confirmado' and para_coluna = 'em_atendimento') then raise exception 'faltou o evento de movimento'; end if;

  -- o Klingo diz "confirmado" mas a equipe já passou o card para Chegou: não puxa para trás; registra a divergência uma vez só
  if public.jornada_aplicar_klingo(6, 'confirmado') <> 'ignorado' then raise exception 'não podia puxar o card para trás'; end if;
  perform public.jornada_aplicar_klingo(6, 'confirmado');
  perform public.jornada_aplicar_klingo(6, 'confirmado');
  select count(*) into n from public.jornada_evento where card_id = 6 and tipo = 'divergencia';
  if n <> 1 then raise exception 'a divergência devia ser registrada uma vez, foi %', n; end if;
  if (select versao from public.jornada_card where id = 6) <> 1 then raise exception 'divergência não mexe no card'; end if;

  -- cancelamento depois do atendimento aberto é ignorado
  if public.jornada_aplicar_klingo(1, 'cancelado') <> 'ignorado' then raise exception 'cancelar depois do atendimento devia ser ignorado'; end if;

  begin perform public.jornada_aplicar_klingo(999, 'confirmado'); raise exception 'card inexistente devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Card 999%' then raise; end if; end;
end $$;

-- ---------------------------------------------------------------- 4. mover à mão
do $$
declare r jsonb; c public.jornada_card%rowtype;
begin
  -- sem login
  begin perform public.jornada_mover_card(6, 'finalizado', 1); raise exception 'sem login devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Faça login%' then raise; end if; end;

  -- sem a permissão da Jornada
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', true);
  begin perform public.jornada_mover_card(6, 'finalizado', 1); raise exception 'sem permissão devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Sem permissão%' then raise; end if; end;

  -- com a permissão
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  r := public.jornada_mover_card(6, 'finalizado', 1, 'saiu da sala');
  if (r ->> 'versao')::integer <> 2 then raise exception 'versão devia ir a 2: %', r; end if;
  select * into c from public.jornada_card where id = 6;
  if c.coluna <> 'finalizado' or c.versao <> 2 then raise exception 'card 6 devia estar finalizado v2'; end if;
  if not exists (select 1 from public.jornada_evento where card_id = 6 and tipo = 'movido' and origem = 'pessoa' and usuario = '00000000-0000-0000-0000-00000000000b'
                 and detalhe ->> 'nota' = 'saiu da sala') then raise exception 'faltou o evento da pessoa'; end if;

  -- trava otimista: a versão antiga perde
  begin perform public.jornada_mover_card(6, 'laudo_pendente', 1); raise exception 'versão velha devia falhar'; exception when raise_exception then
    if sqlerrm not like 'CONFLITO%' then raise; end if; end;
  -- movimento que não existe na tabela
  begin perform public.jornada_mover_card(6, 'concluido', 2); perform public.jornada_mover_card(6, 'chegou', 3); raise exception 'concluido -> chegou devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Movimento não permitido%' then raise; end if; end;
  -- ninguém arrasta para coluna do Klingo
  begin perform public.jornada_mover_card(2, 'em_atendimento', 1); raise exception 'mover para coluna do Klingo devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Movimento não permitido%' then raise; end if; end;
  -- mesma coluna
  begin perform public.jornada_mover_card(2, 'a_confirmar', 1); raise exception 'mesma coluna devia falhar'; exception when raise_exception then
    if sqlerrm not like 'O card já está%' then raise; end if; end;
  -- perder o contato exige motivo
  begin perform public.jornada_mover_card(5, 'perdido', 1); raise exception 'perdido sem motivo devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Diga o motivo%' then raise; end if; end;
  perform public.jornada_mover_card(5, 'perdido', 1, 'achou caro');
  if (select coluna from public.jornada_card where id = 5) <> 'perdido' then raise exception 'contato devia estar perdido'; end if;
  -- card que não existe
  begin perform public.jornada_mover_card(999, 'chegou', 1); raise exception 'card inexistente devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Card não encontrado%' then raise; end if; end;
  -- exceção do Klingo: o Klingo cancelou, ninguém tira de lá à mão
  begin perform public.jornada_mover_card(3, 'chegou', 1); raise exception 'sair de cancelado à mão devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Movimento não permitido%' then raise; end if; end;
  -- card arquivado
  update public.jornada_card set arquivado_em = now() where id = 2;
  begin perform public.jornada_mover_card(2, 'chegou', 1); raise exception 'arquivado devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Card arquivado%' then raise; end if; end;
  update public.jornada_card set arquivado_em = null where id = 2;
end $$;

-- ---------------------------------------------------------------- 5. atribuir
do $$
declare r jsonb;
begin
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  r := public.jornada_atribuir_card(2, '00000000-0000-0000-0000-00000000000a', 1);
  if (select responsavel from public.jornada_card where id = 2) <> '00000000-0000-0000-0000-00000000000a' then raise exception 'responsável não gravou'; end if;
  begin perform public.jornada_atribuir_card(2, null, 1); raise exception 'versão velha devia falhar'; exception when raise_exception then
    if sqlerrm not like 'CONFLITO%' then raise; end if; end;
  begin perform public.jornada_atribuir_card(2, '00000000-0000-0000-0000-0000000000ff', 2); raise exception 'pessoa inexistente devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Pessoa não encontrada%' then raise; end if; end;
  perform public.jornada_atribuir_card(2, null, 2);
  if (select responsavel from public.jornada_card where id = 2) is not null then raise exception 'devia tirar o responsável'; end if;
end $$;

-- ---------------------------------------------------------------- 6. chat interno e histórico imutável
do $$
declare id1 bigint;
begin
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', true);
  begin perform public.jornada_enviar_mensagem(2, 'oi'); raise exception 'sem permissão devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Sem permissão%' then raise; end if; end;

  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  id1 := public.jornada_enviar_mensagem(2, '  Paciente pediu para trocar o horário  ');
  if (select texto from public.jornada_mensagem where id = id1) <> 'Paciente pediu para trocar o horário' then raise exception 'devia gravar sem espaços nas pontas'; end if;
  if (select canal from public.jornada_mensagem where id = id1) <> 'interno' or (select autor_tipo from public.jornada_mensagem where id = id1) <> 'equipe' then raise exception 'canal interno, autor equipe'; end if;
  begin perform public.jornada_enviar_mensagem(2, '   '); raise exception 'vazia devia falhar'; exception when raise_exception then
    if sqlerrm not like 'A mensagem precisa%' then raise; end if; end;
  begin perform public.jornada_enviar_mensagem(2, repeat('x', 2001)); raise exception 'longa devia falhar'; exception when raise_exception then
    if sqlerrm not like 'A mensagem precisa%' then raise; end if; end;
  begin perform public.jornada_enviar_mensagem(999, 'oi'); raise exception 'card inexistente devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Card não encontrado%' then raise; end if; end;

  -- histórico não se altera
  begin update public.jornada_mensagem set texto = 'outra' where id = id1; raise exception 'alterar mensagem devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Registro do histórico%' then raise; end if; end;
  begin update public.jornada_evento set detalhe = '{}' where card_id = 1; raise exception 'alterar evento devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Registro do histórico%' then raise; end if; end;
end $$;

-- ---------------------------------------------------------------- 7. o quadro (RLS: todos com a permissão veem tudo; sem ela, nada)
do $$
declare v public.v_jornada_quadro%rowtype; n integer;
begin
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  set local role authenticated;
  select count(*) into n from public.v_jornada_quadro;
  if n <> 6 then raise exception 'quem tem a permissão devia ver os 6 cards, viu %', n; end if;
  select * into v from public.v_jornada_quadro where id = 3;
  if not v.vazio or v.n_exames <> 1 or v.n_ativos <> 0 then raise exception 'card 3 (só cancelado) devia estar vazio: %', row_to_json(v); end if;
  select * into v from public.v_jornada_quadro where id = 4;
  if v.vazio or v.n_ativos <> 1 or v.n_exames <> 2 then raise exception 'card 4 tem exame ativo, não é vazio: %', row_to_json(v); end if;
  select * into v from public.v_jornada_quadro where id = 5;
  if v.vazio then raise exception 'card manual nunca é vazio'; end if;
  select * into v from public.v_jornada_quadro where id = 2;
  if v.n_mensagens <> 1 or v.paciente_nome <> 'Paciente Dois' then raise exception 'card 2 devia ter 1 mensagem e o nome do paciente: %', row_to_json(v); end if;
  reset role;

  -- mensagem num card vazio o tira de "vazio"
  perform public.jornada_enviar_mensagem(3, 'conferir cancelamento');
  set local role authenticated;
  select * into v from public.v_jornada_quadro where id = 3;
  if v.vazio then raise exception 'card com mensagem não é vazio'; end if;
  reset role;

  -- atraso: Chegou tem prazo de 30 min
  update public.jornada_card set coluna = 'chegou', coluna_desde = now() - interval '3 hours' where id = 4;
  update public.jornada_card set coluna = 'chegou', coluna_desde = now() - interval '5 minutes' where id = 2;
  set local role authenticated;
  if not (select atrasado from public.v_jornada_quadro where id = 4) then raise exception 'card parado há 3 h em Chegou devia estar atrasado'; end if;
  if (select atrasado from public.v_jornada_quadro where id = 2) then raise exception 'card há 5 min em Chegou não está atrasado'; end if;
  if (select minutos_na_coluna from public.v_jornada_quadro where id = 4) not between 179 and 181 then raise exception 'minutos na coluna errado'; end if;
  reset role;

  -- arquivado some do quadro
  update public.jornada_card set arquivado_em = now() where id = 5;
  set local role authenticated;
  if exists (select 1 from public.v_jornada_quadro where id = 5) then raise exception 'card arquivado não devia aparecer'; end if;
  reset role;

  -- sem a permissão: nada (cards, pacientes, exames, mensagens, histórico)
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', true);
  set local role authenticated;
  if (select count(*) from public.v_jornada_quadro) <> 0 or (select count(*) from public.jornada_card) <> 0 or (select count(*) from public.jornada_paciente) <> 0
     or (select count(*) from public.jornada_exame) <> 0 or (select count(*) from public.jornada_mensagem) <> 0 or (select count(*) from public.jornada_evento) <> 0 then
    raise exception 'quem não tem a permissão da Jornada não pode ver nada'; end if;
  -- mas as colunas (que não têm dado de paciente) todos leem
  if (select count(*) from public.jornada_coluna) <> 17 then raise exception 'as colunas são públicas para quem está logado'; end if;
  reset role;

  -- administrador vê tudo, mesmo sem a chave na permissão
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', true);
  set local role authenticated;
  if (select count(*) from public.jornada_card) <> 6 then raise exception 'admin devia ver os 6 cards'; end if;
  reset role;
end $$;

-- ---------------------------------------------------------------- 8. quem abriu o card (LGPD): quem tem permissão registra, só o admin lê
do $$
begin
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  perform public.jornada_registrar_acesso(1);
  perform public.jornada_registrar_acesso(999);                                 -- card inexistente: ignora
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', true);
  perform public.jornada_registrar_acesso(1);                                   -- sem permissão: ignora
  if (select count(*) from public.jornada_acesso) <> 1 then raise exception 'devia haver 1 registro de acesso, há %', (select count(*) from public.jornada_acesso); end if;

  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  set local role authenticated;
  if (select count(*) from public.jornada_acesso) <> 0 then raise exception 'quem não é admin não lê o registro de acessos'; end if;
  reset role;
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', true);
  set local role authenticated;
  if (select count(*) from public.jornada_acesso) <> 1 then raise exception 'admin lê o registro de acessos'; end if;
  reset role;
end $$;

-- ---------------------------------------------------------------- 9. ninguém grava direto; as regras do Klingo só o serviço chama
do $$ begin
  if has_table_privilege('authenticated', 'public.jornada_card', 'update') or has_table_privilege('authenticated', 'public.jornada_card', 'insert') then raise exception 'authenticated não pode gravar em jornada_card'; end if;
  if has_table_privilege('authenticated', 'public.jornada_evento', 'insert') or has_table_privilege('authenticated', 'public.jornada_mensagem', 'insert') then raise exception 'authenticated não pode gravar o histórico direto'; end if;
  if has_table_privilege('anon', 'public.jornada_card', 'select') then raise exception 'anon não lê a Jornada'; end if;
  if has_function_privilege('authenticated', 'public.jornada_aplicar_klingo(bigint,text,jsonb)', 'execute') then raise exception 'só o serviço aplica o Klingo'; end if;
  if has_function_privilege('anon', 'public.jornada_mover_card(bigint,text,integer,text)', 'execute') then raise exception 'anon não move card'; end if;
  if not has_function_privilege('authenticated', 'public.jornada_mover_card(bigint,text,integer,text)', 'execute') then raise exception 'a equipe move card'; end if;
end $$;

-- ---------------------------------------------------------------- 10. pendências que dependem de uma pessoa, na aba Avisos
do $$
declare n integer; a public.aviso%rowtype;
begin
  perform public.jornada_pendencias_sincronizar();
  select count(*) into n from public.aviso where painel = 'atendimento' and escopo = 'jornada' and status = 'aberto';
  if n <> 16 then raise exception 'esperava 16 avisos abertos (1 de relatórios + 15 pendências), achei %', n; end if;
  select * into a from public.aviso where painel = 'atendimento' and chave = 'jornada|api_escrita_klingo';
  if not found or a.nivel <> 'atencao' or not a.persistente or a.sensivel or jsonb_array_length(a.guia -> 'passos') < 1 then raise exception 'pendência da API do Klingo mal formada: %', row_to_json(a); end if;
  if a.titulo not like 'Jornada (etapa 2): %' then raise exception 'título sem a etapa: %', a.titulo; end if;

  -- a conferência do painel Python não resolve as pendências da Jornada
  perform public.aviso_sincronizar('atendimento', array['', '2026-11'], 1, '[]'::jsonb);
  select count(*) into n from public.aviso where painel = 'atendimento' and escopo = 'jornada' and status = 'aberto';
  if n <> 16 then raise exception 'a conferência do painel resolveu pendências da Jornada (% abertas)', n; end if;

  -- pendência desativada some sozinha; nova aparece
  update public.jornada_pendencia set ativa = false where chave = 'feriados';
  insert into public.jornada_pendencia (chave, etapa, titulo, texto, passos) values ('teste_nova', 3, 'Teste', 'texto', '["faça isto"]');
  perform public.jornada_pendencias_sincronizar();
  if (select status from public.aviso where chave = 'jornada|feriados') <> 'resolvido' then raise exception 'pendência desativada devia resolver'; end if;
  if (select status from public.aviso where chave = 'jornada|teste_nova') <> 'aberto' then raise exception 'pendência nova devia abrir'; end if;

  -- só o administrador lê a lista bruta
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  set local role authenticated;
  if (select count(*) from public.jornada_pendencia) <> 0 then raise exception 'quem não é admin não lê jornada_pendencia'; end if;
  reset role;
end $$;

-- ---------------------------------------------------------------- 11. a leitura do #13825 cria e move os cards
-- uma linha do relatório (col0 marcação, col1 atendimento, col2 prontuário, col3 agendado em, col4 agendado para, col5 procedimento, col6 operadora, col10 confirmação,
-- col11 motivo, col12 status, col13 atendido, col14 unidade, col15 nome, col16 celular, col17 telefone); `dias` = deslocamento do dia do exame em relação a hoje (Brasília)
create function public.t_linha(p_periodo date, p_marc text, p_pront text, p_dias integer, p_confirm text, p_status text, p_atendido text, p_motivo text, p_unid text,
                               p_proc text default 'RM JOELHO', p_nome text default 'Fulano', p_quando timestamptz default now()) returns void language sql as $$
  insert into public.fact_relatorio_linha (relatorio_id, periodo, linha, linha_hash, first_seen_at, last_seen_at)
  select r.id, p_periodo,
         jsonb_build_object('col0', p_marc, 'col1', case when p_atendido = 'S' then 'A' || p_marc else '' end, 'col2', p_pront,
           'col3', to_char((now() at time zone 'America/Sao_Paulo') - interval '5 days', 'YYYY-MM-DD HH24:MI:SS'),
           'col4', to_char(((now() at time zone 'America/Sao_Paulo')::date + p_dias) + time '10:30', 'YYYY-MM-DD HH24:MI:SS'),
           'col5', p_proc, 'col6', 'AMIL', 'col8', '999,00', 'col10', p_confirm, 'col11', p_motivo, 'col12', p_status, 'col13', p_atendido,
           'col14', p_unid, 'col15', p_nome, 'col16', '11988887777', 'col17', ''),
         md5(p_marc || p_confirm || p_status || p_atendido || p_motivo || p_quando::text), p_quando, p_quando
  from public.dim_relatorio r where r.klingo_id = '13825' $$;

do $$
declare
  mes date := date_trunc('month', (now() at time zone 'America/Sao_Paulo')::date::timestamp)::date;
  csi text := 'CLÍNICA DE SAÚDE E IMAGEM - CSI'; rm text := 'CLÍNICA DE SAÚDE E IMAGEM - RM/TC'; des text := 'DESENVOAR';
  res jsonb; n integer; hoje date := (now() at time zone 'America/Sao_Paulo')::date; col text; ver integer;
begin
  perform public.t_linha(mes, 'S1', 'T1', 0, 'A Confirmar', 'Aberta', 'N', '', csi);
  perform public.t_linha(mes, 'S2', 'T1', 0, 'Confirmado',  'Aberta', 'N', '', csi, 'RX TORAX');            -- mesmo paciente, mesmo dia, mesma unidade: 2 exames num card
  perform public.t_linha(mes, 'S3', 'T2', 0, 'Confirmado',  'Aberta', 'N', '', rm);
  perform public.t_linha(mes, 'S4', 'T3', 0, 'Confirmado',  'Aberta', 'S', '', csi);
  perform public.t_linha(mes, 'S5', 'T4', -1, 'Confirmado', 'Aberta', 'S', '', csi);                        -- atendido ontem
  perform public.t_linha(mes, 'S6', 'T5', -1, 'A Confirmar', 'Aberta', 'N', '', csi);                       -- ontem, não veio
  perform public.t_linha(mes, 'S7', 'T6', 0, 'A Confirmar', 'Cancelada', 'N', 'Remarcado.', csi);
  perform public.t_linha(mes, 'S8', 'T7', 0, 'Confirmado',  'Cancelada', 'N', 'Atendimento unificado', rm);
  perform public.t_linha(mes, 'S9', 'T8', 1, 'Confirmado',  'Aberta', 'N', '', des);
  perform public.t_linha(mes, 'S10', 'T9', 60, 'A Confirmar', 'Aberta', 'N', '', csi);                      -- fora da janela (60 dias à frente)
  perform public.t_linha(mes, 'S11', 'T10', -10, 'Confirmado', 'Aberta', 'S', '', csi);                     -- fora da janela (10 dias atrás)
  -- a mesma marcação lida duas vezes no mês: vale a leitura mais recente
  perform public.t_linha(mes, 'S12', 'T11', 0, 'A Confirmar', 'Aberta', 'N', '', csi, 'US ABDOME', 'Velho', now() - interval '2 hours');
  perform public.t_linha(mes, 'S12', 'T11', 0, 'Confirmado',  'Aberta', 'N', '', csi, 'US ABDOME', 'Novo',  now() - interval '1 hour');

  res := public.jornada_sincronizar_klingo();
  if (res ->> 'exames')::integer <> 10 then raise exception 'esperava 10 exames na janela, achei %: %', res ->> 'exames', res; end if;
  if (res ->> 'cards_criados')::integer <> 9 then raise exception 'esperava 9 cards criados, achei %', res ->> 'cards_criados'; end if;

  -- colunas
  foreach col in array array['T1:a_confirmar', 'T2:confirmado', 'T3:em_atendimento', 'T4:finalizado', 'T5:faltou', 'T6:remarcado', 'T7:cancelado', 'T8:confirmado', 'T11:confirmado'] loop
    if (select coluna from public.jornada_card where paciente_chave = split_part(col, ':', 1)) is distinct from split_part(col, ':', 2) then
      raise exception 'card % devia estar em %, está em %', split_part(col, ':', 1), split_part(col, ':', 2), (select coluna from public.jornada_card where paciente_chave = split_part(col, ':', 1)); end if;
  end loop;
  if exists (select 1 from public.jornada_card where paciente_chave in ('T9', 'T10')) then raise exception 'fora da janela não vira card'; end if;
  if (select count(*) from public.jornada_exame e join public.jornada_card c on c.id = e.card_id where c.paciente_chave = 'T1') <> 2 then raise exception 'T1 devia ter 2 exames'; end if;
  if (select nome from public.jornada_paciente where prontuario = 'T11') <> 'Novo' then raise exception 'devia valer a leitura mais recente'; end if;
  if (select unidade from public.jornada_card where paciente_chave = 'T2') <> 'CSI 2' or (select unidade from public.jornada_card where paciente_chave = 'T8') <> 'CSI Pediatria' then raise exception 'unidade curta errada'; end if;
  if (select status from public.jornada_exame where marcacao_id = 'S7') <> 'remarcado' or (select status from public.jornada_exame where marcacao_id = 'S8') <> 'cancelado' then raise exception 'status de cancelamento errado'; end if;
  if (select status from public.jornada_exame where marcacao_id = 'S6') <> 'faltou' then raise exception 'ontem, aberta e sem atendimento é falta'; end if;
  if (select atendimento_id from public.jornada_exame where marcacao_id = 'S4') <> 'AS4' then raise exception 'devia guardar o Id do atendimento'; end if;
  -- o valor em R$ não vai para o quadro
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name in ('jornada_exame', 'jornada_card', 'jornada_paciente') and column_name ilike '%valor%') then raise exception 'valor não pode ir para o quadro'; end if;
  -- T4 foi finalizado sozinho (o dia passou) e isso ficou no histórico
  if not exists (select 1 from public.jornada_evento e join public.jornada_card c on c.id = e.card_id where c.paciente_chave = 'T4' and e.origem = 'sistema' and e.para_coluna = 'finalizado') then raise exception 'faltou o evento do sistema'; end if;
  if (res ->> 'finalizados_sozinho')::integer <> 1 then raise exception 'esperava 1 finalizado sozinho: %', res; end if;

  -- repetir não muda nada (nem gera evento novo)
  select count(*) into n from public.jornada_evento;
  res := public.jornada_sincronizar_klingo();
  if (res ->> 'cards_criados')::integer <> 0 or (res ->> 'cards_movidos')::integer <> 0 or (res ->> 'divergencias')::integer <> 0 or (res ->> 'finalizados_sozinho')::integer <> 0 then raise exception 'segunda rodada devia ser vazia: %', res; end if;
  if (select count(*) from public.jornada_evento) <> n then raise exception 'segunda rodada gerou eventos'; end if;

  -- o Klingo avança: T2 foi atendido (leitura nova do mês: a linha antiga deixa de valer)
  insert into public.sync_relatorio_runs (relatorio_id, periodo, started_at, finished_at, status)
    select id, mes, now() + interval '1 minute', now() + interval '1 minute', 'success' from public.dim_relatorio where klingo_id = '13825';
  perform public.t_linha(mes, 'S3', 'T2', 0, 'Confirmado', 'Aberta', 'S', '', rm, 'RM JOELHO', 'Fulano', now() + interval '2 minutes');
  res := public.jornada_sincronizar_klingo();
  if (select coluna from public.jornada_card where paciente_chave = 'T2') <> 'em_atendimento' then raise exception 'T2 devia ir para Em atendimento'; end if;
  if (res ->> 'cards_movidos')::integer <> 1 then raise exception 'esperava 1 card movido: %', res; end if;
  if (select count(*) from public.jornada_exame where marcacao_id = 'S3') <> 1 then raise exception 'a marcação não pode duplicar'; end if;
  -- as outras marcações do mês deixaram de ser "vigentes" (não estão na leitura nova): saem da janela, mas o card já existente fica como estava
  if (select coluna from public.jornada_card where paciente_chave = 'T1') <> 'a_confirmar' then raise exception 'T1 devia continuar como estava'; end if;

  -- a equipe passa o card de T2 para Finalizado; o Klingo ainda diz "atendido" e isso não gera alarme
  select versao into ver from public.jornada_card where paciente_chave = 'T2';
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  perform public.jornada_mover_card((select id from public.jornada_card where paciente_chave = 'T2'), 'finalizado', ver);
  perform public.jornada_sincronizar_klingo();
  if (select coluna from public.jornada_card where paciente_chave = 'T2') <> 'finalizado' then raise exception 'Klingo não pode puxar T2 para trás'; end if;
  if exists (select 1 from public.jornada_evento e join public.jornada_card c on c.id = e.card_id where c.paciente_chave = 'T2' and e.tipo = 'divergencia') then raise exception 'atraso normal do Klingo não é divergência'; end if;
end $$;

-- quando roda: só se o #13825 foi lido de novo ou virou o dia
do $$
declare r jsonb; v timestamptz;
begin
  update public.jornada_sync_estado set ultima_execucao = null, ultima_leitura_vista = null;
  r := public.jornada_sincronizar_se_preciso();
  if not (r ->> 'rodou')::boolean then raise exception 'a primeira vez devia rodar: %', r; end if;
  r := public.jornada_sincronizar_se_preciso();
  if (r ->> 'rodou')::boolean then raise exception 'sem leitura nova não devia rodar'; end if;
  insert into public.sync_relatorio_runs (relatorio_id, periodo, started_at, finished_at, status)
    select id, current_date, now() + interval '5 minutes', now() + interval '5 minutes', 'success' from public.dim_relatorio where klingo_id = '13825';
  r := public.jornada_sincronizar_se_preciso();
  if not (r ->> 'rodou')::boolean then raise exception 'leitura nova devia rodar'; end if;
  update public.jornada_sync_estado set ultima_execucao = now() - interval '2 days';
  r := public.jornada_sincronizar_se_preciso();
  if not (r ->> 'rodou')::boolean then raise exception 'virou o dia: devia rodar'; end if;
  if (select ultimo_resultado ->> 'exames' from public.jornada_sync_estado) is null then raise exception 'devia guardar o último resultado'; end if;
  if not exists (select 1 from cron.agendados where nome = 'jornada-sincronizar') then raise exception 'cron da sincronização não agendado'; end if;
  if has_function_privilege('authenticated', 'public.jornada_sincronizar_klingo(integer,integer)', 'execute') or has_function_privilege('authenticated', 'public.jornada_sincronizar_se_preciso()', 'execute') then raise exception 'só o serviço sincroniza'; end if;
end $$;

-- arquivamento: encerrado há mais de 7 dias sai do quadro; card digitado à mão (manual:) fica
do $$
declare mes date := date_trunc('month', (now() at time zone 'America/Sao_Paulo')::date::timestamp)::date;
begin
  insert into public.jornada_card (paciente_chave, data_ref, unidade, coluna) values ('V1', current_date - 9, 'CSI 1', 'cancelado'), ('V2', current_date - 9, 'CSI 1', 'laudo_pendente'), ('manual:7', current_date - 40, '', 'contato'), ('V3', current_date - 40, 'CSI 1', 'laudo_pendente');
  perform public.jornada_sincronizar_klingo();
  if (select arquivado_em from public.jornada_card where paciente_chave = 'V1') is null then raise exception 'cancelado há 9 dias devia ser arquivado'; end if;
  if (select arquivado_em from public.jornada_card where paciente_chave = 'V2') is not null then raise exception 'laudo pendente há 9 dias ainda é trabalho: não arquiva'; end if;
  if (select arquivado_em from public.jornada_card where paciente_chave = 'V3') is null then raise exception 'qualquer card com mais de 30 dias é arquivado'; end if;
  if (select arquivado_em from public.jornada_card where paciente_chave = 'manual:7') is not null then raise exception 'card manual não é arquivado sozinho'; end if;
end $$;

-- ---------------------------------------------------------------- 12. tempo real, nome de quem escreve e lista da equipe
do $$
declare
  id1 bigint; n integer; ver integer; card bigint;
begin
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);

  -- mensagem: guarda o nome de quem escreveu e avisa os dois canais, sem levar o texto
  update public.jornada_card set arquivado_em = null where id = 2;
  select count(*) into n from realtime.messages;
  id1 := public.jornada_enviar_mensagem(2, 'texto que não pode ir no aviso');
  if (select autor_nome from public.jornada_mensagem where id = id1) <> 'ana' then raise exception 'devia guardar o nome "ana", guardou %', (select autor_nome from public.jornada_mensagem where id = id1); end if;
  if not exists (select 1 from realtime.messages where topic = 'jornada:card:2' and event = 'mensagem' and (payload ->> 'id')::bigint = id1 and private) then raise exception 'faltou o aviso do chat do cartão'; end if;
  if not exists (select 1 from realtime.messages where topic = 'jornada:quadro' and event = 'card' and (payload ->> 'card_id')::bigint = 2 and id > (select max(id) - 2 from realtime.messages)) then raise exception 'faltou o aviso do quadro'; end if;
  if exists (select 1 from realtime.messages where payload::text like '%texto que não pode%') then raise exception 'o aviso não pode levar o texto da mensagem'; end if;

  -- mover pela equipe e pelo Klingo avisa o quadro
  select versao, id into ver, card from public.jornada_card where paciente_chave = 'P4';
  select count(*) into n from realtime.messages where topic = 'jornada:quadro';
  perform public.jornada_mover_card(card, 'finalizado', ver);
  if (select count(*) from realtime.messages where topic = 'jornada:quadro') <= n then raise exception 'mover devia avisar o quadro'; end if;
  select count(*) into n from realtime.messages where topic = 'jornada:quadro';
  update public.jornada_card set prioridade = prioridade where id = card;          -- nada mudou: não avisa
  if (select count(*) from realtime.messages where topic = 'jornada:quadro') <> n then raise exception 'sem mudança não devia avisar'; end if;
  update public.jornada_exame set status = 'atendido' where card_id = card;
  if (select count(*) from realtime.messages where topic = 'jornada:quadro') <= n then raise exception 'mudar o exame devia avisar o quadro'; end if;

  -- se o Realtime falhar, a gravação segue
  create or replace function realtime.send(payload jsonb, event text, topic text, private boolean default true) returns void language plpgsql as $f$ begin raise exception 'Realtime fora do ar'; end $f$;
  id1 := public.jornada_enviar_mensagem(2, 'continua gravando');
  if not exists (select 1 from public.jornada_mensagem where id = id1) then raise exception 'a mensagem devia gravar mesmo com o Realtime fora do ar'; end if;
  create or replace function realtime.send(payload jsonb, event text, topic text, private boolean default true) returns void language sql as $f$ insert into realtime.messages (topic, event, payload, private) values (topic, event, payload, private) $f$;
end $$;

-- a equipe: administradores e quem tem a permissão (bia não tem)
do $$
declare nomes text;
begin
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  select string_agg(nome, ',' order by nome) into nomes from public.jornada_equipe();
  if nomes <> 'adm,ana' then raise exception 'equipe devia ser adm,ana: %', nomes; end if;
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', true);
  begin perform * from public.jornada_equipe(); raise exception 'sem permissão devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Sem permissão%' then raise; end if; end;
  if has_function_privilege('anon', 'public.jornada_equipe()', 'execute') then raise exception 'anon não lista a equipe'; end if;
end $$;

-- o canal: só "jornada:" e só com a permissão
do $$
declare n integer;
begin
  if not exists (select 1 from pg_policies where schemaname = 'realtime' and tablename = 'messages' and policyname = 'jornada_canais_leitura') then raise exception 'faltou a política do canal'; end if;
  perform set_config('realtime.topic', 'jornada:quadro', true);
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  set local role authenticated;
  select count(*) into n from realtime.messages;
  reset role;
  if n = 0 then raise exception 'quem tem a permissão devia receber o canal da Jornada'; end if;

  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', true);
  set local role authenticated;
  select count(*) into n from realtime.messages;
  reset role;
  if n <> 0 then raise exception 'quem não tem a permissão não pode receber o canal'; end if;

  perform set_config('realtime.topic', 'outro:canal', true);
  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
  set local role authenticated;
  select count(*) into n from realtime.messages;
  reset role;
  if n <> 0 then raise exception 'a política vale só para canais "jornada:"'; end if;
end $$;

\echo JORNADA OK
