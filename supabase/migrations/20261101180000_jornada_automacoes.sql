-- Jornada do paciente, etapa 5: automações da equipe (tarefas, checklist, prioridade por atraso e atribuição por escala).
--
-- Ainda não há mensagem automática ao paciente (depende do portal e do jurídico). O que o sistema faz sozinho, para a equipe trabalhar menos:
--   * checklist por coluna: ao entrar numa coluna, o cartão ganha as tarefas do modelo daquela coluna (jornada_checklist_modelo; ex.: Chegou -> conferir pedido médico);
--   * confirmar presença: cartão A confirmar de hoje ou de amanhã ganha a tarefa "Confirmar presença com o paciente";
--   * remarcar: cartão que faltou (ontem ou hoje) ganha a tarefa "Ligar e oferecer nova data";
--   * prioridade por atraso: cartão que passou do prazo da coluna sobe para prioridade 2 e, com o dobro do prazo, 3;
--   * atribuição por escala: cartão de hoje, ontem ou amanhã sem responsável vai para quem tem menos cartões abertos entre os escalados da coluna (jornada_escala).
-- Cada regra pode ser desligada ou ajustada em jornada_regra. Tudo o que o sistema faz fica no histórico do cartão (origem "sistema"). O cron `jornada-regras` roda a cada 5 minutos.
-- Só create, alter table (add/constraint), grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

alter table public.jornada_evento drop constraint if exists jornada_evento_tipo_check;
alter table public.jornada_evento add constraint jornada_evento_tipo_check check (tipo in ('criado', 'movido', 'divergencia', 'atribuido', 'nota', 'tarefa', 'prioridade'));

-- ---------------------------------------------------------------- regras, escala e modelo de checklist
create table if not exists public.jornada_regra (
  chave      text primary key,
  nome       text    not null,
  descricao  text    not null,
  ativa      boolean not null default true,
  parametros jsonb   not null default '{}'::jsonb
);

create table if not exists public.jornada_escala (
  coluna  text    not null references public.jornada_coluna (id),
  usuario uuid    not null,
  ativa   boolean not null default true,
  primary key (coluna, usuario)
);

create table if not exists public.jornada_checklist_modelo (
  id     bigint generated always as identity primary key,
  coluna text    not null references public.jornada_coluna (id),
  ordem  integer not null default 1,
  titulo text    not null check (char_length(titulo) between 3 and 200),
  ativa  boolean not null default true,
  unique (coluna, titulo)
);

insert into public.jornada_regra (chave, nome, descricao, parametros) values
  ('checklist_por_coluna',  'Checklist ao entrar na coluna',  'Ao entrar numa coluna, o cartão ganha as tarefas do modelo daquela coluna (jornada_checklist_modelo).', '{}'),
  ('confirmar_proximo_dia', 'Confirmar presença',             'Cartão em "A confirmar" com atendimento hoje ou nos próximos dias ganha a tarefa de confirmar presença. Vence às vence_hora do dia anterior ao atendimento.', '{"dias_antes": 1, "vence_hora": 16}'),
  ('remarcar_faltou',       'Oferecer nova data a quem faltou', 'Cartão em "Faltou" ganha a tarefa de ligar e oferecer nova data, por até "dias" dias depois da falta.', '{"dias": 1}'),
  ('prioridade_por_atraso', 'Prioridade por atraso',          'Cartão que passou do prazo da coluna sobe para prioridade 2; com o dobro do prazo, para 3. Volta a 0 quando sai do atraso.', '{}'),
  ('atribuir_por_escala',   'Atribuir por escala',            'Cartão de ontem, hoje e amanhã sem responsável vai para a pessoa escalada na coluna (jornada_escala) com menos cartões abertos. Sem escala cadastrada, não faz nada.', '{}')
on conflict (chave) do nothing;

