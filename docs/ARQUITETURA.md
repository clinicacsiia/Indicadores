# Arquitetura

```
Navegador ──HTTPS──► Vercel (Next.js, App Router)
                       ├─ proxy.ts ............ exige sessão em tudo (menos /login, /estado, /sair, /api/cron/*, /api/py/*)
                       ├─ /login, /painel/[menu] (shell + iframe), /conta, /exportar
                       ├─ /api/painel/[menu] ... checa sessão+permissão e chama o cálculo em Python
                       ├─ /api/atualizar, /api/estado, /api/pendencias/*, /api/periodos, /api/exportar-pdf
                       ├─ /api/cron/verificar, /api/cron/processar   (segredo CRON_SECRET)
                       └─ api/py/painel.py (Função Python, pandas) ── lê dados_blocos ─► monta a página HTML ─► cache (painel_cache)
Supabase ◄── Postgres (dados + configuração, RLS em tudo) · Auth · Realtime (dados_versao) · pg_cron+pg_net (chama /api/cron/*)
Klingo   ◄── API externa de relatórios (só o servidor fala com ela, com KLINGO_APP_TOKEN)
```

## Fluxo de uma atualização
1. "Atualizar agora" (ou o `pg_cron`) → `adquirir_trava` (uma atualização por vez, com prazo) → `enfileirarAtualizacao` cria `fila_sincronizacao`
   (um item por relatório × mês, mais um item "aquecer" por painel afetado).
2. `processarFila` (um processador por vez, `pegar_lease`) pega um item, baixa **sequencialmente** (pausa de 0,8 s: a cota é 1.000 pedidos/janela;
   um ciclo faz ~70), valida a resposta (`validar.ts`), converte tipos (`transformar.ts`) e grava o bloco numa transação (`gravar_bloco`).
3. Ao acabar os itens de baixar de um lote: histórico por menu, `subir_versao` (muda a chave do cache e o Realtime avisa os painéis abertos),
   depois os itens "aquecer" recalculam o cache. A trava é liberada no fim. A função se reencadeia até esvaziar a fila; o `pg_cron` retoma a cada minuto.
4. Erros: token recusado e queda de rede abortam o lote (histórico `token_invalido`/`erro`); resposta fora do formato derruba só aquele
   relatório/mês (vira aviso, o mês fica como estava).

## Armadilhas do Klingo tratadas (testes em `tests/klingo/`)
erro com HTTP 200 (`status_code: 400`), filtro errado devolve "hoje" (confere `inputs`), `result: ""` quando vazio, número/texto alternando,
`limit: true` (divide o período ao meio; se não dá, erro), 401, 429 com `Retry-After`, 5xx, relatório sem filtro de data, varredura em paralelo (evitada).

## Segurança
- Nenhuma tabela é legível pela chave anon; usuário logado lê só o próprio perfil, os menus e `dados_versao` (`tests/rls/rls.sql`).
- O navegador nunca recebe tabela bruta: só a página já calculada. Nome de paciente nunca vai a log.
- Segredos só no servidor (`.env.example`). `POST` exige `X-Painel: 1`, mesma origem e corpo ≤ 1 MB. Erros internos são genéricos para o navegador.
- Cabeçalhos: `X-Frame-Options: SAMEORIGIN`, `nosniff`, `Referrer-Policy: no-referrer`, HSTS, `Cache-Control: no-store`, CSP nos painéis.
- A função Python só responde com o cabeçalho `x-interno` = `CRON_SECRET` (o navegador nunca a chama).
