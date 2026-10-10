-- A policy antiga "indicadores_select_authenticated" usava using (true), o que
-- (por policies permissivas somarem com OR) anulava a permissão "Vê Relatórios".
-- Em vez de removê-la, passa a exigir a mesma regra da policy nova.
alter policy "indicadores_select_authenticated"
  on public.indicadores
  using (public.can_view_relatorios());
