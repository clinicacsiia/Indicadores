-- Troca o "anti-duplicata automático" por revisão humana.
--
-- A migration anterior (20261010201738) fazia duas coisas por conta própria:
-- marcava o relatório #12756 como supersedido pelo #13149 e criava um índice
-- único que impedia dois relatórios com o mesmo nome de ficarem ativos. Mas
-- nome repetido no Klingo pode ser versão antiga/nova, ou pode ser erro de
-- cadastro — só uma pessoa conferindo sabe qual é qual. Então aqui:
--   * o bloqueio automático sai;
--   * o sistema passa a APONTAR o possível problema em `etl_alertas`
--     (consulta fácil em `v_etl_pendencias`), sem desativar, esconder nem
--     apagar nada;
--   * `supersedido_por` continua existindo, mas só vale se uma pessoa
--     preencher.
-- Os mesmos alertas cobrem qualquer relatório adicionado no futuro: nome
-- repetido (na hora do cadastro), dados repetidos entre relatórios (após o
-- primeiro sync), coluna nova/ausente, linhas repetidas e erros de sync.

-- 1) Remove o bloqueio automático e devolve o #12756 ao estado neutro.
drop index if exists public.dim_relatorio_nome_ativo_uq;

update public.dim_relatorio
set supersedido_por = null,
    observacoes = 'Mesmo nome do #13149 no painel, ID diferente — em revisão (ver v_etl_pendencias). Pode ser versão antiga ou erro de cadastro; conferir no Klingo antes de ativar.'
where klingo_id = '12756';

comment on column public.dim_relatorio.supersedido_por is 'Decisão HUMANA: aponta o relatório que substitui este. Nunca é preenchido automaticamente. Quando preenchido, a Edge Function pula este relatório mesmo que ativo=true.';

-- 2) Nada de apagar dados por tabela-mãe: excluir um relatório do catálogo
-- agora é barrado enquanto houver dados/alertas ligados a ele (antes o
-- cascade apagaria todas as linhas sincronizadas junto).
alter table public.fact_relatorio_linha
  drop constraint if exists fact_relatorio_linha_relatorio_id_fkey,
  add constraint fact_relatorio_linha_relatorio_id_fkey
    foreign key (relatorio_id) references public.dim_relatorio (id) on delete restrict;

alter table public.dim_relatorio_coluna
  drop constraint if exists dim_relatorio_coluna_relatorio_id_fkey,
  add constraint dim_relatorio_coluna_relatorio_id_fkey
    foreign key (relatorio_id) references public.dim_relatorio (id) on delete restrict;

-- 3) Linhas idênticas dentro do mesmo relatório/dia. Antes a unicidade por
-- hash colapsava linhas legitimamente iguais numa só (subcontando) — e um
-- upsert com duas linhas iguais no mesmo lote falharia o relatório inteiro.
-- Agora a linha é guardada uma vez com a contagem de repetições.
alter table public.fact_relatorio_linha
  add column if not exists repeticoes integer not null default 1 check (repeticoes >= 1);

comment on column public.fact_relatorio_linha.repeticoes is 'Quantas linhas idênticas o Klingo devolveu neste relatório/dia no último sync. >1 pode ser legítimo (itens iguais) ou erro do relatório — gera alerta linhas_repetidas para conferência.';

create index if not exists fact_relatorio_linha_periodo_hash_idx
  on public.fact_relatorio_linha (periodo, linha_hash);

-- 4) Alertas: tudo que merece olho humano fica registrado aqui, nunca é
-- corrigido sozinho. Status: aberto -> em_analise -> resolvido | ignorado.
create table if not exists public.etl_alertas (
  id uuid primary key default gen_random_uuid(),
  tipo text not null check (tipo in (
    'sync_erro',
    'possivel_duplicata_nome',
    'possivel_duplicata_dados',
    'coluna_nova',
    'coluna_ausente',
    'linha_invalida',
    'linhas_repetidas'
  )),
  severidade text not null check (severidade in ('erro', 'aviso', 'info')),
  status text not null default 'aberto' check (status in ('aberto', 'em_analise', 'resolvido', 'ignorado')),
  chave text not null,
  relatorio_id uuid references public.dim_relatorio (id) on delete restrict,
  relatorio_ref_id uuid references public.dim_relatorio (id) on delete restrict,
  periodo date,
  mensagem text not null,
  detalhes jsonb not null default '{}'::jsonb,
  ocorrencias integer not null default 1,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  resolvido_em timestamptz,
  resolucao text
);

