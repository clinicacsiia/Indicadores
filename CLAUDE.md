# Notas para o Claude neste repositório

- **Migrations no Supabase** (projeto `syhcvonwthtqalpjcmtj`): o `apply_migration` cancela sozinho (`cancelled`) quando a chamada tem `drop function`.
  Divida em chamadas pequenas, deixe o `drop` sozinho (ou evite-o com `create or replace`), confira com `execute_sql` e use o SQL Editor para o que não passar.
  Detalhes e o que já foi aplicado: README, seção "Aplicar migrations no Supabase pelo Claude".
- **Branch padrão** do repositório: `ccr-e828f159-nn6n8o` (não existe `main`); é a base dos PRs.
- Testes: `python3 -m unittest discover -s tests` (Python), `supabase/tests/avisos.sql` (Postgres local; ver o cabeçalho do arquivo), `npx tsc --noEmit` e `npx next build` (site).
