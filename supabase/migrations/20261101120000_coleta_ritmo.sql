-- Coleta adaptativa ("ritmo") dos relatórios da Jornada do paciente.
--
-- Os relatórios que alimentam o acompanhamento do paciente (#13404 Fluxo na Recepção e #13825 Agendamentos por Marcação) passam a ser lidos
-- num ritmo próprio, que se ajusta sozinho ao movimento:
--   * dentro do expediente de coleta (06:30–18:30, segunda a sábado, sem feriado): sempre no intervalo mínimo do relatório (1 min);
--   * fora do expediente: continua no mínimo enquanto houver movimento; depois de `leituras_para_desacelerar` leituras seguidas sem
--     mudança, vai espaçando (5, 15, 60 min; o teto é `teto_min`) e nunca dorme além da abertura do expediente seguinte;
--   * qualquer movimento volta ao mínimo na hora: o Klingo devolveu linha nova ou alterada, alguém abriu o painel (`acordar_coleta`).
-- "Movimento no Klingo" = linhas gravadas em `fact_relatorio_linha` por aquela leitura (a linha igual só atualiza last_seen_at; a que mudou vira
-- registro novo, com first_seen_at depois do início da leitura).
--
-- Os demais relatórios seguem como antes (cron de 5 min, `proximos_trabalhos`). O período corrente de um relatório com ritmo sai da lista
-- geral (senão seria lido duas vezes); os períodos anteriores continuam nela.
--
-- Cron: este arquivo agenda `coleta-ritmo-1min` (a cada minuto), que só chama a Edge Function quando algum relatório está vencido.
-- A Edge Function precisa estar na versão que entende {"ritmo": true} (supabase/functions/sync-relatorios-dw).
-- Só create, grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

-- ---------------------------------------------------------------- configuração (uma linha só)
create table if not exists public.coleta_ritmo_config (
  id                        boolean primary key default true check (id),
  exp_ini                   time        not null default '06:30',
  exp_fim                   time        not null default '18:30',
  dias_semana               integer[]   not null default '{1,2,3,4,5,6}',      -- ISO: 1 = segunda ... 7 = domingo
  feriados                  date[]      not null default '{}',
  teto_min                  integer     not null default 60 check (teto_min between 1 and 720),
  passos                    integer[]   not null default '{5,15,60}',          -- degraus da desaceleração, em minutos
  leituras_para_desacelerar integer     not null default 15 check (leituras_para_desacelerar >= 1),
  ultimo_acordar_em         timestamptz
);

insert into public.coleta_ritmo_config (id, feriados) values (true, '{2026-10-12}') on conflict (id) do nothing;

comment on table public.coleta_ritmo_config is 'Ritmo da coleta adaptativa: expediente de coleta, feriados, teto de espera fora do expediente e degraus da desaceleração. Uma linha só; edite pelo SQL Editor.';

-- ---------------------------------------------------------------- estado por relatório
create table if not exists public.coleta_ritmo (
  relatorio_id         uuid primary key references public.dim_relatorio (id),
  ativo                boolean     not null default true,
  minimo_min           integer     not null default 1 check (minimo_min >= 1),   -- menor intervalo entre leituras deste relatório
  marcha               text        not null default 'ao_vivo' check (marcha in ('ao_vivo', 'calmo', 'dormindo')),
  intervalo_atual_min  integer     not null default 1,
  sem_mudanca_seguidas integer     not null default 0,
  erros_seguidos       integer     not null default 0,
  proxima_leitura_em   timestamptz not null default now(),
  ultima_leitura_em    timestamptz,
  ultimo_movimento_em  timestamptz,
  motivo_movimento     text
);

comment on table public.coleta_ritmo is 'Estado da coleta adaptativa de cada relatório da Jornada: marcha atual, intervalo, próxima leitura e último movimento. Mantida por coleta_ritmo_registrar (trigger em sync_relatorio_runs) e acordar_coleta.';

alter table public.coleta_ritmo_config enable row level security;
alter table public.coleta_ritmo        enable row level security;

create policy "coleta_ritmo_config_select" on public.coleta_ritmo_config for select to authenticated using (true);
create policy "coleta_ritmo_select"        on public.coleta_ritmo        for select to authenticated using (true);

revoke all on public.coleta_ritmo_config, public.coleta_ritmo from public, anon, authenticated;
grant select on public.coleta_ritmo_config, public.coleta_ritmo to authenticated;
grant all    on public.coleta_ritmo_config, public.coleta_ritmo to service_role;

-- ---------------------------------------------------------------- regras do ritmo
-- Estamos no expediente de coleta (dia de atendimento, fora de feriado, entre exp_ini e exp_fim, hora de Brasília)?
create or replace function public.coleta_em_expediente(p_ts timestamptz)
returns boolean
language sql
stable
set search_path = ''
as $$
  select extract(isodow from p_ts at time zone 'America/Sao_Paulo')::integer = any (c.dias_semana)
     and not ((p_ts at time zone 'America/Sao_Paulo')::date = any (c.feriados))
     and (p_ts at time zone 'America/Sao_Paulo')::time >= c.exp_ini
     and (p_ts at time zone 'America/Sao_Paulo')::time <  c.exp_fim
  from public.coleta_ritmo_config c;
$$;

-- Próxima abertura de expediente depois de p_ts (nos próximos 10 dias), ou null se não houver dia de atendimento.
create or replace function public.coleta_proximo_expediente(p_ts timestamptz)
returns timestamptz
language sql
stable
set search_path = ''
as $$
  select min(x.ts)
  from (
    select ((d::date + c.exp_ini) at time zone 'America/Sao_Paulo') as ts
    from public.coleta_ritmo_config c,
         generate_series((p_ts at time zone 'America/Sao_Paulo')::date::timestamp, ((p_ts at time zone 'America/Sao_Paulo')::date + 10)::timestamp, interval '1 day') d
    where extract(isodow from d)::integer = any (c.dias_semana)
      and not (d::date = any (c.feriados))
  ) x
  where x.ts > p_ts;
$$;

-- Qual é o próximo intervalo? p_sem_mudanca = leituras seguidas sem movimento, contando a que acabou de terminar; p_movimento = a leitura trouxe movimento.
create or replace function public.coleta_ritmo_proximo(p_agora timestamptz, p_minimo integer, p_sem_mudanca integer, p_movimento boolean)
returns table (intervalo_min integer, marcha text, proxima timestamptz)
language plpgsql
stable
set search_path = ''
as $$
declare
  c        public.coleta_ritmo_config%rowtype;
  v_exp    boolean;
  v_int    integer;
  v_marcha text;
  v_prox   timestamptz;
begin
  select * into c from public.coleta_ritmo_config;
  v_exp := coalesce(public.coleta_em_expediente(p_agora), false);

  if p_movimento or v_exp or p_sem_mudanca < c.leituras_para_desacelerar then
    v_int := p_minimo;
    v_marcha := 'ao_vivo';
  else
    v_int := c.passos[least(p_sem_mudanca - c.leituras_para_desacelerar + 1, cardinality(c.passos))];
    v_int := least(greatest(v_int, p_minimo), greatest(c.teto_min, p_minimo));
    v_marcha := case when v_int >= greatest(c.teto_min, p_minimo) then 'dormindo' else 'calmo' end;
  end if;

  v_prox := p_agora + make_interval(mins => v_int);
  -- fora do expediente nunca dorme além da abertura do próximo (least ignora null)
  if not v_exp then
    v_prox := least(v_prox, public.coleta_proximo_expediente(p_agora));
  end if;

  return query select v_int, v_marcha, v_prox;
end;
$$;

-- ---------------------------------------------------------------- registro de cada leitura (trigger)
-- Depois de cada leitura que terminou (sucesso ou erro) de um relatório com ritmo, no período corrente, atualiza a marcha e a próxima leitura.
-- Qualquer falha aqui só vira aviso: a coleta nunca pode quebrar por causa do ritmo.
create or replace function public.coleta_ritmo_registrar()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  r        public.coleta_ritmo%rowtype;
  v_gran   text;
  v_agora  timestamptz := now();
  v_hoje   date := (now() at time zone 'America/Sao_Paulo')::date;
  v_mov    boolean := false;
  v_sem    integer;
  p        record;
begin
  select * into r from public.coleta_ritmo where relatorio_id = new.relatorio_id and ativo;
  if not found then
    return new;
  end if;

  select coalesce(granularidade, 'dia') into v_gran from public.dim_relatorio where id = new.relatorio_id;
  -- só a leitura do período corrente (hoje, ou o mês corrente) mexe no ritmo
  if new.periodo is distinct from (case when v_gran = 'mes' then date_trunc('month', v_hoje::timestamp)::date else v_hoje end) then
    return new;
  end if;

  if new.status = 'error' then
    update public.coleta_ritmo
       set erros_seguidos = erros_seguidos + 1,
           ultima_leitura_em = v_agora,
           proxima_leitura_em = v_agora + make_interval(mins => least(30, 5 * (1 << least(r.erros_seguidos, 3))))
     where relatorio_id = new.relatorio_id;
    return new;
  end if;

  v_mov := exists (
    select 1 from public.fact_relatorio_linha f
    where f.relatorio_id = new.relatorio_id and f.periodo = new.periodo and f.first_seen_at >= new.started_at
  );
  v_sem := case when v_mov then 0 else r.sem_mudanca_seguidas + 1 end;
  -- a base é o minuto cheio em que a leitura começou: o cron roda no segundo :00 e a leitura termina alguns segundos depois, então contar a partir do
  -- fim faria a próxima vencer logo depois do tick seguinte (1 leitura a cada 2 min em vez de 1)
  select * into p from public.coleta_ritmo_proximo(date_trunc('minute', new.started_at), r.minimo_min, v_sem, v_mov);

  update public.coleta_ritmo
     set erros_seguidos = 0,
         sem_mudanca_seguidas = v_sem,
         intervalo_atual_min = p.intervalo_min,
         marcha = p.marcha,
         proxima_leitura_em = p.proxima,
         ultima_leitura_em = v_agora,
         ultimo_movimento_em = case when v_mov then v_agora else ultimo_movimento_em end,
         motivo_movimento = case when v_mov then 'O Klingo trouxe linha nova ou alterada' else motivo_movimento end
   where relatorio_id = new.relatorio_id;
  return new;
exception when others then
  raise warning 'coleta_ritmo_registrar: %', sqlerrm;
  return new;
end;
$$;

revoke execute on function public.coleta_ritmo_registrar() from public, anon, authenticated;

create or replace trigger sync_relatorio_runs_ritmo
  after update of status on public.sync_relatorio_runs
  for each row
  when (old.status = 'running' and new.status in ('success', 'error'))
  execute function public.coleta_ritmo_registrar();

-- ---------------------------------------------------------------- acordar
-- Quem abre o painel (ou o paciente, no futuro) acorda a coleta que estava devagar. Só afeta quem não está "ao vivo",
-- no máximo uma vez a cada 20 s, para ninguém forçar leituras do Klingo em excesso.
create or replace function public.acordar_coleta(p_motivo text default 'Alguém abriu o painel')
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_n integer;
begin
  if auth.uid() is null then
    raise exception 'Faça login.';
  end if;

  update public.coleta_ritmo_config
     set ultimo_acordar_em = now()
   where id and (ultimo_acordar_em is null or ultimo_acordar_em < now() - interval '20 seconds');
  if not found then
    return jsonb_build_object('ok', true, 'acordou', 0);
  end if;

  update public.coleta_ritmo
     set marcha = 'ao_vivo',
         intervalo_atual_min = minimo_min,
         sem_mudanca_seguidas = 0,
         proxima_leitura_em = case when erros_seguidos = 0 then least(proxima_leitura_em, now()) else proxima_leitura_em end,
         ultimo_movimento_em = now(),
         motivo_movimento = left(coalesce(nullif(trim(p_motivo), ''), 'Alguém abriu o painel'), 80)
   where ativo and marcha <> 'ao_vivo';
  get diagnostics v_n = row_count;
  return jsonb_build_object('ok', true, 'acordou', v_n);
end;
$$;

revoke execute on function public.acordar_coleta(text) from public, anon;
grant  execute on function public.acordar_coleta(text) to authenticated;

-- ---------------------------------------------------------------- o que a barra de atualização mostra
create or replace function public.status_ritmo_coleta()
returns table (
  klingo_id text,
  nome text,
  marcha text,
  intervalo_min integer,
  minimo_min integer,
  ultima_leitura_em timestamptz,
  proxima_leitura_em timestamptz,
  ultimo_movimento_em timestamptz,
  motivo_movimento text,
  erros_seguidos integer,
  em_expediente boolean,
  agora timestamptz
)
language sql
security invoker
stable
set search_path = ''
as $$
  select r.klingo_id, r.nome, c.marcha, c.intervalo_atual_min, c.minimo_min, c.ultima_leitura_em, c.proxima_leitura_em,
         c.ultimo_movimento_em, c.motivo_movimento, c.erros_seguidos, coalesce(public.coleta_em_expediente(now()), false), now()
  from public.coleta_ritmo c
  join public.dim_relatorio r on r.id = c.relatorio_id
  where c.ativo and r.ativo
  order by r.klingo_id;
$$;

revoke execute on function public.status_ritmo_coleta() from public, anon;
grant  execute on function public.status_ritmo_coleta() to authenticated;

-- ---------------------------------------------------------------- o que a coleta de 1 minuto deve ler agora
create or replace function public.proximos_trabalhos_ritmo(p_limite integer default 10)
returns table (relatorio_id uuid, klingo_id text, periodo date, restantes bigint)
language sql
stable
set search_path = ''
as $$
  with alvo as (
    select r.id, r.klingo_id,
           case when coalesce(r.granularidade, 'dia') = 'mes'
                then date_trunc('month', ((now() at time zone 'America/Sao_Paulo')::date)::timestamp)::date
                else (now() at time zone 'America/Sao_Paulo')::date end as periodo
    from public.coleta_ritmo c
    join public.dim_relatorio r on r.id = c.relatorio_id
    where c.ativo and r.ativo and r.supersedido_por is null
      and r.filtro_periodo is not null and r.periodo_validado_em is not null     -- filtro de período já comprovado
      and c.proxima_leitura_em <= now()
      and pg_database_size(current_database()) < 470000000                       -- freio de espaço, igual ao de proximos_trabalhos
  )
  select a.id, a.klingo_id, a.periodo, count(*) over ()
  from alvo a
  where not exists (
    select 1 from public.sync_relatorio_runs s
    where s.relatorio_id = a.id and s.periodo = a.periodo and s.status = 'running' and s.started_at > now() - interval '5 minutes'
  )
  order by a.klingo_id
  limit greatest(least(p_limite, 20), 1);
$$;

revoke execute on function public.proximos_trabalhos_ritmo(integer) from public, anon, authenticated;
grant  execute on function public.proximos_trabalhos_ritmo(integer) to service_role;

-- ---------------------------------------------------------------- lista geral: o período corrente de quem tem ritmo sai dela
-- Igual a 20261014230000_limite_de_espaco.sql, com uma condição a mais em pend_dia e em pend_mes.
create or replace function public.proximos_trabalhos(p_limite integer default 30, p_frescor_minutos integer default 300)
returns table (relatorio_id uuid, klingo_id text, periodo date, restantes bigint)
language sql
stable
set search_path = ''
as $$
  with hoje as (
    select (now() at time zone 'America/Sao_Paulo')::date as d
  ),
  rel as (
    select id, klingo_id, periodicidade, granularidade, primeiro_mes, meses_a_frente, revisar_meses,
      case when filtro_periodo is null or periodo_validado_em is null then 1 else janela_dias end as janela,
      (filtro_periodo is not null and periodo_validado_em is null) as a_comprovar
    from public.dim_relatorio
    where ativo and supersedido_por is null and (pausado_ate is null or pausado_ate <= now())
      and pg_database_size(current_database()) < 470000000
  ),
  pares_dia as (
    select r.id, r.klingo_id, r.periodicidade, r.a_comprovar, g::date as periodo, h.d as hoje
    from rel r
    cross join hoje h
    cross join lateral generate_series(
      (case when r.periodicidade = 'pontual' then h.d else h.d - (r.janela - 1) end)::timestamp,
      h.d::timestamp,
      interval '1 day'
    ) g
    where coalesce(r.granularidade, 'dia') = 'dia'
  ),
  pend_dia as (
    select p.id, p.klingo_id, p.periodo, (p.periodo = p.hoje) as atual
    from pares_dia p
    where
      case when p.periodicidade = 'pontual'
        then not exists (
          select 1 from public.sync_relatorio_runs s where s.relatorio_id = p.id and s.status = 'success'
        )
        else not exists (
          select 1 from public.sync_relatorio_runs s
          where s.relatorio_id = p.id and s.periodo = p.periodo and s.status = 'success'
            and not (p.a_comprovar and p.periodo = p.hoje)
            and (s.finished_at at time zone 'America/Sao_Paulo')::date > p.periodo
            and (p.periodo < p.hoje
                 or s.finished_at > now() - make_interval(mins => greatest(p_frescor_minutos, 1)))
        )
      end
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = p.id and s.periodo = p.periodo
          and ((s.status = 'running' and s.started_at > now() - interval '5 minutes')
            or (s.status = 'error' and s.started_at > now() - interval '30 minutes'))
      )
      and (select count(*) from public.sync_relatorio_runs s
           where s.relatorio_id = p.id and s.periodo = p.periodo and s.status = 'running'
             and s.started_at < now() - interval '5 minutes' and s.started_at > now() - interval '3 hours') < 2
      -- relatório com ritmo: o dia de hoje é da coleta de 1 minuto (proximos_trabalhos_ritmo)
      and not (p.periodo = p.hoje and exists (select 1 from public.coleta_ritmo c where c.relatorio_id = p.id and c.ativo))
  ),
  pares_mes as (
    select r.id, r.klingo_id, r.revisar_meses, r.a_comprovar, g::date as periodo, h.d as hoje
    from rel r
    cross join hoje h
    cross join lateral generate_series(
      (case when r.a_comprovar or r.primeiro_mes is null then date_trunc('month', h.d::timestamp) else r.primeiro_mes::timestamp end),
      date_trunc('month', h.d::timestamp) + make_interval(months => r.meses_a_frente),
      interval '1 month'
    ) g
    where r.granularidade = 'mes'
  ),
  pend_mes as (
    select m.id, m.klingo_id, m.periodo, (m.periodo = date_trunc('month', m.hoje::timestamp)::date) as atual
    from pares_mes m
    where not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = m.id and s.periodo = m.periodo and s.status = 'success'
          and not (m.a_comprovar and m.periodo = date_trunc('month', m.hoje::timestamp)::date)
          and (
            case when m.periodo >= (date_trunc('month', m.hoje::timestamp) - make_interval(months => coalesce(m.revisar_meses, 2)))::date
              then s.finished_at > now() - make_interval(mins => greatest(p_frescor_minutos, 1))
              else (m.revisar_meses is not null or s.finished_at > now() - interval '24 hours')
            end
          )
      )
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = m.id and s.periodo = m.periodo
          and ((s.status = 'running' and s.started_at > now() - interval '5 minutes')
            or (s.status = 'error' and s.started_at > now() - interval '30 minutes'))
      )
      and (select count(*) from public.sync_relatorio_runs s
           where s.relatorio_id = m.id and s.periodo = m.periodo and s.status = 'running'
             and s.started_at < now() - interval '5 minutes' and s.started_at > now() - interval '3 hours') < 2
      -- relatório com ritmo: o mês corrente é da coleta de 1 minuto
      and not (m.periodo = date_trunc('month', m.hoje::timestamp)::date
               and exists (select 1 from public.coleta_ritmo c where c.relatorio_id = m.id and c.ativo))
  ),
  pend_snap as (
    select r.id, r.klingo_id, date '2000-01-01' as periodo, true as atual
    from rel r
    where r.granularidade = 'snapshot'
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = r.id and s.periodo = date '2000-01-01' and s.status = 'success'
          and s.finished_at > now() - make_interval(mins => greatest(p_frescor_minutos, 1))
      )
      and not exists (
        select 1 from public.sync_relatorio_runs s
        where s.relatorio_id = r.id and s.periodo = date '2000-01-01'
          and ((s.status = 'running' and s.started_at > now() - interval '5 minutes')
            or (s.status = 'error' and s.started_at > now() - interval '30 minutes'))
      )
      and (select count(*) from public.sync_relatorio_runs s
           where s.relatorio_id = r.id and s.periodo = date '2000-01-01' and s.status = 'running'
             and s.started_at < now() - interval '5 minutes' and s.started_at > now() - interval '3 hours') < 2
  ),
  todos as (
    select * from pend_dia
    union all
    select * from pend_mes
    union all
    select * from pend_snap
  )
  select id, klingo_id, periodo, count(*) over ()
  from todos
  order by atual desc, periodo desc, klingo_id
  limit greatest(least(p_limite, 100), 1);