insert into public.jornada_checklist_modelo (coluna, ordem, titulo) values
  ('chegou', 1, 'Conferir o pedido médico'),
  ('chegou', 2, 'Conferir documento com foto e carteirinha'),
  ('chegou', 3, 'Conferir guia e autorização do convênio'),
  ('laudo_pendente', 1, 'Conferir se o laudo foi liberado'),
  ('laudo_entregue', 1, 'Registrar como o laudo foi entregue (retirada ou envio)'),
  ('faturamento', 1, 'Conferir se a guia ou a fatura foi enviada')
on conflict (coluna, titulo) do nothing;

-- ---------------------------------------------------------------- tarefas do cartão
create table if not exists public.jornada_tarefa (
  id          bigint generated always as identity primary key,
  card_id     bigint      not null references public.jornada_card (id),
  titulo      text        not null check (char_length(titulo) between 3 and 200),
  origem      text        not null check (origem in ('sistema', 'pessoa')),
  chave       text,                                         -- identifica a tarefa automática; a mesma chave não se repete no cartão
  criada_por  uuid,
  vence_em    timestamptz,
  criada_em   timestamptz not null default now(),
  feita_em    timestamptz,
  feita_por   uuid
);
create unique index if not exists jornada_tarefa_chave_idx on public.jornada_tarefa (card_id, chave) where chave is not null;
create index if not exists jornada_tarefa_abertas_idx on public.jornada_tarefa (card_id) where feita_em is null;

alter table public.jornada_regra            enable row level security;
alter table public.jornada_escala           enable row level security;
alter table public.jornada_checklist_modelo enable row level security;
alter table public.jornada_tarefa           enable row level security;

create policy "jornada_regra_select"            on public.jornada_regra            for select to authenticated using (public.is_admin());
create policy "jornada_escala_select"           on public.jornada_escala           for select to authenticated using (public.is_admin());
create policy "jornada_checklist_modelo_select" on public.jornada_checklist_modelo for select to authenticated using (public.is_admin());
create policy "jornada_tarefa_select"           on public.jornada_tarefa           for select to authenticated using (public.can_view_painel('jornada'));

revoke all on public.jornada_regra, public.jornada_escala, public.jornada_checklist_modelo, public.jornada_tarefa from public, anon, authenticated;
grant select on public.jornada_regra, public.jornada_escala, public.jornada_checklist_modelo, public.jornada_tarefa to authenticated;
grant all    on public.jornada_regra, public.jornada_escala, public.jornada_checklist_modelo, public.jornada_tarefa to service_role;

-- Tarefa feita à mão (a equipe): criar, marcar como feita e reabrir.
create or replace function public.jornada_criar_tarefa(p_card bigint, p_titulo text, p_vence timestamptz default null)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_titulo text := trim(coalesce(p_titulo, ''));
  v_id bigint;
begin
  if auth.uid() is null then raise exception 'Faça login.'; end if;
  if not public.can_view_painel('jornada') then raise exception 'Sem permissão para a Jornada.'; end if;
  if char_length(v_titulo) < 3 or char_length(v_titulo) > 200 then raise exception 'A tarefa precisa ter de 3 a 200 letras.'; end if;
  if not exists (select 1 from public.jornada_card where id = p_card) then raise exception 'Card não encontrado.'; end if;
  insert into public.jornada_tarefa (card_id, titulo, origem, criada_por, vence_em) values (p_card, v_titulo, 'pessoa', auth.uid(), p_vence) returning id into v_id;
  insert into public.jornada_evento (card_id, tipo, origem, usuario, detalhe) values (p_card, 'tarefa', 'pessoa', auth.uid(), jsonb_build_object('acao', 'criada', 'titulo', left(v_titulo, 200)));
  return v_id;
end;
$$;

