-- Testa as migrations 20261014210000_avisos.sql e 20261016120000_dados_financeiros.sql num Postgres vazio (sem Supabase): os papéis e o auth.uid() são simulados aqui.
--
--   createdb avisos_teste && psql -v ON_ERROR_STOP=1 -d avisos_teste -f supabase/tests/avisos.sql    (na raiz do repositório)
--
-- Cada cenário usa um painel próprio e termina com `raise exception` se algo não for o esperado; chegando ao fim, imprime "AVISOS OK".
\set ON_ERROR_STOP on

do $$ begin   -- papéis são do servidor inteiro, não do banco: cria só se ainda não existirem
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema auth;
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
create table public.profiles (id uuid primary key, email text, role text not null default 'viewer', permissions jsonb not null default '{}'::jsonb, status text not null default 'ativo');
grant usage on schema public, auth to anon, authenticated, service_role;
grant select on public.profiles to authenticated;

\i supabase/migrations/20261014210000_avisos.sql

insert into public.profiles values
  ('00000000-0000-0000-0000-00000000000a', 'csiadmin@csi.local', 'admin', '{}'),
  ('00000000-0000-0000-0000-00000000000b', 'ana@csi.local',      'viewer', '{"cenario_perm": true, "cenario_nega": false}'),
  ('00000000-0000-0000-0000-00000000000c', 'bia@csi.local',      'viewer', '{}'),
  -- para a migration de "Dados financeiros" (a regra de quem já via painéis de dinheiro começa com a permissão):
  ('00000000-0000-0000-0000-00000000000d', 'dani@csi.local',     'viewer', '{"despesas": true}'),
  ('00000000-0000-0000-0000-00000000000e', 'edu@csi.local',      'viewer', '{"atendimento": true}'),
  ('00000000-0000-0000-0000-00000000000f', 'fabi@csi.local',     'viewer', '{"faturamento": true, "dados_financeiros": false}');   -- escolha já feita: não se desfaz

-- avisos que já existiam antes da migration de dados financeiros (para o preenchimento de `sensivel`)
insert into public.aviso (painel, chave, tipo, escopo, titulo, texto, nivel) values
  ('despesas',    '|des_zero',        'des_zero',        '', 'Despesas sem valor',                  'texto', 'atencao'),
  ('atendimento', '|ate_valor_zero',  'ate_valor_zero',  '', 'Atendimentos com valor R$ 0,00',      'texto', 'atencao'),
  ('atendimento', '|ate_espera',      'ate_espera',      '', 'Espera acima do aceitável',           'texto', 'atencao'),
  ('atendimento', '|ate_x',           'ate_x',           '', 'Receita por profissional caiu',       'texto', 'atencao'),
  ('suprimentos', '|sup_sem_setor',   'sup_sem_setor',   '', 'Pedidos sem centro de custo',         'texto', 'atencao'),
  ('cesta',       '|cesta_menor_fat', 'cesta_menor_fat', '', 'A receita da Cesta é menor',          'texto', 'atencao');

\i supabase/migrations/20261016120000_dados_financeiros.sql

create function pg_temp.alerta(p_tipo text, p_escopo text default '', p_nivel text default 'atencao', p_itens int default null, p_persistente boolean default false) returns jsonb
language sql as $$
  select jsonb_build_object('chave', p_escopo || '|' || p_tipo, 'tipo', p_tipo, 'escopo', p_escopo, 'titulo', 'Título ' || p_tipo, 'texto', 'texto', 'nivel', p_nivel,
                            'persistente', p_persistente, 'guia', jsonb_build_object('passos', jsonb_build_array('a')), 'itens_total', p_itens,
                            'itens', case when p_itens is null then null else jsonb_build_object('colunas', jsonb_build_array('x'), 'linhas', jsonb_build_array(), 'total', p_itens) end)
