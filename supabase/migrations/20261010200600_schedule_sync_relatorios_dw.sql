-- Chama a Edge Function sync-relatorios-dw a cada hora, mesmo padrão do job
-- sync-indicadores-hourly: a anon key aqui só serve pra passar o verify_jwt
-- da função; a função em si só aceita chamadas autenticadas como
-- service_role (ver isServiceRoleCaller no código) e retorna 403 pra
-- qualquer outra coisa. Por isso este job também fica "quebrado" até a
-- troca pra service_role via Vault ser feita no SQL Editor — mesma pendência
-- documentada no README para o job original.
select cron.schedule(
  'sync-relatorios-dw-hourly',
  '0 * * * *',
  $$
  select net.http_post(
    url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-relatorios-dw',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InN5aGN2b253dGh0cWFscGpjbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE2NTQ0NTgsImV4cCI6MjEwNzIzMDQ1OH0.mmFZrgWPBm4Qf4bs572em9uyQrGDlItEndL_U0CY_GE'
    ),
    body := '{}'::jsonb
  );
  $$
);