create or replace function public.jornada_marcar_tarefa(p_tarefa bigint, p_feita boolean default true)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  t public.jornada_tarefa%rowtype;
begin
  if auth.uid() is null then raise exception 'Faça login.'; end if;
  if not public.can_view_painel('jornada') then raise exception 'Sem permissão para a Jornada.'; end if;
  select * into t from public.jornada_tarefa where id = p_tarefa for update;
  if not found then raise exception 'Tarefa não encontrada.'; end if;
  if p_feita and t.feita_em is null then
    update public.jornada_tarefa set feita_em = now(), feita_por = auth.uid() where id = t.id;
    insert into public.jornada_evento (card_id, tipo, origem, usuario, detalhe) values (t.card_id, 'tarefa', 'pessoa', auth.uid(), jsonb_build_object('acao', 'feita', 'titulo', t.titulo));
  elsif not p_feita and t.feita_em is not null then
    update public.jornada_tarefa set feita_em = null, feita_por = null where id = t.id;
    insert into public.jornada_evento (card_id, tipo, origem, usuario, detalhe) values (t.card_id, 'tarefa', 'pessoa', auth.uid(), jsonb_build_object('acao', 'reaberta', 'titulo', t.titulo));
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

revoke execute on function public.jornada_criar_tarefa(bigint, text, timestamptz) from public, anon;
revoke execute on function public.jornada_marcar_tarefa(bigint, boolean)          from public, anon;
grant  execute on function public.jornada_criar_tarefa(bigint, text, timestamptz) to authenticated;
grant  execute on function public.jornada_marcar_tarefa(bigint, boolean)          to authenticated;

