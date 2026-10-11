-- A sincronização deixa de ser automática: quem atualiza é uma pessoa (admin), pelo botão
-- "Atualizar" na aba Relatórios, que escolhe o relatório e o período. Os dois jobs horários do
-- pg_cron (única origem dos disparos automáticos; não há Vercel Cron nem GitHub Actions) são
-- removidos. As Edge Functions e o secret cron_service_role_key do Vault continuam
-- existindo para cargas históricas via SQL com service_role (ver README).
select cron.unschedule(jobname)
from cron.job
where jobname in ('sync-indicadores-hourly', 'sync-relatorios-dw-hourly');
