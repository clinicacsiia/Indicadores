-- Jornada do paciente, etapa 4: tempo real (o quadro e o chat de cada cartão se atualizam sozinhos), nome de quem escreve e lista da equipe para atribuir.
--
-- Como funciona: gatilhos nas tabelas mandam um AVISO CURTO pelo Realtime do Supabase (realtime.send, canal privado) e o navegador lê de novo só o que mudou, pelas
-- mesmas regras de acesso de sempre. O aviso nunca carrega texto de mensagem nem dado de paciente: só o número do cartão.
--   canal  jornada:quadro          evento "card"      {card_id}   um cartão mudou (coluna, responsável, exames, mensagens)
--   canal  jornada:card:<id>       evento "mensagem"  {id}        chegou uma mensagem no chat daquele cartão
-- Só entra no canal quem tem a permissão da Jornada (política em realtime.messages). Se o Realtime não existir ou falhar, a gravação segue normalmente (o navegador
-- ainda se atualiza sozinho a cada 30 s).
-- Só create, alter table add column, grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

alter table public.jornada_mensagem add column if not exists autor_nome text;

-- "ana@csi.local" -> "ana"
create or replace function public.jornada_nome_de(p_id uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(nullif(trim(p.nome), ''), regexp_replace(coalesce(p.email, ''), '@csi\.local$', ''), 'Equipe')
  from public.profiles p where p.id = p_id;
$$;
revoke execute on function public.jornada_nome_de(uuid) from public, anon, authenticated;
grant  execute on function public.jornada_nome_de(uuid) to service_role;

-- Quem pode receber um cartão: administradores e quem tem a permissão da Jornada.
create or replace function public.jornada_equipe()
returns table (id uuid, nome text)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null or not public.can_view_painel('jornada') then
    raise exception 'Sem permissão para a Jornada.';
  end if;
  return query
    select p.id, public.jornada_nome_de(p.id)
    from public.profiles p
    where p.status = 'ativo' and (p.role = 'admin' or coalesce(p.permissions -> 'jornada' = 'true'::jsonb, false))
    order by 2;
end;
$$;
revoke execute on function public.jornada_equipe() from public, anon;
grant  execute on function public.jornada_equipe() to authenticated;

-- A mensagem passa a guardar o nome de quem escreveu (o navegador não lê os perfis dos outros).
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
  insert into public.jornada_mensagem (card_id, canal, autor, autor_nome, autor_tipo, texto)
  values (p_card, 'interno', auth.uid(), public.jornada_nome_de(auth.uid()), 'equipe', v_texto)
  returning id into v_id;
  return v_id;
end;
$$;

-- ---------------------------------------------------------------- avisos em tempo real
create or replace function public.jornada_transmitir()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_card bigint;
begin
  if to_regprocedure('realtime.send(jsonb,text,text,boolean)') is null then
    return null;
  end if;
  if tg_table_name = 'jornada_card' then
    v_card := new.id;
  else
    v_card := new.card_id;
  end if;
  perform realtime.send(jsonb_build_object('card_id', v_card), 'card', 'jornada:quadro', true);
  if tg_table_name = 'jornada_mensagem' then
    perform realtime.send(jsonb_build_object('id', new.id), 'mensagem', 'jornada:card:' || v_card, true);
  end if;
  return null;
exception when others then
  raise warning 'jornada_transmitir: %', sqlerrm;
  return null;
end;
$$;
revoke execute on function public.jornada_transmitir() from public, anon, authenticated;

create or replace trigger jornada_card_transmite_novo     after insert on public.jornada_card     for each row execute function public.jornada_transmitir();
create or replace trigger jornada_card_transmite_muda     after update on public.jornada_card     for each row when (old.* is distinct from new.*) execute function public.jornada_transmitir();
create or replace trigger jornada_exame_transmite_novo    after insert on public.jornada_exame    for each row execute function public.jornada_transmitir();
create or replace trigger jornada_exame_transmite_muda    after update on public.jornada_exame    for each row when (old.* is distinct from new.*) execute function public.jornada_transmitir();
create or replace trigger jornada_mensagem_transmite_novo after insert on public.jornada_mensagem for each row execute function public.jornada_transmitir();

-- ---------------------------------------------------------------- quem entra nos canais
-- Receber avisos do Realtime exige uma política de leitura em realtime.messages. Só os canais "jornada:" e só com a permissão da Jornada.
do $$
begin
  if to_regclass('realtime.messages') is not null
     and not exists (select 1 from pg_policies where schemaname = 'realtime' and tablename = 'messages' and policyname = 'jornada_canais_leitura') then
    execute $p$
      create policy "jornada_canais_leitura" on realtime.messages for select to authenticated
      using (realtime.topic() like 'jornada:%' and public.can_view_painel('jornada'))
    $p$;
  end if;
end $$;

-- Pendências desta etapa (aparecem na aba Avisos pela jornada_pendencias_sincronizar, todo dia às 06:00).
insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('liberar_equipe_jornada', 4,
   'Liberar a Jornada para a equipe em Configurações',
   'O quadro já permite mover cartões, atribuir responsável e conversar. Hoje só os administradores o veem: ninguém mais tem a permissão "Jornada". Quem tem a permissão vê TODOS os pacientes do quadro e todas as conversas.',
   'atencao',
   '["Em Configurações > Usuários, marque \"Jornada do paciente\" para recepção, call center, laudos e faturamento.", "Antes, confirme com o jurídico/encarregado de dados quem pode ver o nome e o telefone de todos os pacientes (o acesso a cada cartão fica registrado)."]'::jsonb),
  ('regra_uso_chat', 4,
   'Combinar com a equipe como usar a conversa dos cartões',
   'A conversa de cada cartão é interna e fica ligada ao nome do paciente. Mensagens não podem ser editadas nem apagadas por quem escreve. Sem regra clara, a equipe pode escrever diagnóstico, resultado de exame ou assunto pessoal.',
   'info',
   '["Defina o que pode e o que não pode ser escrito (a tela já avisa: sem diagnóstico nem resultado de exame).", "Defina por quanto tempo as conversas ficam guardadas (junto da decisão do jurídico sobre prontuário) e quem pode pedir para corrigir uma mensagem."]'::jsonb),
  ('limites_tempo_real', 4,
   'Conferir os limites do tempo real no plano do Supabase',
   'O tempo real usa uma conexão aberta por pessoa com o quadro aberto, mais uma por conversa aberta. O plano gratuito limita as conexões simultâneas e as mensagens por segundo. Se o limite estourar, o quadro continua funcionando, mas passa a se atualizar só a cada 30 s (o indicador "tempo real" da tela apaga).',
   'info',
   '["Veja o limite do seu plano em Supabase > Project Settings > Realtime e compare com quantas pessoas vão abrir o quadro ao mesmo tempo.", "Se o indicador \"tempo real\" apagar com frequência, avise: dá para reduzir o que é transmitido ou subir de plano."]'::jsonb)
on conflict (chave) do nothing;

insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('conferir_tempo_real', 4,
   'Conferir se o tempo real está funcionando (abrir a aba Jornada)',
   'O banco avisa o navegador pelo Realtime do Supabase, mas em 01/11/2026 a tabela realtime.messages não tinha nenhuma partição (o serviço as cria quando alguém se conecta). Enquanto isso, o aviso é descartado em silêncio e a tela só se atualiza a cada 30 s. Não deu para testar a conexão de dentro do ambiente de desenvolvimento.',
   'atencao',
   '["Abra a aba Jornada em dois navegadores (ou com duas pessoas), mova um cartão num deles e veja se aparece no outro na hora. O texto no alto do quadro deve mostrar \"● tempo real\" (verde).", "Se continuar \"○ atualiza a cada 30 s\" depois de uns minutos, avise: provavelmente falta criar as partições de realtime.messages ou liberar o Realtime do projeto."]'::jsonb)
on conflict (chave) do nothing;
