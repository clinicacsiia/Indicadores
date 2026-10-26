-- Apaga do banco tudo o que era do CRM Ressonância (a aba saiu do site).
-- Rodar à mão no SQL Editor do Supabase: o MCP não executa `drop`/`delete` (ver CLAUDE.md).
-- Não mexe em fact_relatorio_linha nem no cadastro do relatório #13825, que a coleta continua usando.

drop function if exists public.crm_rm_agenda_klingo(date, date);
drop function if exists public.crm_rm_agenda_atualizada_em();
drop function if exists public.crm_rm_realizados_klingo(date, date);
drop function if exists public.crm_rm_precos(integer);
drop function if exists public.crm_rm_semear_catalogo(date);

drop table if exists public.crm_rm_agenda;
drop table if exists public.crm_rm_contato;
drop table if exists public.crm_rm_convenio;
drop table if exists public.crm_rm_exame;

drop function if exists public.crm_rm_toca_atualizado();
drop function if exists public.pode_preencher_crm_rm();

-- Tira as permissões antigas dos perfis.
update public.profiles set permissions = permissions - 'crm_rm' - 'crm_rm_preencher'
 where permissions ?| array['crm_rm', 'crm_rm_preencher'];
