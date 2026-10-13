# Plano por fases e situação

| Fase | Conteúdo | Situação |
|---|---|---|
| 1 | Leitura do legado, plano, `PREMISSAS.md`, dúvidas | **Feita (parcial):** faltam arquivos do legado (ver PREMISSAS §1) |
| 2 | Repositório, CI, Next.js, Supabase local, migrações, Auth + perfis + permissões, login/conta/pedidos, auditoria, RLS e testes | **Feita**, sem teste ponta a ponta contra um Supabase real (só migrações e RLS no Postgres) |
| 3 | Motor Klingo (fila, trava, cota, validações), "Atualizar agora"/cron, histórico, Realtime | **Feita** (56 testes), nunca rodou contra o Klingo real |
| 4 | Núcleo de cálculo e visual: período De/até, shell, Metas e Faturamento | **Feita** com dados sintéticos; sem paridade com o legado ainda |
| 5 | Financeiro, Despesas, Indicadores | Código do legado em uso; sem dados reais |
| 6 | Cesta, Suprimentos (custos), Atendimento (+ responsáveis) | Código do legado em uso; custos migrados para `custos_itens` |
| 7 | Guia dos alertas e "marcar como resolvido" | **Feita**; textos reescritos (revisar) |
| 8 | Exportar/Imprimir + PDF; suíte "Conferir números" | PDF **feito** (testado no Chromium local); "Conferir números": ver `OPERACAO.md` |
| 9 | Segurança final, backups, deploy, checklist | Cabeçalhos e proxy **feitos e verificados** (build de produção + preview na Vercel); backups, domínio e checklist dependem de você (`OPERACAO.md`) |

Ainda **não** feito: importação das planilhas (`scripts/importar_planilhas.ts` espera os `.xlsx`), golden master, E2E com Playwright contra Supabase
local, verificação visual lado a lado com o legado.
