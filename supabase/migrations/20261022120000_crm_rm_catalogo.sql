-- Catálogo de exames e convênios da RM com o nome EXATO do Klingo, e os preços praticados.
--
-- Por que: a primeira versão da aba usava uma lista inventada ("Joelho", "Coluna lombar") e um
-- campo de convênio em texto livre. Nada daquilo cruzava com o Klingo, a atendente tinha de
-- adivinhar o preço e cada pessoa escrevia o convênio de um jeito. Agora as duas listas vêm do
-- que o Klingo já faturou (relatório 52): 63 exames e 22 convênios.
--
-- preparo, contraste, duração, exige_autorizacao e prazo são conteúdo CLÍNICO/ADMINISTRATIVO:
-- nascem vazios de propósito e a clínica preenche no Table Editor. A tela diz "não cadastrado"
-- em vez de inventar orientação de preparo.

create table if not exists public.crm_rm_exame (
  id            bigint generated always as identity primary key,
  nome          text not null unique,
  grupo         text not null,
  sedacao       boolean not null default false,
  contraste     text check (contraste is null or contraste in ('Não usa', 'Pode precisar', 'Sempre usa')),
  preparo       text check (preparo is null or char_length(preparo) <= 600),
  duracao_min   integer check (duracao_min is null or duracao_min between 5 and 240),
  observacao    text check (observacao is null or char_length(observacao) <= 600),
  ativo         boolean not null default true,
  visto_em      date,
  atendimentos  integer not null default 0
);

comment on table public.crm_rm_exame is 'Catálogo de exames de RM com o nome exato do Klingo. Semeado por crm_rm_semear_catalogo(); preparo, contraste e duração são preenchidos pela clínica.';

create table if not exists public.crm_rm_convenio (
  id                 bigint generated always as identity primary key,
  nome               text not null unique,
  tipo               text not null check (tipo in ('Particular', 'Convênio', 'SUS', 'Cetrus')),
  exige_autorizacao  boolean,
  prazo_autorizacao  integer check (prazo_autorizacao is null or prazo_autorizacao between 0 and 90),
  observacao         text check (observacao is null or char_length(observacao) <= 600),
  ativo              boolean not null default true,
  atendimentos       integer not null default 0
);

comment on table public.crm_rm_convenio is 'Convênios que o Klingo registra em RM, com o nome exato. Cetrus = antigo "SUS CURSO", como no resto do sistema.';

create index if not exists crm_rm_exame_grupo_idx on public.crm_rm_exame (grupo, nome);

-- Lê o que o Klingo faturou em RM e enche o catálogo. Não sobrescreve o que a clínica preencheu.
-- security definer: fact_relatorio_linha só é legível por admin.
create or replace function public.crm_rm_semear_catalogo(p_desde date default null)
returns table (exames_novos integer, convenios_novos integer)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_desde date := coalesce(p_desde, (now() at time zone 'America/Sao_Paulo')::date - 180);
  v_ex integer;
  v_cv integer;
begin
  create temp table _rm on commit drop as
  select f.linha->>'nome_procedimento' as nome, f.linha->>'operadora' as operadora, f.periodo
  from public.fact_relatorio_linha f
  join public.dim_relatorio r on r.id = f.relatorio_id
  where r.klingo_id = '52'
    and f.linha->>'Categoria' ilike '%RESSON%'
    and f.periodo >= v_desde
    and coalesce(f.linha->>'nome_procedimento', '') <> ''
    -- "PCTE ..." é pacote de autorização e "CONTRASTE ..." é cobrança à parte: não são exames
    and f.linha->>'nome_procedimento' !~* '^(PCTE|CONTRASTE)';

  with novos as (
    insert into public.crm_rm_exame (nome, grupo, sedacao, visto_em, atendimentos)
    select x.nome,
      case
        when x.nome ~* 'SEDA'                                                        then 'Com sedação'
        when x.nome ~* 'ANGIO'                                                       then 'Angiorressonância'
        when x.nome ~* 'MAMA'                                                        then 'Mama'
        when x.nome ~* 'CORAÇ|CORAC|AORTA|CINE-RM'                                   then 'Coração'
        when x.nome ~* 'COLUNA|LOMBO|CERVICAL|TOR[AÁ]CICA|DORSAL'                    then 'Coluna'
        when x.nome ~* 'CR[AÂ]NIO|ENC[EÉ]FALO|SELA|[OÓ]RBITA|TEMPORA|FACE|ATM|PESCO' then 'Crânio, face e pescoço'
        when x.nome ~* 'ABDOME|ABDOMEN|PELVE|PR[OÓ]STATA|P[EÉ]LVICOS|HIDRO|DEFECO|P[EÊ]NIS' then 'Abdome e pelve'
        when x.nome ~* 'ARTICUL|ARTRO|JOELHO|OMBRO|TORNOZELO|BACIA|SACRO|COXO|M[AÃ]O|PUNHO|P[EÉ] ' then 'Articulações'
        when x.nome ~* 'PERNA|COXA|MEMBRO|BRAQUIAL'                                  then 'Membros'
        else 'Outros'
      end,
      x.nome ~* 'SEDA', max(x.periodo), count(*)::integer
    from _rm x group by x.nome
    on conflict (nome) do update
      set visto_em = greatest(public.crm_rm_exame.visto_em, excluded.visto_em),
          atendimentos = excluded.atendimentos
    returning (xmax = 0) as inserido
  )
  select count(*) filter (where inserido) into v_ex from novos;

  with novos as (
    insert into public.crm_rm_convenio (nome, tipo, atendimentos)
    select x.operadora,
      case when x.operadora ilike 'Particular' then 'Particular'
           when x.operadora ilike 'SUS CURSO'  then 'Cetrus'
           when x.operadora ilike 'SUS'        then 'SUS'
           else 'Convênio' end,
      count(*)::integer
    from _rm x where coalesce(x.operadora, '') <> '' group by x.operadora
    on conflict (nome) do update set atendimentos = excluded.atendimentos
    returning (xmax = 0) as inserido
  )
  select count(*) filter (where inserido) into v_cv from novos;

  return query select v_ex, v_cv;