$$;
create function pg_temp.aviso(p_painel text, p_chave text) returns public.aviso language sql as $$ select * from public.aviso where painel = p_painel and chave = p_chave $$;
create function pg_temp.eventos(p_painel text, p_chave text) returns text language sql as
$$ select coalesce(string_agg(e.tipo, ',' order by e.id), '') from public.aviso_evento e join public.aviso a on a.id = e.aviso_id where a.painel = p_painel and a.chave = p_chave $$;
create function pg_temp.sync(p_painel text, p_versao bigint, p_alertas jsonb, p_escopos text[] default array['']) returns jsonb language sql as
$$ select public.aviso_sincronizar(p_painel, p_escopos, p_versao, p_alertas) $$;
create function pg_temp.espera(p_ok boolean, p_msg text) returns void language plpgsql as $$ begin if not coalesce(p_ok, false) then raise exception 'FALHOU: %', p_msg; end if; end $$;
create function pg_temp.como(p_uid text) returns void language sql as $$ select set_config('request.jwt.claim.sub', p_uid, false) $$;
-- true se a chamada levanta erro com a mensagem pedida
create function pg_temp.erra(p_sql text, p_trecho text) returns boolean language plpgsql as $$ begin execute p_sql; return false; exception when others then return position(p_trecho in sqlerrm) > 0; end $$;

-- ---- 1. ciclo de vida sem justificativa: novo -> continua -> some -> volta
do $$
declare r jsonb; a public.aviso;
begin
  r := pg_temp.sync('c1', 100, jsonb_build_array(pg_temp.alerta('t1', '', 'critico', 5)));
  perform pg_temp.espera((r ->> 'novos')::int = 1, 'novo aviso');
  a := pg_temp.aviso('c1', '|t1');
  perform pg_temp.espera(a.status = 'aberto' and a.recorrencias = 0 and a.itens_total = 5 and a.versao_dados = 100, 'nasce aberto');
  perform pg_temp.sync('c1', 100, jsonb_build_array(pg_temp.alerta('t1', '', 'critico', 7)));
  a := pg_temp.aviso('c1', '|t1');
  perform pg_temp.espera(a.status = 'aberto' and a.itens_total = 7 and pg_temp.eventos('c1', '|t1') = 'detectado', 'continua aberto, sem evento novo, itens atualizados');
  r := pg_temp.sync('c1', 101, '[]'::jsonb);
  a := pg_temp.aviso('c1', '|t1');
  perform pg_temp.espera((r ->> 'resolvidos')::int = 1 and a.status = 'resolvido' and a.resolvido_em is not null, 'sumiu = resolvido');
  perform pg_temp.sync('c1', 102, '[]'::jsonb);   -- continua ausente: nada muda
  perform pg_temp.espera(pg_temp.eventos('c1', '|t1') = 'detectado,sumiu', 'ausente de novo não gera evento');
  r := pg_temp.sync('c1', 103, jsonb_build_array(pg_temp.alerta('t1', '', 'critico', 2)));
  a := pg_temp.aviso('c1', '|t1');
  perform pg_temp.espera((r ->> 'voltaram')::int = 1 and a.status = 'aberto' and a.recorrencias = 1 and a.resolvido_em is null and a.ultima_recorrencia is not null, 'voltou = aberto + recorrência');
  perform pg_temp.espera(pg_temp.eventos('c1', '|t1') = 'detectado,sumiu,reapareceu', 'histórico do ciclo');
end $$;

