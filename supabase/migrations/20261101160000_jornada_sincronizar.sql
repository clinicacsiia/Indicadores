-- Jornada do paciente, etapa 3: a leitura do Klingo cria e move os cards.
--
-- Fonte: relatório #13825 (Agendamentos - Visão Consolidada por Marcação), uma linha por marcação. Colunas (dim_relatorio_coluna): col0 Id da Marcação, col1 Id do Atendimento,
-- col2 Prontuário, col3 Agendado Em, col4 Agendado Para, col5 Procedimento, col6 Operadora, col10 Confirm Status, col11 Cancelamento - Motivo, col12 Status (Aberta/Cancelada),
-- col13 Atendido (S/N), col14 Unidade, col15 Nome, col16 Celular, col17 Telefone. Datas em texto "AAAA-MM-DD hh:mm:ss", horário de Brasília. O valor (col8) NÃO é copiado.
--
-- Um card = prontuário + dia do exame + unidade. A janela é de hoje-2 a hoje+30 dias, pela data do EXAME.
--   Situação de cada exame: atendido (Atendido = S, vale mesmo se cancelada depois) · remarcado / cancelado (Status Cancelada; motivo "Remarcado" = remarcado) ·
--   faltou (aberta, sem atendimento e dia já passado) · confirmado (Confirm Status Confirmado) · agendado (o resto).
--   Coluna do card: algum atendido -> Em atendimento; sem exame ativo -> Faltou / Remarcado / Cancelado; todos ativos confirmados -> Confirmado; senão A confirmar.
--   Regras de movimento: as de jornada_aplicar_klingo (o Klingo nunca puxa o card para trás de uma coluna manual). Quando a equipe já passou o card adiante, o atraso do Klingo é normal e é ignorado sem alarde.
--   Automação: Em atendimento de um dia que já passou vira Finalizado sozinho (evento "sistema"); cards encerrados há mais de 7 dias (ou qualquer card com mais de 30) são arquivados.
-- Quem chama: o cron `jornada-sincronizar` (todo minuto, só roda se o #13825 foi lido de novo ou virou o dia). Só cria, nunca apaga.
-- Só create, grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

create table if not exists public.jornada_sync_estado (
  id                    boolean primary key default true check (id),
  ultima_leitura_vista  timestamptz,
  ultima_execucao       timestamptz,
  ultimo_resultado      jsonb
);
insert into public.jornada_sync_estado (id) values (true) on conflict (id) do nothing;

alter table public.jornada_sync_estado enable row level security;
create policy "jornada_sync_estado_select" on public.jornada_sync_estado for select to authenticated using (public.can_view_painel('jornada'));
revoke all on public.jornada_sync_estado from public, anon, authenticated;
grant select on public.jornada_sync_estado to authenticated;
grant all    on public.jornada_sync_estado to service_role;

-- "CLÍNICA DE SAÚDE E IMAGEM - RM/TC" -> "CSI 2" (os nomes dos grupos do metas.json)
create or replace function public.jornada_unidade_curta(p text)
returns text
language sql
immutable
set search_path = ''
as $$
  select case
    when upper(coalesce(p, '')) like '%RM/TC%' then 'CSI 2'
    when upper(coalesce(p, '')) like '%- CSI' then 'CSI 1'
    when upper(coalesce(p, '')) like 'DESENVOAR%' then 'CSI Pediatria'
    else coalesce(nullif(trim(p), ''), '')
  end;
$$;

create or replace function public.jornada_status_exame(p_status text, p_atendido text, p_motivo text, p_confirm text, p_para date, p_hoje date)
returns text
language sql
immutable
set search_path = ''
as $$
  select case
    when upper(trim(coalesce(p_atendido, ''))) = 'S' then 'atendido'
    when coalesce(p_status, '') ilike 'cancel%' then case when coalesce(p_motivo, '') ilike 'remarcad%' then 'remarcado' else 'cancelado' end
    when p_para < p_hoje then 'faltou'
    when coalesce(p_confirm, '') ilike 'confirmad%' then 'confirmado'
    else 'agendado'
  end;
$$;

-- Coluna do Klingo para um card, a partir da situação dos seus exames.
create or replace function public.jornada_coluna_do_card(p_status text[])
returns text
language sql
immutable
set search_path = ''
as $$
  select case
    when 'atendido' = any (p_status) then 'em_atendimento'
    when not exists (select 1 from unnest(p_status) s where s in ('agendado', 'confirmado')) then
      case when 'faltou' = any (p_status) then 'faltou' when 'remarcado' = any (p_status) then 'remarcado' else 'cancelado' end
    when not exists (select 1 from unnest(p_status) s where s = 'agendado') then 'confirmado'
    else 'a_confirmar'
  end;
$$;

-- As marcações da janela, uma linha por marcação (a leitura mais recente), já com a situação do exame e a coluna do card.
-- Custo: lê o histórico do relatório (~12 mil páginas; de 0,3 a 5 s conforme o cache). Por isso a sincronização só roda quando o #13825 é lido de novo
-- (a cada 15 min por enquanto). Quando existir o relatório por data do exame, isto passa a ler só o que mudou (ver a pendência dos relatórios).
create or replace function public.jornada_marcacoes_janela(p_atras integer default 2, p_frente integer default 30)
returns table (
  marcacao_id text, atendimento_id text, prontuario text, nome text, celular text, telefone text, procedimento text, operadora text,
  unidade text, agendado_em timestamptz, agendado_para timestamptz, data_ref date, status text, confirm_status text, motivo text, coluna_card text
)
language sql
stable
set search_path = ''
as $$
  with h as (
    select (now() at time zone 'America/Sao_Paulo')::date as d
  ),
  rel as (
    select id from public.dim_relatorio where klingo_id = '13825'
  ),
  periodos as materialized (
    -- a última leitura de cada mês, calculada uma vez por mês (por linha, a janela levava 10 s)
    select g::date as p,
           (select max(s.started_at) from public.sync_relatorio_runs s, rel where s.relatorio_id = rel.id and s.periodo = g::date and s.status = 'success') as ini
    from h, generate_series(date_trunc('month', (h.d - 62)::timestamp), date_trunc('month', h.d::timestamp), interval '1 month') g
  ),
  linhas as (
    -- só o que a última leitura de cada mês viu (a mesma regra de v_relatorio_linha_vigente)
    select f.linha, f.last_seen_at, f.periodo
    from periodos p
    cross join rel
    join public.fact_relatorio_linha f on f.relatorio_id = rel.id and f.periodo = p.p and (p.ini is null or f.last_seen_at >= p.ini)
  ),
  unica as materialized (
    select distinct on (l.linha ->> 'col0') l.linha
    from linhas l
    where coalesce(l.linha ->> 'col0', '') <> '' and coalesce(l.linha ->> 'col2', '') <> '' and coalesce(l.linha ->> 'col4', '') ~ '^\d{4}-\d{2}-\d{2}'
    order by l.linha ->> 'col0', l.last_seen_at desc, l.periodo desc
  ),
  exames as (
    select
      u.linha ->> 'col0' as marcacao_id,
      nullif(u.linha ->> 'col1', '') as atendimento_id,
      u.linha ->> 'col2' as prontuario,
      nullif(trim(u.linha ->> 'col15'), '') as nome,
      nullif(trim(u.linha ->> 'col16'), '') as celular,
      nullif(trim(u.linha ->> 'col17'), '') as telefone,
      coalesce(nullif(trim(u.linha ->> 'col5'), ''), 'Procedimento não informado') as procedimento,
      nullif(trim(u.linha ->> 'col6'), '') as operadora,
      public.jornada_unidade_curta(u.linha ->> 'col14') as unidade,
      case when coalesce(u.linha ->> 'col3', '') ~ '^\d{4}-\d{2}-\d{2}' then (u.linha ->> 'col3')::timestamp at time zone 'America/Sao_Paulo' end as agendado_em,
      (u.linha ->> 'col4')::timestamp at time zone 'America/Sao_Paulo' as agendado_para,
      ((u.linha ->> 'col4')::timestamp)::date as data_ref,
      public.jornada_status_exame(u.linha ->> 'col12', u.linha ->> 'col13', u.linha ->> 'col11', u.linha ->> 'col10', ((u.linha ->> 'col4')::timestamp)::date, h.d) as status,
      nullif(trim(u.linha ->> 'col10'), '') as confirm_status,
      nullif(trim(u.linha ->> 'col11'), '') as motivo
    from unica u
    cross join h
    where ((u.linha ->> 'col4')::timestamp)::date between h.d - p_atras and h.d + p_frente
  )
  select e.marcacao_id, e.atendimento_id, e.prontuario, e.nome, e.celular, e.telefone, e.procedimento, e.operadora, e.unidade,
         e.agendado_em, e.agendado_para, e.data_ref, e.status, e.confirm_status, e.motivo,
         public.jornada_coluna_do_card(array_agg(e.status) over (partition by e.prontuario, e.data_ref, e.unidade))
  from exames e;
$$;

-- O trabalho: cria pacientes, cards e exames, e leva cada card para a coluna que o Klingo indica (respeitando as regras do quadro).
create or replace function public.jornada_sincronizar_klingo(p_atras integer default 2, p_frente integer default 30)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_hoje    date := (now() at time zone 'America/Sao_Paulo')::date;
  v_ini     timestamptz := clock_timestamp();
  r         record;
  c         public.jornada_card%rowtype;
  v_id      bigint;
  v_res     text;
  v_ord_alvo integer;
  v_ord_atual integer;
  n_exames  integer := 0;
  n_criados integer := 0;
  n_movidos integer := 0;
  n_diverg  integer := 0;
  n_finaliz integer := 0;
  n_arquiv  integer := 0;
begin
  perform pg_advisory_xact_lock(hashtext('jornada_sincronizar_klingo'));

  -- 1) pacientes, cards e exames
  for r in select * from public.jornada_marcacoes_janela(p_atras, p_frente) loop
    n_exames := n_exames + 1;

    insert into public.jornada_paciente as p (prontuario, nome, celular, telefone)
    values (r.prontuario, r.nome, r.celular, r.telefone)
    on conflict (prontuario) do update
      set nome = coalesce(excluded.nome, p.nome), celular = coalesce(excluded.celular, p.celular), telefone = coalesce(excluded.telefone, p.telefone), atualizado_em = now()
      where (p.nome, p.celular, p.telefone) is distinct from (coalesce(excluded.nome, p.nome), coalesce(excluded.celular, p.celular), coalesce(excluded.telefone, p.telefone));

    select id into v_id from public.jornada_card where paciente_chave = r.prontuario and data_ref = r.data_ref and unidade = r.unidade;
    if v_id is null then
      insert into public.jornada_card (paciente_chave, data_ref, unidade, coluna) values (r.prontuario, r.data_ref, r.unidade, r.coluna_card)
      on conflict (paciente_chave, data_ref, unidade) do nothing
      returning id into v_id;
      if v_id is not null then
        insert into public.jornada_evento (card_id, tipo, origem, para_coluna, detalhe) values (v_id, 'criado', 'klingo', r.coluna_card, jsonb_build_object('marcacao', r.marcacao_id));
        n_criados := n_criados + 1;
      else
        select id into v_id from public.jornada_card where paciente_chave = r.prontuario and data_ref = r.data_ref and unidade = r.unidade;
      end if;
    end if;

    insert into public.jornada_exame as e (card_id, marcacao_id, atendimento_id, procedimento, operadora, unidade, agendado_em, agendado_para, status, confirm_status, cancelamento_motivo)
    values (v_id, r.marcacao_id, r.atendimento_id, r.procedimento, r.operadora, r.unidade, r.agendado_em, r.agendado_para, r.status, r.confirm_status, r.motivo)
    on conflict (marcacao_id) do update
      set card_id = excluded.card_id, atendimento_id = excluded.atendimento_id, procedimento = excluded.procedimento, operadora = excluded.operadora, unidade = excluded.unidade,
          agendado_em = excluded.agendado_em, agendado_para = excluded.agendado_para, status = excluded.status, confirm_status = excluded.confirm_status,
          cancelamento_motivo = excluded.cancelamento_motivo, atualizado_em = now()
      where (e.card_id, e.atendimento_id, e.procedimento, e.operadora, e.unidade, e.agendado_em, e.agendado_para, e.status, e.confirm_status, e.cancelamento_motivo)
            is distinct from (excluded.card_id, excluded.atendimento_id, excluded.procedimento, excluded.operadora, excluded.unidade, excluded.agendado_em, excluded.agendado_para,
                              excluded.status, excluded.confirm_status, excluded.cancelamento_motivo);
  end loop;

  -- 2) a coluna de cada card (o que o Klingo indica pelos exames dele, com as regras do quadro)
  for r in
    select k.id, k.coluna, x.alvo
    from public.jornada_card k
    cross join lateral (select public.jornada_coluna_do_card(array_agg(e.status)) as alvo, count(*) as n from public.jornada_exame e where e.card_id = k.id) x
    where k.arquivado_em is null and k.paciente_chave not like 'manual:%' and k.data_ref between v_hoje - p_atras and v_hoje + p_frente and x.n > 0
  loop
    if r.coluna = r.alvo then
      continue;
    end if;
    select ordem into v_ord_alvo from public.jornada_coluna where id = r.alvo;
    select ordem into v_ord_atual from public.jornada_coluna where id = r.coluna;
    -- a equipe já passou o card adiante e o Klingo ainda não alcançou: é o normal, sem alarde
    if r.alvo in ('a_confirmar', 'confirmado', 'em_atendimento') and v_ord_atual > v_ord_alvo and v_ord_atual < 20 then
      continue;
    end if;
    v_res := public.jornada_aplicar_klingo(r.id, r.alvo, jsonb_build_object('fonte', '13825'));
    if v_res = 'moveu' then n_movidos := n_movidos + 1; elsif v_res = 'ignorado' then n_diverg := n_diverg + 1; end if;
  end loop;

  -- 3) Em atendimento de um dia que já passou vira Finalizado sozinho
  for c in select * from public.jornada_card where coluna = 'em_atendimento' and data_ref < v_hoje and arquivado_em is null loop
    update public.jornada_card set coluna = 'finalizado', coluna_desde = now(), versao = versao + 1, atualizado_em = now() where id = c.id;
    insert into public.jornada_evento (card_id, tipo, origem, de_coluna, para_coluna, detalhe)
    values (c.id, 'movido', 'sistema', 'em_atendimento', 'finalizado', jsonb_build_object('motivo', 'O dia do atendimento já passou.'));
    n_finaliz := n_finaliz + 1;
  end loop;

  -- 4) arquivar o que já acabou (cards digitados à mão, chave "manual:", ficam)
  update public.jornada_card
     set arquivado_em = now(), atualizado_em = now()
   where arquivado_em is null and paciente_chave not like 'manual:%'
     and ((data_ref < v_hoje - 7 and coluna in ('concluido', 'cancelado', 'remarcado', 'faltou')) or data_ref < v_hoje - 30);
  get diagnostics n_arquiv = row_count;

  return jsonb_build_object('exames', n_exames, 'cards_criados', n_criados, 'cards_movidos', n_movidos, 'divergencias', n_diverg,
                            'finalizados_sozinho', n_finaliz, 'arquivados', n_arquiv,
                            'duracao_ms', round(extract(epoch from (clock_timestamp() - v_ini)) * 1000));