end;
$$;

revoke execute on function public.crm_rm_semear_catalogo(date) from public, anon, authenticated;

-- Preço que a clínica REALMENTE cobrou em cada exame: a atendente não adivinha mais.
-- (RM de crânio simples ficou entre R$ 420 e 490; sob sedação, entre R$ 2.150 e 2.350.)
create or replace function public.crm_rm_precos(p_meses integer default 6)
returns table (exame text, particular_min numeric, particular_max numeric, particular_mediana numeric,
               convenio_medio numeric, atendimentos integer)
language sql
security definer
set search_path = ''
stable
as $$
  select f.linha->>'nome_procedimento',
         min((f.linha->>'Valor')::numeric) filter (where f.linha->>'operadora' = 'Particular'),
         max((f.linha->>'Valor')::numeric) filter (where f.linha->>'operadora' = 'Particular'),
         percentile_cont(0.5) within group (order by (f.linha->>'Valor')::numeric)
           filter (where f.linha->>'operadora' = 'Particular'),
         round(avg((f.linha->>'Valor')::numeric) filter (where f.linha->>'operadora' <> 'Particular'), 2),
         count(*)::integer
  from public.fact_relatorio_linha f
  join public.dim_relatorio r on r.id = f.relatorio_id
  where r.klingo_id = '52'
    and f.linha->>'Categoria' ilike '%RESSON%'
    and f.periodo >= ((now() at time zone 'America/Sao_Paulo')::date - (greatest(coalesce(p_meses, 6), 1) * 30))
    and coalesce(f.linha->>'nome_procedimento', '') <> ''
    and (f.linha->>'Valor') ~ '^[0-9.]+$'
  group by 1;
$$;

revoke execute on function public.crm_rm_precos(integer) from public, anon;
grant execute on function public.crm_rm_precos(integer) to authenticated;

-- Quantas ressonâncias o Klingo faturou no período: mede a COBERTURA do CRM. Se a equipe registra
-- 20 de 300 exames, todo indicador desta aba fala de 7% da operação e não serve para decidir.
create or replace function public.crm_rm_realizados_klingo(p_de date, p_ate date)
returns integer
language sql
security definer
set search_path = ''
stable
as $$
  select count(*)::integer
  from public.fact_relatorio_linha f
  join public.dim_relatorio r on r.id = f.relatorio_id
  where r.klingo_id = '52'
    and f.linha->>'Categoria' ilike '%RESSON%'
    and f.periodo between p_de and p_ate
    and coalesce(f.linha->>'nome_procedimento', '') !~* '^(PCTE|CONTRASTE)';
$$;

revoke execute on function public.crm_rm_realizados_klingo(date, date) from public, anon;
grant execute on function public.crm_rm_realizados_klingo(date, date) to authenticated;

-- Quem preenche OU quem vê o CRM lê os catálogos; ninguém escreve pelo site.
alter table public.crm_rm_exame    enable row level security;
alter table public.crm_rm_convenio enable row level security;

create policy "crm_rm_exame_select" on public.crm_rm_exame for select to authenticated
  using (public.can_view_painel('crm_rm') or public.pode_preencher_crm_rm());
create policy "crm_rm_convenio_select" on public.crm_rm_convenio for select to authenticated
  using (public.can_view_painel('crm_rm') or public.pode_preencher_crm_rm());

revoke all on public.crm_rm_exame    from public, anon, authenticated;
revoke all on public.crm_rm_convenio from public, anon, authenticated;
grant select on public.crm_rm_exame, public.crm_rm_convenio to authenticated;