comment on table public.etl_alertas is 'Pendências do ETL de relatórios para revisão humana (possíveis duplicatas, erros de sync, mudança de layout). O sistema só registra — nunca apaga, desativa nem corrige sozinho. Escrita via service_role; quem revisa muda status/resolucao pelo SQL Editor.';
comment on column public.etl_alertas.chave is 'Identifica o problema para não gerar o mesmo alerta toda hora: enquanto houver um alerta aberto/em_analise com a mesma chave, só incrementa ocorrencias.';
comment on column public.etl_alertas.resolucao is 'Anotação de quem revisou: o que foi decidido e por quê (ex.: "duplicata real, #12756 descontinuado" ou "erro de cadastro, manter os dois").';

create unique index if not exists etl_alertas_chave_aberta_uq
  on public.etl_alertas (chave)
  where status in ('aberto', 'em_analise');

create index if not exists etl_alertas_status_idx
  on public.etl_alertas (status, severidade, last_seen_at desc);

alter table public.etl_alertas enable row level security;

create policy "etl_alertas_select_authenticated"
  on public.etl_alertas
  for select
  to authenticated
  using (true);

-- 5) Registro de alerta com deduplicação por chave.
--   * já existe um aberto/em_analise: só soma ocorrência e atualiza o texto;
--   * já foi resolvido/ignorado: não reabre sozinho (a decisão humana vale),
--     exceto quando p_reabrir = true (usado em erro de sync, que pode voltar);
--   * não existe: cria.
create or replace function public.registrar_alerta(
  p_tipo text,
  p_severidade text,
  p_chave text,
  p_mensagem text,
  p_relatorio_id uuid default null,
  p_relatorio_ref_id uuid default null,
  p_periodo date default null,
  p_detalhes jsonb default '{}'::jsonb,
  p_reabrir boolean default false
)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
begin
  select a.status into v_status
  from public.etl_alertas a
  where a.chave = p_chave
  order by a.first_seen_at desc
  limit 1;

  if v_status in ('aberto', 'em_analise') then
    update public.etl_alertas
    set ocorrencias = ocorrencias + 1,
        last_seen_at = now(),
        mensagem = p_mensagem,
        detalhes = p_detalhes,
        periodo = coalesce(p_periodo, periodo)
    where chave = p_chave
      and status in ('aberto', 'em_analise');
  elsif v_status is null or p_reabrir then
    insert into public.etl_alertas
      (tipo, severidade, chave, mensagem, relatorio_id, relatorio_ref_id, periodo, detalhes)
    values
      (p_tipo, p_severidade, p_chave, p_mensagem, p_relatorio_id, p_relatorio_ref_id, p_periodo, p_detalhes)
    on conflict (chave) where status in ('aberto', 'em_analise') do nothing;
  end if;
end;
$$;

-- 6) Nome repetido: roda no cadastro (trigger) e pode ser chamado à mão.
-- Só compara nomes iguais (ignorando caixa e espaços); nomes parecidos mas
-- diferentes não são detectados.
create or replace function public.analisar_duplicata_nome(p_relatorio_id uuid)
returns integer
language plpgsql
set search_path = ''
as $$
declare
  r record;
  n integer := 0;
begin
  for r in
    select
      a.id as a_id, a.klingo_id as a_klingo, a.nome as a_nome,
      o.id as o_id, o.klingo_id as o_klingo
    from public.dim_relatorio a
    join public.dim_relatorio o
      on o.id <> a.id
     and lower(regexp_replace(btrim(o.nome), '\s+', ' ', 'g'))
       = lower(regexp_replace(btrim(a.nome), '\s+', ' ', 'g'))
    where a.id = p_relatorio_id
  loop
    perform public.registrar_alerta(
      'possivel_duplicata_nome',
      'aviso',
      'dup_nome:' || least(r.a_id::text, r.o_id::text) || ':' || greatest(r.a_id::text, r.o_id::text),
      format(
        'Dois relatórios com o mesmo nome "%s": #%s e #%s. Pode ser versão antiga/nova ou erro de cadastro — conferir no Klingo qual é o correto antes de decidir. Nada foi desativado nem apagado.',
        r.a_nome, r.a_klingo, r.o_klingo
      ),
      r.a_id,
      r.o_id,
      null,
      jsonb_build_object('klingo_ids', jsonb_build_array(r.a_klingo, r.o_klingo))
    );
    n := n + 1;
  end loop;
  return n;
end;
$$;

create or replace function public.dim_relatorio_analisar_nome()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  perform public.analisar_duplicata_nome(new.id);
  return new;
end;
$$;

create trigger dim_relatorio_analisa_nome
  after insert or update of nome on public.dim_relatorio
  for each row
  execute function public.dim_relatorio_analisar_nome();

