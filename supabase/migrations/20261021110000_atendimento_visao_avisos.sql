-- Restrição por usuário no Atendimento (Configurações > "Atendimento: o que a pessoa vê").
--
-- profiles.permissions.atendimento_visao = id do responsável (Atendimento/responsaveis.json): a pessoa só vê o Atendimento daquela parte da clínica.
-- Quem entrega a página é o servidor Python (restricao.py), que tira da página os números do resto da clínica. Os avisos, porém, falam da clínica inteira
-- ("usuários com mais casos", "por setor"...) e vêm direto do banco: quem está restrito a uma parte do painel não pode lê-los, então can_view_painel
-- passa a dizer "não" quando existe <painel>_visao preenchido. Vale para qualquer painel que ganhe essa restrição.
-- can_view_painel também alimenta paineis_renovando(): a pessoa restrita deixa de ver o aviso "atualizando agora" desse painel na tela Início (só isso).
create or replace function public.can_view_painel(p_painel text)
returns boolean
language sql
security definer
set search_path = ''
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and (role = 'admin'
           or (coalesce(permissions -> p_painel = 'true'::jsonb, false)
               and coalesce(permissions ->> (p_painel || '_visao'), '') = ''))
  );
$$;