-- ---------------------------------------------------------------- as automações
create or replace function public.jornada_regra_ativa(p_chave text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select coalesce((select ativa from public.jornada_regra where chave = p_chave), false);
$$;

-- Checklist do modelo da coluna em que o cartão está (a mesma tarefa não se repete: chave "ck:<id do modelo>").
create or replace function public.jornada_checklist_do_card(p_card bigint)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  n integer;
begin
  if not public.jornada_regra_ativa('checklist_por_coluna') then
    return 0;
  end if;
  insert into public.jornada_tarefa (card_id, titulo, origem, chave)
  select c.id, m.titulo, 'sistema', 'ck:' || m.id
  from public.jornada_card c
  join public.jornada_checklist_modelo m on m.coluna = c.coluna and m.ativa
  where c.id = p_card and c.arquivado_em is null
  on conflict (card_id, chave) where chave is not null do nothing;
  get diagnostics n = row_count;
  return n;
end;
$$;

create or replace function public.jornada_checklist_gatilho()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform public.jornada_checklist_do_card(new.id);
  return null;
exception when others then
  raise warning 'jornada_checklist_gatilho: %', sqlerrm;
  return null;
end;
$$;
revoke execute on function public.jornada_checklist_do_card(bigint) from public, anon, authenticated;
revoke execute on function public.jornada_checklist_gatilho()       from public, anon, authenticated;
revoke execute on function public.jornada_regra_ativa(text)         from public, anon, authenticated;
grant  execute on function public.jornada_regra_ativa(text)         to service_role;

create or replace trigger jornada_card_checklist_novo after insert on public.jornada_card for each row execute function public.jornada_checklist_gatilho();
create or replace trigger jornada_card_checklist_muda after update of coluna on public.jornada_card for each row when (old.coluna is distinct from new.coluna) execute function public.jornada_checklist_gatilho();

-- Roda as regras de tempo (cron a cada 5 min). Devolve quantas tarefas, prioridades e atribuições mudaram.
create or replace function public.jornada_aplicar_regras()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_hoje     date := (now() at time zone 'America/Sao_Paulo')::date;
  p          jsonb;
  n_conf     integer := 0;
  n_remarc   integer := 0;
  n_prio     integer := 0;
  n_atrib    integer := 0;
  r          record;
  v_alvo     uuid;
begin
  perform pg_advisory_xact_lock(hashtext('jornada_aplicar_regras'));

  -- confirmar presença
  if public.jornada_regra_ativa('confirmar_proximo_dia') then
    select parametros into p from public.jornada_regra where chave = 'confirmar_proximo_dia';
    insert into public.jornada_tarefa (card_id, titulo, origem, chave, vence_em)
    select c.id, 'Confirmar presença com o paciente', 'sistema', 'confirmar',
           ((c.data_ref - coalesce((p ->> 'dias_antes')::integer, 1))::timestamp + make_interval(hours => coalesce((p ->> 'vence_hora')::integer, 16))) at time zone 'America/Sao_Paulo'
    from public.jornada_card c
    where c.coluna = 'a_confirmar' and c.arquivado_em is null and c.paciente_chave not like 'manual:%'
      and c.data_ref between v_hoje and v_hoje + coalesce((p ->> 'dias_antes')::integer, 1)
    on conflict (card_id, chave) where chave is not null do nothing;
    get diagnostics n_conf = row_count;
  end if;

  -- oferecer nova data a quem faltou
  if public.jornada_regra_ativa('remarcar_faltou') then
    select parametros into p from public.jornada_regra where chave = 'remarcar_faltou';
    insert into public.jornada_tarefa (card_id, titulo, origem, chave, vence_em)
    select c.id, 'Ligar e oferecer nova data', 'sistema', 'remarcar',
           ((c.data_ref + 1)::timestamp + interval '12 hours') at time zone 'America/Sao_Paulo'
    from public.jornada_card c
    where c.coluna = 'faltou' and c.arquivado_em is null
      and c.data_ref >= v_hoje - coalesce((p ->> 'dias')::integer, 1)
    on conflict (card_id, chave) where chave is not null do nothing;
    get diagnostics n_remarc = row_count;
  end if;

  -- prioridade por atraso
  if public.jornada_regra_ativa('prioridade_por_atraso') then
    for r in
      select c.id, c.coluna, c.prioridade,
             case
               when k.sla_min is null or now() - c.coluna_desde <= make_interval(mins => k.sla_min) then 0
               when now() - c.coluna_desde > make_interval(mins => k.sla_min * 2) then 3
               else 2
             end as nova
      from public.jornada_card c join public.jornada_coluna k on k.id = c.coluna
      where c.arquivado_em is null
    loop
      if r.nova <> r.prioridade then
        update public.jornada_card set prioridade = r.nova, atualizado_em = now() where id = r.id;
        if r.nova > r.prioridade then
          insert into public.jornada_evento (card_id, tipo, origem, detalhe) values (r.id, 'prioridade', 'sistema', jsonb_build_object('de', r.prioridade, 'para', r.nova, 'motivo', 'Passou do prazo da coluna.'));
        end if;
        n_prio := n_prio + 1;
      end if;
    end loop;
  end if;

  -- atribuir por escala
  if public.jornada_regra_ativa('atribuir_por_escala') then
    for r in
      select c.id, c.coluna
      from public.jornada_card c
      where c.arquivado_em is null and c.responsavel is null and c.paciente_chave not like 'manual:%'
        and c.data_ref between v_hoje - 1 and v_hoje + 1
        and exists (select 1 from public.jornada_escala e where e.coluna = c.coluna and e.ativa)
      order by c.data_ref, c.id
    loop
      select e.usuario into v_alvo
      from public.jornada_escala e
      where e.coluna = r.coluna and e.ativa
      order by (select count(*) from public.jornada_card x where x.responsavel = e.usuario and x.arquivado_em is null and x.coluna <> 'concluido'), e.usuario
      limit 1;
      if v_alvo is not null then
        update public.jornada_card set responsavel = v_alvo, versao = versao + 1, atualizado_em = now() where id = r.id and responsavel is null;
        insert into public.jornada_evento (card_id, tipo, origem, detalhe) values (r.id, 'atribuido', 'sistema', jsonb_build_object('responsavel', v_alvo, 'motivo', 'Escala da coluna.'));
        n_atrib := n_atrib + 1;
      end if;
    end loop;
  end if;

  return jsonb_build_object('tarefas_confirmar', n_conf, 'tarefas_remarcar', n_remarc, 'prioridades_mudadas', n_prio, 'atribuidos', n_atrib);
end;
$$;

revoke execute on function public.jornada_aplicar_regras() from public, anon, authenticated;
grant  execute on function public.jornada_aplicar_regras() to service_role;

-- as tarefas também avisam o quadro (o número de pendências aparece no cartão)
create or replace trigger jornada_tarefa_transmite_novo after insert on public.jornada_tarefa for each row execute function public.jornada_transmitir();
create or replace trigger jornada_tarefa_transmite_muda after update on public.jornada_tarefa for each row when (old.* is distinct from new.*) execute function public.jornada_transmitir();

-- ---------------------------------------------------------------- o quadro passa a trazer as tarefas (colunas novas no fim da visão)
create or replace view public.v_jornada_quadro with (security_invoker = true) as
select
  c.id, c.paciente_chave, p.nome as paciente_nome, c.data_ref, c.unidade,
  c.coluna, k.nome as coluna_nome, k.etapa, k.origem, k.ordem,
  c.coluna_desde, c.responsavel, c.prioridade, c.versao,
  n.n_exames, n.n_ativos, n.n_mensagens,
  (n.n_ativos = 0 and n.n_mensagens = 0 and k.origem = 'klingo') as vazio,
  (k.sla_min is not null and now() - c.coluna_desde > make_interval(mins => k.sla_min)) as atrasado,
  floor(extract(epoch from (now() - c.coluna_desde)) / 60)::integer as minutos_na_coluna,
  n.n_tarefas_abertas, n.n_tarefas_vencidas
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

-- ---------------------------------------------------------------- agendamento e pendências desta etapa
select cron.schedule('jornada-regras', '*/5 * * * *', $cmd$ select public.jornada_aplicar_regras(); $cmd$);

insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('escala_por_coluna', 5,
   'Cadastrar quem atende cada coluna (escala) para a atribuição automática',
   'A regra "Atribuir por escala" já está ligada, mas não faz nada enquanto ninguém estiver escalado numa coluna. Com a escala, cada cartão de ontem, hoje e amanhã sem responsável vai sozinho para a pessoa com menos cartões abertos.',
   'atencao',
   '["Diga, por coluna, quem deve receber os cartões (ex.: A confirmar = call center; Chegou = recepção; Laudo pendente = laudos; Guia/faturamento = faturamento).", "Eu cadastro em jornada_escala. Para você mesmo: insert into public.jornada_escala (coluna, usuario) select ''chegou'', id from public.profiles where email = ''fulano@csi.local'';"]'::jsonb),
  ('revisar_regras_automaticas', 5,
   'Revisar as regras automáticas e os prazos das tarefas',
   'Ligadas: checklist ao entrar na coluna; confirmar presença (cartão A confirmar de hoje e amanhã, vence às 16h do dia anterior); oferecer nova data a quem faltou (por 1 dia); prioridade por atraso (2 ao passar do prazo da coluna, 3 com o dobro); atribuir por escala.',
   'info',
   '["Diga o que mudar. Para desligar uma regra: update public.jornada_regra set ativa = false where chave = ''remarcar_faltou'';", "Para ajustar o horário de vencer a confirmação: update public.jornada_regra set parametros = ''{\"dias_antes\": 1, \"vence_hora\": 15}'' where chave = ''confirmar_proximo_dia'';"]'::jsonb),
  ('modelo_checklist', 5,
   'Revisar os itens do checklist de cada coluna',
   'Coloquei itens administrativos genéricos: Chegou (pedido médico, documento com foto e carteirinha, guia e autorização), Laudo pendente (laudo liberado?), Laudo entregue (como foi entregue), Guia/faturamento (guia ou fatura enviada). Não há checklist por tipo de exame (preparo, contraste, termo) porque falta o catálogo de preparo.',
   'info',
   '["Diga o que acrescentar, tirar ou renomear em cada coluna.", "O checklist por tipo de exame entra quando o catálogo de preparo (pendência anterior) estiver preenchido."]'::jsonb)
on conflict (chave) do nothing;
