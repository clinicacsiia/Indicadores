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
- `supabase/functions/sync-relatorios-dw/` — Edge Function genérica que
  sincroniza qualquer relatório cadastrado em `dim_relatorio` (ver seção
  "Data warehouse de relatórios" abaixo).

## Data warehouse de relatórios

Além do `sync-indicadores` original (que só lê o relatório `13397` e grava 4
agregados por dia em `indicadores`), existe uma segunda camada pensada pra
cobrir **qualquer** relatório do Klingo sem precisar de código novo a cada
relatório:

- **`dim_relatorio`** — catálogo dos relatórios do Klingo. Cada linha tem o
  `klingo_id`, nome, categoria e uma flag `ativo`. Só relatórios com
  `ativo = true` são sincronizados.
- **`fact_relatorio_linha`** — uma linha por linha de relatório efetivamente
  observada, guardada como veio do Klingo (`jsonb`), deduplicada por
  `linha_hash` (sha256 do conteúdo). Reexecutar o sync pro mesmo
  relatório/dia é idempotente: linha igual não cria registro novo (só
  atualiza `last_seen_at`); linha que mudou de conteúdo cria um registro novo
  com hash novo. **Nada é apagado** — o histórico funciona como uma
  slowly-changing-dimension, não como uma foto única sobrescrita a cada sync.
- **`sync_relatorio_runs`** — auditoria por relatório/dia. Um relatório
  falhando (ex.: não aceita o parâmetro de período padrão) não derruba os
  outros.

A função `sync-relatorios-dw` varre os relatórios ativos e, pra cada um,
chama o Klingo um dia por vez (mesmo parâmetro `:periodo0` do
`sync-indicadores`). Aceita o mesmo corpo `{"from":"AAAA-MM-DD","to":"AAAA-MM-DD"}`
pra carga histórica (máx. 31 dias por chamada), autenticado como
`service_role`.

### Catálogo inicial e como ativar mais relatórios

O painel do Klingo desta clínica lista **101 relatórios** ao todo. A
migration `20261010200526_create_relatorios_dw_schema.sql` cadastrou os
**50** identificados até agora (capturados em 10/10/2026), todos **inativos**
por padrão — exceto o `13397`, já validado. Ficam inativos porque nem todo
relatório necessariamente aceita o mesmo parâmetro de período por dia
(`:periodo0-from`/`:periodo0-to`); alguns (ex.: `Arquivos #12712`,
`Verificação de ID #13437`) podem ser cadastros pontuais sem filtro de data.

Para ativar um relatório depois de confirmar que ele funciona com esse
parâmetro:

```sql
update public.dim_relatorio set ativo = true where klingo_id = '13222';
```

Para cadastrar um relatório que ainda não está no catálogo:

```sql
insert into public.dim_relatorio (klingo_id, nome, categoria, ativo)
values ('<id-no-klingo>', '<nome>', '<categoria>', false);
```

### ATENÇÃO LGPD

Diferente de `indicadores` (que só guarda agregados sem identificar
paciente), `fact_relatorio_linha` grava a linha do relatório como o Klingo
devolveu — vários relatórios desta clínica trazem dado identificável (nome
de paciente, CPF, etc., dependendo do relatório). O `select` continua restrito
a `authenticated`, mas isso foi uma decisão consciente: antes de ativar um
relatório sensível ou de expor esses dados a mais gente além do painel
atual, avalie RLS adicional ou mascaramento.

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

      O job `sync-relatorios-dw-hourly` (data warehouse de relatórios) tem o
      mesmo problema e usa o mesmo secret do Vault — depois de criar o
      `cron_service_role_key` acima, rode também:

      ```sql
      select cron.alter_job(
        (select jobid from cron.job where jobname = 'sync-relatorios-dw-hourly'),
        command := $$
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