end;
$$;

-- Roda o trabalho só quando precisa: o #13825 foi lido de novo, ou virou o dia (o "faltou" depende da data).
create or replace function public.jornada_sincronizar_se_preciso()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_rel    uuid;
  v_visto  timestamptz;
  e        public.jornada_sync_estado%rowtype;
  v_hoje   date := (now() at time zone 'America/Sao_Paulo')::date;
  v_res    jsonb;
begin
  select id into v_rel from public.dim_relatorio where klingo_id = '13825' and ativo;
  if v_rel is null then
    return jsonb_build_object('rodou', false, 'motivo', 'sem relatório 13825');
  end if;
  select max(finished_at) into v_visto from public.sync_relatorio_runs where relatorio_id = v_rel and status = 'success';
  select * into e from public.jornada_sync_estado;

  if e.ultima_execucao is not null and e.ultima_leitura_vista is not distinct from v_visto
     and (e.ultima_execucao at time zone 'America/Sao_Paulo')::date = v_hoje then
    return jsonb_build_object('rodou', false);
  end if;

  v_res := public.jornada_sincronizar_klingo();
  update public.jornada_sync_estado set ultima_leitura_vista = v_visto, ultima_execucao = now(), ultimo_resultado = v_res where id;
  return jsonb_build_object('rodou', true) || v_res;
