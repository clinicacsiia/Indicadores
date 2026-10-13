# Operação: o que só você pode fazer e como manter

## 0. Antes de tudo: o app antigo
O repositório ainda tem o app antigo (pastas `app/`, `lib/`, `proxy.ts`, `next.config.js` e `supabase/functions/`). Ele **precisa ser apagado**
para o site novo (que usa `src/`) compilar; o novo `next.config.ts` já existe ao lado. Comando (os arquivos continuam no histórico do Git):

```
git rm -r app lib proxy.ts next.config.js supabase/functions
```
Os arquivos de `supabase/migrations/2026101*.sql` ficam (são o histórico já aplicado no banco); a migração nova remove as tabelas antigas.

## 1. Supabase (região São Paulo)
1. Projeto atual: `Indicadores` (`syhcvonwthtqalpjcmtj`). Anote **URL**, **anon key** e **service role key** (esta nunca vai ao navegador).
2. Aplicar as migrações: `supabase link --project-ref syhcvonwthtqalpjcmtj` e `supabase db push`
   (ou cole os dois arquivos `supabase/migrations/20261013*.sql` no SQL Editor, na ordem). **Isso apaga** as tabelas do app antigo
   (`profiles`, `indicadores`, `dim_relatorio`, `fact_relatorio_linha`…); se houver algo nelas que valha guardar, exporte antes.
3. Extensões **pg_cron** e **pg_net** (Database → Extensions).
4. Authentication → Providers → Email: **desligar "Allow new users to sign up"** (só o servidor cria usuários) e, se quiser, ativar CAPTCHA.
5. Backups: ligar o backup do projeto (plano Pro) **ou** agendar `pg_dump` por GitHub Actions para um bucket privado.
   Restauração: `supabase db reset` em um projeto novo + `psql < dump.sql` (ou "Restore" no painel do Supabase).
6. Depois do primeiro deploy, agendar a verificação automática **uma vez** (SQL Editor):
   `select public.agendar_sincronizacao('https://SEU-SITE.vercel.app', 'O-MESMO-VALOR-DO-CRON_SECRET');`
   (cria os jobs `csi-verificar`, a cada 30 min, e `csi-processar-fila`, a cada minuto; o segredo fica no Vault).

## 2. Vercel
1. Importar o repositório (projeto `indicadores`); framework Next.js; **sem** "Root Directory".
2. Variáveis de ambiente (Production e Preview): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, `KLINGO_APP_TOKEN`, `CRON_SECRET` (gere com `openssl rand -hex 32`). Nunca com prefixo `NEXT_PUBLIC_` os três últimos.
3. Plano: confirmar o limite de tempo das funções (`vercel.json` pede 300 s para o cálculo Python; o plano gratuito pode limitar a menos —
   nesse caso a primeira abertura de um período novo pode falhar; o cache e o pré-aquecimento ajudam). O cron é do Supabase (a Vercel gratuita só tem cron diário).
4. Se o projeto tiver "Vercel Authentication" nos previews, defina `VERCEL_AUTOMATION_BYPASS_SECRET` para a função Python ser chamada.
5. Domínio: Settings → Domains.

## 3. Klingo
Peça ao suporte um **token novo** (o atual circulou em texto puro) e cadastre só na Vercel (`KLINGO_APP_TOKEN`). Se o painel avisar
"O Klingo recusou o token", troque a variável e faça um novo deploy/redeploy.

## 4. Primeiro acesso e usuários
Abra `/login`: com o banco vazio aparece "Primeiro acesso": o primeiro usuário vira administrador e **define a própria senha** (não há senha padrão).
Depois, em **Conta**, crie/aprove os demais (hoje: `csi admin` e `Ludmila`). Pedidos de cadastro aparecem em "Pedidos de cadastro".

## 5. Carregar a história (uma vez)
Com os `.xlsx` de `Dados do Indicadores CSI\` numa pasta **fora do Git**:
```
npm ci
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... npx tsx scripts/importar_planilhas.ts "C:\caminho\Dados do Indicadores CSI" --simular   # só conta
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... npx tsx scripts/importar_planilhas.ts "C:\caminho\Dados do Indicadores CSI"
```
Depois use "Atualizar agora" para refazer os meses recentes.

## 6. Dia a dia
- **Conta → Histórico/Auditoria:** quem atualizou, erros por relatório/mês, quem entrou/errou senha, quem mexeu em usuários e pendências.
- **Conta → Conferir números:** cruza os relatórios (hoje só as conferências cruzadas; ver `PREMISSAS.md`).
- **Conta → Custos dos itens:** custo por unidade do estoque (Suprimentos); vale depois de "Atualizar agora".
- Ajustes (`intervalo_minimo_minutos`, etc.): tabela `configuracoes`.
- Desenvolvimento: `cp .env.example .env.local`, `npm ci`, `npm run dev`; Python: `pip install -r requirements.txt`.
  Testes: `npm test`, `npm run lint`, `python -m unittest discover -s tests/python -v`, RLS: `supabase start && supabase db reset && psql ... -f tests/rls/rls.sql`.

## 7. Checklist de entrada em produção
- [ ] App antigo removido (seção 0) e CI verde na `main`; branch `main` protegida (PR obrigatório, CI verde); secret scanning e push protection ligados.
- [ ] Migrações aplicadas; sign-ups desligados; pg_cron/pg_net ligados; `agendar_sincronizacao` executado; backups ligados.
- [ ] Variáveis na Vercel; token novo do Klingo; domínio ligado; primeiro admin criado.
- [ ] Importação das planilhas feita; "Atualizar agora" ok; histórico sem erro.
- [ ] **Aceite numérico assinado por você** (receita produzida, faturado, recebido, saldo, despesas do mês, atendimentos, espera mediana, metas % por unidade) igual ao programa atual no mesmo mês.
- [ ] Verificação visual lado a lado em 390 px e 1280 px, claro e escuro. Revisão dos textos do guia dos alertas (`painel_py/guia_regras.py`).
- [ ] Enviar os arquivos do legado que faltam (`PREMISSAS.md` §1) para trocar as reconstruções pelos originais.
