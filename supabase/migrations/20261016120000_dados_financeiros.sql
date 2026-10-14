-- "Dados financeiros": permissão para ver receitas, despesas e valores em R$ (Configurações > Dados sensíveis).
--
-- Fica em profiles.permissions.dados_financeiros (a chave não pode ser "financeiro": as chaves de painel são os ids dos painéis, e já existe um com esse id).
-- Administrador sempre vê. Quem não tem:
--   * não abre os painéis só de dinheiro (modulos.json: "financeiro": "total" — Faturamento, Financeiro, Despesas, Indicadores);
--   * recebe os painéis mistos (Atendimento, Cesta, Suprimentos) sem os valores em R$ (feito pelo servidor Python, sigilo.py);
--   * não vê, na aba Avisos, os avisos que falam de dinheiro (esta migration). A regra de antes continua valendo por cima: o aviso só aparece
--     se o painel dele estiver liberado para a pessoa (can_view_painel).

-- ---------------------------------------------------------------- permissão
create or replace function public.can_view_financeiro()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin' or coalesce(permissions -> 'dados_financeiros' = 'true'::jsonb, false))
  );
$$;

revoke execute on function public.can_view_financeiro() from public, anon;
grant  execute on function public.can_view_financeiro() to authenticated;

-- Quem já via Faturamento, Financeiro, Despesas ou Indicadores (painéis com dinheiro por inteiro) continua vendo: começa com a permissão marcada.
-- Os demais começam sem. Só mexe em quem ainda não tem a chave (rodar de novo não desfaz uma escolha feita em Configurações).
update public.profiles
   set permissions = permissions || '{"dados_financeiros": true}'::jsonb
 where role <> 'admin'
   and not (permissions ? 'dados_financeiros')
   and (   coalesce(permissions -> 'faturamento' = 'true'::jsonb, false)
        or coalesce(permissions -> 'financeiro'  = 'true'::jsonb, false)
        or coalesce(permissions -> 'despesas'    = 'true'::jsonb, false)
        or coalesce(permissions -> 'indicadores' = 'true'::jsonb, false));

-- Porta dos fundos: a tabela `indicadores` (valores em R$ dos indicadores) é lida direto pela API do Supabase com can_view_relatorios(), sem passar pelo
-- servidor dos painéis. Sem "Dados financeiros" a leitura direta também deixa de valer (o site de hoje não usa essa tabela; é só para não ficar um caminho aberto).
create or replace function public.can_view_relatorios()
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and status = 'ativo'
      and (role = 'admin'
           or (coalesce((permissions ->> 'relatorios')::boolean, true)
               and coalesce(permissions -> 'dados_financeiros' = 'true'::jsonb, false)))
  );
$$;

-- ---------------------------------------------------------------- avisos
-- `sensivel`: o aviso fala de dinheiro (ou é de um painel só de dinheiro). Quem decide é o servidor Python (guia_pendencias.sensivel) a cada
-- sincronização; o valor abaixo só cobre os avisos que já existiam até a próxima vez que cada painel for refeito.
alter table public.aviso add column if not exists sensivel boolean not null default false;

update public.aviso
   set sensivel = true
 where not sensivel
   and tipo <> 'ate_valor_zero'   -- problema de cadastro (quantos registros estão com valor zerado): não mostra dinheiro
   and (   painel in ('faturamento', 'financeiro', 'despesas', 'indicadores')
        or tipo in ('cesta_menor_fat', 'cesta_ticket_queda', 'cesta_valor_zero', 'sup_valor_concentrado', 'sup_sem_custo')
        or (titulo || ' ' || texto) ~* '(R\$|receita|ticket|faturament|glosa|(?<!centro de )custo|pre[cç]o|despesa|compras?\y|pagamento|reais\y)');

create or replace function public.can_view_aviso(p_painel text, p_sensivel boolean)
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select public.can_view_painel(p_painel) and (not coalesce(p_sensivel, false) or public.can_view_financeiro());
$$;

-- o histórico (aviso_evento) segue o aviso a que pertence
create or replace function public.can_view_aviso_id(p_aviso bigint)
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (select 1 from public.aviso a where a.id = p_aviso and public.can_view_aviso(a.painel, a.sensivel));
$$;

revoke execute on function public.can_view_aviso(text, boolean), public.can_view_aviso_id(bigint) from public, anon;
grant  execute on function public.can_view_aviso(text, boolean), public.can_view_aviso_id(bigint) to authenticated;

drop policy if exists "aviso_select_com_permissao" on public.aviso;
create policy "aviso_select_com_permissao"
  on public.aviso for select to authenticated
  using (public.can_view_aviso(painel, sensivel));

drop policy if exists "aviso_evento_select_com_permissao" on public.aviso_evento;
create policy "aviso_evento_select_com_permissao"
  on public.aviso_evento for select to authenticated
  using (public.can_view_aviso_id(aviso_id));

-- Fechar e reabrir à mão também respeitam: quem não vê o aviso não consegue mexer nele.
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
  if not found or not public.can_view_aviso(v.painel, v.sensivel) then
    raise exception 'Aviso não encontrado.' using errcode = '42501';
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
  if not found or not public.can_view_aviso(v.painel, v.sensivel) then
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

-- A sincronização (servidor Python, service_role) passa a gravar `sensivel` junto de cada aviso.
-- Igual à versão anterior, só com a coluna nova no insert e no update.
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
  v_sensivel boolean;
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
      st := 'aberto'; ev := 'reapareceu';
      det := 'Estava resolvido desde ' || to_char(v.resolvido_em at time zone 'America/Sao_Paulo', 'DD/MM/YYYY') || ' e voltou a aparecer nos dados.';
      n_voltaram := n_voltaram + 1;
    elsif v.status = 'justificado' then
      if v_persiste then
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
      reaberturas  = reaberturas  + case when ev in ('nao_corrigido', 'piorou') then 1 else 0 end,
      ultima_recorrencia = case when ev is not null then agora else ultima_recorrencia end,
      ultima_deteccao = agora, ultima_conferencia = agora, versao_dados = greatest(versao_dados, coalesce(p_versao, 0))
    where public.aviso.id = v.id;

    if ev is not null then
      insert into public.aviso_evento (aviso_id, painel, quando, tipo, detalhe, itens_total) values (v.id, p_painel, agora, ev, det, v_total);
    end if;
  end loop;

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

-- aviso_sincronizar só o servidor (service_role) chama; fechar/reabrir são do usuário logado. Os grants de antes continuam (create or replace não os troca).