end;
$$;

revoke execute on function public.jornada_marcacoes_janela(integer, integer)  from public, anon, authenticated;
revoke execute on function public.jornada_sincronizar_klingo(integer, integer) from public, anon, authenticated;
revoke execute on function public.jornada_sincronizar_se_preciso()             from public, anon, authenticated;
grant  execute on function public.jornada_marcacoes_janela(integer, integer)  to service_role;
grant  execute on function public.jornada_sincronizar_klingo(integer, integer) to service_role;
grant  execute on function public.jornada_sincronizar_se_preciso()             to service_role;

select cron.schedule('jornada-sincronizar', '* * * * *', $cmd$ select public.jornada_sincronizar_se_preciso(); $cmd$);

-- Pendências desta etapa (aparecem na aba Avisos pela jornada_pendencias_sincronizar, todo dia às 06:00).
insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('banco_espaco', 3,
   'O banco está perto do limite de espaço (a coleta para sozinha em 470 MB)',
   'Em 01/11/2026 o banco tinha 422 MB; 334 MB são o histórico dos relatórios (fact_relatorio_linha). Acima de 470 MB a coleta do Klingo para sozinha (freio de emergência) e o quadro deixa de atualizar. O quadro e o chat vão acrescentar dados todos os dias.',
   'critico',
   '["Decida: passar para um plano com mais espaço, ou limpar o histórico dos relatórios que ninguém usa (peça e eu preparo a lista do que dá para limpar; apagar linhas exige rodar no SQL Editor).", "Enquanto isso, não ative novos relatórios na coleta sem avisar."]'::jsonb),
  ('regras_automaticas_quadro', 3,
   'Conferir as regras automáticas do quadro',
   'O sistema faz sozinho: (1) Em atendimento de um dia que já passou vira Finalizado; (2) cards de Cancelado, Remarcado, Faltou e Concluído com mais de 7 dias, e qualquer card com mais de 30 dias, saem do quadro (arquivados, não apagados); (3) "Faltou" = marcação aberta, sem atendimento, com a data já passada; (4) o quadro só traz exames de 2 dias atrás até 30 dias à frente.',
   'info',
   '["Diga o que mudar. Exemplos: arquivar Laudo pendente que fica parado há muito tempo? Concluir sozinho o card depois do NPS? Janela maior que 30 dias à frente?"]'::jsonb),
  ('nomes_unidades', 3,
   'Conferir os nomes das unidades no quadro',
   'O Klingo traz três unidades e o quadro as chama: CSI 1 (CLÍNICA DE SAÚDE E IMAGEM - CSI), CSI 2 (... - RM/TC) e CSI Pediatria (DESENVOAR), os mesmos nomes dos grupos de metas.',
   'info',
   '["Se a equipe usa outros nomes, diga quais; muda em uma função (jornada_unidade_curta)."]'::jsonb)
on conflict (chave) do nothing;
