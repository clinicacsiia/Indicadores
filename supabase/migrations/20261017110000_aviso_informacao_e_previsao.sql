-- Aba "Avisos": justificativa que vira INFORMAÇÃO, data prevista e recorrência só quando a justificativa não vale.
--
-- Antes: um aviso fechado com justificativa reabria sozinho se, depois de os dados serem atualizados, o problema continuasse; e um aviso resolvido que
-- voltava reabria como "voltou a acontecer", mesmo já tendo sido explicado. Agora:
--   * a pessoa pode informar uma DATA PREVISTA ao justificar (ex.: "o envio da Petrobras é dia 20/10"). Até essa data o aviso fica como informação,
--     mesmo com os dados atualizados; passou a data e o problema continua -> reabre ("prazo_vencido") e conta como recorrência;
--   * aviso resolvido que VOLTA a aparecer e já tinha uma justificativa que valia -> fica como informação (status "justificado", `em_informacao`) com a
--     justificativa dada, e só reabre se piorar; não conta como recorrência (conta em `retornos_informados`);
--   * a recorrência (`reaberturas`) passa a contar também quando a pessoa diz "Ainda não resolvi" ou "Não explica o problema": aí a justificativa
--     deixa de valer (`justificativa_vale = false`) e o aviso volta a ser tratado como qualquer outro;
--   * continua valendo: justificado À MÃO, sem data e sem ser "persistente", reabre se os dados forem atualizados e o problema continuar; justificado com
--     data, persistente ou mantido como informação só reabre se piorar (nível mais grave ou 25% mais registros).
-- Eventos novos no histórico: 'informado' (voltou e ficou como informação), 'prazo_vencido' (a data prevista passou) e 'atualizacao' (o painel mudou por
-- causa do aviso).

alter table public.aviso add column if not exists previsto_para        date;                                   -- data informada na justificativa (envio, correção...)
alter table public.aviso add column if not exists justificativa_vale   boolean not null default false;        -- a justificativa ainda vale se o problema voltar
alter table public.aviso add column if not exists retornos_informados  integer not null default 0 check (retornos_informados >= 0);   -- voltou e ficou como informação
alter table public.aviso add column if not exists em_informacao        boolean not null default false;        -- voltou e foi mantido como informação (só reabre se piorar)

comment on column public.aviso.previsto_para is 'Data prevista informada ao justificar: até ela o aviso fica como informação; passou e o problema continua, reabre.';
comment on column public.aviso.justificativa_vale is 'Verdadeiro enquanto a justificativa explica o problema: se o aviso for resolvido e voltar, volta como informação. "Ainda não resolvi", "Não explica", prazo vencido ou piora desligam.';
comment on column public.aviso.em_informacao is 'Verdadeiro quando o aviso voltou depois de resolvido e foi mantido como informação por já ter justificativa: continua assim até piorar, ser resolvido ou reaberto.';
comment on column public.aviso.retornos_informados is 'Quantas vezes o problema voltou depois de resolvido e foi mantido como informação por já ter justificativa (não conta como recorrência).';

-- o que já estava justificado ou resolvido com justificativa segue valendo
update public.aviso set justificativa_vale = true where justificativa is not null and status in ('justificado', 'resolvido') and not justificativa_vale;

alter table public.aviso_evento drop constraint if exists aviso_evento_tipo_check;
alter table public.aviso_evento add constraint aviso_evento_tipo_check
  check (tipo in ('detectado', 'sumiu', 'justificado', 'confirmado', 'reapareceu', 'nao_corrigido', 'piorou', 'reaberto', 'informado', 'prazo_vencido', 'atualizacao'));

