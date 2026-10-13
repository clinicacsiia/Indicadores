-- SEGURANÇA (LGPD): fact_relatorio_linha guarda as linhas dos relatórios do Klingo
-- como vieram (financeiro, glosas, identificação de paciente...). Com todos os
-- relatórios sendo sincronizados, deixar a leitura aberta a qualquer usuário logado
-- exporia tudo pela API. Nada no site lê esta tabela direto: quem lê é a Edge
-- Function (service_role) e metas_atendimentos_mes (SECURITY DEFINER, que confere
-- can_view_metas e devolve só contagens). Então a leitura direta fica só para admin.
drop policy if exists "fact_relatorio_linha_select_authenticated" on public.fact_relatorio_linha;

create policy "fact_relatorio_linha_select_admin"
  on public.fact_relatorio_linha
  for select
  to authenticated
  using (public.is_admin());

revoke all on public.fact_relatorio_linha from anon;