-- 7) Dados repetidos entre relatórios: depois de sincronizar um relatório
-- num dia, compara as linhas dele (por hash do conteúdo) com as linhas de
-- TODOS os outros relatórios no mesmo dia. Se pelo menos metade das linhas
-- (e no mínimo 3) já existe idêntica em outro relatório, a informação
-- provavelmente já está lá — vira alerta, nada é apagado. Só pega linhas
-- idênticas em todas as colunas; sobreposição parcial (mesma informação em
-- colunas diferentes) precisa de olho humano.
create or replace function public.analisar_sobreposicao_dados(p_relatorio_id uuid, p_periodo date)
returns integer
language plpgsql
set search_path = ''
as $$
declare
  r record;
  n integer := 0;
  v_total integer;
  v_klingo text;
  v_nome text;
begin
  select count(*) into v_total
  from public.fact_relatorio_linha
  where relatorio_id = p_relatorio_id and periodo = p_periodo;

  if v_total = 0 then
    return 0;
  end if;

  select klingo_id, nome into v_klingo, v_nome
  from public.dim_relatorio where id = p_relatorio_id;

  for r in
    select f.relatorio_id as outro_id, d.klingo_id as outro_klingo, count(*) as iguais
    from public.fact_relatorio_linha m
    join public.fact_relatorio_linha f
      on f.periodo = m.periodo
     and f.linha_hash = m.linha_hash
     and f.relatorio_id <> m.relatorio_id
    join public.dim_relatorio d on d.id = f.relatorio_id
    where m.relatorio_id = p_relatorio_id
      and m.periodo = p_periodo
    group by f.relatorio_id, d.klingo_id
  loop
    if r.iguais >= 3 and r.iguais::numeric / v_total >= 0.5 then
      perform public.registrar_alerta(
        'possivel_duplicata_dados',
        'aviso',
        'dup_dados:' || least(p_relatorio_id::text, r.outro_id::text) || ':' || greatest(p_relatorio_id::text, r.outro_id::text),
        format(
          '%s de %s linhas do relatório #%s em %s já existem idênticas no relatório #%s — a mesma informação pode estar cadastrada duas vezes (ou um dos relatórios está errado). Conferir antes de decidir. Nada foi apagado.',
          r.iguais, v_total, v_klingo, p_periodo, r.outro_klingo
        ),
        p_relatorio_id,
        r.outro_id,
        p_periodo,
        jsonb_build_object(
          'periodo', p_periodo,
          'linhas_iguais', r.iguais,
          'linhas_total', v_total,
          'percentual', round(100.0 * r.iguais / v_total, 1)
        )
      );
      n := n + 1;
    end if;
  end loop;
  return n;
end;
$$;

-- Funções de manutenção: só a service_role (Edge Function) e o SQL Editor
-- executam. Sem isso, anon/authenticated poderiam chamá-las pela API REST.
revoke execute on function public.registrar_alerta(text, text, text, text, uuid, uuid, date, jsonb, boolean) from public, anon, authenticated;
revoke execute on function public.analisar_duplicata_nome(uuid) from public, anon, authenticated;
revoke execute on function public.analisar_sobreposicao_dados(uuid, date) from public, anon, authenticated;
revoke execute on function public.dim_relatorio_analisar_nome() from public, anon, authenticated;
grant execute on function public.registrar_alerta(text, text, text, text, uuid, uuid, date, jsonb, boolean) to service_role;
grant execute on function public.analisar_duplicata_nome(uuid) to service_role;
grant execute on function public.analisar_sobreposicao_dados(uuid, date) to service_role;

-- 8) Visão de pendências: o que está aberto, mais grave primeiro.
create or replace view public.v_etl_pendencias
with (security_invoker = true) as
select
  a.id,
  a.severidade,
  a.tipo,
  a.status,
  a.mensagem,
  r.klingo_id,
  r.nome as relatorio,
  rr.klingo_id as klingo_id_ref,
  rr.nome as relatorio_ref,
  a.periodo,
  a.ocorrencias,
  a.first_seen_at,
  a.last_seen_at,
  a.detalhes
from public.etl_alertas a
left join public.dim_relatorio r on r.id = a.relatorio_id
left join public.dim_relatorio rr on rr.id = a.relatorio_ref_id
where a.status in ('aberto', 'em_analise')
order by
  case a.severidade when 'erro' then 0 when 'aviso' then 1 else 2 end,
  a.last_seen_at desc;

comment on view public.v_etl_pendencias is 'Alertas do ETL ainda não resolvidos, mais graves primeiro. Para encerrar um: update public.etl_alertas set status = ''resolvido'' (ou ''ignorado''), resolvido_em = now(), resolucao = ''o que foi decidido'' where id = ''...'';';

-- 9) Varre o catálogo atual: pega o par "Faturas Emitidas" (#13149/#12756).
select public.analisar_duplicata_nome(id) from public.dim_relatorio;
