create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Chama a Edge Function sync-indicadores a cada hora.
-- O header usa a anon key (pública, a mesma usada no front-end) só para
-- satisfazer o verify_jwt da função; a credencial da API externa nunca
-- passa por aqui, fica isolada nos secrets da Edge Function.
select cron.schedule(
  'sync-indicadores-hourly',
  '0 * * * *',
  $$
  select net.http_post(
    url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-indicadores',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InN5aGN2b253dGh0cWFscGpjbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE2NTQ0NTgsImV4cCI6MjEwNzIzMDQ1OH0.mmFZrgWPBm4Qf4bs572em9uyQrGDlItEndL_U0CY_GE'
    ),
    body := '{}'::jsonb
  );
  $$
);
