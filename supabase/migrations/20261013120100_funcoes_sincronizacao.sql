-- Funcoes atomicas usadas pelo motor de sincronizacao (src/klingo/motor.ts). Todas so para o servidor (service role).

-- fundador: so um primeiro administrador pode ser criado pela tela de login (indice unico parcial protege de corrida)
alter table public.perfis add column fundador boolean not null default false;
create unique index perfis_fundador_uq on public.perfis ((fundador)) where fundador;

-- trava unica de atualizacao, com prazo (nunca fica presa). Devolve {ok, modulo, usuario, inicio, expira_em} de quem a detem.
create or replace function public.adquirir_trava(p_modulo text, p_usuario text, p_minutos int default 15) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r public.atualizacao_trava;
begin
  update public.atualizacao_trava
     set em_andamento = true, modulo = p_modulo, usuario = p_usuario, inicio = now(), expira_em = now() + make_interval(mins => p_minutos)
   where id = 1 and (not em_andamento or expira_em is null or expira_em < now())
  returning * into r;
  if found then
    return jsonb_build_object('ok', true, 'modulo', r.modulo, 'usuario', r.usuario, 'inicio', r.inicio, 'expira_em', r.expira_em);
  end if;
  select * into r from public.atualizacao_trava where id = 1;
  return jsonb_build_object('ok', false, 'modulo', r.modulo, 'usuario', r.usuario, 'inicio', r.inicio, 'expira_em', r.expira_em);
end $$;

create or replace function public.estender_trava(p_minutos int default 5) returns void
language sql security definer set search_path = public as $$
  update public.atualizacao_trava set expira_em = now() + make_interval(mins => p_minutos) where id = 1 and em_andamento;
$$;

create or replace function public.liberar_trava() returns void
language sql security definer set search_path = public as $$
  update public.atualizacao_trava set em_andamento = false, modulo = null, usuario = null, inicio = null, expira_em = null where id = 1;
$$;

-- proximo item da fila (um por vez, sem duas execucoes simultaneas do mesmo item); devolve a linha reservada ou nada
create or replace function public.reservar_item_fila() returns public.fila_sincronizacao
language plpgsql security definer set search_path = public as $$
declare it public.fila_sincronizacao;
begin
  -- item que ficou "executando" ha mais de 5 min (funcao interrompida) volta para a fila
  update public.fila_sincronizacao
     set estado = 'pendente', tentativas = tentativas + 1
   where estado = 'executando' and iniciado_em < now() - interval '5 minutes' and tentativas < 3;
  update public.fila_sincronizacao
     set estado = 'erro', erro = coalesce(erro, 'interrompido (tempo esgotado)'), finalizado_em = now()
   where estado = 'executando' and iniciado_em < now() - interval '5 minutes' and tentativas >= 3;
  select * into it from public.fila_sincronizacao where estado = 'pendente' order by id limit 1 for update skip locked;
  if not found then return null; end if;
  update public.fila_sincronizacao set estado = 'executando', iniciado_em = now() where id = it.id returning * into it;
  return it;
end $$;

-- grava (ou substitui) o bloco de uma aba/mes em UMA transacao; com p_apagar_outros, apaga os demais meses da aba (relatorio sem filtro de data)
create or replace function public.gravar_bloco(p_menu text, p_aba text, p_mes text, p_colunas jsonb, p_linhas int, p_conteudo text, p_apagar_outros boolean default false) returns void
language plpgsql security definer set search_path = public as $$
begin
  insert into public.dados_blocos (menu, aba, mes, colunas, linhas, conteudo, atualizado_em)
  values (p_menu, p_aba, p_mes, p_colunas, p_linhas, p_conteudo, now())
  on conflict (menu, aba, mes) do update
    set colunas = excluded.colunas, linhas = excluded.linhas, conteudo = excluded.conteudo, atualizado_em = now();
  if p_apagar_outros then
    delete from public.dados_blocos where menu = p_menu and aba = p_aba and mes <> p_mes;
  end if;
end $$;

-- poda do historico em 5.000 linhas
create or replace function public.podar_historico() returns void
language sql security definer set search_path = public as $$
  delete from public.historico_atualizacoes where id in (select id from public.historico_atualizacoes order by id desc offset 5000);
$$;

-- so um processador da fila por vez (pg_cron a cada minuto + auto-encadeamento podem se sobrepor)
create table public.fila_lease (id int primary key default 1 check (id = 1), ate timestamptz);
insert into public.fila_lease (id, ate) values (1, null);
alter table public.fila_lease enable row level security;

create or replace function public.pegar_lease(p_segundos int) returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.fila_lease set ate = now() + make_interval(secs => p_segundos) where id = 1 and (ate is null or ate < now());
  return found;
end $$;
create or replace function public.soltar_lease() returns void language sql security definer set search_path = public as $$
  update public.fila_lease set ate = null where id = 1;
$$;

revoke all on function public.pegar_lease(int), public.soltar_lease() from public, anon, authenticated;
revoke all on function public.adquirir_trava(text, text, int), public.estender_trava(int), public.liberar_trava(),
  public.reservar_item_fila(), public.gravar_bloco(text, text, text, jsonb, int, text, boolean), public.podar_historico()
  from public, anon, authenticated;
