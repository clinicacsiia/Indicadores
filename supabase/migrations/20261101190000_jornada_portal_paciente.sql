-- Jornada do paciente, etapa 6: portal do paciente (DESLIGADO por padrão) e a conversa da equipe com o paciente.
--
-- Como o paciente entra: sem conta e sem SMS. A equipe gera um LINK SEGURO por cartão (jornada_portal_gerar_link) e o envia por onde quiser (a tela monta a mensagem do WhatsApp).
-- O link carrega um código aleatório de 244 bits; o banco guarda só o hash (sha256), nunca o código. Vale até depois do dia do atendimento (jornada_config.link_validade_dias),
-- pode ser trocado (o link anterior morre) e só existe enquanto o portal estiver ligado (jornada_config.portal_ativo, nasce FALSE).
-- O navegador do paciente NÃO fala com o banco: a página do site (rota /p/<código>) chama as funções portal_* com a chave de serviço, que só o servidor tem. Essas funções
-- não são executáveis por anon nem authenticated.
-- O que o paciente vê: primeiro nome, dia, unidade, exames (hora, nome, situação) e a conversa com a equipe. NÃO vê telefone, prontuário, convênio, valores, laudos nem a conversa interna.
-- O que o paciente faz: confirmar presença (a equipe registra no Klingo, que o site ainda não escreve), pedir para remarcar e escrever para a equipe (limite por hora).
-- Cada ação vira tarefa para a equipe e fica no histórico do cartão. Tentativas com código errado são contadas por origem (hash do IP) e bloqueadas por 1 hora.
-- Só create, alter table add column, grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

create table if not exists public.jornada_config (
  id                  boolean primary key default true check (id),
  portal_ativo        boolean not null default false,
  link_validade_dias  integer not null default 3 check (link_validade_dias between 1 and 30),
  mensagens_por_hora  integer not null default 20 check (mensagens_por_hora between 1 and 200),
  tentativas_por_hora integer not null default 30 check (tentativas_por_hora between 5 and 1000)
);
insert into public.jornada_config (id) values (true) on conflict (id) do nothing;

alter table public.jornada_config enable row level security;
create policy "jornada_config_select" on public.jornada_config for select to authenticated using (public.is_admin());
revoke all on public.jornada_config from public, anon, authenticated;
grant select on public.jornada_config to authenticated;
grant all    on public.jornada_config to service_role;
comment on table public.jornada_config is 'Chaves do portal do paciente. portal_ativo nasce desligado: ligar só depois de resolver as pendências de LGPD/jurídico.';

alter table public.jornada_card add column if not exists portal_confirmou_em timestamptz;

create table if not exists public.jornada_portal_acesso (
  id               bigint generated always as identity primary key,
  card_id          bigint      not null references public.jornada_card (id),
  token_hash       text        not null unique,
  criado_por       uuid,
  criado_em        timestamptz not null default now(),
  expira_em        timestamptz not null,
  revogado_em      timestamptz,
  ultimo_acesso_em timestamptz,
  n_acessos        integer     not null default 0
);
create index if not exists jornada_portal_acesso_card_idx on public.jornada_portal_acesso (card_id);

create table if not exists public.portal_tentativa (
  ip_hash text        not null,
  janela  timestamptz not null,
  n       integer     not null default 0,
  primary key (ip_hash, janela)
);

alter table public.jornada_portal_acesso enable row level security;
alter table public.portal_tentativa      enable row level security;
create policy "jornada_portal_acesso_select" on public.jornada_portal_acesso for select to authenticated using (public.can_view_painel('jornada'));

revoke all on public.jornada_portal_acesso, public.portal_tentativa from public, anon, authenticated;
-- a equipe vê o estado do link (validade, último acesso), mas nunca o hash do código
grant select (id, card_id, criado_por, criado_em, expira_em, revogado_em, ultimo_acesso_em, n_acessos) on public.jornada_portal_acesso to authenticated;
grant all on public.jornada_portal_acesso, public.portal_tentativa to service_role;

-- ---------------------------------------------------------------- lado da equipe
create or replace function public.jornada_portal_ativo()
returns boolean
language sql
stable
set search_path = ''
as $$
  select coalesce((select portal_ativo from public.jornada_config), false);
$$;
revoke execute on function public.jornada_portal_ativo() from public, anon, authenticated;
grant  execute on function public.jornada_portal_ativo() to service_role;

-- Gera (ou troca) o link do cartão. Devolve o código UMA vez; depois só existe o hash.
create or replace function public.jornada_portal_gerar_link(p_card bigint)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  c        public.jornada_card%rowtype;
  v_token  text := replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', '');
  v_dias   integer;
  v_expira timestamptz;
