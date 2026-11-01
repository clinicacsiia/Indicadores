-- Testa a migration 20261101120000_coleta_ritmo.sql (coleta adaptativa da Jornada) num Postgres vazio (sem Supabase):
-- as tabelas do data warehouse, os papéis, o cron e o auth.uid() são simulados aqui.
--
--   createdb ritmo_teste && psql -v ON_ERROR_STOP=1 -d ritmo_teste -f supabase/tests/coleta_ritmo.sql    (na raiz do repositório)
--
-- Cada cenário termina com `raise exception` se algo não for o esperado; chegando ao fim, imprime "RITMO OK".
\set ON_ERROR_STOP on

do $$ begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create table public.profiles (id uuid primary key, email text, role text not null default 'viewer', permissions jsonb not null default '{}'::jsonb, status text not null default 'ativo');
grant usage on schema public, auth to anon, authenticated, service_role;
grant select on public.profiles to authenticated;

-- pg_cron: só registra o que seria agendado
create schema cron;
create table cron.agendados (nome text, agenda text, comando text);
create function cron.schedule(p_nome text, p_agenda text, p_comando text) returns bigint language sql as $$ insert into cron.agendados values (p_nome, p_agenda, p_comando) returning 1::bigint $$;

-- as tabelas do data warehouse que a migration usa (colunas mínimas)
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

-- os dois relatórios da Jornada já existem quando a migration roda (ela só inclui quem existe); 13402 e um relatório qualquer ficam de fora
insert into public.dim_relatorio (id, klingo_id, nome, granularidade, filtro_periodo, periodo_validado_em, janela_dias) values
  ('00000000-0000-0000-0000-0000000013ff', '13404', 'Fluxo na Recepção',    'dia', 'periodo0', now(), 30),
  ('00000000-0000-0000-0000-000000013825', '13825', 'Agendamentos por Marcação', 'mes', 'periodo0', now(), 30),
  ('00000000-0000-0000-0000-000000013402', '13402', 'Visão Gerencial',      'mes', 'periodo0', now(), 30),
  ('00000000-0000-0000-0000-000000000099', '99',    'Outro relatório',      'dia', 'periodo0', now(), 3);

\i supabase/migrations/20261101120000_coleta_ritmo.sql

-- ---------------------------------------------------------------- 1. a migration colocou os dois relatórios no ritmo, e agendou o cron
do $$ declare n integer; m integer; begin
  select count(*) into n from public.coleta_ritmo;
  if n <> 2 then raise exception 'esperava 2 relatórios no ritmo, achei %', n; end if;
  select minimo_min into m from public.coleta_ritmo c join public.dim_relatorio r on r.id = c.relatorio_id where r.klingo_id = '13404';
  if m <> 1 then raise exception '13404 devia ter mínimo 1, tem %', m; end if;
  select minimo_min into m from public.coleta_ritmo c join public.dim_relatorio r on r.id = c.relatorio_id where r.klingo_id = '13825';
  if m <> 15 then raise exception '13825 devia ter mínimo 15, tem %', m; end if;
  if not exists (select 1 from cron.agendados where nome = 'coleta-ritmo-1min' and agenda = '* * * * *') then raise exception 'cron de 1 minuto não agendado'; end if;
  if not exists (select 1 from cron.agendados where nome = 'jornada-pendencias-diaria') then raise exception 'cron da pendência não agendado'; end if;
end $$;

