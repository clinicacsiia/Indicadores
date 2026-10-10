-- A permissão "Vê Relatórios" precisa valer no banco, não só na interface.
create policy "indicadores_select_com_permissao"
  on public.indicadores
  for select
  to authenticated
  using (public.can_view_relatorios());
