-- Jornada do paciente, etapa 2: modelo de dados e regras do quadro (Kanban).
--
-- Um card = um paciente num dia e numa unidade (chave: prontuário + data + unidade), com os exames dentro (`jornada_exame`, uma linha por marcação do Klingo).
-- Tudo o que acontece vira um evento em `jornada_evento` (só se acrescenta, nunca se altera). A coluna do card obedece a uma máquina de estados:
--   * colunas do Klingo (origem 'klingo') andam sozinhas, por `jornada_aplicar_klingo` (service_role); ninguém arrasta para elas;
--   * colunas manuais (origem 'manual') só se movem por `jornada_mover_card`, por uma transição cadastrada em `jornada_transicao`;
--   * o Klingo nunca puxa um card para trás de uma coluna manual (registra uma "divergência"); o cancelamento só vale antes do atendimento.
-- Quem tem a permissão `jornada` (profiles.permissions.jornada = true; o administrador sempre) vê TUDO do quadro e age nele. Ninguém grava direto nas
-- tabelas: só pelas funções. A tela, a leitura do Klingo e o tempo real vêm nas próximas etapas.
-- Só create, grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

-- ---------------------------------------------------------------- colunas e transições (a máquina de estados)
create table if not exists public.jornada_coluna (
  id      text primary key,
  nome    text    not null,
  ordem   integer not null,
  etapa   text    not null check (etapa in ('antes', 'agendamento', 'depois', 'pos', 'excecao')),
  origem  text    not null check (origem in ('klingo', 'manual')),
  sla_min integer check (sla_min is null or sla_min > 0),     -- tempo máximo no card nesta coluna antes de ficar "atrasado"
  ativa   boolean not null default true
);

create table if not exists public.jornada_transicao (
  de   text not null references public.jornada_coluna (id),
  para text not null references public.jornada_coluna (id),
  primary key (de, para)
);

insert into public.jornada_coluna (id, nome, ordem, etapa, origem, sla_min) values
  ('contato',        'Novo contato',          1,  'antes',       'manual', 120),
  ('orcamento',      'Orçamento',             2,  'antes',       'manual', 1440),
  ('autorizacao',    'Aguardando autorização', 3, 'antes',       'manual', 4320),
  ('a_confirmar',    'A confirmar',           4,  'agendamento', 'klingo', null),
  ('confirmado',     'Confirmado',            5,  'agendamento', 'klingo', null),
  ('chegou',         'Chegou',                6,  'depois',      'manual', 30),
  ('em_atendimento', 'Em atendimento',        7,  'depois',      'klingo', 120),
  ('finalizado',     'Finalizado',            8,  'depois',      'manual', 30),
  ('laudo_pendente', 'Laudo pendente',        9,  'pos',         'manual', 2880),
  ('laudo_entregue', 'Laudo entregue',        10, 'pos',         'manual', 1440),
  ('faturamento',    'Guia / faturamento',    11, 'pos',         'manual', 4320),
  ('nps_retorno',    'NPS e retorno',         12, 'pos',         'manual', 4320),
  ('concluido',      'Concluído',             13, 'pos',         'manual', null),
  ('cancelado',      'Cancelado',             20, 'excecao',     'klingo', null),
  ('remarcado',      'Remarcado',             21, 'excecao',     'klingo', null),
  ('faltou',         'Faltou',                22, 'excecao',     'klingo', null),
  ('perdido',        'Perdido',               23, 'excecao',     'manual', null)
on conflict (id) do nothing;

insert into public.jornada_transicao (de, para) values
  ('contato', 'orcamento'), ('contato', 'autorizacao'), ('orcamento', 'autorizacao'),
  ('contato', 'perdido'), ('orcamento', 'perdido'), ('autorizacao', 'perdido'), ('perdido', 'contato'),
  ('a_confirmar', 'chegou'), ('confirmado', 'chegou'),
  ('chegou', 'finalizado'), ('em_atendimento', 'finalizado'),
  ('finalizado', 'laudo_pendente'), ('finalizado', 'concluido'),
  ('laudo_pendente', 'laudo_entregue'), ('laudo_entregue', 'laudo_pendente'),
  ('laudo_entregue', 'faturamento'), ('laudo_entregue', 'concluido'),
  ('faturamento', 'nps_retorno'), ('faturamento', 'concluido'), ('faturamento', 'laudo_entregue'),
  ('nps_retorno', 'concluido'), ('nps_retorno', 'faturamento'),
  ('concluido', 'nps_retorno')
