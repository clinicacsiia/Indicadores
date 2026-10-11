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
- `lib/supabase/profile.ts` — lê o perfil (`profiles`) do usuário logado.
- `lib/supabase/middleware.ts` + `proxy.ts` — exige sessão válida em toda
  rota (exceto `/login`); redireciona para login quem não está autenticado.
- `app/login/` — tela de login (email/senha via Supabase Auth).
- `app/(app)/layout.tsx` — menu lateral (Relatórios / Configurações) das
  telas logadas; "Configurações" só aparece para quem tem `role = admin`.
- `app/(app)/page.tsx` — aba "Relatórios": filtro de período (padrão: últimos
  30 dias, com atalhos 7/30/90 dias e "Este ano"), totais do período e tabela
  por dia com os indicadores sincronizados.
- `app/(app)/atualizar-form.tsx` + `atualizar-actions.ts` — botão "Atualizar"
  (só admin): escolhe o relatório do catálogo `dim_relatorio` e o período.
  O relatório `13397` também atualiza os totais mostrados na tela.
- `app/(app)/configuracoes/` — aba "Configurações" (admin): define quem é
  admin e quem pode ver Relatórios. Protegida tanto na página quanto por RLS.
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
- **`dim_relatorio_coluna`** — dicionário de colunas por relatório (ver
  seção própria abaixo).
- **`etl_alertas`** / **`v_etl_pendencias`** — pendências para revisão humana
  (possíveis duplicatas, erros, mudança de layout). Ver "Duplicatas e erros".

A função `sync-relatorios-dw` varre os relatórios ativos (ou só os escolhidos
no botão "Atualizar", via `klingo_ids`, mesmo que inativos) e, pra cada um,
chama o Klingo um dia por vez (mesmo parâmetro `:periodo0` do
`sync-indicadores`), com 1 retry automático em falha transitória de rede.
Aceita o mesmo corpo `{"from":"AAAA-MM-DD","to":"AAAA-MM-DD"}`
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

### Duplicatas e erros: o sistema aponta, uma pessoa decide

Duplicata aparente nem sempre é duplicata: dois relatórios com o mesmo nome
(como "Faturas Emitidas", `#13149` e `#12756`) podem ser versão antiga/nova
ou um erro de cadastro no Klingo. Por isso **nada é desativado, escondido ou
apagado automaticamente**. Tudo que merece conferência vira um alerta em
`etl_alertas`, e o que está aberto aparece em `v_etl_pendencias` (mais grave
primeiro):

| Tipo | Quando aparece |
| --- | --- |
| `possivel_duplicata_nome` | dois relatórios com o mesmo nome (na hora do cadastro) |
| `possivel_duplicata_dados` | após o sync, ≥ 50% das linhas (mín. 3) de um relatório no dia já existem idênticas em outro relatório |
| `sync_erro` | falha ao buscar/gravar um relatório (já com 1 retry) |
| `coluna_nova` / `coluna_ausente` | o layout de um relatório já mapeado mudou |
| `linhas_repetidas` | linhas totalmente idênticas no mesmo relatório/dia |
| `linha_invalida` | o Klingo devolveu algo que não é uma linha de colunas |

Cada alerta repetido só soma `ocorrencias` em vez de criar outro. Para
encerrar um, registre o que foi decidido (um alerta resolvido ou ignorado não
reabre sozinho, exceto `sync_erro`, que pode voltar):

```sql
select * from public.v_etl_pendencias;

update public.etl_alertas
set status = 'resolvido',   -- ou 'em_analise' / 'ignorado'
    resolvido_em = now(),
    resolucao = 'duplicata real: #12756 descontinuado, manter só o #13149'
where id = '<id do alerta>';
```

Se a conferência concluir que um relatório realmente substitui outro, marque
`supersedido_por` à mão — é decisão humana, nunca preenchida pelo sistema, e a
Edge Function pula relatórios com ele preenchido:

```sql
update public.dim_relatorio
set ativo = false,
    supersedido_por = (select id from public.dim_relatorio where klingo_id = '<id-que-fica>')
where klingo_id = '<id-que-sai>';
```