-- ---- 2. justificar (não persistente): espera a próxima atualização; some = confirmado; continua = reaberto
do $$
declare a public.aviso; r jsonb;
begin
  perform pg_temp.sync('c2', 200, jsonb_build_array(pg_temp.alerta('t1', '2026-10', 'atencao', 3)), array['', '2026-10']);
  a := pg_temp.aviso('c2', '2026-10|t1');
  perform pg_temp.como('00000000-0000-0000-0000-00000000000a');
  perform pg_temp.espera(pg_temp.erra(format('select public.fechar_aviso(%s, %L)', a.id, 'curta'), 'pelo menos 15'), 'justificativa curta é recusada');
  perform pg_temp.espera(pg_temp.erra(format('select public.fechar_aviso(%s, %L)', a.id, '               '), 'pelo menos 15'), 'só espaços é recusado');
  perform public.fechar_aviso(a.id, '  Corrigi os lançamentos 10, 11 e 12 no Klingo.  ');
  a := pg_temp.aviso('c2', '2026-10|t1');
  perform pg_temp.espera(a.status = 'justificado' and a.justificativa = 'Corrigi os lançamentos 10, 11 e 12 no Klingo.' and a.justificado_por = 'csiadmin@csi.local'
                         and a.justificado_versao = 200 and a.justificado_em is not null, 'justificou (texto aparado, autor, versão dos dados)');
  perform pg_temp.espera(pg_temp.erra(format('select public.fechar_aviso(%s, %L)', a.id, 'Tentando fechar de novo o mesmo'), 'não está aberto'), 'não fecha duas vezes');
  perform pg_temp.sync('c2', 200, jsonb_build_array(pg_temp.alerta('t1', '2026-10', 'atencao', 3)), array['', '2026-10']);   -- mesmos dados: ainda não dá para conferir
  perform pg_temp.espera((pg_temp.aviso('c2', '2026-10|t1')).status = 'justificado', 'mesma versão dos dados: aguarda a próxima atualização');
  r := pg_temp.sync('c2', 201, jsonb_build_array(pg_temp.alerta('t1', '2026-10', 'atencao', 3)), array['', '2026-10']);   -- dados novos e continua
  a := pg_temp.aviso('c2', '2026-10|t1');
  perform pg_temp.espera((r ->> 'reabertos')::int = 1 and a.status = 'aberto' and a.reaberturas = 1 and a.recorrencias = 0 and a.justificativa is not null, 'continuou depois da justificativa = reaberto');
  perform public.fechar_aviso(a.id, 'Agora sim corrigido, conferi no Klingo.');
  perform pg_temp.sync('c2', 202, '[]'::jsonb, array['', '2026-10']);
  a := pg_temp.aviso('c2', '2026-10|t1');
  perform pg_temp.espera(a.status = 'resolvido' and pg_temp.eventos('c2', '2026-10|t1') = 'detectado,justificado,nao_corrigido,justificado,confirmado', 'sumiu depois da justificativa = confirmado: ' || pg_temp.eventos('c2', '2026-10|t1'));
  -- volta de novo: recorrência
  perform pg_temp.sync('c2', 203, jsonb_build_array(pg_temp.alerta('t1', '2026-10', 'atencao', 3)), array['', '2026-10']);
  a := pg_temp.aviso('c2', '2026-10|t1');
  perform pg_temp.espera(a.status = 'aberto' and a.recorrencias = 1 and a.reaberturas = 1, 'voltou depois de confirmado');
end $$;

-- ---- 3. persistente: aceito com justificativa, só reabre se piorar (25% mais registros, ou nível mais grave)
do $$
declare a public.aviso;
begin
  perform pg_temp.sync('c3', 300, jsonb_build_array(pg_temp.alerta('zero', '', 'atencao', 20, true)));
  a := pg_temp.aviso('c3', '|zero');
  perform pg_temp.como('00000000-0000-0000-0000-00000000000a');
  perform public.fechar_aviso(a.id, 'São retornos e cortesias, não têm cobrança.');
  perform pg_temp.sync('c3', 301, jsonb_build_array(pg_temp.alerta('zero', '', 'atencao', 20, true)));
  perform pg_temp.sync('c3', 302, jsonb_build_array(pg_temp.alerta('zero', '', 'atencao', 24, true)));
  perform pg_temp.espera((pg_temp.aviso('c3', '|zero')).status = 'justificado', 'persistente segue fechado com dados novos e pouca variação');
  perform pg_temp.sync('c3', 303, jsonb_build_array(pg_temp.alerta('zero', '', 'atencao', 25, true)));   -- 20 + 5 (25%)
  a := pg_temp.aviso('c3', '|zero');
  perform pg_temp.espera(a.status = 'aberto' and a.reaberturas = 1 and a.recorrencias = 0 and pg_temp.eventos('c3', '|zero') like '%piorou', 'piorou 25%: reabre');
  -- nível mais grave
  perform public.fechar_aviso(a.id, 'Aceito de novo, são cortesias.');
  perform pg_temp.sync('c3', 304, jsonb_build_array(pg_temp.alerta('zero', '', 'critico', 25, true)));
  perform pg_temp.espera((pg_temp.aviso('c3', '|zero')).status = 'aberto' and (pg_temp.aviso('c3', '|zero')).reaberturas = 2, 'nível mais grave reabre');
  -- persistente também é confirmado quando some
  perform public.fechar_aviso((pg_temp.aviso('c3', '|zero')).id, 'Aceito mais uma vez, tudo cortesia.');
  perform pg_temp.sync('c3', 305, '[]'::jsonb);
  perform pg_temp.espera((pg_temp.aviso('c3', '|zero')).status = 'resolvido', 'persistente que some = resolvido');