on conflict (de, para) do nothing;

comment on table public.jornada_coluna is 'Colunas do quadro da Jornada. origem klingo = anda sozinha pela leitura do Klingo; manual = só por jornada_mover_card.';
comment on table public.jornada_transicao is 'Movimentos manuais permitidos entre colunas (de -> para). O Klingo segue as regras de jornada_klingo_pode_mover, não esta tabela.';

-- ---------------------------------------------------------------- paciente, card, exames
create table if not exists public.jornada_paciente (
  prontuario     text primary key,
  nome           text,
  celular        text,
  telefone       text,
  email          text,
  nascimento     date,
  atualizado_em  timestamptz not null default now()
);

create table if not exists public.jornada_card (
  id             bigint generated always as identity primary key,
  paciente_chave text        not null,                         -- prontuário do Klingo (ou outra chave, para contato manual)
  data_ref       date        not null,                         -- dia do atendimento (ou do contato)
  unidade        text        not null default '',
  coluna         text        not null references public.jornada_coluna (id),
  coluna_desde   timestamptz not null default now(),
  responsavel    uuid,
  prioridade     smallint    not null default 0 check (prioridade between 0 and 3),
  versao         integer     not null default 1,               -- trava otimista: duas pessoas não movem o mesmo card ao mesmo tempo
  arquivado_em   timestamptz,
  criado_em      timestamptz not null default now(),
  atualizado_em  timestamptz not null default now(),
  unique (paciente_chave, data_ref, unidade)
);
create index if not exists jornada_card_coluna_idx on public.jornada_card (coluna) where arquivado_em is null;
create index if not exists jornada_card_data_idx on public.jornada_card (data_ref desc);

-- Uma linha por marcação do Klingo. Sem valor em R$ de propósito: o quadro é de toda a equipe e o dinheiro tem permissão própria.
create table if not exists public.jornada_exame (
  id                    bigint generated always as identity primary key,
  card_id               bigint      not null references public.jornada_card (id),
  marcacao_id           text        not null unique,           -- "Id da Marcação" do Klingo
  atendimento_id        text,                                  -- "Id do Atendimento" (só existe quando o paciente foi atendido)
  procedimento          text        not null,
  operadora             text,
  unidade               text,
  agendado_em           timestamptz,
  agendado_para         timestamptz,
  status                text        not null default 'agendado' check (status in ('agendado', 'confirmado', 'atendido', 'cancelado', 'remarcado', 'faltou')),
  confirm_status        text,
  cancelamento_motivo   text,
  atualizado_em         timestamptz not null default now()
);
create index if not exists jornada_exame_card_idx on public.jornada_exame (card_id);

-- Histórico do card: só se acrescenta.
create table if not exists public.jornada_evento (
  id          bigint generated always as identity primary key,
  card_id     bigint      not null references public.jornada_card (id),
  quando      timestamptz not null default now(),
  tipo        text        not null check (tipo in ('criado', 'movido', 'divergencia', 'atribuido', 'nota')),
  origem      text        not null check (origem in ('klingo', 'pessoa', 'sistema')),
  usuario     uuid,
  de_coluna   text,
  para_coluna text,
  detalhe     jsonb       not null default '{}'::jsonb
);
create index if not exists jornada_evento_card_idx on public.jornada_evento (card_id, quando desc);

-- Chat do card. `paciente` fica reservado para o portal do paciente (ainda fechado: jornada_enviar_mensagem só aceita 'interno').
create table if not exists public.jornada_mensagem (
  id          bigint generated always as identity primary key,
  card_id     bigint      not null references public.jornada_card (id),
  canal       text        not null check (canal in ('interno', 'paciente')),
  autor       uuid,
  autor_tipo  text        not null check (autor_tipo in ('equipe', 'paciente', 'sistema')),
  texto       text        not null check (char_length(texto) between 1 and 2000),
  criado_em   timestamptz not null default now()
);
create index if not exists jornada_mensagem_card_idx on public.jornada_mensagem (card_id, criado_em);

-- Quem abriu o prontuário de quem (LGPD): só o administrador lê.
create table if not exists public.jornada_acesso (
  id       bigint generated always as identity primary key,
  card_id  bigint      not null references public.jornada_card (id),
  usuario  uuid        not null,
  quando   timestamptz not null default now()
);