Linhas idênticas dentro do mesmo relatório/dia ficam num registro só com a
contagem em `repeticoes`, então nada é subcontado. Excluir um relatório do
catálogo é barrado enquanto houver dados ou alertas ligados a ele.

Limites: a checagem de nome só pega nomes iguais (ignorando caixa/espaços), e a
de dados só pega linhas idênticas em todas as colunas — mesma informação em
colunas diferentes precisa de olho humano.

### Adicionando relatórios no futuro

Novos relatórios entram sempre pelo cadastro manual — o sistema **não
descobre IDs testando a API do Klingo**, e só consulta relatórios com
`ativo = true`, um por vez, com pausa entre as requisições.

1. Cadastre com `ativo = false` (insert da seção anterior). O cadastro já
   dispara a checagem de nome repetido; veja `v_etl_pendencias`.
2. Ative (`ativo = true`). No primeiro sync a função compara as linhas com as
   dos outros relatórios no mesmo dia e abre `possivel_duplicata_dados` se a
   informação já existir em outro lugar.
3. Revise os alertas antes de confiar nos dados: se for duplicata real,
   decida (e registre em `resolucao`); se for erro do relatório, o dado
   continua guardado para correção — nada é apagado.

Ative poucos relatórios por vez: a função consulta todos os ativos em
sequência numa única execução, e muitos de uma vez podem estourar o tempo
limite da Edge Function.

### Dicionário de colunas (`dim_relatorio_coluna`)

Os relatórios do Klingo vêm com colunas genéricas (`col1`, `col2`, ...) sem
nome — pra saber "em qual relatório está tal informação" é preciso mapear o
que cada coluna significa relatório por relatório. A cada sync,
`dim_relatorio_coluna` registra automaticamente quais `coluna_key` (col1,
col2...) apareceram em cada relatório e o tipo do valor observado (`string`,
`number`, `boolean`, etc.) — isso vai se completando sozinho conforme mais
relatórios são ativados, sem precisar mexer em código.

