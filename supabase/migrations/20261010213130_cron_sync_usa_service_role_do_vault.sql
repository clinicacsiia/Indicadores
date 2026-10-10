-- Os dois jobs chamam Edge Functions que só aceitam service_role. A chave fica
-- criptografada no Vault (secret cron_service_role_key, criado no painel) e é
-- lida na hora da chamada; nunca aparece em texto puro na definição do job.
select cron.alter_job(
  (select jobid from cron.job where jobname = 'sync-indicadores-hourly'),
  command := $cmd$
    select net.http_post(
      url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-indicadores',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer ' || (
          select decrypted_secret from vault.decrypted_secrets
          where name = 'cron_service_role_key'
        )
      ),
      body := '{}'::jsonb
    );
  $cmd$
);

select cron.alter_job(
  (select jobid from cron.job where jobname = 'sync-relatorios-dw-hourly'),
  command := $cmd$
    select net.http_post(
      url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-relatorios-dw',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer ' || (
          select decrypted_secret from vault.decrypted_secrets
          where name = 'cron_service_role_key'
        )
      ),
      body := '{}'::jsonb
    );
  $cmd$
);