create or replace function public.jornada_imutavel()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'Registro do histórico não pode ser alterado.';
end;
$$;

create or replace trigger jornada_evento_imutavel   before update on public.jornada_evento   for each row execute function public.jornada_imutavel();
create or replace trigger jornada_mensagem_imutavel before update on public.jornada_mensagem for each row execute function public.jornada_imutavel();

-- ---------------------------------------------------------------- permissões (RLS: ler = permissão `jornada`; escrever = só pelas funções)
alter table public.jornada_coluna    enable row level security;
alter table public.jornada_transicao enable row level security;
alter table public.jornada_paciente  enable row level security;
alter table public.jornada_card      enable row level security;
alter table public.jornada_exame     enable row level security;
alter table public.jornada_evento    enable row level security;
alter table public.jornada_mensagem  enable row level security;
alter table public.jornada_acesso    enable row level security;

create policy "jornada_coluna_select"    on public.jornada_coluna    for select to authenticated using (true);
create policy "jornada_transicao_select" on public.jornada_transicao for select to authenticated using (true);
create policy "jornada_paciente_select"  on public.jornada_paciente  for select to authenticated using (public.can_view_painel('jornada'));
create policy "jornada_card_select"      on public.jornada_card      for select to authenticated using (public.can_view_painel('jornada'));
create policy "jornada_exame_select"     on public.jornada_exame     for select to authenticated using (public.can_view_painel('jornada'));
create policy "jornada_evento_select"    on public.jornada_evento    for select to authenticated using (public.can_view_painel('jornada'));
create policy "jornada_mensagem_select"  on public.jornada_mensagem  for select to authenticated using (public.can_view_painel('jornada'));
create policy "jornada_acesso_select"    on public.jornada_acesso    for select to authenticated using (public.is_admin());

revoke all on public.jornada_coluna, public.jornada_transicao, public.jornada_paciente, public.jornada_card, public.jornada_exame,
              public.jornada_evento, public.jornada_mensagem, public.jornada_acesso from public, anon, authenticated;
grant select on public.jornada_coluna, public.jornada_transicao, public.jornada_paciente, public.jornada_card, public.jornada_exame,
                public.jornada_evento, public.jornada_mensagem, public.jornada_acesso to authenticated;
grant all on public.jornada_coluna, public.jornada_transicao, public.jornada_paciente, public.jornada_card, public.jornada_exame,
             public.jornada_evento, public.jornada_mensagem, public.jornada_acesso to service_role;

-- ---------------------------------------------------------------- regras
-- O Klingo pode levar o card de `p_atual` para `p_alvo`? (só para colunas de origem 'klingo')
create or replace function public.jornada_klingo_pode_mover(p_atual text, p_alvo text)
returns boolean
language plpgsql
stable
set search_path = ''
as $$
declare
  a public.jornada_coluna%rowtype;
  b public.jornada_coluna%rowtype;
  o_atendimento integer;
  o_chegou integer;
begin
  select * into a from public.jornada_coluna where id = p_atual;
  select * into b from public.jornada_coluna where id = p_alvo;
  if a.id is null or b.id is null or b.origem <> 'klingo' or a.id = b.id then
    return false;
  end if;
  select ordem into o_atendimento from public.jornada_coluna where id = 'em_atendimento';
  select ordem into o_chegou from public.jornada_coluna where id = 'chegou';

  -- exceções do Klingo: cancelar/remarcar vale até o atendimento; faltar só antes de a pessoa chegar
  if b.etapa = 'excecao' then
    if a.etapa = 'excecao' then
      return false;      -- de uma exceção para outra não anda sozinho
    end if;
    return a.ordem < case b.id when 'faltou' then o_chegou else o_atendimento end;
  end if;

  -- saindo de uma exceção (marcação reativada, paciente que veio atrasado, contato que virou marcação)
  if a.etapa = 'excecao' then
    return true;
  end if;

  -- confirmação vai e volta
  if a.id in ('a_confirmar', 'confirmado') and b.id in ('a_confirmar', 'confirmado') then
    return true;
  end if;

  -- o resto só para a frente: o Klingo nunca puxa o card para trás de uma coluna manual
  return b.ordem > a.ordem;
end;
$$;

