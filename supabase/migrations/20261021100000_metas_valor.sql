-- Aba Configurações > Metas: o admin muda a meta de um serviço a partir de um mês, e ela vale também nos meses seguintes até a próxima mudança.
-- Sem linha aqui, vale a meta do "Acompanhamento de META/metas.json". Chave do serviço: "grupo/item" (ex.: csi1/densitometria).
create table if not exists public.metas_valor (
  servico      text not null,
  a_partir_de  date not null check (a_partir_de = date_trunc('month', a_partir_de)::date),
  meta         integer not null check (meta >= 0),
  alterado_por uuid default auth.uid(),
  alterado_em  timestamptz not null default now(),
  primary key (servico, a_partir_de)
);

comment on table public.metas_valor is 'Mudanças de meta feitas em Configurações: valem do mês a_partir_de em diante, até a próxima mudança do mesmo serviço. Sem linha, vale o metas.json.';

alter table public.metas_valor enable row level security;

revoke all on public.metas_valor from public, anon;
grant select, insert, update, delete on public.metas_valor to authenticated;
grant all on public.metas_valor to service_role;

-- Quem pode ver Metas lê; só admin altera.
create policy "metas_valor_select" on public.metas_valor for select to authenticated using (public.can_view_metas());
create policy "metas_valor_insert" on public.metas_valor for insert to authenticated with check (public.is_admin());
create policy "metas_valor_update" on public.metas_valor for update to authenticated using (public.is_admin()) with check (public.is_admin());
create policy "metas_valor_delete" on public.metas_valor for delete to authenticated using (public.is_admin());