$$;

-- ---------------------------------------------------------------- quem entra no ritmo
-- #13404: relatório do dia (lido por inteiro todo minuto). #13825: relatório do mês (~8,5 mil linhas, ~16 s por leitura) filtrado pela data em que a
-- marcação foi FEITA; enquanto não existir o relatório por data do exame (ver o aviso da Jornada), o mínimo é 15 min, não 1.
insert into public.coleta_ritmo (relatorio_id, minimo_min, intervalo_atual_min)
select id, case klingo_id when '13404' then 1 else 15 end, case klingo_id when '13404' then 1 else 15 end
from public.dim_relatorio
where klingo_id in ('13404', '13825')
on conflict (relatorio_id) do nothing;

-- ---------------------------------------------------------------- agendamento: a cada minuto, só chama a Edge Function se alguém está vencido
select cron.schedule(
  'coleta-ritmo-1min',
  '* * * * *',
  $cmd$
    select net.http_post(
      url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-relatorios-dw',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer ' || (
          select decrypted_secret from vault.decrypted_secrets
          where name = 'cron_service_role_key'
        )
      ),
      body := '{"modo":"auto","ritmo":true,"limite":10}'::jsonb,
      timeout_milliseconds := 150000
    )
    where exists (select 1 from public.coleta_ritmo c where c.ativo and c.proxima_leitura_em <= now());
  $cmd$
);