-- Move o card por decisão do Klingo (chamada pela leitura, service_role). Devolve 'moveu', 'igual' ou 'ignorado' (e registra a divergência uma vez).
create or replace function public.jornada_aplicar_klingo(p_card bigint, p_alvo text, p_detalhe jsonb default '{}'::jsonb)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  c public.jornada_card%rowtype;
begin
  select * into c from public.jornada_card where id = p_card for update;
  if not found then
    raise exception 'Card % não existe.', p_card;
  end if;
  if c.coluna = p_alvo then
    return 'igual';
  end if;

  if not public.jornada_klingo_pode_mover(c.coluna, p_alvo) then
    -- diverge do Klingo: avisa uma vez, não a cada leitura
    if not exists (
      select 1 from public.jornada_evento e
      where e.card_id = c.id and e.tipo = 'divergencia' and e.para_coluna = p_alvo and e.de_coluna = c.coluna
    ) then
      insert into public.jornada_evento (card_id, tipo, origem, de_coluna, para_coluna, detalhe)
      values (c.id, 'divergencia', 'klingo', c.coluna, p_alvo, coalesce(p_detalhe, '{}'::jsonb) || jsonb_build_object('motivo', 'O Klingo indica outra coluna, mas o card já está mais adiante ou numa coluna manual.'));
    end if;
    return 'ignorado';
  end if;

  update public.jornada_card
     set coluna = p_alvo, coluna_desde = now(), versao = versao + 1, atualizado_em = now()
   where id = c.id;
  insert into public.jornada_evento (card_id, tipo, origem, de_coluna, para_coluna, detalhe)
  values (c.id, 'movido', 'klingo', c.coluna, p_alvo, coalesce(p_detalhe, '{}'::jsonb));
  return 'moveu';
end;
$$;

