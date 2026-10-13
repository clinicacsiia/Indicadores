-- Testes de RLS/permissão (rodam no Postgres do Supabase local: `supabase start && supabase db reset`, depois `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/rls/rls.sql`).
-- Regra: o navegador nunca lê tabela de dados. anon não lê nada; usuário logado só lê o próprio perfil, a lista de menus e a versão dos dados.
begin;

-- dados de teste (como dono do banco)
insert into auth.users (id, email) values ('00000000-0000-0000-0000-00000000000a', 'a@t.local'), ('00000000-0000-0000-0000-00000000000b', 'b@t.local') on conflict do nothing;
insert into public.perfis (id, usuario, admin, relatorios) values
  ('00000000-0000-0000-0000-00000000000a', 'usuario_a', false, '{faturamento}'),
  ('00000000-0000-0000-0000-00000000000b', 'usuario_b', true, '{*}');
insert into public.dados_blocos (menu, aba, mes, colunas, linhas, conteudo) values ('faturamento', 'Receita Produzida', '2026-10', '[]', 0, '');
insert into public.dados_versao (menu, versao) values ('faturamento', 1) on conflict (menu) do nothing;
insert into public.pendencias_resolvidas (painel, chave, titulo, usuario, versao) values ('faturamento', '2026-10|x', 'x', 'usuario_a', 1);
insert into public.historico_atualizacoes (modulo_id, status) values ('faturamento', 'ok');
insert into public.auditoria (acao) values ('teste');
insert into public.custos_itens (item) values ('LUVA');
insert into public.solicitacoes_cadastro (usuario, user_id) values ('pedido', '00000000-0000-0000-0000-00000000000b');
insert into public.fila_sincronizacao (lote, menu) values (gen_random_uuid(), 'faturamento');
insert into public.painel_cache (menu, periodo, chave_versao, conteudo) values ('faturamento', '', 'x', 'x');
insert into public.tentativas_acesso (tipo, chave) values ('ip', 'x');
insert into public.configuracoes (chave, valor) values ('teste', '1') on conflict do nothing;

create or replace function public.t_contar(p_tabela text) returns bigint language plpgsql security invoker as $$
declare n bigint; begin execute format('select count(*) from public.%I', p_tabela) into n; return n; end $$;

create or replace function public.t_exigir(p_ok boolean, p_msg text) returns void language plpgsql as $$
begin if not p_ok then raise exception 'FALHOU: %', p_msg; end if; end $$;

grant execute on function public.t_contar(text), public.t_exigir(boolean, text) to anon, authenticated;

-- 1) anon não lê nada
set local role anon;
select public.t_exigir(public.t_contar(t) = 0, 'anon leu ' || t)
  from unnest(array['perfis','solicitacoes_cadastro','tentativas_acesso','modulos','configuracoes','historico_atualizacoes','atualizacao_trava','fila_sincronizacao',
                    'dados_blocos','dados_versao','painel_cache','custos_itens','pendencias_resolvidas','auditoria']) as t;
reset role;

-- 2) usuário logado (não admin): só o próprio perfil, os menus e a versão dos dados
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', true);
set local role authenticated;
select public.t_exigir(public.t_contar('perfis') = 1, 'usuário viu perfil de outra pessoa');
select public.t_exigir((select usuario from public.perfis) = 'usuario_a', 'perfil lido não é o próprio');
select public.t_exigir(public.t_contar('modulos') = 8, 'usuário não leu a lista de menus');
select public.t_exigir(public.t_contar('dados_versao') >= 1, 'usuário não leu a versão dos dados (Realtime)');
select public.t_exigir(public.t_contar(t) = 0, 'usuário logado leu ' || t)
  from unnest(array['solicitacoes_cadastro','tentativas_acesso','configuracoes','historico_atualizacoes','atualizacao_trava','fila_sincronizacao',
                    'dados_blocos','painel_cache','custos_itens','pendencias_resolvidas','auditoria']) as t;

-- 3) usuário logado não escreve em nada (nem no próprio perfil: admin/permissões só pelo servidor)
do $$ begin
  begin update public.perfis set admin = true where id = '00000000-0000-0000-0000-00000000000a';
    perform public.t_exigir((select admin from public.perfis) = false, 'usuário se promoveu a admin');
  exception when insufficient_privilege then null; end;
  begin insert into public.dados_blocos (menu, aba, mes, colunas, conteudo) values ('x', 'y', '2026-10', '[]', '');
    raise exception 'FALHOU: usuário gravou dados';
  exception when insufficient_privilege or others then if sqlerrm like 'FALHOU%' then raise; end if; end;
end $$;
reset role;

-- 4) funções internas não são chamáveis por usuário logado
set local role authenticated;
do $$ begin
  begin perform public.subir_versao('faturamento'); raise exception 'FALHOU: usuário chamou subir_versao';
  exception when insufficient_privilege then null; end;
  begin perform public.adquirir_trava('x', 'y', 1); raise exception 'FALHOU: usuário chamou adquirir_trava';
  exception when insufficient_privilege then null; end;
  begin perform public.gravar_bloco('x', 'y', '2026-10', '[]', 0, '', false); raise exception 'FALHOU: usuário chamou gravar_bloco';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

-- 5) todas as tabelas do esquema public têm RLS ligada
select public.t_exigir(not exists (select 1 from pg_tables where schemaname = 'public' and not rowsecurity), 'há tabela sem RLS: ' || coalesce((select string_agg(tablename, ',') from pg_tables where schemaname = 'public' and not rowsecurity), ''));

rollback;
\echo 'RLS: tudo certo'