-- ---------------------------------------------------------------- pendência: como deve ser o relatório da Jornada
-- Aviso do painel Atendimento, no escopo "jornada" (a conferência do painel Python só mexe no escopo "" e nos meses, então não o resolve por engano).
-- Resolve sozinho quando as colunas pedidas aparecem em dim_relatorio_coluna.
create or replace function public.jornada_pendencias_sincronizar()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_linhas   jsonb := '[]'::jsonb;
  v_alertas  jsonb := '[]'::jsonb;
  v_url      text := 'https://clinicacsi.klingo.app/#/relatorio/';
  v_tem_novo boolean;
begin
  select exists (select 1 from public.dim_relatorio where ativo and nome ilike 'Jornada do Paciente%') into v_tem_novo;

  if not v_tem_novo then
    v_linhas := v_linhas || jsonb_build_array(jsonb_build_array(
      'NOVO: Jornada do Paciente - Marcações por Data do Exame',
      'Criar o relatório (uma linha por marcação) com filtro por Data do Exame (Agendado Para) e, se o Klingo permitir, por Alterado em.',
      'O #13825 só filtra pela data em que a marcação foi FEITA. Cancelamento, confirmação e atendimento de uma marcação antiga não aparecem sem reler o mês inteiro (~8,5 mil linhas, 16 s).'));
  end if;

  if not exists (
    select 1 from public.dim_relatorio_coluna c join public.dim_relatorio r on r.id = c.relatorio_id
    where r.klingo_id = '13404' and coalesce(c.titulo_klingo, c.rotulo) ~* 'id d[oa] atendimento'
  ) then
    v_linhas := v_linhas || jsonb_build_array(jsonb_build_array(
      '#13404 Fluxo na Recepção',
      'Acrescentar as colunas Id do Atendimento, Id da Marcação e Prontuário.',
      'Sem o Id, a recepção não se liga ao paciente: só dá para acompanhar em agregado.'));
  end if;

  if not exists (
    select 1 from public.dim_relatorio_coluna c join public.dim_relatorio r on r.id = c.relatorio_id
    where r.klingo_id = '13402' and coalesce(c.titulo_klingo, c.rotulo) ~* 'id d[oa] atendimento'
  ) then
    v_linhas := v_linhas || jsonb_build_array(jsonb_build_array(
      '#13402 Visão Gerencial de Produtividade',
      'Acrescentar as colunas Id do Atendimento, Id da Marcação e Prontuário.',
      'Sem o Id, o início, o fim e a duração do exame não se ligam ao paciente.'));
  end if;

  if jsonb_array_length(v_linhas) > 0 then
    v_alertas := jsonb_build_array(jsonb_build_object(
      'chave', 'jornada|jornada_relatorio_klingo',
      'tipo', 'jornada_relatorio_klingo',
      'escopo', 'jornada',
      'nivel', 'info',
      'persistente', true,
      'titulo', 'Jornada do paciente: relatórios do Klingo a criar ou alterar',
      'texto', 'Para acompanhar cada paciente da marcação ao atendimento, com atualização a cada minuto, o Klingo precisa entregar os dados de um jeito mais fácil: '
               || 'um relatório de marcações por data do exame e o Id do atendimento nos relatórios da recepção. Enquanto isso não existe, a coleta de 1 minuto só enxerga marcações novas.',
      'itens_total', jsonb_array_length(v_linhas),
      'itens', jsonb_build_object(
        'colunas', jsonb_build_array('Relatório', 'O que fazer', 'Por quê'),
        'linhas', v_linhas,
        'total', jsonb_array_length(v_linhas),
        'numericas', '[]'::jsonb),
      'guia', jsonb_build_object(
        'relatorios', jsonb_build_array(
          jsonb_build_object('id', 13825, 'nome', 'Agendamentos - Visão Consolidada por Marcação (modelo do novo relatório)', 'url', v_url || '13825'),
          jsonb_build_object('id', 13404, 'nome', 'Atendimentos - Tempos de Espera e Fluxo na Recepção - Mensal', 'url', v_url || '13404'),
          jsonb_build_object('id', 13402, 'nome', 'Atendimentos - Visão Gerencial de Produtividade, Espera e Receita - Mensal', 'url', v_url || '13402')),
        'passos', jsonb_build_array(
          'Duplique o relatório #13825 e chame de "Jornada do Paciente - Marcações por Data do Exame".',
          'Filtro de período: Data do Exame (Agendado Para). Se houver, inclua também o filtro "Alterado em" (última alteração da marcação).',
          'Uma linha por marcação, com estas colunas: Id da Marcação, Id do Atendimento, Prontuário, Data Agendado Em, Data Agendado Para (com hora), Procedimento, Unidade/Sala/Equipamento, Profissional solicitante, Operadora, Valor, Responsável (quem marcou).',
          'Situação da marcação: Status, Cancelamento - Motivo, data do cancelamento, Confirm Status, data e usuário da confirmação, Atendido (S/N), Observação.',
          'Dia do exame: Check-In (hora), início e fim do exame, situação do laudo (e data de liberação) e situação da autorização do convênio (e número).',
          'Paciente (só para a equipe, com permissão): nome, data de nascimento, celular, telefone, e-mail e responsável legal (Pediatria).',
          'Controle: uma coluna com a data e a hora da última alteração de cada marcação.',
          'Nos relatórios #13404 e #13402, inclua as colunas Id do Atendimento, Id da Marcação e Prontuário.',
          'Avise o Claude quando o relatório novo existir: ele cadastra o relatório (dim_relatorio), confere as colunas e libera a leitura de 1 minuto.'),
        'resolve', 'Quando existir um relatório ativo chamado "Jornada do Paciente ..." e os relatórios #13404 e #13402 tiverem a coluna Id do Atendimento, o aviso se resolve sozinho (conferido todo dia às 06:00).'))
    );
  end if;

  return public.aviso_sincronizar('atendimento', array['jornada'], 0, v_alertas);
end;
$$;

revoke execute on function public.jornada_pendencias_sincronizar() from public, anon, authenticated;
grant  execute on function public.jornada_pendencias_sincronizar() to service_role;

select cron.schedule('jornada-pendencias-diaria', '0 9 * * *', $cmd$ select public.jornada_pendencias_sincronizar(); $cmd$);   -- 09:00 UTC = 06:00 em Brasília
