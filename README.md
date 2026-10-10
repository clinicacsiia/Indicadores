# Indicadores

App Next.js conectado a um projeto Supabase dedicado. Painel de indicadores
sincronizados de uma API externa, com acesso restrito a usuários autenticados.

## Supabase

- Projeto: `Indicadores` (organização clinicacsiIA)
- Região: `sa-east-1`
- URL: `https://syhcvonwthtqalpjcmtj.supabase.co`

## Configuração local

1. Copie `.env.local.example` para `.env.local`.
2. Instale as dependências: `npm install`.
3. Rode o servidor de desenvolvimento: `npm run dev`.

## Estrutura

- `lib/supabase/client.ts` — client Supabase para uso no browser.
- `lib/supabase/server.ts` — client Supabase para Server Components e rotas.
- `lib/supabase/middleware.ts` + `middleware.ts` — exige sessão válida em toda
  rota (exceto `/login`); redireciona para login quem não está autenticado.
- `app/login/` — tela de login (email/senha via Supabase Auth).
- `app/page.tsx` — lista os indicadores sincronizados (só acessível logado).
- `supabase/functions/sync-indicadores/` — Edge Function que busca a API
  externa e grava os dados no banco.

## Arquitetura de segurança

O site **nunca** fala diretamente com a API externa. O fluxo é:

```
API externa → Edge Function (sync-indicadores) → tabela indicadores (Supabase)
                                                        ↑
                                              site Next.js (só leitura, logado)
```

Pontos chave:

- **Credencial da API externa** (`KLINGO_APP_TOKEN`) vive
  só nos *secrets* da Edge Function, no painel do Supabase. Nunca entra no
  repositório, no `.env.local` do site, nem em nenhuma variável `NEXT_PUBLIC_*`.
- **RLS habilitado** em `indicadores` e `sync_runs` desde a migration que as
  criou. Só existe policy de `select` para o papel `authenticated` — não há
  policy de insert/update/delete para `authenticated` nem `anon`, então o
  navegador nunca consegue escrever nessas tabelas. Só a Edge Function (via
  `service_role`, que ignora RLS) grava os dados.
- **Login obrigatório**: o `middleware.ts` bloqueia qualquer rota exceto
  `/login` para quem não tem sessão. Isso é reforçado pelo RLS (defesa em
  profundidade): mesmo que o middleware tivesse um bug, o banco ainda nega o
  acesso.
- **Sem cadastro público**: não existe página de signup. Os usuários devem
  ser criados pelo painel do Supabase (Authentication → Users) ou via SQL,
  pensado para um painel interno.
- **Sincronização automática**: `pg_cron` chama a Edge Function a cada hora
  (job `sync-indicadores-hourly`), autenticando a chamada com a chave pública
  (anon key) — ela só serve para passar a verificação de JWT da função, não
  dá acesso a nada sensível. A Edge Function usa a `service_role` key
  (injetada automaticamente pelo runtime, nunca manual) para gravar no banco.

### Pendências de configuração (precisam ser feitas no painel do Supabase)

- [ ] Definir o secret `KLINGO_APP_TOKEN` (token `X-APP-TOKEN` do Klingo) em
      *Edge Functions → Secrets*. Nunca commitar nem colar em chat/issue.
- [ ] Criar os usuários que terão acesso ao painel (Authentication → Users).
- [ ] **Trocar a chave usada pelo `pg_cron` de anon key para `service_role`.**
      A função `sync-indicadores` agora só aceita chamadas autenticadas como
      `service_role` (ver `isServiceRoleCaller` no código) — qualquer outra
      chamada recebe 403. Isso impede que a anon key pública (que vai estar
      no bundle do site) seja usada para disparar o sync manualmente. O job
      de cron ainda está configurado com a anon key (só serve pra passar o
      `verify_jwt` da plataforma) e vai receber 403 até isso ser corrigido.
      Rode isto você mesmo no **SQL Editor do Supabase** (a chave nunca deve
      passar pelo chat, por um commit ou por mim): cole a `service_role key`
      de *Project Settings → API* no lugar indicado.

      ```sql
      -- Guarda a service_role key de forma criptografada no Vault, em vez de
      -- deixá-la em texto puro na definição do job do pg_cron.
      select vault.create_secret('<cole aqui a service_role key>', 'cron_service_role_key');

      select cron.alter_job(
        (select jobid from cron.job where jobname = 'sync-indicadores-hourly'),
        command := $$
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
        $$
      );
      ```

### Fonte de dados (Klingo)

A função consulta o relatório `13397` ("AGENDADOS X REALIZADOS") do Klingo,
um dia por vez (`:periodo0=l` com `from = to = dia`), e grava **somente
agregados** por dia em `indicadores`: `agendamentos_total`,
`atendimentos_finalizados`, `atendimentos_avulsos` e
`valor_total_procedimentos`. O relatório vem por paciente, mas nome de
paciente e demais dados linha-a-linha são descartados na função (minimização
de dados / LGPD) e nunca chegam ao banco.

Por padrão sincroniza o dia atual (fuso America/Sao_Paulo). Para carga
histórica, chame a função com `{"from":"AAAA-MM-DD","to":"AAAA-MM-DD"}` (máx.
31 dias por chamada), autenticado como `service_role`.

### Observação sobre advisories

O advisor de segurança do Supabase aponta `pg_net` instalado no schema
`public` (nível WARN). Essa extensão não suporta `SET SCHEMA`, então esse
aviso é esperado em qualquer projeto que use `pg_cron` + `pg_net` para chamar
Edge Functions — não expõe dados nem credenciais, é só o mecanismo de rede.
