-- Testa as migrations 20261101140000_jornada_modelo.sql e 20261101150000_jornada_pendencias.sql (quadro da Jornada: colunas, regras do Klingo,
-- movimentos à mão, chat, permissões e pendências) num Postgres vazio (sem Supabase): papéis, auth.uid() e as tabelas do data warehouse são simulados aqui.
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
create table public.profiles (id uuid primary key, email text, role text not null default 'viewer', permissions jsonb not null default '{}'::jsonb, status text not null default 'ativo');
create function public.is_admin() returns boolean language sql security definer set search_path = '' stable as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin') $$;
grant execute on function public.is_admin() to authenticated;
grant usage on schema public, auth to anon, authenticated, service_role;
grant select on public.profiles to authenticated;

create schema cron;
create table cron.agendados (nome text, agenda text, comando text);
create function cron.schedule(p_nome text, p_agenda text, p_comando text) returns bigint language sql as $$ insert into cron.agendados values (p_nome, p_agenda, p_comando) returning 1::bigint $$;

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

-- gente: admin, quem tem a permissão da Jornada, quem não tem
insert into public.profiles values
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
  if n <> 9 then raise exception 'esperava 9 avisos abertos (1 de relatórios + 8 pendências), achei %', n; end if;
  select * into a from public.aviso where painel = 'atendimento' and chave = 'jornada|api_escrita_klingo';
  if not found or a.nivel <> 'atencao' or not a.persistente or a.sensivel or jsonb_array_length(a.guia -> 'passos') < 1 then raise exception 'pendência da API do Klingo mal formada: %', row_to_json(a); end if;
  if a.titulo not like 'Jornada (etapa 2): %' then raise exception 'título sem a etapa: %', a.titulo; end if;

  -- a conferência do painel Python não resolve as pendências da Jornada
  perform public.aviso_sincronizar('atendimento', array['', '2026-11'], 1, '[]'::jsonb);
  select count(*) into n from public.aviso where painel = 'atendimento' and escopo = 'jornada' and status = 'aberto';
  if n <> 9 then raise exception 'a conferência do painel resolveu pendências da Jornada (% abertas)', n; end if;

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

\echo JORNADA OK