end $$;

-- ---- 4. escopos: aviso de um mês que saiu da janela não é "resolvido" por engano
do $$
begin
  perform pg_temp.sync('c4', 400, jsonb_build_array(pg_temp.alerta('a', '2026-09'), pg_temp.alerta('b', '2026-10'), pg_temp.alerta('c', '')), array['', '2026-09', '2026-10']);
  perform pg_temp.sync('c4', 401, jsonb_build_array(pg_temp.alerta('b', '2026-10'), pg_temp.alerta('c', '')), array['', '2026-10', '2026-11']);   -- janela andou: 2026-09 saiu
  perform pg_temp.espera((pg_temp.aviso('c4', '2026-09|a')).status = 'aberto', 'mês fora da janela fica como estava');
  perform pg_temp.sync('c4', 402, jsonb_build_array(pg_temp.alerta('c', '')), array['', '2026-10', '2026-11']);
  perform pg_temp.espera((pg_temp.aviso('c4', '2026-10|b')).status = 'resolvido' and (pg_temp.aviso('c4', '|c')).status = 'aberto', 'mês dentro da janela que sumiu = resolvido');
  perform pg_temp.espera(pg_temp.erra($q$select public.aviso_sincronizar('c4', array[''], 1, '{}'::jsonb)$q$, 'array'), 'lista inválida é recusada');
end $$;

-- ---- 5. quem vê e quem fecha
do $$
declare id_perm bigint; id_nega bigint; n int;
begin
  perform pg_temp.sync('cenario_perm', 500, jsonb_build_array(pg_temp.alerta('t1')));
  perform pg_temp.sync('cenario_nega', 500, jsonb_build_array(pg_temp.alerta('t1')));
  select id into id_perm from public.aviso where painel = 'cenario_perm';
  select id into id_nega from public.aviso where painel = 'cenario_nega';

  set local role authenticated;
  perform pg_temp.como('00000000-0000-0000-0000-00000000000a');   -- admin: vê tudo
  select count(*) into n from public.aviso where painel in ('cenario_perm', 'cenario_nega');
  perform pg_temp.espera(n = 2, 'admin vê todos os painéis');
  select count(*) into n from public.aviso_evento where painel in ('cenario_perm', 'cenario_nega');
  perform pg_temp.espera(n = 2, 'admin vê o histórico de todos');

  perform pg_temp.como('00000000-0000-0000-0000-00000000000b');   -- ana: só o painel liberado
  select count(*) into n from public.aviso where painel in ('cenario_perm', 'cenario_nega');
  perform pg_temp.espera(n = 1, 'viewer vê só o painel liberado');
  select count(*) into n from public.aviso_evento where painel = 'cenario_nega';
  perform pg_temp.espera(n = 0, 'viewer não vê o histórico do painel bloqueado');
  perform pg_temp.espera(pg_temp.erra(format('select public.fechar_aviso(%s, %L)', id_nega, 'Tentando fechar o que não posso ver'), 'não encontrado'), 'viewer não fecha aviso de painel bloqueado');
  perform public.fechar_aviso(id_perm, 'Conferi com o faturamento e já foi regularizado.');
  perform pg_temp.espera((select justificado_por from public.aviso where id = id_perm) = 'ana@csi.local', 'registra quem justificou');
  perform pg_temp.espera(pg_temp.erra(format('update public.aviso set status = %L where id = %s', 'resolvido', id_perm), 'permission denied'), 'viewer não altera a tabela direto');
  perform pg_temp.espera(pg_temp.erra($q$select public.aviso_sincronizar('x', array[''], 1, '[]'::jsonb)$q$, 'permission denied'), 'viewer não chama a sincronização');
  perform public.reabrir_aviso(id_perm);
  perform pg_temp.espera((select status from public.aviso where id = id_perm) = 'aberto', 'reabrir à mão');

  perform pg_temp.como('00000000-0000-0000-0000-00000000000c');   -- bia: nenhum painel
  select count(*) into n from public.aviso where painel in ('cenario_perm', 'cenario_nega');
  perform pg_temp.espera(n = 0, 'viewer sem permissão não vê nada');
  perform pg_temp.como('');
  perform pg_temp.espera(pg_temp.erra(format('select public.fechar_aviso(%s, %L)', id_perm, 'Sem estar logado no sistema'), 'Entre no site'), 'sem login não fecha');
  reset role;
