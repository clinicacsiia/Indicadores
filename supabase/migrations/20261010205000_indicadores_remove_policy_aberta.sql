-- Remove a policy aberta (using true): como policies permissivas somam (OR),
-- ela anularia a restrição de "Vê Relatórios". Ainda NÃO aplicada no banco.
drop policy if exists "indicadores_select_authenticated" on public.indicadores;