-- ---------------------------------------------------------------- fechar (agora com a data prevista) e reabrir (agora conta recorrência)
drop function if exists public.fechar_aviso(bigint, text);
create or replace function public.fechar_aviso(p_aviso bigint, p_justificativa text, p_previsto date default null)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v     public.aviso%rowtype;
  v_texto text := btrim(coalesce(p_justificativa, ''));
  v_email text;
  v_hoje  date := (now() at time zone 'America/Sao_Paulo')::date;
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
  if p_previsto is not null and (p_previsto < v_hoje or p_previsto > v_hoje + 365) then
    raise exception 'A data prevista precisa ser de hoje até um ano à frente.' using errcode = '22023';
  end if;

  select * into v from public.aviso where id = p_aviso for update;
  if not found or not public.can_view_aviso(v.painel, v.sensivel) then
    raise exception 'Aviso não encontrado.' using errcode = '42501';
  end if;
  if v.status <> 'aberto' then
    raise exception 'Este aviso já não está aberto.' using errcode = '55000';
  end if;

  select coalesce(p.email, '') into v_email from public.profiles p where p.id = auth.uid();
  update public.aviso set status = 'justificado', justificativa = v_texto, justificado_por = v_email, justificado_em = now(),
                          justificado_versao = versao_dados, justificado_nivel = nivel, justificado_itens = itens_total,
                          previsto_para = p_previsto, justificativa_vale = true, em_informacao = false
  where id = v.id;
  insert into public.aviso_evento (aviso_id, painel, tipo, usuario, detalhe, itens_total)
  values (v.id, v.painel, 'justificado', v_email,
          v_texto || case when p_previsto is not null then E'\nPrevisão: ' || to_char(p_previsto, 'DD/MM/YYYY') || '.' else '' end, v.itens_total);
  return jsonb_build_object('ok', true);
end;
$$;

-- "Ainda não resolvi" (p_motivo = 'nao_resolvi') e "Não explica o problema" ('nao_explicou'): desfazem o fechamento e CONTAM como recorrência.
drop function if exists public.reabrir_aviso(bigint);
create or replace function public.reabrir_aviso(p_aviso bigint, p_motivo text default 'nao_resolvi')
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
  if p_motivo not in ('nao_resolvi', 'nao_explicou') then
    raise exception 'Motivo inválido.' using errcode = '22023';
  end if;
  select * into v from public.aviso where id = p_aviso for update;
  if not found or not public.can_view_aviso(v.painel, v.sensivel) then
    raise exception 'Aviso não encontrado.' using errcode = '42501';
  end if;
  if v.status <> 'justificado' then
    raise exception 'Só dá para reabrir um aviso fechado com justificativa.' using errcode = '55000';
  end if;
  select coalesce(p.email, '') into v_email from public.profiles p where p.id = auth.uid();
  update public.aviso set status = 'aberto', reaberturas = reaberturas + 1, ultima_recorrencia = now(), previsto_para = null, justificativa_vale = false, em_informacao = false
  where id = v.id;
  insert into public.aviso_evento (aviso_id, painel, tipo, usuario, detalhe, itens_total)
  values (v.id, v.painel, 'reaberto', v_email,
          case p_motivo when 'nao_explicou' then 'Reaberto à mão: a justificativa não explica o problema. Conta como recorrência.'
                        else 'Reaberto à mão: o problema ainda não foi resolvido. Conta como recorrência.' end, v.itens_total);
  return jsonb_build_object('ok', true);
end;
$$;

revoke execute on function public.fechar_aviso(bigint, text, date) from public, anon;
revoke execute on function public.reabrir_aviso(bigint, text)      from public, anon;
grant  execute on function public.fechar_aviso(bigint, text, date) to authenticated;
grant  execute on function public.reabrir_aviso(bigint, text)      to authenticated;

-- ---------------------------------------------------------------- sincronização
-- Igual à versão anterior (20261016120000_dados_financeiros.sql), com: data prevista, "voltou e já tinha justificativa -> informação" e o prazo vencido.
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
  v_hoje   date := (now() at time zone 'America/Sao_Paulo')::date;
  chaves   text[] := '{}';
  v_nivel  text;
  v_total  integer;
  v_persiste boolean;
  v_sensivel boolean;
  st       text;
  ev       text;
  det      text;
  n_novos integer := 0; n_voltaram integer := 0; n_reabertos integer := 0; n_resolvidos integer := 0; n_pioraram integer := 0; n_informados integer := 0;
  aumento  integer;