end $$;

-- ---- 6. dados financeiros: permissão, preenchimento do que já existia e quem vê/fecha o aviso de dinheiro
do $$
declare n int; id_s bigint; id_n bigint;
begin
  -- 6a. quem já via painel de dinheiro começa com a permissão; os outros não; a escolha já feita fica
  perform pg_temp.espera((select permissions ->> 'dados_financeiros' from public.profiles where email = 'dani@csi.local') = 'true', 'quem já via Despesas começa com Dados financeiros');
  perform pg_temp.espera((select not (permissions ? 'dados_financeiros') from public.profiles where email = 'edu@csi.local'), 'quem só via painel misto começa sem');
  perform pg_temp.espera((select permissions ->> 'dados_financeiros' from public.profiles where email = 'fabi@csi.local') = 'false', 'a escolha já feita não é desfeita');
  perform pg_temp.espera((select not (permissions ? 'dados_financeiros') from public.profiles where role = 'admin'), 'admin não precisa da chave (sempre vê)');

  -- 6b. avisos que já existiam: de painel só de dinheiro e os que falam de dinheiro viram sensíveis; os de cadastro/operação não
  perform pg_temp.espera((select sensivel from public.aviso where painel = 'despesas' and tipo = 'des_zero'), 'aviso de painel só de dinheiro é sensível');
  perform pg_temp.espera((select sensivel from public.aviso where tipo = 'cesta_menor_fat'), 'aviso de receita da Cesta é sensível');
  perform pg_temp.espera((select sensivel from public.aviso where tipo = 'ate_x'), 'aviso que cita receita é sensível (pelo texto)');
  perform pg_temp.espera(not (select sensivel from public.aviso where tipo = 'ate_valor_zero'), 'valor zerado é problema de cadastro, não mostra dinheiro');
  perform pg_temp.espera(not (select sensivel from public.aviso where tipo = 'ate_espera'), 'espera não é dinheiro');
  perform pg_temp.espera(not (select sensivel from public.aviso where tipo = 'sup_sem_setor'), '"centro de custo" é setor, não dinheiro');

  -- 6c. a sincronização grava `sensivel` (e corrige se o servidor mudar de ideia)
  perform pg_temp.sync('cenario_fin', 600, jsonb_build_array(
    pg_temp.alerta('dinheiro') || '{"sensivel": true}'::jsonb, pg_temp.alerta('normal')));
  perform pg_temp.espera((pg_temp.aviso('cenario_fin', '|dinheiro')).sensivel and not (pg_temp.aviso('cenario_fin', '|normal')).sensivel, 'sync grava sensivel');
  perform pg_temp.sync('cenario_fin', 601, jsonb_build_array(pg_temp.alerta('dinheiro'), pg_temp.alerta('normal')));
  perform pg_temp.espera(not (pg_temp.aviso('cenario_fin', '|dinheiro')).sensivel, 'sync também atualiza sensivel');
  perform pg_temp.sync('cenario_fin', 602, jsonb_build_array(pg_temp.alerta('dinheiro') || '{"sensivel": true}'::jsonb, pg_temp.alerta('normal')));

  -- 6d. quem vê: o painel liberado E (aviso não sensível OU Dados financeiros)
  update public.profiles set permissions = '{"cenario_fin": true}' where email = 'ana@csi.local';                                  -- ana: painel, sem dinheiro
  update public.profiles set permissions = '{"cenario_fin": true, "dados_financeiros": true}' where email = 'bia@csi.local';       -- bia: painel e dinheiro
  select id into id_s from public.aviso where painel = 'cenario_fin' and tipo = 'dinheiro';
  select id into id_n from public.aviso where painel = 'cenario_fin' and tipo = 'normal';

  set local role authenticated;
  perform pg_temp.como('00000000-0000-0000-0000-00000000000b');   -- ana
  select count(*) into n from public.aviso where painel = 'cenario_fin';
  perform pg_temp.espera(n = 1, 'sem Dados financeiros: só o aviso que não é de dinheiro');
  perform pg_temp.espera(not exists (select 1 from public.aviso where id = id_s), 'o aviso de dinheiro não aparece');
  select count(*) into n from public.aviso_evento where painel = 'cenario_fin';
  perform pg_temp.espera(n = 1, 'o histórico do aviso de dinheiro também não aparece');
  perform pg_temp.espera(pg_temp.erra(format('select public.fechar_aviso(%s, %L)', id_s, 'Tentando fechar aviso de dinheiro'), 'não encontrado'), 'não fecha aviso de dinheiro');
  perform public.fechar_aviso(id_n, 'Conferi no Klingo e já foi corrigido.');
  perform pg_temp.espera(pg_temp.erra(format('select public.reabrir_aviso(%s)', id_s), 'não encontrado'), 'não reabre aviso de dinheiro');

  perform pg_temp.como('00000000-0000-0000-0000-00000000000c');   -- bia
  select count(*) into n from public.aviso where painel = 'cenario_fin';
  perform pg_temp.espera(n = 2, 'com Dados financeiros: vê os dois');
  select count(*) into n from public.aviso_evento where painel = 'cenario_fin';
  perform pg_temp.espera(n >= 3, 'com Dados financeiros: vê o histórico dos dois');
  perform public.fechar_aviso(id_s, 'Conferi os valores com o faturamento.');

  perform pg_temp.como('00000000-0000-0000-0000-00000000000a');   -- admin: tudo
  select count(*) into n from public.aviso where painel = 'cenario_fin';
  perform pg_temp.espera(n = 2, 'admin vê os dois');
  reset role;

  -- 6f. a tabela legada `indicadores` (lida direto pela API) também exige Dados financeiros
  update public.profiles set permissions = '{"relatorios": true}' where email = 'ana@csi.local';
  update public.profiles set permissions = '{"relatorios": true, "dados_financeiros": true}' where email = 'bia@csi.local';
  update public.profiles set permissions = '{"relatorios": false, "dados_financeiros": true}' where email = 'dani@csi.local';
  perform pg_temp.como('00000000-0000-0000-0000-00000000000a'); perform pg_temp.espera(public.can_view_relatorios(), 'admin lê indicadores');
  perform pg_temp.como('00000000-0000-0000-0000-00000000000b'); perform pg_temp.espera(not public.can_view_relatorios(), 'relatorios liberado mas sem Dados financeiros: não lê indicadores');
  perform pg_temp.como('00000000-0000-0000-0000-00000000000c'); perform pg_temp.espera(public.can_view_relatorios(), 'relatorios + Dados financeiros: lê indicadores');
  perform pg_temp.como('00000000-0000-0000-0000-00000000000d'); perform pg_temp.espera(not public.can_view_relatorios(), 'relatorios bloqueado continua bloqueado');

  -- 6e. painel não liberado continua escondendo tudo, mesmo com Dados financeiros
  update public.profiles set permissions = '{"dados_financeiros": true}' where email = 'bia@csi.local';
  set local role authenticated;
  perform pg_temp.como('00000000-0000-0000-0000-00000000000c');
  select count(*) into n from public.aviso where painel = 'cenario_fin';
  perform pg_temp.espera(n = 0, 'Dados financeiros não libera painel: a regra de painel vem primeiro');
  reset role;
end $$;

select 'AVISOS OK' as resultado;
