-- Aba "Avisos": as pendências de todos os painéis num lugar só.
--
-- Cada alerta com guia que um painel calcula (Faturamento, Financeiro, ...) vira uma linha em `aviso`. A cada vez que a página de um painel
-- é refeita (dados novos ou novo dia), `aviso_sincronizar` compara o que o painel mostra agora com o que já estava registrado:
--   * apareceu pela primeira vez            -> aviso novo, "aberto";
--   * continua aparecendo                   -> segue "aberto";
--   * deixou de aparecer                    -> "resolvido" (o problema foi corrigido nos dados);
--   * estava resolvido e voltou a aparecer  -> "aberto" de novo, com `recorrencias` + 1 (o problema voltou a acontecer);
--   * fechado com justificativa e os dados foram atualizados e ele continua -> "aberto" de novo, `reaberturas` + 1 (a justificativa não resolveu).
-- Para fechar um aviso à mão é preciso justificar (`fechar_aviso`). Um aviso "persistente" (que a clínica pode aceitar, como cortesias com valor
-- zero) fica fechado enquanto o painel continuar mostrando, e só reabre se piorar. Tudo o que acontece fica em `aviso_evento`.
--
-- Quem vê o quê: o administrador vê tudo; os demais só os avisos dos painéis liberados em Configurações (profiles.permissions.<painel>).

create table if not exists public.aviso (
  id                 bigint generated always as identity primary key,
  painel             text        not null,                      -- id do painel em modulos.json
  chave              text        not null,                      -- "escopo|tipo": mesmo alerta = mesma chave (escopo "" vale para hoje, "AAAA-MM" para o mês)
  tipo               text        not null,                      -- id do tipo de alerta (guia_pendencias.py)
  escopo             text        not null default '',
  titulo             text        not null,
  texto              text        not null default '',           -- explicação em texto simples
  nivel              text        not null check (nivel in ('critico', 'atencao', 'info')),
  persistente        boolean     not null default false,        -- a clínica pode aceitar com justificativa; só reabre se piorar
  guia               jsonb       not null default '{}'::jsonb,  -- relatórios do Klingo, passo a passo e quando some
  itens              jsonb,                                     -- tabela dos registros afetados
  itens_total        integer,
  status             text        not null default 'aberto' check (status in ('aberto', 'justificado', 'resolvido')),
  primeira_deteccao  timestamptz not null default now(),
  ultima_deteccao    timestamptz not null default now(),        -- última vez que o alerta apareceu nos dados
  ultima_conferencia timestamptz not null default now(),        -- última vez que o painel conferiu os dados (apareça ou não)
  versao_dados       bigint      not null default 0,            -- versão dos dados na última conferência
  resolvido_em       timestamptz,
  recorrencias       integer     not null default 0 check (recorrencias >= 0),   -- vezes que voltou depois de resolvido
  reaberturas        integer     not null default 0 check (reaberturas >= 0),    -- vezes que foi fechado com justificativa e o problema continuou ou piorou
  ultima_recorrencia timestamptz,
  justificativa      text,
  justificado_por    text,
  justificado_em     timestamptz,
  justificado_versao bigint,
  justificado_nivel  text,
  justificado_itens  integer,
  unique (painel, chave)
);

create index if not exists aviso_status_idx on public.aviso (status, painel);

create table if not exists public.aviso_evento (
  id          bigint generated always as identity primary key,
  aviso_id    bigint      not null references public.aviso (id) on delete cascade,
  painel      text        not null,
  quando      timestamptz not null default now(),
  tipo        text        not null check (tipo in ('detectado', 'sumiu', 'justificado', 'confirmado', 'reapareceu', 'nao_corrigido', 'piorou', 'reaberto')),
  usuario     text        not null default '',
  detalhe     text        not null default '',
  itens_total integer
);

create index if not exists aviso_evento_aviso_idx on public.aviso_evento (aviso_id, quando desc);

comment on table public.aviso is 'Pendências dos painéis (alertas com guia). Preenchida por aviso_sincronizar (servidor Python); fechada à mão só por fechar_aviso, que exige justificativa.';
comment on table public.aviso_evento is 'Histórico de cada aviso: quando apareceu, foi justificado, resolvido, voltou ou piorou.';