begin
  if auth.uid() is null then raise exception 'Faça login.'; end if;
  if not public.can_view_painel('jornada') then raise exception 'Sem permissão para a Jornada.'; end if;
  if not public.jornada_portal_ativo() then raise exception 'O portal do paciente está desligado.'; end if;
  select * into c from public.jornada_card where id = p_card;
  if not found or c.arquivado_em is not null then raise exception 'Card não encontrado.'; end if;
  if c.paciente_chave like 'manual:%' then raise exception 'Este cartão ainda não tem paciente do Klingo.'; end if;

  select link_validade_dias into v_dias from public.jornada_config;
  -- vale até a virada do dia (data do atendimento + validade); se o atendimento já passou, conta a partir de hoje
  v_expira := greatest(((c.data_ref + v_dias + 1)::timestamp) at time zone 'America/Sao_Paulo', now() + make_interval(days => v_dias));

  update public.jornada_portal_acesso set revogado_em = now() where card_id = p_card and revogado_em is null;
  insert into public.jornada_portal_acesso (card_id, token_hash, criado_por, expira_em)
  values (p_card, encode(sha256(convert_to(v_token, 'UTF8')), 'hex'), auth.uid(), v_expira);
  insert into public.jornada_evento (card_id, tipo, origem, usuario, detalhe) values (p_card, 'nota', 'pessoa', auth.uid(), jsonb_build_object('acao', 'link_do_paciente_gerado'));
  return jsonb_build_object('token', v_token, 'expira_em', v_expira);
end;
$$;

create or replace function public.jornada_portal_revogar_link(p_card bigint)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  n integer;
begin
  if auth.uid() is null then raise exception 'Faça login.'; end if;
  if not public.can_view_painel('jornada') then raise exception 'Sem permissão para a Jornada.'; end if;
  update public.jornada_portal_acesso set revogado_em = now() where card_id = p_card and revogado_em is null;
  get diagnostics n = row_count;
  if n > 0 then
    insert into public.jornada_evento (card_id, tipo, origem, usuario, detalhe) values (p_card, 'nota', 'pessoa', auth.uid(), jsonb_build_object('acao', 'link_do_paciente_revogado'));
  end if;
  return jsonb_build_object('ok', true, 'revogados', n);
end;
$$;