-- Move o card à mão (a equipe). Confere permissão, transição permitida e versão (trava otimista).
create or replace function public.jornada_mover_card(p_card bigint, p_para text, p_versao integer, p_nota text default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  c public.jornada_card%rowtype;
  v_nota text := nullif(trim(coalesce(p_nota, '')), '');
begin
  if auth.uid() is null then
    raise exception 'Faça login.';
  end if;
  if not public.can_view_painel('jornada') then
    raise exception 'Sem permissão para a Jornada.';
  end if;

  select * into c from public.jornada_card where id = p_card for update;
  if not found then
    raise exception 'Card não encontrado.';
  end if;
  if c.versao <> p_versao then
    raise exception 'CONFLITO: o card foi alterado por outra pessoa. Atualize a tela e tente de novo.';
  end if;
  if c.arquivado_em is not null then
    raise exception 'Card arquivado.';
  end if;
  if c.coluna = p_para then
    raise exception 'O card já está nesta coluna.';
  end if;
  if not exists (select 1 from public.jornada_transicao t join public.jornada_coluna k on k.id = t.para where t.de = c.coluna and t.para = p_para and k.ativa and k.origem = 'manual') then
    raise exception 'Movimento não permitido: de "%" para "%".', c.coluna, p_para;
  end if;
  if p_para = 'perdido' and (v_nota is null or char_length(v_nota) < 3) then
    raise exception 'Diga o motivo de perder o contato (mínimo 3 letras).';
  end if;

  update public.jornada_card
     set coluna = p_para, coluna_desde = now(), versao = versao + 1, atualizado_em = now()
   where id = c.id;
  insert into public.jornada_evento (card_id, tipo, origem, usuario, de_coluna, para_coluna, detalhe)
  values (c.id, 'movido', 'pessoa', auth.uid(), c.coluna, p_para, case when v_nota is null then '{}'::jsonb else jsonb_build_object('nota', left(v_nota, 500)) end);
  return jsonb_build_object('ok', true, 'versao', c.versao + 1);
end;
$$;

-- Atribui o card a uma pessoa (ou tira, com null).
create or replace function public.jornada_atribuir_card(p_card bigint, p_responsavel uuid, p_versao integer)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  c public.jornada_card%rowtype;
begin
  if auth.uid() is null then raise exception 'Faça login.'; end if;
  if not public.can_view_painel('jornada') then raise exception 'Sem permissão para a Jornada.'; end if;
  select * into c from public.jornada_card where id = p_card for update;
  if not found then raise exception 'Card não encontrado.'; end if;
  if c.versao <> p_versao then raise exception 'CONFLITO: o card foi alterado por outra pessoa. Atualize a tela e tente de novo.'; end if;
  if p_responsavel is not null and not exists (select 1 from public.profiles where id = p_responsavel) then
    raise exception 'Pessoa não encontrada.';
  end if;
  update public.jornada_card set responsavel = p_responsavel, versao = versao + 1, atualizado_em = now() where id = c.id;
  insert into public.jornada_evento (card_id, tipo, origem, usuario, detalhe)
  values (c.id, 'atribuido', 'pessoa', auth.uid(), jsonb_build_object('responsavel', p_responsavel));
  return jsonb_build_object('ok', true, 'versao', c.versao + 1);
end;
$$;

-- Mensagem no chat interno do card. O canal do paciente só abre com o portal.
create or replace function public.jornada_enviar_mensagem(p_card bigint, p_texto text)
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
  if char_length(v_texto) < 1 or char_length(v_texto) > 2000 then raise exception 'A mensagem precisa ter de 1 a 2000 letras.'; end if;
  if not exists (select 1 from public.jornada_card where id = p_card) then raise exception 'Card não encontrado.'; end if;
  insert into public.jornada_mensagem (card_id, canal, autor, autor_tipo, texto) values (p_card, 'interno', auth.uid(), 'equipe', v_texto) returning id into v_id;
  return v_id;
end;
$$;

-- Registro de quem abriu o card (LGPD).
create or replace function public.jornada_registrar_acesso(p_card bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null or not public.can_view_painel('jornada') then return; end if;
  if exists (select 1 from public.jornada_card where id = p_card) then
    insert into public.jornada_acesso (card_id, usuario) values (p_card, auth.uid());
  end if;
end;
$$;

revoke execute on function public.jornada_klingo_pode_mover(text, text)               from public, anon, authenticated;
revoke execute on function public.jornada_aplicar_klingo(bigint, text, jsonb)         from public, anon, authenticated;
revoke execute on function public.jornada_mover_card(bigint, text, integer, text)     from public, anon;
revoke execute on function public.jornada_atribuir_card(bigint, uuid, integer)        from public, anon;
revoke execute on function public.jornada_enviar_mensagem(bigint, text)               from public, anon;
revoke execute on function public.jornada_registrar_acesso(bigint)                    from public, anon;
grant  execute on function public.jornada_klingo_pode_mover(text, text)               to service_role;
grant  execute on function public.jornada_aplicar_klingo(bigint, text, jsonb)         to service_role;
grant  execute on function public.jornada_mover_card(bigint, text, integer, text)     to authenticated;
grant  execute on function public.jornada_atribuir_card(bigint, uuid, integer)        to authenticated;
grant  execute on function public.jornada_enviar_mensagem(bigint, text)               to authenticated;
grant  execute on function public.jornada_registrar_acesso(bigint)                    to authenticated;

-- ---------------------------------------------------------------- o que o quadro lê
-- security_invoker: a RLS das tabelas vale para quem consulta (sem permissão `jornada`, vem vazio).
-- `vazio` = não há nada a fazer: sem exame ativo, sem mensagem e numa coluna do Klingo (cards manuais nunca ficam vazios).
create or replace view public.v_jornada_quadro with (security_invoker = true) as
select
  c.id, c.paciente_chave, p.nome as paciente_nome, c.data_ref, c.unidade,
  c.coluna, k.nome as coluna_nome, k.etapa, k.origem, k.ordem,
  c.coluna_desde, c.responsavel, c.prioridade, c.versao,
  n.n_exames, n.n_ativos, n.n_mensagens,
  (n.n_ativos = 0 and n.n_mensagens = 0 and k.origem = 'klingo') as vazio,
  (k.sla_min is not null and now() - c.coluna_desde > make_interval(mins => k.sla_min)) as atrasado,
  floor(extract(epoch from (now() - c.coluna_desde)) / 60)::integer as minutos_na_coluna
from public.jornada_card c
join public.jornada_coluna k on k.id = c.coluna
left join public.jornada_paciente p on p.prontuario = c.paciente_chave
cross join lateral (
  select
    (select count(*) from public.jornada_exame e where e.card_id = c.id)::integer as n_exames,
    (select count(*) from public.jornada_exame e where e.card_id = c.id and e.status not in ('cancelado', 'remarcado'))::integer as n_ativos,
    (select count(*) from public.jornada_mensagem m where m.card_id = c.id)::integer as n_mensagens
) n
where c.arquivado_em is null;

revoke all on public.v_jornada_quadro from public, anon, authenticated;
grant select on public.v_jornada_quadro to authenticated;
grant all    on public.v_jornada_quadro to service_role;