-- ---------------------------------------------------------------- 2. expediente (hora de Brasília; 04/11/2026 é quarta, 08/11 é domingo, 12/10/2026 foi feriado numa segunda)
do $$ begin
  if not public.coleta_em_expediente(timestamptz '2026-11-04 10:00-03') then raise exception 'quarta 10:00 devia estar no expediente'; end if;
  if public.coleta_em_expediente(timestamptz '2026-11-04 06:29-03') then raise exception '06:29 ainda não é expediente'; end if;
  if not public.coleta_em_expediente(timestamptz '2026-11-04 06:30-03') then raise exception '06:30 já é expediente'; end if;
  if public.coleta_em_expediente(timestamptz '2026-11-04 18:30-03') then raise exception '18:30 já saiu do expediente'; end if;
  if not public.coleta_em_expediente(timestamptz '2026-11-07 12:00-03') then raise exception 'sábado entra no expediente'; end if;
  if public.coleta_em_expediente(timestamptz '2026-11-08 10:00-03') then raise exception 'domingo não é expediente'; end if;
  if public.coleta_em_expediente(timestamptz '2026-10-12 10:00-03') then raise exception 'feriado não é expediente'; end if;
  -- 01:30 de Brasília é 04:30 UTC: o dia de Brasília é que vale
  if public.coleta_em_expediente(timestamptz '2026-11-04 01:30-03') then raise exception 'madrugada não é expediente'; end if;

  if public.coleta_proximo_expediente(timestamptz '2026-11-07 19:00-03') <> timestamptz '2026-11-09 06:30-03' then
    raise exception 'sábado à noite devia esperar a segunda 06:30, achei %', public.coleta_proximo_expediente(timestamptz '2026-11-07 19:00-03'); end if;
  if public.coleta_proximo_expediente(timestamptz '2026-11-04 05:00-03') <> timestamptz '2026-11-04 06:30-03' then raise exception 'quarta 05:00 devia esperar 06:30 do mesmo dia'; end if;
  if public.coleta_proximo_expediente(timestamptz '2026-10-11 20:00-03') <> timestamptz '2026-10-13 06:30-03' then raise exception 'domingo à noite antes do feriado devia pular para terça'; end if;
end $$;

-- ---------------------------------------------------------------- 3. as marchas (fora do expediente: domingo 08/11 à noite)
do $$
declare p record; t timestamptz := timestamptz '2026-11-08 22:00-03';
begin
  -- dentro do expediente: sempre o mínimo, mesmo sem movimento há horas
  select * into p from public.coleta_ritmo_proximo(timestamptz '2026-11-04 10:00-03', 1, 500, false);
  if p.intervalo_min <> 1 or p.marcha <> 'ao_vivo' then raise exception 'no expediente devia ser 1 min ao vivo: % %', p.intervalo_min, p.marcha; end if;

  -- fora do expediente: 14 leituras sem mudança ainda é o mínimo
  select * into p from public.coleta_ritmo_proximo(t, 1, 14, false);
  if p.intervalo_min <> 1 or p.marcha <> 'ao_vivo' then raise exception '14 sem mudança devia seguir em 1 min: % %', p.intervalo_min, p.marcha; end if;
  -- 15 -> 5, 16 -> 15, 17 e adiante -> 60 (teto)
  select * into p from public.coleta_ritmo_proximo(t, 1, 15, false);
  if p.intervalo_min <> 5 or p.marcha <> 'calmo' then raise exception '15 sem mudança devia ir a 5 min calmo: % %', p.intervalo_min, p.marcha; end if;
  select * into p from public.coleta_ritmo_proximo(t, 1, 16, false);
  if p.intervalo_min <> 15 or p.marcha <> 'calmo' then raise exception '16 sem mudança devia ir a 15 min: % %', p.intervalo_min, p.marcha; end if;
  select * into p from public.coleta_ritmo_proximo(t, 1, 17, false);
  if p.intervalo_min <> 60 or p.marcha <> 'dormindo' then raise exception '17 sem mudança devia dormir 60 min: % %', p.intervalo_min, p.marcha; end if;
  select * into p from public.coleta_ritmo_proximo(t, 1, 400, false);
  if p.intervalo_min <> 60 or p.proxima <> t + interval '60 minutes' then raise exception 'o teto é 60 min: % %', p.intervalo_min, p.proxima; end if;

  -- qualquer movimento volta ao mínimo na hora, mesmo de madrugada
  select * into p from public.coleta_ritmo_proximo(t, 1, 400, true);
  if p.intervalo_min <> 1 or p.marcha <> 'ao_vivo' or p.proxima <> t + interval '1 minute' then raise exception 'movimento devia voltar a 1 min: % % %', p.intervalo_min, p.marcha, p.proxima; end if;

  -- relatório com mínimo maior (13825: 15 min) nunca fica abaixo do próprio mínimo
  select * into p from public.coleta_ritmo_proximo(t, 15, 15, false);
  if p.intervalo_min <> 15 then raise exception 'mínimo 15 não pode cair para %', p.intervalo_min; end if;
  select * into p from public.coleta_ritmo_proximo(t, 15, 400, false);
  if p.intervalo_min <> 60 then raise exception 'mínimo 15 no teto devia ser 60, achei %', p.intervalo_min; end if;

  -- nunca dorme além da abertura do expediente: quarta 06:00 com 60 min de teto acorda às 06:30
  select * into p from public.coleta_ritmo_proximo(timestamptz '2026-11-04 06:00-03', 1, 400, false);
  if p.proxima <> timestamptz '2026-11-04 06:30-03' then raise exception 'devia acordar às 06:30, achei %', p.proxima; end if;
  -- sábado 22:00 com teto 60: dorme 60 min, e a abertura é só na segunda
  select * into p from public.coleta_ritmo_proximo(timestamptz '2026-11-07 22:00-03', 1, 400, false);
  if p.proxima <> timestamptz '2026-11-07 23:00-03' then raise exception 'sábado 22:00 devia ler de novo às 23:00, achei %', p.proxima; end if;

  -- teto configurável: com 3 horas a madrugada fica 180 min (mas só se o degrau chegar lá)
  update public.coleta_ritmo_config set teto_min = 180, passos = '{5,15,60,180}';
  select * into p from public.coleta_ritmo_proximo(t, 1, 18, false);
  if p.intervalo_min <> 180 or p.marcha <> 'dormindo' then raise exception 'teto de 180 devia dormir 180: % %', p.intervalo_min, p.marcha; end if;
  update public.coleta_ritmo_config set teto_min = 60, passos = '{5,15,60}';