-- Resposta da equipe ao paciente (canal "paciente"). Fecha sozinha a tarefa "Responder o paciente".
create or replace function public.jornada_enviar_mensagem_paciente(p_card bigint, p_texto text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_texto text := trim(coalesce(p_texto, ''));
  v_id bigint;
begin
  if auth.uid() is null then raise exception 'Faça login.'; end if;
  if not public.can_view_painel('jornada') then raise exception 'Sem permissão para a Jornada.'; end if;
  if not public.jornada_portal_ativo() then raise exception 'O portal do paciente está desligado.'; end if;
  if char_length(v_texto) < 1 or char_length(v_texto) > 1000 then raise exception 'A mensagem ao paciente precisa ter de 1 a 1000 letras.'; end if;
  if not exists (select 1 from public.jornada_card where id = p_card) then raise exception 'Card não encontrado.'; end if;
  insert into public.jornada_mensagem (card_id, canal, autor, autor_nome, autor_tipo, texto)
  values (p_card, 'paciente', auth.uid(), public.jornada_nome_de(auth.uid()), 'equipe', v_texto)
  returning id into v_id;
  update public.jornada_tarefa set feita_em = now(), feita_por = auth.uid() where card_id = p_card and chave like 'responder:%' and feita_em is null;
  return v_id;
end;
$$;

revoke execute on function public.jornada_portal_gerar_link(bigint)               from public, anon;
revoke execute on function public.jornada_portal_revogar_link(bigint)             from public, anon;
revoke execute on function public.jornada_enviar_mensagem_paciente(bigint, text)  from public, anon;
grant  execute on function public.jornada_portal_gerar_link(bigint)               to authenticated;
grant  execute on function public.jornada_portal_revogar_link(bigint)             to authenticated;
grant  execute on function public.jornada_enviar_mensagem_paciente(bigint, text)  to authenticated;

-- ---------------------------------------------------------------- lado do paciente (só a chave de serviço, chamada pelo servidor do site)
-- Procura o link; conta o erro por origem (hash do IP). Devolve null quando o código não vale.
create or replace function public.portal_resolver(p_token text, p_ip text)
returns public.jornada_portal_acesso
language plpgsql
security definer
set search_path = ''
as $$
declare
  a public.jornada_portal_acesso%rowtype;
  v_limite integer;
begin
  select * into a from public.jornada_portal_acesso
  where token_hash = encode(sha256(convert_to(coalesce(p_token, ''), 'UTF8')), 'hex') and revogado_em is null and expira_em > now();
  if found then
    return a;
  end if;
  if coalesce(p_ip, '') <> '' then
    insert into public.portal_tentativa (ip_hash, janela, n) values (p_ip, date_trunc('hour', now()), 1)
    on conflict (ip_hash, janela) do update set n = public.portal_tentativa.n + 1;
  end if;
  return null;
end;
$$;

create or replace function public.portal_bloqueado(p_ip text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(p_ip, '') <> '' and coalesce((select sum(n) from public.portal_tentativa where ip_hash = p_ip and janela >= now() - interval '1 hour'), 0) >= (select tentativas_por_hora from public.jornada_config);
$$;

-- A página do paciente. Só primeiro nome, dia, unidade, exames e a conversa do canal "paciente".
create or replace function public.portal_ver(p_token text, p_ip text default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  a public.jornada_portal_acesso%rowtype;
  c public.jornada_card%rowtype;
  v_hoje date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  if not public.jornada_portal_ativo() then return jsonb_build_object('ok', false, 'motivo', 'desligado'); end if;
  if public.portal_bloqueado(p_ip) then return jsonb_build_object('ok', false, 'motivo', 'limite'); end if;
  a := public.portal_resolver(p_token, p_ip);
  if a.id is null then return jsonb_build_object('ok', false, 'motivo', 'invalido'); end if;
  update public.jornada_portal_acesso set ultimo_acesso_em = now(), n_acessos = n_acessos + 1 where id = a.id;
  select * into c from public.jornada_card where id = a.card_id;
  return jsonb_build_object(
    'ok', true,
    'nome', coalesce((select initcap(split_part(trim(p.nome), ' ', 1)) from public.jornada_paciente p where p.prontuario = c.paciente_chave), ''),
    'data', c.data_ref,
    'unidade', c.unidade,
    'confirmou_em', c.portal_confirmou_em,
    'pode_agir', c.coluna in ('a_confirmar', 'confirmado') and c.data_ref >= v_hoje,
    'exames', coalesce((
      select jsonb_agg(jsonb_build_object('hora', to_char(e.agendado_para at time zone 'America/Sao_Paulo', 'HH24:MI'), 'exame', e.procedimento, 'situacao', e.status) order by e.agendado_para, e.id)
      from public.jornada_exame e where e.card_id = c.id), '[]'::jsonb),
    'mensagens', coalesce((
      select jsonb_agg(jsonb_build_object('de', case when m.autor_tipo = 'paciente' then 'paciente' else 'equipe' end, 'texto', m.texto, 'quando', m.criado_em) order by m.id)
      from (select * from public.jornada_mensagem where card_id = c.id and canal = 'paciente' order by id desc limit 100) m), '[]'::jsonb)
  );
end;
$$;

create or replace function public.portal_confirmar(p_token text, p_ip text default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  a public.jornada_portal_acesso%rowtype;
  c public.jornada_card%rowtype;
  v_hoje date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  if not public.jornada_portal_ativo() then return jsonb_build_object('ok', false, 'motivo', 'desligado'); end if;
  if public.portal_bloqueado(p_ip) then return jsonb_build_object('ok', false, 'motivo', 'limite'); end if;
  a := public.portal_resolver(p_token, p_ip);
  if a.id is null then return jsonb_build_object('ok', false, 'motivo', 'invalido'); end if;
  select * into c from public.jornada_card where id = a.card_id for update;
  if c.coluna not in ('a_confirmar', 'confirmado') or c.data_ref < v_hoje then return jsonb_build_object('ok', false, 'motivo', 'indisponivel'); end if;
  if c.portal_confirmou_em is null then
    update public.jornada_card set portal_confirmou_em = now(), versao = versao + 1, atualizado_em = now() where id = c.id;
    update public.jornada_tarefa set feita_em = now() where card_id = c.id and chave = 'confirmar' and feita_em is null;
    insert into public.jornada_tarefa (card_id, titulo, origem, chave, vence_em)
    values (c.id, 'Registrar no Klingo a confirmação feita pelo paciente', 'sistema', 'klingo_confirmar', now() + interval '2 hours')
    on conflict (card_id, chave) where chave is not null do nothing;
    insert into public.jornada_evento (card_id, tipo, origem, detalhe) values (c.id, 'nota', 'sistema', jsonb_build_object('acao', 'paciente_confirmou_pelo_site'));
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function public.portal_remarcar(p_token text, p_nota text default null, p_ip text default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  a public.jornada_portal_acesso%rowtype;
  c public.jornada_card%rowtype;
  v_nota text := left(trim(coalesce(p_nota, '')), 500);
  v_hoje date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  if not public.jornada_portal_ativo() then return jsonb_build_object('ok', false, 'motivo', 'desligado'); end if;
  if public.portal_bloqueado(p_ip) then return jsonb_build_object('ok', false, 'motivo', 'limite'); end if;
  a := public.portal_resolver(p_token, p_ip);
  if a.id is null then return jsonb_build_object('ok', false, 'motivo', 'invalido'); end if;
  select * into c from public.jornada_card where id = a.card_id for update;
  if c.coluna not in ('a_confirmar', 'confirmado') or c.data_ref < v_hoje then return jsonb_build_object('ok', false, 'motivo', 'indisponivel'); end if;
  insert into public.jornada_mensagem (card_id, canal, autor, autor_nome, autor_tipo, texto)
  values (c.id, 'paciente', null, 'Paciente', 'paciente', 'Preciso remarcar.' || case when v_nota <> '' then ' ' || v_nota else '' end);
  insert into public.jornada_tarefa (card_id, titulo, origem, chave, vence_em)
  values (c.id, 'Paciente pediu para remarcar: ligar e combinar nova data', 'sistema', 'pedido_remarcar:' || to_char(now() at time zone 'America/Sao_Paulo', 'YYYYMMDDHH24'), now() + interval '1 hour')
  on conflict (card_id, chave) where chave is not null do nothing;
  update public.jornada_card set prioridade = greatest(prioridade, 2), versao = versao + 1, atualizado_em = now() where id = c.id;
  insert into public.jornada_evento (card_id, tipo, origem, detalhe) values (c.id, 'nota', 'sistema', jsonb_build_object('acao', 'paciente_pediu_para_remarcar'));
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function public.portal_enviar_mensagem(p_token text, p_texto text, p_ip text default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  a public.jornada_portal_acesso%rowtype;
  v_texto text := trim(coalesce(p_texto, ''));
  v_id bigint;
  v_limite integer;
begin
  if not public.jornada_portal_ativo() then return jsonb_build_object('ok', false, 'motivo', 'desligado'); end if;
  if public.portal_bloqueado(p_ip) then return jsonb_build_object('ok', false, 'motivo', 'limite'); end if;
  a := public.portal_resolver(p_token, p_ip);
  if a.id is null then return jsonb_build_object('ok', false, 'motivo', 'invalido'); end if;
  if char_length(v_texto) < 1 or char_length(v_texto) > 1000 then return jsonb_build_object('ok', false, 'motivo', 'tamanho'); end if;
  select mensagens_por_hora into v_limite from public.jornada_config;
  if (select count(*) from public.jornada_mensagem where card_id = a.card_id and autor_tipo = 'paciente' and criado_em > now() - interval '1 hour') >= v_limite then
    return jsonb_build_object('ok', false, 'motivo', 'muitas');
  end if;
  insert into public.jornada_mensagem (card_id, canal, autor, autor_nome, autor_tipo, texto) values (a.card_id, 'paciente', null, 'Paciente', 'paciente', v_texto) returning id into v_id;
  if not exists (select 1 from public.jornada_tarefa where card_id = a.card_id and chave like 'responder:%' and feita_em is null) then
    insert into public.jornada_tarefa (card_id, titulo, origem, chave, vence_em) values (a.card_id, 'Responder a mensagem do paciente', 'sistema', 'responder:' || v_id, now() + interval '1 hour');
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

revoke execute on function public.portal_resolver(text, text)              from public, anon, authenticated;
revoke execute on function public.portal_bloqueado(text)                   from public, anon, authenticated;
revoke execute on function public.portal_ver(text, text)                   from public, anon, authenticated;
revoke execute on function public.portal_confirmar(text, text)             from public, anon, authenticated;
revoke execute on function public.portal_remarcar(text, text, text)        from public, anon, authenticated;
revoke execute on function public.portal_enviar_mensagem(text, text, text) from public, anon, authenticated;
grant  execute on function public.portal_resolver(text, text)              to service_role;
grant  execute on function public.portal_bloqueado(text)                   to service_role;
grant  execute on function public.portal_ver(text, text)                   to service_role;
grant  execute on function public.portal_confirmar(text, text)             to service_role;
grant  execute on function public.portal_remarcar(text, text, text)        to service_role;
grant  execute on function public.portal_enviar_mensagem(text, text, text) to service_role;

-- o quadro mostra quem confirmou pelo site (coluna nova no fim da visão)
create or replace view public.v_jornada_quadro with (security_invoker = true) as
select
  c.id, c.paciente_chave, p.nome as paciente_nome, c.data_ref, c.unidade,
  c.coluna, k.nome as coluna_nome, k.etapa, k.origem, k.ordem,
  c.coluna_desde, c.responsavel, c.prioridade, c.versao,
  n.n_exames, n.n_ativos, n.n_mensagens,
  (n.n_ativos = 0 and n.n_mensagens = 0 and k.origem = 'klingo') as vazio,
  (k.sla_min is not null and now() - c.coluna_desde > make_interval(mins => k.sla_min)) as atrasado,
  floor(extract(epoch from (now() - c.coluna_desde)) / 60)::integer as minutos_na_coluna,
  n.n_tarefas_abertas, n.n_tarefas_vencidas,
  c.portal_confirmou_em
from public.jornada_card c
join public.jornada_coluna k on k.id = c.coluna
left join public.jornada_paciente p on p.prontuario = c.paciente_chave
cross join lateral (
  select
    (select count(*) from public.jornada_exame e where e.card_id = c.id)::integer as n_exames,
    (select count(*) from public.jornada_exame e where e.card_id = c.id and e.status not in ('cancelado', 'remarcado'))::integer as n_ativos,
    (select count(*) from public.jornada_mensagem m where m.card_id = c.id)::integer as n_mensagens,
    (select count(*) from public.jornada_tarefa t where t.card_id = c.id and t.feita_em is null)::integer as n_tarefas_abertas,
    (select count(*) from public.jornada_tarefa t where t.card_id = c.id and t.feita_em is null and t.vence_em < now())::integer as n_tarefas_vencidas
) n
where c.arquivado_em is null;

-- ---------------------------------------------------------------- pendências desta etapa
insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('ligar_portal', 6,
   'Ligar o portal do paciente (hoje DESLIGADO) depois de resolver o jurídico',
   'O portal está pronto, mas nasce desligado: com ele desligado, a equipe não gera link e a página do paciente responde "indisponível". Ligar expõe dado de saúde (nome dos exames e horários) a quem tiver o link.',
   'critico',
   '["Só ligue depois de: (1) parecer do jurídico/encarregado sobre base legal, aviso de privacidade e retenção das conversas; (2) texto final do aviso de privacidade colocado na página do paciente; (3) escolha de como enviar o link (WhatsApp da clínica, por exemplo).", "Para ligar: update public.jornada_config set portal_ativo = true;  Para desligar de novo (os links deixam de funcionar na hora): update public.jornada_config set portal_ativo = false;", "Ajustes: link_validade_dias (3), mensagens_por_hora (20) e tentativas_por_hora (30) na mesma tabela."]'::jsonb),
  ('texto_privacidade_portal', 6,
   'Escrever o aviso de privacidade que aparece na página do paciente',
   'A página do paciente mostra apenas um aviso curto provisório ("conversa com a equipe da clínica; não envie documentos nem informações de saúde por aqui"). O texto definitivo precisa vir do jurídico/encarregado de dados: quem é o controlador, para que os dados são usados, por quanto tempo ficam, como pedir correção ou exclusão e o contato do encarregado.',
   'atencao',
   '["Mande o texto final e o contato do encarregado; eu coloco na página e num link no rodapé.", "Decida também se o paciente precisa marcar ''li e concordo'' antes de escrever para a equipe."]'::jsonb),
  ('identidade_link_portal', 6,
   'Decidir se o link seguro basta ou se o paciente deve se identificar',
   'Hoje quem tem o link vê o primeiro nome, o dia, a unidade, os exames e a conversa. Não há senha nem código por SMS: o risco é o paciente (ou alguém) repassar o link. Mitigações já prontas: link de 244 bits, vale só alguns dias, a equipe pode trocar ou revogar, e o portal nunca mostra telefone, prontuário, convênio, valor nem laudo. Para exibir mais (laudo, por exemplo), o link sozinho não basta.',
   'atencao',
   '["Responda se o link sozinho é aceitável para confirmar presença e conversar, ou se quer pedir também a data de nascimento do paciente (o Klingo não entrega esse dado hoje: seria preciso incluí-lo no relatório novo).", "Laudos e resultados só entram no portal depois dessa decisão e do parecer do jurídico."]'::jsonb)
on conflict (chave) do nothing;
