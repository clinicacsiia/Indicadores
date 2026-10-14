-- Roda depois que a Edge Function sync-relatorios-dw com o modo "auto" estiver publicada.
-- Agendamento: a cada 5 minutos a Edge Function pega um lote do que venceu (modo "auto"): o dia de
-- hoje de cada relatório vence a cada 5 horas, e o histórico novo é puxado aos poucos. Sem pendência
-- ela responde na hora, sem tocar no Klingo. A chave service_role vem do Vault.
-- cron.schedule com o mesmo nome apenas atualiza o job existente.
select cron.schedule(
  'coleta-relatorios-5min',
  '*/5 * * * *',
  $cmd$
    select net.http_post(
      url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-relatorios-dw',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer ' || (
          select decrypted_secret from vault.decrypted_secrets
          where name = 'cron_service_role_key'
        )
      ),
      body := '{"modo":"auto","limite":40}'::jsonb,
      timeout_milliseconds := 150000
    );
  $cmd$
);