end $$;

-- ---------------------------------------------------------------- 4. cada leitura terminada atualiza o ritmo (trigger)
do $$
declare
  rel uuid := '00000000-0000-0000-0000-0000000013ff';
  rec public.coleta_ritmo%rowtype;
  run uuid;
  hoje date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  -- leitura que trouxe linha nova -> movimento
  insert into public.sync_relatorio_runs (relatorio_id, periodo, started_at) values (rel, hoje, now() - interval '1 minute') returning id into run;
  insert into public.fact_relatorio_linha (relatorio_id, periodo, linha_hash, linha) values (rel, hoje, 'h1', '{}');
  update public.sync_relatorio_runs set status = 'success', finished_at = now(), linhas_sincronizadas = 1 where id = run;
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.sem_mudanca_seguidas <> 0 or rec.ultimo_movimento_em is null or rec.marcha <> 'ao_vivo' or rec.ultima_leitura_em is null then
    raise exception 'leitura com linha nova devia marcar movimento: %', row_to_json(rec); end if;

  -- a próxima leitura conta do minuto cheio em que a leitura começou (vence antes do tick seguinte do cron)
  if rec.proxima_leitura_em <> date_trunc('minute', now() - interval '1 minute') + interval '1 minute' then
    raise exception 'a próxima leitura devia vencer no minuto cheio seguinte ao início: %', rec.proxima_leitura_em; end if;

  -- leitura sem nada novo (a linha só foi revista) -> uma sem mudança a mais
  insert into public.sync_relatorio_runs (relatorio_id, periodo, started_at) values (rel, hoje, now() + interval '1 second') returning id into run;
  update public.fact_relatorio_linha set last_seen_at = now() where relatorio_id = rel;
  update public.sync_relatorio_runs set status = 'success', finished_at = now(), linhas_sincronizadas = 1 where id = run;
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.sem_mudanca_seguidas <> 1 then raise exception 'sem mudança devia ser 1, é %', rec.sem_mudanca_seguidas; end if;

  -- leitura de um dia antigo não mexe no ritmo
  insert into public.sync_relatorio_runs (relatorio_id, periodo, started_at) values (rel, hoje - 3, now() + interval '2 seconds') returning id into run;
  update public.sync_relatorio_runs set status = 'success', finished_at = now() where id = run;
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.sem_mudanca_seguidas <> 1 then raise exception 'dia antigo não podia mexer no ritmo (sem mudança = %)', rec.sem_mudanca_seguidas; end if;

  -- erro: tenta de novo em 5 min, depois 10, e o contador zera no primeiro sucesso
  insert into public.sync_relatorio_runs (relatorio_id, periodo) values (rel, hoje) returning id into run;
  update public.sync_relatorio_runs set status = 'error', finished_at = now(), error_message = 'x' where id = run;
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.erros_seguidos <> 1 or rec.proxima_leitura_em < now() + interval '4 minutes 50 seconds' or rec.proxima_leitura_em > now() + interval '5 minutes 10 seconds' then
    raise exception '1º erro devia esperar 5 min: %', row_to_json(rec); end if;
  insert into public.sync_relatorio_runs (relatorio_id, periodo) values (rel, hoje) returning id into run;
  update public.sync_relatorio_runs set status = 'error', finished_at = now(), error_message = 'x' where id = run;
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.erros_seguidos <> 2 or rec.proxima_leitura_em < now() + interval '9 minutes 50 seconds' or rec.proxima_leitura_em > now() + interval '10 minutes 10 seconds' then
    raise exception '2º erro devia esperar 10 min: %', row_to_json(rec); end if;
  insert into public.sync_relatorio_runs (relatorio_id, periodo, started_at) values (rel, hoje, now() + interval '3 seconds') returning id into run;
  update public.sync_relatorio_runs set status = 'success', finished_at = now() where id = run;
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.erros_seguidos <> 0 then raise exception 'o sucesso devia zerar os erros'; end if;

  -- relatório fora do ritmo não é tocado
  insert into public.sync_relatorio_runs (relatorio_id, periodo) values ('00000000-0000-0000-0000-000000000099', hoje) returning id into run;
  update public.sync_relatorio_runs set status = 'success', finished_at = now() where id = run;
  if exists (select 1 from public.coleta_ritmo where relatorio_id = '00000000-0000-0000-0000-000000000099') then raise exception 'relatório fora do ritmo ganhou linha'; end if;