O campo `rotulo` (o que a coluna *significa* de fato, ex. "nome do
convênio") é só manual — a Edge Function nunca escreve nele, pra não chutar
errado. Depois de ativar um relatório, confira as colunas no painel do
Klingo (ícone de engrenagem ao lado do relatório) e preencha:

```sql
update public.dim_relatorio_coluna
set rotulo = 'nome do convênio'
where relatorio_id = (select id from public.dim_relatorio where klingo_id = '13222')
  and coluna_key = 'col3';
```

Pra achar em qual relatório está uma informação, depois de alguns
relatórios mapeados:

```sql
select r.klingo_id, r.nome, c.coluna_key, c.rotulo
from public.dim_relatorio_coluna c
join public.dim_relatorio r on r.id = c.relatorio_id
where c.rotulo ilike '%convênio%';
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
botão "Atualizar" (admin logado, site Next.js)
        │  JWT do admin
        ▼
Edge Function (sync-indicadores / sync-relatorios-dw) ← API externa (Klingo)
        │  service_role (só dentro da função)
        ▼
tabelas no Supabase  →  site Next.js (leitura, logado)
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
- **Permissões em tabela separada (`profiles`)**: nunca em código. Ao criar
  um usuário no Supabase Auth, um trigger cria automaticamente a linha
  correspondente em `profiles` com `role = 'viewer'`. Só quem já é
  `role = 'admin'` consegue promover outro usuário a admin ou mudar quem vê
  Relatórios — e isso é garantido por RLS (`is_admin()`), não só pela
  interface. Nenhuma senha é lida, mostrada ou guardada por essa tabela.
- **Sincronização manual (sem agendamento)**: não há mais atualização
  automática. Antes, o `pg_cron` do Supabase chamava as Edge Functions a cada
  hora (era a única origem dos disparos: o projeto não usa Vercel Cron nem
  GitHub Actions). Os jobs foram removidos
  (migration `20261011170000_remove_cron_sync_automatico.sql`). Agora um
  **admin** clica em **Atualizar** na aba Relatórios, escolhe o relatório e o
  período (máx. 31 dias) e o site chama as Edge Functions com o JWT do próprio
  admin. As funções aceitam apenas `service_role` (SQL/carga histórica) ou um
  usuário logado com `is_admin()`; a anon key pública recebe 403. Nenhuma
  chave privilegiada existe no site/Vercel. O secret `cron_service_role_key`
  do Vault continua disponível só para cargas históricas via SQL.

## Deploy (Vercel)

- Projeto Vercel `indicadores` (time `clinicacsiia-9662`), ligado a este
  repositório no GitHub. Cada push no branch de produção
  (`ccr-e828f159-nn6n8o`, o branch padrão do repositório) publica em
  produção; outros branches geram previews.
- URL pública: **https://indicadores-virid.vercel.app** (pede login do
  painel). As URLs de deployment/preview (`*-clinicacsiia-9662.vercel.app`)
  ficam atrás do *Vercel Authentication*, só para quem é do time na Vercel.
- Variáveis usadas pelo site: `NEXT_PUBLIC_SUPABASE_URL` e
  `NEXT_PUBLIC_SUPABASE_ANON_KEY` (produção e preview). As demais variáveis
  `POSTGRES_*`/`SUPABASE_*` foram criadas pela integração Supabase da Vercel e
  não são usadas pelo código.

### Pendências de configuração

- [x] Secret `KLINGO_APP_TOKEN` definido em *Edge Functions → Secrets*.
- [x] Usuário `csiadmin` criado direto no banco e promovido a admin (login
      pela tela inicial com usuário `csiadmin`; internamente vira o email
      `csiadmin@csi.local`). **Troque a senha após o primeiro acesso** e não
      a registre em código, commit ou chat. Novos usuários: crie em
      Authentication → Users (nascem `viewer`) e ajuste em "Configurações".
- [x] Policy aberta `using (true)` de `indicadores` neutralizada: agora exige
      `can_view_relatorios()`, então "Vê Relatórios" desmarcado bloqueia de
      fato no banco (migration `20261010212149_indicadores_restringe_policy_aberta.sql`).
- [x] Jobs do `pg_cron` usando a `service_role` key do Vault (os dois jobs).
- [x] Carga histórica de `indicadores` desde 01/01/2026.
- [ ] Ativar *Leaked password protection* em Authentication → Providers →
      Email (aviso do advisor de segurança). Só existe no painel do Supabase
      (não há API/SQL para isso) e depende do plano da organização.

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
31 dias por chamada), autenticado como `service_role`. Do SQL Editor, sem
copiar a chave para lugar nenhum:

```sql
select net.http_post(
  url := 'https://syhcvonwthtqalpjcmtj.supabase.co/functions/v1/sync-indicadores',
  headers := jsonb_build_object(
    'Content-Type', 'application/json',
    'Authorization', 'Bearer ' || (
      select decrypted_secret from vault.decrypted_secrets
      where name = 'cron_service_role_key'
    )
  ),
  body := '{"from":"2026-01-01","to":"2026-01-31"}'::jsonb,
  timeout_milliseconds := 150000
);
-- resultado: select * from net._http_response order by created desc limit 1;
```

Rode uma janela por vez: chamadas em paralelo esbarram no limite de
requisições do Klingo (HTTP 429). A função já espera e tenta de novo quando
recebe 429, e um dia com problema não impede os outros de serem gravados —
as falhas ficam em `sync_runs.error_message`, por dia. Dia sem nenhum
agendamento vem do Klingo como `result: ""` e é gravado com zeros.

### Observação sobre advisories

O advisor de segurança do Supabase aponta `pg_net` instalado no schema
`public` (nível WARN). Essa extensão não suporta `SET SCHEMA`, então esse
aviso é esperado em qualquer projeto que use `pg_cron` + `pg_net` para chamar
Edge Functions — não expõe dados nem credenciais, é só o mecanismo de rede.

Também aparece (WARN) que `is_admin()` e `can_view_relatorios()` são
`SECURITY DEFINER` executáveis por `authenticated`. É intencional: as policies
de RLS dependem delas, e elas só devolvem `true`/`false` sobre o próprio
usuário logado (`auth.uid()`), sem expor dado de ninguém. `anon` não executa.