-- ---------------------------------------------------------------- quem pode ver
-- Admin vê todos os painéis; os demais só os marcados em profiles.permissions. Painel novo nasce bloqueado.
create or replace function public.can_view_painel(p_painel text)
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin' or coalesce(permissions -> p_painel = 'true'::jsonb, false))
  );
$$;

revoke execute on function public.can_view_painel(text) from public, anon;
grant  execute on function public.can_view_painel(text) to authenticated;

alter table public.aviso        enable row level security;
alter table public.aviso_evento enable row level security;

create policy "aviso_select_com_permissao"
  on public.aviso for select to authenticated
  using (public.can_view_painel(painel));

create policy "aviso_evento_select_com_permissao"
  on public.aviso_evento for select to authenticated
  using (public.can_view_painel(painel));

-- Ninguém grava direto: só pelas funções abaixo (o navegador não tem insert/update/delete).
revoke all on public.aviso, public.aviso_evento from public, anon, authenticated;
grant  select on public.aviso, public.aviso_evento to authenticated;
grant  all    on public.aviso, public.aviso_evento to service_role;

-- ---------------------------------------------------------------- sincronização (servidor Python, service_role)
create or replace function public.aviso_peso_nivel(p_nivel text)
returns integer
language sql
immutable
set search_path = ''
as $$
  select case p_nivel when 'critico' then 3 when 'atencao' then 2 else 1 end;
$$;