end $$;

-- ---------------------------------------------------------------- 5. acordar
do $$
declare
  rel uuid := '00000000-0000-0000-0000-0000000013ff';
  rel2 uuid := '00000000-0000-0000-0000-000000013825';
  r jsonb; rec public.coleta_ritmo%rowtype;
begin
  -- sem login não acorda
  begin perform public.acordar_coleta(); raise exception 'acordar sem login devia falhar'; exception when raise_exception then
    if sqlerrm not like 'Faça login%' then raise; end if; end;

  perform set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', true);
  update public.coleta_ritmo set marcha = 'dormindo', intervalo_atual_min = 60, sem_mudanca_seguidas = 40, proxima_leitura_em = now() + interval '50 minutes' where relatorio_id = rel;
  update public.coleta_ritmo set marcha = 'ao_vivo', proxima_leitura_em = now() + interval '9 minutes' where relatorio_id = rel2;

  r := public.acordar_coleta('Teste');
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if (r ->> 'acordou')::integer <> 1 then raise exception 'devia acordar 1 relatório, acordou %', r; end if;
  if rec.marcha <> 'ao_vivo' or rec.intervalo_atual_min <> 1 or rec.sem_mudanca_seguidas <> 0 or rec.proxima_leitura_em > now() or rec.motivo_movimento <> 'Teste' then
    raise exception 'acordar devia voltar ao vivo, 1 min, já vencido: %', row_to_json(rec); end if;
  -- quem já estava ao vivo não é adiantado (não força o Klingo à toa)
  select * into rec from public.coleta_ritmo where relatorio_id = rel2;
  if rec.proxima_leitura_em < now() + interval '8 minutes' then raise exception 'relatório ao vivo não devia ser adiantado'; end if;

  -- segunda chamada em menos de 20 s não faz nada
  update public.coleta_ritmo set marcha = 'dormindo', proxima_leitura_em = now() + interval '50 minutes' where relatorio_id = rel;
  r := public.acordar_coleta('Teste 2');
  if (r ->> 'acordou')::integer <> 0 then raise exception 'chamada seguida devia ser ignorada: %', r; end if;
  -- passados 20 s, acorda de novo
  update public.coleta_ritmo_config set ultimo_acordar_em = now() - interval '21 seconds';
  r := public.acordar_coleta('Teste 3');
  if (r ->> 'acordou')::integer <> 1 then raise exception 'depois de 20 s devia acordar: %', r; end if;

  -- com erros em andamento, acordar não ignora a espera do erro
  update public.coleta_ritmo set marcha = 'calmo', erros_seguidos = 2, proxima_leitura_em = now() + interval '9 minutes' where relatorio_id = rel;
  update public.coleta_ritmo_config set ultimo_acordar_em = now() - interval '21 seconds';
  perform public.acordar_coleta('Teste 4');
  select * into rec from public.coleta_ritmo where relatorio_id = rel;
  if rec.proxima_leitura_em < now() + interval '8 minutes' then raise exception 'acordar não pode atropelar a espera depois de erro'; end if;
