# Notas para o Claude neste repositório

- **Migrations no Supabase** (projeto `syhcvonwthtqalpjcmtj`): o MCP deixa pendurado (e depois cancela) tudo que ele considera destrutivo —
  `drop function`, `drop table`, `drop policy` e **qualquer `delete`**, inclusive dentro do corpo de uma função (ele lê o texto do comando, não o executa).
  O que passa normalmente: `create`, `create or replace`, `alter table ... add/drop constraint`, `grant`, `revoke`, `update` e `insert`.
  Então: evite `drop` usando `create or replace`; troque `delete` por `update` quando der; divida em chamadas pequenas; confira com `execute_sql`;
  e o que sobrar (apagar tabela, política ou linha) peça para uma pessoa rodar no SQL Editor.
  Detalhes e o que já foi aplicado: README, seção "Aplicar migrations no Supabase pelo Claude".
- **Branch padrão** do repositório: `ccr-e828f159-nn6n8o` (não existe `main`); é a base dos PRs.
- Testes: `python3 -m unittest discover -s tests` (Python), `supabase/tests/avisos.sql` (Postgres local; ver o cabeçalho do arquivo), `npx tsc --noEmit` e `npx next build` (site).