-- p_alertas = lista de {chave, tipo, escopo, titulo, texto, nivel, persistente, guia, itens, itens_total} que o painel mostra agora.
-- p_escopos = escopos que o painel conferiu ("" e os meses olhados): avisos de outros meses não são mexidos (o mês pode só ter saído da janela).
-- p_versao  = versão dos dados (epoch da última atualização) que gerou a lista.
create or replace function public.aviso_sincronizar(p_painel text, p_escopos text[], p_versao bigint, p_alertas jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  a        jsonb;
  v        public.aviso%rowtype;
  agora    timestamptz := now();
  chaves   text[] := '{}';
  v_nivel  text;
  v_total  integer;
  v_persiste boolean;
  st       text;
  ev       text;
  det      text;
  n_novos integer := 0; n_voltaram integer := 0; n_reabertos integer := 0; n_resolvidos integer := 0; n_pioraram integer := 0;
  aumento  integer;
begin
  if coalesce(p_painel, '') = '' then
    raise exception 'Falta o painel.';
  end if;
  if p_alertas is null or jsonb_typeof(p_alertas) <> 'array' then
    raise exception 'A lista de alertas precisa ser um array.';
  end if;
  -- duas atualizações do mesmo painel ao mesmo tempo esperam uma pela outra
  perform pg_advisory_xact_lock(hashtext('aviso_sincronizar:' || p_painel));

  for a in select x from jsonb_array_elements(p_alertas) x loop
    chaves   := chaves || (a ->> 'chave');
    v_nivel  := case when a ->> 'nivel' in ('critico', 'atencao', 'info') then a ->> 'nivel' else 'info' end;
    v_total  := (a ->> 'itens_total')::integer;
    v_persiste := coalesce((a ->> 'persistente')::boolean, false);

    select * into v from public.aviso where painel = p_painel and chave = a ->> 'chave' for update;

    if not found then
      insert into public.aviso (painel, chave, tipo, escopo, titulo, texto, nivel, persistente, guia, itens, itens_total,
                                primeira_deteccao, ultima_deteccao, ultima_conferencia, versao_dados)
      values (p_painel, a ->> 'chave', coalesce(a ->> 'tipo', ''), coalesce(a ->> 'escopo', ''), a ->> 'titulo', coalesce(a ->> 'texto', ''),
              v_nivel, v_persiste, coalesce(a -> 'guia', '{}'::jsonb), case when jsonb_typeof(a -> 'itens') = 'object' then a -> 'itens' end, v_total,
              agora, agora, agora, coalesce(p_versao, 0))
      returning * into v;
      insert into public.aviso_evento (aviso_id, painel, quando, tipo, detalhe, itens_total)
      values (v.id, p_painel, agora, 'detectado', 'Apareceu nos dados pela primeira vez.', v_total);
      n_novos := n_novos + 1;
      continue;
    end if;

    st := v.status; ev := null; det := null;

    if v.status = 'resolvido' then
      -- estava corrigido e voltou
      st := 'aberto'; ev := 'reapareceu';
      det := 'Estava resolvido desde ' || to_char(v.resolvido_em at time zone 'America/Sao_Paulo', 'DD/MM/YYYY') || ' e voltou a aparecer nos dados.';
      n_voltaram := n_voltaram + 1;
    elsif v.status = 'justificado' then
      if v_persiste then
        -- aceito com justificativa: só reabre se piorar (nível mais grave, ou 25% mais registros — e ao menos 1 a mais)
        aumento := case when v.justificado_itens is null then null else greatest(1, ceil(v.justificado_itens * 0.25)::integer) end;
        if public.aviso_peso_nivel(v_nivel) > public.aviso_peso_nivel(coalesce(v.justificado_nivel, v_nivel)) then
          st := 'aberto'; ev := 'piorou';
          det := 'O problema aceito com justificativa ficou mais grave (de ' || coalesce(v.justificado_nivel, '?') || ' para ' || v_nivel || ').';
        elsif v_total is not null and aumento is not null and v_total >= v.justificado_itens + aumento then
          st := 'aberto'; ev := 'piorou';
          det := 'O problema aceito com justificativa piorou: de ' || v.justificado_itens || ' para ' || v_total || ' registros.';
        end if;
        if ev is not null then n_pioraram := n_pioraram + 1; end if;
      elsif coalesce(p_versao, 0) > coalesce(v.justificado_versao, 0) then
        -- os dados foram atualizados depois da justificativa e o problema continua
        st := 'aberto'; ev := 'nao_corrigido';
        det := 'Foi fechado com justificativa, mas os dados foram atualizados e o problema continua aparecendo.';
        n_reabertos := n_reabertos + 1;
      end if;
    end if;

    update public.aviso set
      titulo = a ->> 'titulo', texto = coalesce(a ->> 'texto', ''), nivel = v_nivel, persistente = v_persiste,
      guia = coalesce(a -> 'guia', '{}'::jsonb),
      itens = case when jsonb_typeof(a -> 'itens') = 'object' then a -> 'itens' end,
      itens_total = v_total,
      status = st,
      resolvido_em = case when st = 'resolvido' then resolvido_em else null end,
      recorrencias = recorrencias + case when ev = 'reapareceu' then 1 else 0 end,
      reaberturas  = reaberturas  + case when ev in ('nao_corrigido', 'piorou') then 1 else 0 end,
      ultima_recorrencia = case when ev is not null then agora else ultima_recorrencia end,
      ultima_deteccao = agora, ultima_conferencia = agora, versao_dados = greatest(versao_dados, coalesce(p_versao, 0))
    where public.aviso.id = v.id;

    if ev is not null then
      insert into public.aviso_evento (aviso_id, painel, quando, tipo, detalhe, itens_total) values (v.id, p_painel, agora, ev, det, v_total);
    end if;
  end loop;

  -- o que estava aberto ou justificado e não aparece mais, nos escopos conferidos: foi corrigido
  for v in
    select * from public.aviso
    where painel = p_painel and escopo = any (coalesce(p_escopos, array['']::text[])) and status in ('aberto', 'justificado')
      and not (chave = any (chaves))
    for update
  loop
    update public.aviso set status = 'resolvido', resolvido_em = agora, ultima_conferencia = agora, versao_dados = greatest(versao_dados, coalesce(p_versao, 0))
    where id = v.id;
    insert into public.aviso_evento (aviso_id, painel, quando, tipo, detalhe, itens_total)
    values (v.id, p_painel, agora, case when v.status = 'justificado' then 'confirmado' else 'sumiu' end,
            case when v.status = 'justificado' then 'Depois da justificativa, o problema deixou de aparecer nos dados: resolvido.'
                 else 'Não aparece mais nos dados: resolvido.' end, null);
    n_resolvidos := n_resolvidos + 1;
  end loop;

  update public.aviso set ultima_conferencia = agora, versao_dados = greatest(versao_dados, coalesce(p_versao, 0))
  where painel = p_painel and escopo = any (coalesce(p_escopos, array['']::text[])) and status = 'resolvido';

  return jsonb_build_object('novos', n_novos, 'voltaram', n_voltaram, 'reabertos', n_reabertos, 'pioraram', n_pioraram, 'resolvidos', n_resolvidos,
                            'total', jsonb_array_length(p_alertas));
end;
$$;

revoke execute on function public.aviso_sincronizar(text, text[], bigint, jsonb) from public, anon, authenticated;
grant  execute on function public.aviso_sincronizar(text, text[], bigint, jsonb) to service_role;
revoke execute on function public.aviso_peso_nivel(text) from public, anon;
grant  execute on function public.aviso_peso_nivel(text) to authenticated, service_role;

-- ---------------------------------------------------------------- fechar e reabrir (usuário logado)
create or replace function public.fechar_aviso(p_aviso bigint, p_justificativa text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v     public.aviso%rowtype;
  v_texto text := btrim(coalesce(p_justificativa, ''));
  v_email text;
begin
  if auth.uid() is null then
    raise exception 'Entre no site para fechar um aviso.' using errcode = '42501';
  end if;
  if char_length(v_texto) < 15 then
    raise exception 'Explique em pelo menos 15 caracteres o que foi feito ou por que o aviso pode ser fechado.' using errcode = '22023';
  end if;
  if char_length(v_texto) > 1000 then
    raise exception 'A justificativa pode ter no máximo 1000 caracteres.' using errcode = '22023';
  end if;

  select * into v from public.aviso where id = p_aviso for update;
  if not found or not public.can_view_painel(v.painel) then
    raise exception 'Aviso não encontrado.' using errcode = '42501';   -- mesma resposta para o que não existe e o que a pessoa não pode ver
  end if;
  if v.status <> 'aberto' then
    raise exception 'Este aviso já não está aberto.' using errcode = '55000';
  end if;

  select coalesce(p.email, '') into v_email from public.profiles p where p.id = auth.uid();
  update public.aviso set status = 'justificado', justificativa = v_texto, justificado_por = v_email, justificado_em = now(),
                          justificado_versao = versao_dados, justificado_nivel = nivel, justificado_itens = itens_total
  where id = v.id;
  insert into public.aviso_evento (aviso_id, painel, tipo, usuario, detalhe, itens_total) values (v.id, v.painel, 'justificado', v_email, v_texto, v.itens_total);
  return jsonb_build_object('ok', true);
end;
$$;

-- "Ainda não resolvi": desfaz um fechamento (o aviso volta para a lista de abertos).
create or replace function public.reabrir_aviso(p_aviso bigint)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v     public.aviso%rowtype;
  v_email text;
begin
  if auth.uid() is null then
    raise exception 'Entre no site para reabrir um aviso.' using errcode = '42501';
  end if;
  select * into v from public.aviso where id = p_aviso for update;
  if not found or not public.can_view_painel(v.painel) then
    raise exception 'Aviso não encontrado.' using errcode = '42501';
  end if;
  if v.status <> 'justificado' then
    raise exception 'Só dá para reabrir um aviso fechado com justificativa.' using errcode = '55000';
  end if;
  select coalesce(p.email, '') into v_email from public.profiles p where p.id = auth.uid();
  update public.aviso set status = 'aberto' where id = v.id;
  insert into public.aviso_evento (aviso_id, painel, tipo, usuario, detalhe, itens_total)
  values (v.id, v.painel, 'reaberto', v_email, 'Reaberto à mão: o problema ainda não foi resolvido.', v.itens_total);
  return jsonb_build_object('ok', true);
end;
$$;

revoke execute on function public.fechar_aviso(bigint, text) from public, anon;
revoke execute on function public.reabrir_aviso(bigint)      from public, anon;
grant  execute on function public.fechar_aviso(bigint, text) to authenticated;
grant  execute on function public.reabrir_aviso(bigint)      to authenticated;