end $$;

-- ---------------------------------------------------------------- 6. o que a coleta de 1 minuto lê, e o que sobra para a lista geral
do $$
declare
  rel uuid := '00000000-0000-0000-0000-0000000013ff';
  rel2 uuid := '00000000-0000-0000-0000-000000013825';
  n integer; hoje date := (now() at time zone 'America/Sao_Paulo')::date;
  run uuid;
begin
  update public.coleta_ritmo set erros_seguidos = 0, proxima_leitura_em = now() - interval '1 second' where relatorio_id = rel;
  update public.coleta_ritmo set proxima_leitura_em = now() + interval '10 minutes' where relatorio_id = rel2;
  select count(*) into n from public.proximos_trabalhos_ritmo(10);
  if n <> 1 then raise exception 'só o vencido devia sair, saíram %', n; end if;
  if (select periodo from public.proximos_trabalhos_ritmo(10)) <> hoje then raise exception 'relatório diário lê o dia de hoje'; end if;

  update public.coleta_ritmo set proxima_leitura_em = now() - interval '1 second' where relatorio_id = rel2;
  if (select periodo from public.proximos_trabalhos_ritmo(10) where klingo_id = '13825') <> date_trunc('month', hoje::timestamp)::date then raise exception 'relatório mensal lê o mês corrente'; end if;

  -- leitura em andamento há menos de 5 min: não repete
  insert into public.sync_relatorio_runs (relatorio_id, periodo) values (rel, hoje) returning id into run;
  if exists (select 1 from public.proximos_trabalhos_ritmo(10) where klingo_id = '13404') then raise exception 'não pode ler de novo enquanto roda'; end if;
  update public.sync_relatorio_runs set status = 'success', finished_at = now() where id = run;

  -- filtro de período não comprovado: fica de fora
  update public.dim_relatorio set periodo_validado_em = null where id = rel2;
  if exists (select 1 from public.proximos_trabalhos_ritmo(10) where klingo_id = '13825') then raise exception 'sem filtro comprovado não lê'; end if;
  update public.dim_relatorio set periodo_validado_em = now() where id = rel2;

  -- lista geral: o dia de hoje de quem tem ritmo não aparece (nem o mês corrente); os dias anteriores sim; os outros relatórios seguem como antes
  if exists (select 1 from public.proximos_trabalhos(100) where klingo_id = '13404' and periodo = hoje) then raise exception 'a lista geral não devia ler hoje do 13404'; end if;
  if not exists (select 1 from public.proximos_trabalhos(100) where klingo_id = '13404' and periodo = hoje - 1) then raise exception 'a lista geral devia seguir com os dias anteriores do 13404'; end if;
  if not exists (select 1 from public.proximos_trabalhos(100) where klingo_id = '99' and periodo = hoje) then raise exception 'relatório sem ritmo devia seguir na lista geral'; end if;
  if exists (select 1 from public.proximos_trabalhos(100) where klingo_id = '13825' and periodo = date_trunc('month', hoje::timestamp)::date) then raise exception 'a lista geral não devia ler o mês corrente do 13825'; end if;
end $$;