begin
  if coalesce(p_painel, '') = '' then
    raise exception 'Falta o painel.';
  end if;
  if p_alertas is null or jsonb_typeof(p_alertas) <> 'array' then
    raise exception 'A lista de alertas precisa ser um array.';
  end if;
  perform pg_advisory_xact_lock(hashtext('aviso_sincronizar:' || p_painel));

  for a in select x from jsonb_array_elements(p_alertas) x loop
    chaves   := chaves || (a ->> 'chave');
    v_nivel  := case when a ->> 'nivel' in ('critico', 'atencao', 'info') then a ->> 'nivel' else 'info' end;
    v_total  := (a ->> 'itens_total')::integer;
    v_persiste := coalesce((a ->> 'persistente')::boolean, false);
    v_sensivel := coalesce((a ->> 'sensivel')::boolean, false);

    select * into v from public.aviso where painel = p_painel and chave = a ->> 'chave' for update;

    if not found then
      insert into public.aviso (painel, chave, tipo, escopo, titulo, texto, nivel, persistente, sensivel, guia, itens, itens_total,
                                primeira_deteccao, ultima_deteccao, ultima_conferencia, versao_dados)
      values (p_painel, a ->> 'chave', coalesce(a ->> 'tipo', ''), coalesce(a ->> 'escopo', ''), a ->> 'titulo', coalesce(a ->> 'texto', ''),
              v_nivel, v_persiste, v_sensivel, coalesce(a -> 'guia', '{}'::jsonb), case when jsonb_typeof(a -> 'itens') = 'object' then a -> 'itens' end, v_total,
              agora, agora, agora, coalesce(p_versao, 0))
      returning * into v;
      insert into public.aviso_evento (aviso_id, painel, quando, tipo, detalhe, itens_total)
      values (v.id, p_painel, agora, 'detectado', 'Apareceu nos dados pela primeira vez.', v_total);
      n_novos := n_novos + 1;
      continue;
    end if;

    st := v.status; ev := null; det := null;

    if v.status = 'resolvido' then
      if v.justificativa_vale and v.justificativa is not null then
        -- já foi explicado e a explicação vale: volta como informação, sem contar recorrência
        st := 'justificado'; ev := 'informado';
        det := 'Estava resolvido desde ' || to_char(v.resolvido_em at time zone 'America/Sao_Paulo', 'DD/MM/YYYY') || ' e voltou a aparecer nos dados. '
               || 'Como já havia justificativa, fica como informação: “' || v.justificativa || '”. '
               || 'Se isso não explica o que aconteceu, use “Ainda não resolvi” ou “Não explica o problema”.';
        n_informados := n_informados + 1;
      else
        st := 'aberto'; ev := 'reapareceu';
        det := 'Estava resolvido desde ' || to_char(v.resolvido_em at time zone 'America/Sao_Paulo', 'DD/MM/YYYY') || ' e voltou a aparecer nos dados.';
        n_voltaram := n_voltaram + 1;
      end if;
    elsif v.status = 'justificado' then
      if v.previsto_para is not null and v.previsto_para < v_hoje then
        -- a data informada passou e o problema continua
        st := 'aberto'; ev := 'prazo_vencido';
        det := 'A data prevista (' || to_char(v.previsto_para, 'DD/MM/YYYY') || ') passou e o problema continua aparecendo nos dados.';
        n_reabertos := n_reabertos + 1;
      elsif v_persiste or v.previsto_para is not null or v.em_informacao then
        -- aceito, dentro da data informada ou mantido como informação: só reabre se piorar (nível mais grave, ou 25% mais registros — e ao menos 1 a mais)
        aumento := case when v.justificado_itens is null then null else greatest(1, ceil(v.justificado_itens * 0.25)::integer) end;
        if public.aviso_peso_nivel(v_nivel) > public.aviso_peso_nivel(coalesce(v.justificado_nivel, v_nivel)) then
          st := 'aberto'; ev := 'piorou';
          det := 'O problema justificado ficou mais grave (de ' || coalesce(v.justificado_nivel, '?') || ' para ' || v_nivel || ').';
        elsif v_total is not null and aumento is not null and v_total >= v.justificado_itens + aumento then
          st := 'aberto'; ev := 'piorou';
          det := 'O problema justificado piorou: de ' || v.justificado_itens || ' para ' || v_total || ' registros.';
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
      titulo = a ->> 'titulo', texto = coalesce(a ->> 'texto', ''), nivel = v_nivel, persistente = v_persiste, sensivel = v_sensivel,
      guia = coalesce(a -> 'guia', '{}'::jsonb),
      itens = case when jsonb_typeof(a -> 'itens') = 'object' then a -> 'itens' end,
      itens_total = v_total,
      status = st,
      resolvido_em = case when st = 'resolvido' then resolvido_em else null end,
      recorrencias = recorrencias + case when ev = 'reapareceu' then 1 else 0 end,
      reaberturas  = reaberturas  + case when ev in ('nao_corrigido', 'piorou', 'prazo_vencido') then 1 else 0 end,
      retornos_informados = retornos_informados + case when ev = 'informado' then 1 else 0 end,
      ultima_recorrencia = case when ev is not null and ev <> 'informado' then agora else ultima_recorrencia end,
      -- voltou como informação: a comparação do "piorou" recomeça deste ponto
      justificado_versao = case when ev = 'informado' then coalesce(p_versao, 0) else justificado_versao end,
      justificado_nivel  = case when ev = 'informado' then v_nivel else justificado_nivel end,
      justificado_itens  = case when ev = 'informado' then v_total else justificado_itens end,
      -- reabriu por piorar, prazo vencido ou por continuar: a justificativa deixa de valer e a data de antes também
      justificativa_vale = case when st = 'aberto' and v.status = 'justificado' then false else justificativa_vale end,
      em_informacao = case when ev = 'informado' then true when st = 'justificado' then em_informacao else false end,
      previsto_para = case when st = 'justificado' then previsto_para else null end,
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
    update public.aviso set status = 'resolvido', resolvido_em = agora, previsto_para = null, em_informacao = false, ultima_conferencia = agora, versao_dados = greatest(versao_dados, coalesce(p_versao, 0))
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
                            'informados', n_informados, 'total', jsonb_array_length(p_alertas));
end;
$$;

-- ---------------------------------------------------------------- o aviso de "Faturas esperando envio" justificado em 14/10/2026
-- A justificativa dizia que o envio da Petrobras é dia 20/10/2026: a data vira a data prevista (e o aviso fica como informação até lá). O painel de
-- Faturamento também mudou nesse dia: o SUS passou a ter prazo próprio (45 dias) e uma análise mês a mês. Só mexe no aviso que bate com isso, uma vez.
with alvo as (
  update public.aviso set previsto_para = date '2026-10-20'
  where painel = 'faturamento' and tipo = 'fat_espera_envio' and status = 'justificado' and previsto_para is null
    and justificativa like '%20/10/2026%'
  returning id, painel, itens_total
)
insert into public.aviso_evento (aviso_id, painel, tipo, detalhe, itens_total)
select id, painel, 'atualizacao',
       'Painel atualizado em 14/10/2026: o SUS passou a ter prazo próprio de 45 dias (em vez de 7) e uma análise mês a mês; a data de envio informada na justificativa '
       || '(20/10/2026) foi registrada como data prevista: o aviso fica como informação até lá e reabre se o problema continuar depois.', itens_total
from alvo;