-- ---------------------------------------------------------------- 7. a barra de atualização enxerga os relatórios do ritmo
do $$ declare n integer; begin
  select count(*) into n from public.status_ritmo_coleta();
  if n <> 2 then raise exception 'a barra devia ver 2 relatórios, viu %', n; end if;
  if exists (select 1 from public.status_ritmo_coleta() where agora is null) then raise exception 'a barra precisa do relógio do servidor'; end if;
end $$;

-- ---------------------------------------------------------------- 8. pendência: como deve ser o relatório da Jornada
do $$
declare
  a public.aviso%rowtype; r jsonb;
  rel13404 uuid := '00000000-0000-0000-0000-0000000013ff';
  rel13402 uuid := '00000000-0000-0000-0000-000000013402';
begin
  perform public.jornada_pendencias_sincronizar();
  select * into a from public.aviso where painel = 'atendimento' and chave = 'jornada|jornada_relatorio_klingo';
  if not found or a.status <> 'aberto' or a.escopo <> 'jornada' or a.nivel <> 'info' then raise exception 'a pendência devia nascer aberta: %', row_to_json(a); end if;
  if a.itens_total <> 3 then raise exception 'esperava 3 itens (relatório novo, #13404 e #13402), achei %', a.itens_total; end if;
  if jsonb_array_length(a.guia -> 'passos') < 5 or jsonb_array_length(a.guia -> 'relatorios') <> 3 then raise exception 'guia incompleto'; end if;
  if a.sensivel then raise exception 'a pendência não fala de dinheiro'; end if;

  -- a conferência do painel Python (escopo "") não a resolve por engano
  perform public.aviso_sincronizar('atendimento', array['', '2026-11'], 1, '[]'::jsonb);
  select * into a from public.aviso where painel = 'atendimento' and chave = 'jornada|jornada_relatorio_klingo';
  if a.status <> 'aberto' then raise exception 'a conferência do painel resolveu a pendência da Jornada: %', a.status; end if;

  -- o Klingo passa a entregar o Id do atendimento no #13404: sobram 2 itens
  insert into public.dim_relatorio_coluna (relatorio_id, coluna_key, rotulo, titulo_klingo) values (rel13404, 'col9', 'id_atendimento', 'Id do Atendimento');
  perform public.jornada_pendencias_sincronizar();
  select * into a from public.aviso where painel = 'atendimento' and chave = 'jornada|jornada_relatorio_klingo';
  if a.status <> 'aberto' or a.itens_total <> 2 then raise exception 'devia sobrar 2 itens: % %', a.status, a.itens_total; end if;

  -- tudo pronto: resolve sozinho
  insert into public.dim_relatorio_coluna (relatorio_id, coluna_key, rotulo, titulo_klingo) values (rel13402, 'col9', 'id_atendimento', 'Id do Atendimento');
  insert into public.dim_relatorio (klingo_id, nome) values ('14000', 'Jornada do Paciente - Marcações por Data do Exame');
  r := public.jornada_pendencias_sincronizar();
  select * into a from public.aviso where painel = 'atendimento' and chave = 'jornada|jornada_relatorio_klingo';
  if a.status <> 'resolvido' then raise exception 'com tudo pronto devia resolver: %', a.status; end if;
end $$;

-- ---------------------------------------------------------------- 9. permissões: a equipe lê o ritmo, mas não escreve
do $$ begin
  if has_table_privilege('authenticated', 'public.coleta_ritmo', 'update') or has_table_privilege('authenticated', 'public.coleta_ritmo', 'insert') then raise exception 'authenticated não pode escrever em coleta_ritmo'; end if;
  if not has_table_privilege('authenticated', 'public.coleta_ritmo', 'select') then raise exception 'authenticated precisa ler coleta_ritmo'; end if;
  if has_function_privilege('anon', 'public.acordar_coleta(text)', 'execute') then raise exception 'anon não pode acordar a coleta'; end if;
  if has_function_privilege('authenticated', 'public.proximos_trabalhos_ritmo(integer)', 'execute') then raise exception 'só o service_role lê a fila do ritmo'; end if;
  if has_function_privilege('authenticated', 'public.jornada_pendencias_sincronizar()', 'execute') then raise exception 'só o service_role sincroniza a pendência'; end if;
end $$;

\echo RITMO OK
