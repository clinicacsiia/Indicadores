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
- `app/globals.css` — identidade visual da Clínica CSI: tokens de cor
  (tema claro e escuro automáticos), tipografia (Bricolage Grotesque nos
  títulos, Figtree no texto) e todos os estilos. Marca: "Clínica CSI";
  nome do sistema: "Indicadores". As cores das séries dos gráficos
  (`--s-agendados`, `--s-realizados`) foram validadas para daltonismo e
  contraste nos dois temas.
- `app/components/` — marca (`Brand`), ícones, navegação com item ativo
  (`NavLinks`), `Sparkline` (cards) e `TendenciaChart` (gráfico interativo
  de agendados × realizados, com tooltip e navegação por setas do teclado).
- `app/login/` — tela de login (usuário/senha via Supabase Auth) e botão **Solicitar acesso**: a pessoa escolhe
  usuário e senha, o usuário nasce **bloqueado** (ban no Auth, `profiles.status = 'pendente'`) e só entra depois que
  um administrador aprova em Configurações (migration `20261015100000_solicitacao_acesso.sql`).
- `app/(app)/layout.tsx` — menu lateral (Relatórios / Configurações) das
  telas logadas; vira barra no topo no celular. "Configurações" só aparece
  para quem tem `role = admin`.
- `app/(app)/page.tsx` — aba "Relatórios": filtro de período (padrão: últimos
  30 dias, com atalhos 7/30/90 dias e "Este ano"), cards de totais com
  tendência, gráfico agendados × realizados e tabela por dia (com total).
- `app/(app)/page.tsx` + `lib/inicio.ts` — aba "Início": um cartão por relatório ativo, medido **na unidade em que ele é coletado**
  (`status_coleta_relatorios()`): dias recentes nos diários ("faltam 83 dias"), **meses** nos mensais ("8 de 11 meses coletados"), 1/0 nos
  pontuais. Mostra também **pausado até hh:mm**, falhas seguidas e tentativas com erro nas últimas 24 h (a partir de 3; o último erro só
  aparece para admin), a última coleta automática (e avisa se passou de 30 min sem coletar nada) e os painéis em Python que estão sendo
  **atualizando agora** (`paineis_renovando()`, só os que a pessoa pode ver). A tela se atualiza sozinha (10 s com atualização em
  andamento, 60 s sem). A `status_sincronizacao_relatorios()` antiga continua no banco, sem uso na tela.
- `app/(app)/loading.tsx` — esqueleto exibido enquanto a página carrega.
- `app/(app)/atualizar-form.tsx` + `atualizar-actions.ts` — botão "Atualizar"
  (só admin): escolhe o relatório do catálogo `dim_relatorio` e o período.
  O relatório `13397` também atualiza os totais mostrados na tela.
- `app/(app)/avisos/` + `lib/avisos.ts` — aba "Avisos": as pendências de todos os painéis, com justificativa obrigatória para
  fechar e conferência de recorrência. Ver "Aba Avisos" abaixo.
- `app/(app)/metas/page.tsx` — aba "Metas": escolhe o mês (de `primeiro_mes`
  até o mês atual) e mostra, por grupo (CSI 1, CSI 2, CSI Pediatria), meta ×
  realizado, % de cumprimento, quanto falta, quanto fazer por dia útil,
  projeção do mês, SUS × outros e a situação (batida / no ritmo / atenção /
  atrasado). Ver "Aba Metas" abaixo.
- `lib/metas/` — `calculo.ts` (regras e contas das metas, porte do
  `Acompanhamento de META/gerar_dashboard.py`) e `config.ts` (lê o
  `metas.json`).
- `app/(app)/configuracoes/` — aba "Configurações" (admin): define quem é
  admin e quem pode ver Relatórios e Metas, com um "Salvar" por usuário e
  aviso de sucesso/erro. Também aprova/recusa pedidos de acesso (já com permissão e telas) e exclui usuários.
  Protegida tanto na página quanto por RLS.
- `supabase/functions/sync-indicadores/` — Edge Function que busca a API
  externa e grava os dados no banco.
- `supabase/functions/sync-relatorios-dw/` — Edge Function genérica que
  sincroniza qualquer relatório cadastrado em `dim_relatorio` (ver seção
  "Data warehouse de relatórios" abaixo).

## Painéis em Python (Faturamento, Financeiro, Despesas, Indicadores, Cesta, Suprimentos, Atendimento, Tempo, NPS × Google)

São os painéis do programa local (`servidor_portal.py` / `Indicadores CSI.exe`), agora publicados neste mesmo site. O
código de cálculo (`*/gerar_*.py`, `klingo_relatorios.py`, `painel_comum.py`) e as telas
(`*/dashboard_modelo.html`, `painel_base.js/css`) são **os mesmos**; mudou só onde ficam os dados e quem serve a página:

| No programa local | Aqui |
| --- | --- |
| Excel por painel (`Faturamento.xlsx`...) | tabelas `painel_dados` / `painel_mes` no Supabase (`armazenamento.py`) |
| SQLite (marcações "resolvido", histórico) | `aviso` e `aviso_evento` (aba Avisos); `painel_atualizacao` guarda o histórico de atualizações. `painel_pendencia` ficou sem uso |
| `Custos dos Itens.xlsx` (Suprimentos) | tabela `painel_custo_item` (preencher no Table Editor: colunas `item` e `custo`) |
| Login/usuários do portal (`autenticacao.py`) | login do Supabase (o mesmo do site) + `profiles.permissions.<painel>` |
| Servidor local, rede, certificado, `.exe` | funções Python da Vercel em `api/` |
| Página recalculada quando a planilha muda | HTML pronto guardado em `painel_pagina`, refeito quando os dados ou o dia mudam |

Como funciona:

```
site (menu "Faturamento", "Financeiro"...)  →  /painel/<id>  →  iframe  →  /api/painel?id=<id>   (api/painel.py)
                                                                              │ confere login (Supabase Auth) e permissão (profiles)
                                                                              ▼
                              painel_pagina (HTML pronto)  ←──  gerar_<id>.py  ←──  painel_dados (linhas do Klingo, por mês)
botão "Atualizar agora" (só admin) ou sozinho a cada 5 h  →  /api/atualizar?id=<id>  →  BANCO (fact_relatorio_linha, coletado pelo Supabase)  →  grava o mês inteiro (troca atômica)  →  refaz a página
```

- **Arquivos novos:** `armazenamento.py` (Supabase), `portal_nuvem.py` (login, permissão, página pronta, atualização),
  `api/*.py` (as funções da Vercel), `vercel.json` (arquivos incluídos, tempo máximo, cron),
  `supabase/migrations/20261013130000_paineis_python.sql`, `lib/paineis.ts` e `app/(app)/painel/[id]/`.
  A lista de painéis vem do `modulos.json`, o mesmo arquivo dos dois lados.
- **O que o programa local ganhou:** quase nada. As funções que liam/gravavam Excel ganharam um `if armazenamento.ativo()`
  (na Vercel ou com `PORTAL_ARMAZENAMENTO=supabase`); sem isso tudo continua Excel + SQLite como antes.
  `painel_base.js` fala com `/api/*` quando a página traz `window.PAINEL_NUVEM`.
- **Permissões:** cada painel é uma chave em `profiles.permissions` (id do painel). Administrador vê todos; os demais só os
  marcados em **Configurações**. Painel novo nasce **bloqueado** (dado financeiro e, em alguns, de paciente).
- **Dados financeiros:** em **Configurações > Dados sensíveis**, a chave `profiles.permissions.dados_financeiros` (não pode ser
  `financeiro`: é o id de um painel) libera receitas, despesas e valores em R$. Administrador sempre vê. Sem ela:
  - os painéis só de dinheiro (`"financeiro": "total"` no `modulos.json`: Faturamento, Financeiro, Despesas, Indicadores) **nem abrem**
    (`conferir_acesso` no servidor, `podeVerPainel` no site, que também os tira do menu e do Início);
  - os painéis mistos (`"financeiro": "parcial"`: Atendimento, Cesta, Suprimentos) abrem **sem os valores em R$**. Esconder com CSS/JS não
    bastaria (o valor continua no código da página), então `sigilo.py` REMOVE do JSON da página os campos de dinheiro (`CHAVES` e `RAIZ`, por
    painel) e os alertas de dinheiro antes de entregar; o modelo (`SEM_FIN`, `fin()`, `{fin: 1}` em `kpi`/`tabela`/`acordeao`, `data-fin`)
    só deixa de desenhar o que sobrou sem dado. **Painel misto novo ou gráfico novo com dinheiro:** acrescente o campo em `sigilo.py` e marque o
    pedaço no modelo; `tests/test_sigilo.py` falha se sobrar campo ou valor em R$ no JSON ou na tela;
  - os avisos que falam de dinheiro (`guia_pendencias.sensivel`: todo aviso dos painéis só de dinheiro e, nos mistos, os que citam R$,
    receita, ticket, custo etc.) ficam invisíveis na aba Avisos e em `/api/pendencias` (`aviso.sensivel` + RLS `can_view_aviso`); a regra de antes
    segue por cima: o aviso só aparece se o painel dele estiver liberado.
  Quem já via Faturamento, Financeiro, Despesas ou Indicadores ficou com a permissão marcada (migration `20261016120000_dados_financeiros.sql`).

  **Painel, relatório ou gráfico novo: o que fazer para já nascer protegido** (os testes forçam cada passo):
  1. `modulos.json`: `"financeiro": "total"` (só dinheiro), `"parcial"` (misto) ou `"nenhum"`. **Sem o campo o painel conta como `"total"`**: esquecer bloqueia, não libera.
  2. Painel `parcial`: campos de dinheiro em `sigilo.CHAVES`/`RAIZ`, nomes parecidos mas que não são dinheiro em `sigilo.MANTER`, colunas de dinheiro dos
     relatórios em `sigilo.COLUNAS_DE_DINHEIRO`, uma página com dados em `tests/paineis_de_mentira.py` e, no modelo, `fin()`/`{fin: 1}`/`data-fin` nos
     pedaços de dinheiro. Em produção, mesmo sem nada disso, o servidor já tira qualquer campo com nome de dinheiro e mascara `R$` solto nos textos; os
     testes é que não deixam passar sem decisão por escrito.
  3. Alerta novo com dinheiro num painel misto: o texto com `R$`/receita/ticket/custo e as colunas de valor já o marcam como sensível sozinhos
     (`guia_pendencias.sensivel`); se o texto não cita dinheiro, acrescente o id em `SENSIVEIS_PARCIAIS`.
  4. Relatório novo do Klingo num painel misto com coluna de valor: `tests/test_sigilo.py` falha até a coluna entrar em `COLUNAS_DE_DINHEIRO`.
  Fora do alcance disto: o portal do computador da clínica (`servidor_portal.py`, `Gerar EXE.bat`), que tem usuários próprios e não lê `profiles`.
- **Atualização (do banco):** os painéis **não consultam mais o Klingo**. Uma coleta só (Edge Function `sync-relatorios-dw`,
  pg_cron a cada 5 min) guarda os relatórios em `fact_relatorio_linha`; `fonte_banco.py` copia dali para `painel_dados`, no
  formato que os geradores já liam. O relatório dos painéis é coletado **por mês** (`dim_relatorio.granularidade = 'mes'`,
  com `primeiro_mes`, `meses_a_frente` e `revisar_meses` vindos do `relatorios.json`), exatamente como o painel pedia ao
  Klingo; as Metas (#13339) vêm dia a dia. Cada mês coletado por inteiro **substitui o mês inteiro** guardado (troca atômica);
  mês que o banco ainda não coletou, relatório sem filtro de período comprovado, desativado ou sem título de coluna ficam
  como estavam e viram aviso. Só regrava o mês cujo dado no banco é mais novo que o do painel. O botão **Atualizar agora**
  (só administrador) copia na hora; além disso, quando alguém abre um painel cuja última atualização tem mais de **5 h**, ele
  copia sozinho (`portal_nuvem.renovar`, também no cron diário), **sem fazer ninguém esperar** (ver "Abertura rápida" abaixo).
  `PAINEL_FONTE=klingo` (variável da Vercel)
  volta ao caminho antigo, que consulta o Klingo direto.
- **Horário:** as funções rodam com fuso de Brasília (`TZ=BRT3`), senão "hoje" viraria amanhã depois das 21h.
- **Cron (opcional):** `vercel.json` agenda `/api/preaquecer` todo dia às 06:30 (Brasília) para refazer as páginas e o primeiro
  acesso do dia não esperar a conta (a Cesta chega a levar mais de 1 min). Só funciona se existir a variável `CRON_SECRET`.
- **Não existe na Vercel:** exportar PDF pelo Chromium do `exportar_pdf.py` (no site, a aba **Configurações → Extrair** gera o PDF pelo
  navegador: `/extrair` empilha os painéis e abre a impressão), acesso em rede/`.exe`, usuários próprios
  do portal e as "visões" em PDF do Atendimento. A aba **Metas** continua sendo a do site (abaixo); a base das Metas em Python
  só existe para o Atendimento.

### Abertura rápida e renovação em segundo plano

Abrir um painel **nunca espera a atualização**. `/api/painel` entrega na hora a última página guardada (`painel_pagina`), mesmo velha, e
marca no HTML se ela está **vencida** (`window.PAINEL_VENCIDO`): dado novo no banco, dia novo, layout novo ou cópia do banco com mais de 5 h.
Só espera a conta quem não tem nenhuma página guardada, ou pediu um período livre cuja página está velha.

Quando vencida, a tela do site (`app/(app)/painel/[id]/PainelFrame.tsx`) lê isso do iframe e mostra o aviso **"Atualizando os dados deste
painel…"** com uma barra e **quanto falta** (estimativa: mediana das últimas 5 renovações do mesmo tipo em `painel_atualizacao`; sem
histórico, 40 s com cópia do banco ou 20 s só refazendo a página). Em segundo plano ela chama `POST /api/renovar?id=<painel>`
(`portal_nuvem.renovar`: copia do banco se venceu, refaz a página) e, ao terminar, recarrega o quadro. Qualquer pessoa com acesso ao painel
pode pedir (só copia do banco, não consulta o Klingo). No máximo 2 renovações por abertura da tela, para nunca entrar em laço.

**Só uma renovação por painel de cada vez** (`painel_renovacao`, uma linha por painel enquanto renova; vence sozinha em 6 min se a função
morrer). Duas gravando o mesmo painel se atropelavam: a troca atômica de uma (`painel_publicar_mes`) apagava os lotes ainda em gravação
da outra e a atualização falhava com `Nenhum lote gravado para ...`. Quem chega depois recebe o andamento da que já roda
(`/api/estado` devolve `atualizando` e `andamento`) e acompanha o mesmo aviso; o botão **Atualizar agora** e o cron respeitam a mesma trava.
Sem a tabela, o código segue sem trava (como antes). Refazer só a página fica no histórico com `status = 'pagina'` e não conta como atualização dos dados.

### Visual e filtros padronizados

Todas as abas (Início, Metas, Configurações e os 8 painéis em Python) seguem o mesmo padrão do site:

- **Visual:** `painel_base.css` usa as mesmas cores, fontes (Figtree e Bricolage Grotesque), cabeçalho ("Clínica CSI" + título +
  descrição), cartões e tabelas de `app/globals.css`. Dentro do site o painel aparece **sem moldura e com a altura do conteúdo**
  (`app/(app)/painel/[id]/PainelFrame.tsx`), então a tela rola inteira como as outras. Ao mudar uma cor ou fonte do site, repita em
  `painel_base.css` (a seção "Padrão das telas do site" tem as mesmas classes do `globals.css`).
- **Filtro de período (todas as abas com dados):** atalhos de **mês**, atalhos dos **últimos 7/30/90 dias** e **período livre** (campos
  *De* e *Até* com data + *Aplicar*). Nos painéis Python a barra é montada por `iniciarPeriodo()` (`painel_base.js`); em Metas é o
  componente `app/components/FiltroPeriodo.tsx`, com as mesmas classes.
- **Período por dias exatos (painéis Python):** `?de=2026-09-10&ate=2026-10-25` (também aceita meses: `?de=2026-09&ate=2026-10`).
  Datas que cobrem meses inteiros viram o filtro por mês (e usam a página pronta). `painel_comum.Periodo` carrega o recorte;
  `reagrupar(..., datacol="Data")` corta as linhas pela data de cada uma e o cálculo mensal de sempre roda sobre elas. O período
  anterior (base das comparações) é o de **mesmo número de dias** logo antes. Dias úteis e feriados valem para os dias do período.
  O que o Klingo só entrega **por mês** (Controle por Convênio do Faturamento e do Indicadores, faturas por competência) entra com os
  meses inteiros que o período toca, e a página avisa isso no alto. Páginas de dias exatos são calculadas na hora e guardadas em
  `painel_pagina` com as datas na chave (limpas junto com as de vários meses).
- **Metas com período livre:** `lib/metas/calculo.ts` → `calcularPeriodo()` (o mês é o caso particular). A meta de cada mês que o
  período toca vale pela parte dos dias úteis do mês que cai dentro do período. Período que não é um mês usa a função
  `metas_atendimentos_periodo(de, ate)` (migration `20261014120000_metas_periodo_livre.sql`); **aplique a migration** antes de usar o
  período livre em Metas (o filtro por mês continua usando `metas_atendimentos_mes`).

### Aplicar migrations no Supabase pelo Claude (e o que já foi aplicado)

Projeto de produção: `Indicadores`, id `syhcvonwthtqalpjcmtj`. O Claude aplica migrations pela ferramenta `apply_migration` do Supabase, mas ela
**cancela sozinha (`cancelled`, sem aplicar nada) quando a chamada tem `drop function`** (e foi assim com a migration inteira de uma vez). Não é falta
de permissão nem erro de conexão (as consultas de leitura funcionam). O que funciona, e deve ser repetido:
- **dividir em chamadas pequenas** e deixar o `drop function` sozinho em uma chamada (ou fora, usando só `create or replace` com a assinatura nova);
- conferir depois com `execute_sql` (colunas, funções, constraints); `execute_sql` com vários comandos devolve só o resultado do último;
- o que tiver `drop function` e não passar, rodar no SQL Editor do Supabase (https://supabase.com/dashboard/project/syhcvonwthtqalpjcmtj/sql/new).
As versões que o Supabase registra em `list_migrations` não são as dos arquivos (ele usa a data da aplicação), e migrations aplicadas pelo SQL Editor
não aparecem na lista: confira pelo banco, não pela lista.

**15/10/2026, `20261017110000_aviso_informacao_e_previsao.sql`:** aplicada em 4 partes pelo `apply_migration` (colunas e tipos de evento; `fechar_aviso` e
`reabrir_aviso` novos; `aviso_sincronizar`; ajuste do aviso de Faturamento justificado em 14/10, que ganhou a data prevista 20/10/2026 e a nota de
atualização). **Pendente, opcional:** remover as duas versões antigas, que o site não usa mais (o `drop function` foi cancelado):
`drop function if exists public.fechar_aviso(bigint, text); drop function if exists public.reabrir_aviso(bigint);`

**15/10/2026, `20261019100000_corrige_justificativa_no_aviso_errado.sql`:** aplicada em 2 partes pelo `apply_migration` (o tipo de evento `correcao` e a correção dos dados). A nota da
atualização PR#36, postada por engano em "Quase nada de convênio aparece como recebido" (Setembro/2026), saiu de lá (o aviso voltou a ficar **aberto**, sem justificativa)
e foi para o histórico de "Faturas esperando envio há mais de 7 dias", que mantém a justificativa e a data prevista (20/10/2026) de quem fechou antes. Os dois
históricos ganharam o evento "Correção de registro"; a linha original não foi apagada.

**19/10/2026, `20261019120000_despesas_planilha.sql` (+ `..120100_..._base.sql` e `..120200_..._historico.sql`):** aplicadas pelo `apply_migration` (as tabelas, sem `drop`) e pelo
`execute_sql` (os dados de seed: 78 itens, 59 ligações categoria → item, 33 linhas de fornecedor e 659 valores mensais de out/2025 a ago/2026). Ver "Aba Planilha (Despesas)".

**20/10/2026, `20261020120000_cadastra_relatorio_nps_13697.sql`:** aplicada pelo `apply_migration` (um `insert ... on conflict`, sem `drop`). Cadastra o #13697 (NPS) como ativo, coleta mensal desde set/2026; a primeira coleta
trouxe 283 respostas (174 em set e 109 em out) e o filtro de período foi comprovado sozinho. Ver "Aba NPS × Google".

### Para colocar no ar

1. **Banco:** aplicar `supabase/migrations/20261013130000_paineis_python.sql` e, para a aba Avisos,
   `supabase/migrations/20261014210000_avisos.sql` (SQL Editor do Supabase). Depois, em ordem, as que mudam os avisos:
   `20261016120000_dados_financeiros.sql` e `20261017110000_aviso_informacao_e_previsao.sql` (**aplique antes de publicar o site**: a aba Avisos lê as colunas novas).
2. **Variáveis da Vercel** (Settings → Environment Variables):
   - `KLINGO_APP_TOKEN` — marcar *Sensitive*; Production (e Preview se for testar). É o mesmo token do secret da Edge Function.
   - `SUPABASE_SERVICE_ROLE_KEY` — **já existe** (criada pela integração Supabase), mas só em *Production*: marque também
     *Preview* se for testar um preview. Fica só no servidor (nunca `NEXT_PUBLIC_*`).
   - `CRON_SECRET` — opcional, qualquer texto longo aleatório, para o cron diário.
3. **Deploy:** publicar este branch (preview) e, conferido, juntar no branch de produção.
4. **Configurações:** liberar cada painel para quem deve ver (administradores já veem todos).
5. Em cada painel, como administrador: **Atualizar agora** (repetir se avisar que parou pelo tempo limite).

### Segurança desta parte

- As tabelas `painel_*` têm RLS ligado **sem policy** e acesso revogado de `anon`/`authenticated`: o navegador nunca lê nem grava
  nelas (as linhas do Klingo podem ter nome de paciente — ver "ATENÇÃO LGPD"). Só as funções de `api/`, com a `service_role`
  no servidor, e **depois** de conferir o login (`/auth/v1/user`) e a permissão (`profiles`).
- **Mudança consciente em relação ao resto do site:** o site Next.js continua sem chave privilegiada, mas as funções Python
  precisam da `service_role` (gravam dados e leem as tabelas fechadas). Ela fica só como variável de servidor da Vercel.
- Escritas (`atualizar`) exigem o cabeçalho `X-Painel: 1`, que um site de fora não consegue mandar com o
  cookie do usuário; o quadro do painel só aparece dentro do próprio site (`frame-ancestors 'self'`).
- Fechar um alerta é feito só na aba Avisos (`fechar_aviso`, no banco, com justificativa). Quem fechou vem do login (`auth.uid()`),
  nunca do corpo do pedido.

### O Klingo começou em setembro/2026

O Klingo só passou a ser usado em **setembro/2026**. O que existe de antes (fevereiro a agosto) é **teste ou do sistema anterior (Clinical)** e não pode virar histórico,
média, comparação com o mês anterior nem previsão. Uma só definição vale para tudo: `"inicio_klingo": "2026-09"` no `modulos.json` (lido por `painel_comum.INICIO_KLINGO`
no Python e por `lib/inicio-klingo.ts` no site). Para mudar a data, mude só ali.

- **Todos os painéis Python** (`painel_comum`): `completar_payload` tira do painel e do filtro qualquer mês anterior e leva `inicio_klingo` para a página;
  `periodo_pedido` corta o período pedido (`info["antes_klingo"]` explica o recorte na tela); `acrescentar_periodo` só traz o período anterior se ele começa no Klingo
  ou depois; o seletor De/Até não deixa escolher data de antes; a linha do período mostra "dados do Klingo desde setembro/2026".
- **Despesas** é a única exceção declarada (`historico_antes_klingo`): mostra a planilha antiga (out/2025 a ago/2026) como histórico "parcial" (pode estar incompleto),
  que **não entra** em médias, comparações, "o que mais subiu", previsão nem tendência.
- **Suprimentos:** o "Mês a mês", o consumo por mês de cada item, as pendências, o ritmo de pedidos e as baixas em bloco só olham o Klingo em diante; as movimentações
  de antes entram apenas no **saldo do estoque** (ele depende de todo o histórico).
- **Suprimentos, aba "Consumo médio":** a quantidade **pedida** pelos setores (inclui o pendente), só do Klingo em diante, por item e por setor: média por dia/semana/mês
  (total ÷ dias desde o primeiro pedido do Klingo, o mesmo para todos os itens) e "pede a cada N dias" (período ÷ dias com pedido). Não usa valores em R$, então abre também sem "Dados financeiros".
- **Faturamento:** faturas emitidas antes de setembro não entram em prazo aprendido por convênio, cancelamento, SUS mês a mês nem funil (a tela diz quantas ficaram de fora);
  a conferência com as Faturas em Aberto olha todas.
- **Metas** (painel e site): nunca antes do `inicio_klingo`, mesmo que o `metas.json` peça; o filtro do site explica a data de início.
- Testes: `tests/test_inicio_klingo.py` (inclui a regra de que nenhum `relatorios.json`, fora o da Despesas, começa antes do Klingo).

### Testes

`python -m unittest discover -s tests -v` — sobe um Supabase e um Klingo simulados (`tests/mock_nuvem.py`) e confere login,
permissões, atualização (mês substituído, não somado), tipos das colunas, página pronta guardada e invalidada, avisos e
corte por tempo. A regra da aba Avisos dentro do banco (novo / resolvido / voltou / justificado, permissões e RLS) é testada num
Postgres de verdade: `createdb avisos_teste && psql -v ON_ERROR_STOP=1 -d avisos_teste -f supabase/tests/avisos.sql` (inclui "Dados financeiros": o preenchimento
da permissão, `aviso.sensivel` e quem vê/fecha o aviso de dinheiro). `tests/test_sigilo.py` gera Atendimento, Cesta e Suprimentos COM DADOS
(`tests/paineis_de_mentira.py`, nos três períodos do filtro) e confere que a versão sem dinheiro não leva campo nem valor em R$, no JSON e (se houver
Chromium) na tela: cada mês, cada responsável do Atendimento e cada gráfico da lista do Início. `tests/test_paineis_ts.py` roda o `podeVerPainel` do
site no Node e compara com o do servidor em centenas de combinações; `tests/test_painel_base_js.py` testa os helpers que os 7 painéis usam e confere a
sintaxe do JavaScript de cada modelo; `test_nuvem.py` tem a matriz painel × usuário × rota. `SIGILO_RAPIDO=1` pula a matriz grande de navegador. Os 7 painéis também foram gerados de ponta a ponta com dados de mentira e o botão **Atualizar agora**
foi exercitado no Chromium. **Não foi testado:** o deploy na Vercel de verdade (funções Python junto do Next.js, tamanho do
pacote com pandas, tempo da carga inicial) nem o Klingo/Supabase reais — confira o primeiro deploy e o log das funções.

## Aba Avisos

Todas as pendências dos painéis num lugar só (menu **Avisos**, com o contador de abertos). Cada alerta com guia que um painel calcula
(os mesmos de "Como achar o problema") vira um **aviso**. **O administrador vê tudo; os demais só os avisos dos painéis liberados
em Configurações** (RLS: `can_view_painel`, a mesma regra de `profiles.permissions.<painel>`), e os avisos que falam de dinheiro só
para quem tem **Dados financeiros** (`can_view_aviso`).

**Como os avisos nascem e se atualizam.** Quando a página de um painel é refeita (dados novos, novo dia ou **Atualizar agora**),
`portal_nuvem.registrar_avisos` pega os alertas dela (`avisos.py`) e chama `aviso_sincronizar` no Supabase. Só a página padrão
conta (não um período escolhido no filtro) e, para os alertas de um mês, o mês atual e o anterior (`JANELA_MESES`); aviso de um mês
que saiu da janela fica como estava. Painel sem dados não resolve nada. Falhar aqui nunca impede de abrir o painel.

| O que o painel mostra agora | O que acontece com o aviso |
| --- | --- |
| alerta novo | aviso **aberto** (histórico: "apareceu nos dados") |
| continua aparecendo | segue aberto |
| deixou de aparecer | **resolvido** (o painel segue conferindo) |
| estava resolvido e **voltou**, sem justificativa que valesse | aberto de novo, selo **"Voltou a acontecer N×"** |
| estava resolvido e **voltou**, e já tinha justificativa que valia | **informação**: segue com a justificativa dada, selo **"Voltou N× como informação"**; **não** conta como recorrência e só reabre se piorar |
| fechado com justificativa, os dados foram atualizados e **continua** (sem data prevista) | aberto de novo, selo **"Reaberto N×"** (a justificativa não resolveu) |
| fechado com justificativa **e data prevista**, os dados foram atualizados e continua | segue como **informação** até a data; só reabre antes se piorar |
| passou a **data prevista** e o problema continua | aberto de novo ("a data prevista passou"), conta como **recorrência** |
| fechado com justificativa e **some** | resolvido e confirmado |

**Fechar exige justificativa** (mínimo de 15 e máximo de 1000 caracteres; conferido no formulário, na action e no banco), e a justificativa
fica à mostra como **informação** (o filtro "Informações (justificados)"). Ao justificar dá para informar uma **data prevista** (opcional, de hoje a
um ano): ex.: "o envio da Petrobras é dia 20/10". Quem vê a informação e discorda usa **"Ainda não resolvi"** ou **"Não explica o problema"**: os dois
reabrem o aviso e **contam como recorrência** ("Reaberto N×"), e a justificativa deixa de valer (se o aviso for resolvido e voltar, volta como
recorrência de verdade). Quem justificou, quando, a previsão e o texto ficam no aviso e em todo o **histórico**. Regras no banco:
`aviso_sincronizar`, `fechar_aviso`, `reabrir_aviso` (migration `20261017110000_aviso_informacao_e_previsao.sql`; teste: `supabase/tests/avisos.sql`).

**Vencimento como referência (dentro do prazo não é aviso).** Um alerta pode trazer `vencimento` (AAAA-MM-DD): a data em que o prazo dele acaba. Até essa data
(inclusive) ele continua aparecendo no painel, mas **não vira aviso** (`avisos.no_prazo`; se já era aviso e voltou para dentro do prazo, é dado como resolvido); passada a data, entra
como qualquer outro. Sem o campo, nada muda. Hoje usam: **"Quase nada de convênio aparece como recebido"** (último vencimento das faturas ativas da competência, `vencimento_do_mes`)
e **"Despesas lançadas com valor zero"** (vencimento do primeiro lançamento zerado: antes dele ainda dá tempo de preencher). Em Despesas, **"Produção médica sem Honorário Médico
lançado"** só cobra o mês depois do prazo do repasse (`PRAZO_REPASSE_MESES`, hoje até o fim do mês seguinte, já que o repasse vence depois da produção); antes disso a aba Repasse
médico mostra "ainda dentro do prazo". Testes: `VencimentoComoReferenciaTest` (`tests/test_avisos.py`) e `MesDeVencimentoTest`.

**Dica e nota de atualização no guia.** `guia_pendencias.DICAS` e `ATUALIZACOES` acrescentam ao guia de um alerta uma dica e "Painel atualizado em
dd/mm/aaaa: ..." (aparecem no painel e na aba Avisos). Use `ATUALIZACOES` quando uma regra do painel mudar por causa de um aviso já tratado.

**Prazo de envio de cada convênio (aprendido) e o SUS no Faturamento.** Cada convênio leva um tempo diferente da emissão ao envio (a maioria
sai no mesmo dia; a única fatura SUS enviada até 14/10/2026 saiu 35 dias depois). O painel **aprende o prazo habitual de cada um** com as faturas já
enviadas (`prazo_tipico` em `Faturamento/gerar_faturamento.py`) e só avisa em "Faturas esperando envio" quando uma fatura espera mais que **prazo
habitual × 1,3 + 7 dias** (nunca menos de 7; crítico 23 dias depois). Para não se enganar:
- sem fatura enviada: vale o prazo geral (7 dias);
- **pouco histórico** (menos de 3 enviadas, `MIN_AMOSTRAS`): vale o **maior** que já aconteceu (um convênio com uma única fatura, de 90 dias, tem 90 dias);
- com histórico: a **média**, **sem os casos isolados**: quem passou de 2× a mediana + 3 dias só entra na média se isso se **repetir** (2 vezes,
  `RECORRENCIA`). Assim um caso fora da normalidade não puxa o prazo do convênio, mas se virar rotina o prazo acompanha.
A tabela "Prazo de envio de cada convênio" (Detalhes) mostra o prazo habitual, quantas faturas entraram e quando o painel avisa. O aviso não conta a
fatura que está dentro do prazo habitual do convênio e diz isso no texto. O SUS ganhou também a seção **"SUS: mês a mês"** (Análise): os meses em que
ele aparece, com faturas enviadas, a enviar e canceladas e os dias da emissão ao envio contra os demais convênios (`ACOMPANHAR_MES_A_MES`).
Teste: `tests/test_faturamento_sus.py`.

**Avisos que podem ser aceitos** (`guia_pendencias.PERSISTENTES`: cortesia com valor zero, glosa conhecida, queda sazonal, meta
decidida...): não são erro de cadastro e continuam aparecendo mesmo depois de resolvidos. Fechados com justificativa, **ficam
fechados enquanto o painel mostrar o mesmo problema** e só reabrem se **piorar** (nível mais grave ou 25% mais registros, e ao
menos 1 a mais). Para mudar a lista ou o limite: `PERSISTENTES` e a função `aviso_sincronizar`.

**Nos painéis** o botão "Marcar como resolvido" virou **"Justificar e fechar"** (abre o aviso na aba Avisos) e cada alerta mostra
o que se sabe dele: fechado por quem e por quê, quantas vezes voltou, e os resolvidos dos últimos 30 dias. `/api/pendencias?id=<painel>`
agora só lista (GET); no programa local (sem Supabase) o botão antigo continua como era. As marcações antigas de `painel_pendencia`
não foram migradas: esses alertas aparecem como abertos na primeira conferência.

**Limites a saber:** os avisos só são conferidos quando a página do painel é refeita — por alguém abrindo o painel, pelo botão **Atualizar
agora** ou pelo cron diário —, então um aviso pode estar até um dia atrasado. "Voltou a acontecer" só é detectado entre uma conferência
e outra (um problema que some e volta entre duas conferências não é visto).

## Despesas: o mês é o do vencimento

Desde 19/10/2026 o painel de Despesas conta cada lançamento no mês em que ele **vence**, não no da competência (um boleto de competência setembro que vence em outubro entra
em outubro). O vencimento vem do Financeiro (#798) pelo **ID do lançamento** (o #13509 traz o ID); a conta está em `aplicar_vencimento()`, em `Despesas/gerar_despesas.py`, e tudo
que agrupa por mês (KPIs, evolução, categorias, fornecedores, previsão, matriz da aba Planilha, filtro De/Até por dia) já usa a coluna `_ym` dela. Detalhes:

- Lançamento sem vencimento no Financeiro (emitido antes do período que o #798 baixa, ou Financeiro ainda não atualizado) fica no mês da competência e vira o aviso "Despesas sem
  data de vencimento" no alto do painel.
- Os relatórios continuam baixados por competência (6 meses à frente). O que vence depois do último mês baixado fica de fora, para o último mês não aparecer incompleto.
- **Vale para tudo, inclusive o Repasse médico:** o que conta é o mês em que o dinheiro sai. A produção médica (#26) continua pela data do atendimento, então o repasse de um mês costuma
  pagar a produção de meses anteriores (a proporção repasse/produção de um mês isolado varia).
- As tabelas de lançamentos mostram só o Vencimento. Testes: `MesDeVencimentoTest` em `tests/test_planilha_despesas.py`.

## Aba Planilha (Despesas)

A planilha de despesas que a equipe consultava (`FORNECEDORES - MM.AAAA.xlsx`, abas "Planilha2" e "Planilha1") virou a aba **Planilha** do painel de Despesas, no mesmo
formato (grupos > itens > meses; fornecedores com divisão CSI / CSI 2), atualizada sozinha pelo Klingo. Código: `Despesas/planilha_despesas.py`; tela: `planilhaMatriz()` e
`planilhaFornecedores()` em `Despesas/dashboard_modelo.html`; testes: `tests/test_planilha_despesas.py`.

- **Despesas por grupo e mês** (antiga Planilha2). Cada lançamento do #13505 vai para um item da planilha pela tabela `despesa_de_para` (categoria do Klingo → item). Meses **antes do
  início confiável** (`inicio_klingo` do `modulos.json`, hoje 2026-09) usam os valores da planilha antiga, guardados em `despesa_historico` (out/2025 a ago/2026); do
  início em diante, só o Klingo. Categoria do Klingo que o de-para não conhece cai no grupo **SEM CLASSIFICAÇÃO** (o total nunca perde dinheiro). Item da planilha sem categoria no Klingo
  aparece com "só histórico". Ligação deduzida (não confirmada pela planilha de mapeamento) aparece com "a confirmar" (`despesa_de_para.confirmado = false`).
- **Meses descendo, grupos que abrem e gráfico no clique.** Na planilha os meses **descem** (uma linha por mês, o mais recente primeiro; os botões "Meses" e "Ordem dos meses" voltam ao
  formato antigo, com os meses nas colunas). A **Visão geral** mostra os grupos lado a lado e cada grupo abre para mostrar os itens (com mapa de calor por coluna). Clicar no nome de um
  grupo, item ou no botão "Ver gráfico" abre uma janela com a linha mensal, a média dos meses fechados, os números-chave e o peso de cada item do grupo.
- **Comparar** (bloco logo abaixo da Planilha; `comparar()`, `cmpGrafico()` e `PRESETS` em `Despesas/dashboard_modelo.html`; teste no navegador: `tests/test_comparar_despesas.py`).
  O leitor escolhe até 8 séries (o total, grupos inteiros e/ou itens), o período (De/Até ou 12 meses, 6 meses, Só Klingo), a **medida** (R$, % do total das despesas, variação sobre o mês
  anterior, índice com o 1º mês = 100) e o **gráfico**. No modo **Automático** o tipo vem dos dados: % do total de partes que não se sobrepõem → barras empilhadas; poucos meses (até 6) →
  barras agrupadas; mais meses ou índice → linhas. Há visões prontas (executiva, composição por grupo, maiores despesas, grupos nos últimos 6 meses, o que mais subiu, um grupo por dentro) e
  "Minhas visões" salvas no navegador (`localStorage`, chave `csi_despesas_visoes_v1`, por nome de grupo/item: sobrevive a mudança de ordem da planilha). Abaixo do gráfico: leitura em
  frases, resumo (total, média, maior mês, último mês fechado, variação e peso nas despesas) e a tabela do gráfico. O mês em andamento aparece tracejado/mais claro e fica fora das médias e
  variações; uma linha pontilhada marca onde os dados passam da planilha antiga para o Klingo. Cores: paleta categórica de 8 tons em ordem fixa, validada para daltonismo nos dois temas
  (`--c1`…`--c8` no modelo), sempre com legenda, tooltip e tabela.
- **Fornecedores do mês** (antiga Planilha1). O que **vence** no mês na empresa `CLÍNICA DE SAÚDE E IMAGEM - CSI`, somado por fornecedor com o nome da planilha antiga e dividido entre CSI e
  CSI 2 (`despesa_fornecedor.pct_csi`, 50% como na planilha). O Financeiro (#798) traz empresa e vencimento mas não o fornecedor; as Despesas Detalhadas (#13509) trazem o fornecedor; o painel
  cruza os dois pelo **ID do lançamento** (o #798 repete o lançamento, uma linha por conta/conciliação: conta uma vez). Por isso `armazenamento.DEPENDENCIAS["despesas"] = ["financeiro"]` e o
  "Atualizar agora" das Despesas atualiza também o Financeiro. O que não está na lista da planilha aparece em "Outros fornecedores".
- **Onde editar (Table Editor do Supabase):** `despesa_item` (layout), `despesa_de_para` (categoria → item), `despesa_historico` (meses antigos), `despesa_fornecedor` (nome na planilha, fornecedor e
  categoria do Klingo que entram nele, % da CSI). RLS ligado e sem policy: só o servidor lê. No programa local (Excel) e se o banco não responder, vale `Despesas/planilha_base.json`.
- **Reimportar a planilha:** `python Despesas/importar_planilha.py "FORNECEDORES - 09.2026.xlsx"` regrava os itens e os meses do JSON (e avisa quando um total da planilha não bate com a soma
  dos itens: em fev/2026 a própria planilha diz R$ 815.406,09 de total e os grupos somam R$ 827.433,06; o painel mostra a soma).
- **Falha na aba não derruba o painel:** sem base, sem Financeiro ou com erro de conta, a parte afetada mostra o motivo e o resto das Despesas abre normalmente.

## Aba Tempo

Quanto o paciente espera e fica na clínica, **hora a hora**: espera, tempo total, pico de gargalo de cada dia, pacientes simultâneos, ocupação dos equipamentos e os
tempos "fora do normal" (encerramento esquecido). Painel `tempo` (`Tempo/`), **sem dinheiro** (`"financeiro": "nenhum"` no `modulos.json`); nasce bloqueado como os outros e
é liberado por usuário em Configurações.

- **Sem relatório próprio.** Lê as abas "Atendimentos" (#13402) e "Fluxo na Recepção" (#13404) que o painel Atendimento já guarda, então não duplica dado no banco (o plano
  gratuito tem 500 MB) e a página se refaz sozinha quando o Atendimento atualiza (`armazenamento.DEPENDENCIAS["tempo"] = ["atendimento"]`). **Atualizar agora** no Tempo
  atualiza o Atendimento. Os limites de espera (`espera_meta_min`, `espera_critica_min`...) vêm de `Atendimento/parametros.json`; `Tempo/parametros.json` acrescenta os próprios
  (método de outlier, piso, mínimo de chegadas para a "pior hora") e sobrepõe os herdados. Expediente, dias de atendimento e feriados vêm do `metas.json`.
- **Contas em `Tempo/metricas_tempo.py`** (pandas puro, sem Klingo nem Supabase; testado em pandas 2.2 e 3.0): `ciclo_por_atendimento` (Check-In → fim de Finalizado = tempo total;
  Check-In → início de Em Atendimento = espera; etapa Chamado = fila), `sinalizar_outliers` (IQR de Tukey ou MAD, em escala log, por grupo, com piso, teto e cerca global para grupo
  pequeno), `ratear_por_janela` (reparte cada intervalo pelas horas que ele toca; `resample` sozinho joga o intervalo inteiro na hora do início), `intervalos_de_uso`
  (ociosidade = buraco entre exames, com sentinelas e fusão de usos sobrepostos), `perfil_por_hora`, `carga_por_hora`, `pico_de_gargalo` e `construir_tabelas` (as mesmas
  contas como tabelas planas para BI: `janelas_hora`, `janelas_dia`, `gargalo_dia`, `ocupacao_hora`, `ocupacao_dia`, `limites`). `Tempo/exemplo_tempo.py` roda tudo com dados sintéticos.
  O raciocínio e os números dos dados reais estão em `Tempo/RELATORIO.md`.
- **Regras a não esquecer:** a hora é a do **Check-In**; mediana e 90% de cada hora e dia são recalculados dos atendimentos (nunca média de médias); a **cerca de outlier vem do
  histórico inteiro** (por etapa e setor), não do mês mostrado, para o limite não mudar de um mês para o outro; o atendimento com tempo fora do normal continua contado nas
  chegadas, só não entra nas medianas; fora do expediente a ociosidade não conta.
- **Limite dos dados:** só parte dos exames traz o **equipamento** na coluna "Profissional / Equipamento" (em setembro, 124 de 1.374 linhas de RM/TC); nos outros a coluna traz o
  nome do profissional. Por isso a seção de equipamentos mostra a **cobertura** (exames identificados ÷ total) ao lado dos percentuais e a "ociosidade" pode incluir máquina parada
  (não há log de status do equipamento). Para ociosidade confiável é preciso saber a máquina de cada exame ou receber os eventos do equipamento.
- **Testes:** `tests/test_tempo.py` (contas, com respostas feitas à mão) e `tests/test_tempo_painel.py` (página gerada de dados inventados em `tests/paineis_de_mentira.py`, nos três
  períodos do filtro, e aberta no Chromium: sem erro de JavaScript, sem sobra horizontal no celular). Painel novo precisa entrar na lista `todos` de `tests/test_nuvem.py` (permissões).
- **Não verificado:** o tema escuro da tela (os mesmos tokens de cor do resto do site), o tempo da página com o volume real de um ano e o deploy na Vercel de verdade.

## Aba NPS × Google

A satisfação medida pela clínica ao lado da nota pública no Google Maps, com análises para decidir o que melhorar. Painel `nps` (`Nps/`), **sem dinheiro** (`"financeiro": "nenhum"`);
nasce bloqueado e é liberado por usuário em Configurações. Aparece no menu como **NPS × Google**.

- **NPS (Klingo):** relatório **#13697 "Relatorio NPS - Notas por Marcação"** (migration `20261020120000_cadastra_relatorio_nps_13697.sql`: coleta mensal desde set/2026, como o #13402). Colunas:
  Data Agendado Para, Id da Marcação, NPS - Nota, NPS - Classificação, NPS - Data de Resposta, NPS - Comentário, Profissional, Procedimento, Unidade (sem nome de paciente). Passa pelo mesmo caminho dos
  outros painéis (`Nps/relatorios.json` → `fonte_banco` → `painel_dados`); o mês é o do **agendamento** e a chave é o Id da Marcação. A classe vem da nota (9-10 promotor, 7-8 neutro, 0-6 detrator, igual à do Klingo).
- **Contas em `Nps/metricas_nps.py`** (pandas puro, testado à mão em `tests/test_nps.py`): NPS, **margem de erro de 95%** (variância da diferença de proporções; uma diferença só vale como mudança quando passa de √(m₁² + m₂²)),
  **contribuição ao NPS** de cada grupo (a soma dos grupos é o NPS geral), temas dos comentários por palavras (`Nps/parametros.json`, com "negacao" para o elogio não contar "não recomendo"), **pontos de NPS que cada tema custa**
  (detratores que falam dele ÷ respostas × 100) e o **caminho até a meta** (quantos detratores converter ou quantas respostas novas de promotores, em conta exata com `Fraction`: com `float` dava 51 onde o certo é 50).
- **O que a página mostra:** Resumo (NPS com margem, meta e comparação com o período anterior, respostas por dia, detratores, nota média, nota do Google, leitura automática em frases); **NPS × Google** (tabela lado a lado, mês a mês,
  avaliações do Google e os assuntos das de 1 a 3 estrelas); Análise (distribuição das notas, unidades, assuntos dos comentários, dia da semana e hora do agendamento, profissionais e procedimentos, onde estão os detratores, dia a dia, meta);
  Voz do cliente (comentários dos detratores e neutros, com filtro por assunto) e Detalhes (tabelas). Grupos com menos de `minimo_grupo` respostas aparecem em cinza e ficam fora dos rankings.
- **Google Maps pela API oficial (Places API New),** `Nps/google_maps.py`: a página de avaliações do Google carrega por JavaScript e raspá-la viola os termos. A API entrega **nota, total de avaliações e até 5 avaliações** (as "mais
  relevantes", não as mais novas). Por isso a cada atualização (automática a cada 5 h, no máximo; o botão pode repetir depois de 30 min) o painel guarda o **resumo do dia** (aba `Google` do `painel_dados` do painel `nps`) e as **avaliações
  ainda não vistas** (aba `Google avaliações`). O histórico da nota **só começa no dia em que a coleta é ligada** e a lista de avaliações é uma amostra que cresce com o tempo. Como fica no `painel_dados`, a página pronta se refaz sozinha
  quando entra dado novo. Falha do Google (chave, cota, rede) vira aviso e nunca derruba a atualização do NPS. Só funciona na nuvem; no programa local o painel mostra só o NPS.
- **Para ligar o Google (uma vez):** criar uma chave de API no Google Cloud com a **Places API (New)** ativada e guardá-la na Vercel como **`GOOGLE_PLACES_API_KEY`** (nunca em arquivo do projeto); opcional: **`GOOGLE_PLACE_ID`** (ChIJ...) se o painel
  não achar o perfil. Sem `GOOGLE_PLACE_ID`, o perfil é achado pela busca "Clínica CSI" e conferido pelo **CID** `13831494129270129913` (o `0xbff356a0d00c04f9` do link do Maps da clínica), em `Nps/parametros.json`.
- **Comparar NPS e Google é por tendência, não por igualdade:** perguntas e públicos diferentes. O painel compara a nota média do NPS ÷ 2 com as estrelas e mostra um "NPS equivalente" do Google (5★ promotor, 4★ neutro, 1-3★ detrator)
  só quando há `minimo_google_equivalencia` avaliações no período. `unidades_no_google` (null = todas) tira do NPS comparável uma unidade que tenha perfil próprio no Google (ex.: Desenvoar).
- **Dados de paciente:** o relatório não traz nome, mas os **comentários são texto livre** e podem citar nomes e detalhes. O Id da Marcação não vai para a página; a tela avisa para não compartilhar os comentários.
- **Testes:** `tests/test_nps.py` (contas com respostas feitas à mão, assuntos e o cliente do Google com a API simulada) e `tests/test_nps_painel.py` (página gerada de dados inventados em `tests/paineis_de_mentira.py`, nos três períodos do
  filtro, com e sem Google, e aberta no Chromium: sem erro de JavaScript, sem sobra horizontal no celular, filtro por assunto).
- **Não verificado:** a chamada real à API do Google (só com a chave), o volume real de um ano de respostas e o deploy na Vercel. A taxa de resposta (respostas ÷ atendimentos) não é calculada: o #13402 não traz o Id da marcação.

## Aba Metas

Fonte dos dados: relatório `13339` do Klingo (atendimentos por unidade,
classe, especialidade, procedimento e operadora), sincronizado para
`fact_relatorio_linha` como qualquer outro relatório. Fonte das metas e
regras: **`Acompanhamento de META/metas.json`** — o mesmo arquivo do painel
local; o site o lê direto. Para mudar uma meta, edite o arquivo e publique;
`metas_por_mes` ajusta só um mês (`{"2026-11": {"csi1/densitometria": 520}}`).
O calendário (seg–sáb, feriados, expediente 07h–18h, `primeiro_mes`) também
vem dele; o dia de hoje conta só a parte do expediente que já passou.

- A função `metas_atendimentos_mes(mês)` (migration `20261013120000_aba_metas`)
  entrega os atendimentos do mês já contados. Cada atendimento conta uma vez
  (ID = coluna "Exames Realizados", versão mais recente) e o que o Klingo
  deixou de devolver no último sync do dia deixa de contar. Aplica a
  permissão `permissions.metas` (padrão: liberado, como Relatórios).
- A função precisa saber qual `colN` é qual coluna; por isso a
  `sync-relatorios-dw` passou a gravar o título de cada coluna em
  `dim_relatorio_coluna.titulo_klingo`. Enquanto nenhum sync com essa versão
  rodou para o `13339`, a aba mostra "Nenhum atendimento".
- Atendimentos que não entram em nenhuma meta aparecem em "fora de qualquer
  meta"; os que entram em mais de uma geram um aviso (ajuste as regras).
- **Metas com SUS × só pagante** (logo abaixo do gráfico "SUS e não SUS"; `app/(app)/metas/ComparacaoPagante.tsx`). A meta é a mesma: a seção mostra
  quanto dela estaria cumprida se só o pagante contasse (pagante = convênio informado que não é SUS, particular incluído; sem convênio informado não
  entra em nenhum dos dois lados e é avisado). Barras duplas (geral, grupo e serviço), dois gráficos de linha (cumprimento acumulado com SUS × só
  pagante × esperado, e participação do pagante em média de 7 dias) e uma leitura automática (`analisarPagante()`). **Só quantidade e porcentagem,
  nunca R$**: as Metas não trazem receita, então não há valor a esconder de quem não tem "Dados financeiros". Os gráficos de linha vêm de
  `metas_atendimentos_por_dia(de, ate)` (migration `20261018100000`, mesma regra de contagem, uma linha por dia); sem ela aplicada no banco a seção
  aparece só com as barras e o aviso de que a evolução dia a dia não está disponível.

**Para colocar no ar:** aplicar a migration, publicar a Edge Function
`sync-relatorios-dw` e, na aba Metas (como admin), clicar em "Atualizar" para
o mês desejado (um mês por vez, máx. 31 dias).

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

### Coleta inteligente (janela de 90 dias, sozinha)

Todos os relatórios do catálogo (menos os `supersedido_por`) ficam `ativo = true`. Para o site
não ficar lento, **o navegador não percorre mais nada**: o banco sabe o que falta e a Edge Function
`sync-relatorios-dw` (modo `{"modo":"auto"}`) busca só isso.

- `proximos_trabalhos()` lista os pares (relatório, dia) que faltam dentro de `dim_relatorio.janela_dias`
  (máx. 90), dos dias mais recentes para os mais antigos. Dia só vale como completo se o sync terminou
  depois da meia-noite dele; o dia de hoje é refeito no máximo a cada 60 min. Relatório `pontual`
  (ou que não aceita filtro de período) é buscado uma vez.
- Um job do pg_cron (`coleta-relatorios-5min`) chama a função a cada 5 minutos, em lotes de até 40
  consultas e no máximo 100 s. Sem pendência, ela responde na hora sem tocar no Klingo. O botão
  **Atualizar tudo** só antecipa o mesmo trabalho (lotes de 30, com barra de progresso).
- Disjuntor: 3 falhas seguidas pausam o relatório por 6 h (`falhas_seguidas`, `pausado_ate`); um par que
  falhou só é tentado de novo depois de 30 min. Os alertas continuam em `v_etl_pendencias`.
- **Descoberta:** relatório que nunca foi sincronizado começa com `janela_dias = 1` — só o dia de hoje,
  o bastante para o sistema registrar as colunas (`dim_relatorio_coluna`) e mostrar se ele funciona.
  Depois de conferir as colunas, defina o essencial e libere os 90 dias:

```sql
-- só estas colunas serão gravadas (NULL = todas)
update public.dim_relatorio
set colunas_essenciais = array['col0','col1','col4'], janela_dias = 90
where klingo_id = '13339';
```

  Ao mudar `colunas_essenciais` de um relatório que já tem dados, apague antes as linhas dele em
  `fact_relatorio_linha` (e os `sync_relatorio_runs` dele, para o histórico ser refeito); senão as linhas
  antigas, com todas as colunas, ficam ao lado das novas e o mesmo dia é contado duas vezes.
- **Dados de paciente:** nos relatórios que os painéis não usam (#12757, #13256, #13434, #13510, #18, #19, #275, #319, #47, #52,
  #681), `dim_relatorio.colunas_essenciais` já deixa de gravar nome, telefone, matrícula, prontuário, CID e observações livres;
  ficam os IDs. As linhas gravadas **antes** dessa regra continuam no banco com essas colunas (nada é apagado sozinho); para
  apagá-las de um relatório: `delete from public.fact_relatorio_linha where relatorio_id = (select id from public.dim_relatorio where klingo_id = '275');`
  (e depois deixe a coleta refazer os dias). Os relatórios dos painéis em Python (#13374, #13376, #13280...) gravam todas as colunas
  porque os painéis as usam.
- Vários relatórios (Faturamento, Financeiro, Cesta etc.) também são baixados pelos painéis em Python
  para `painel_dados`. Não é preciso mantê-los nos dois lugares: se um painel já cobre o relatório,
  deixe `ativo = false` aqui (`update public.dim_relatorio set ativo = false where klingo_id = '...'`).

### Regras para somar e cruzar os dados

- **Leia por `v_relatorio_linha_vigente`, não por `fact_relatorio_linha`.** A tabela guarda o histórico (linha que
  mudou vira registro novo); a visão devolve só o que a última coleta de cada relatório/dia viu. Somar a tabela
  crua conta em dobro.
- **`repeticoes`** é quantas linhas idênticas o Klingo devolveu no mesmo dia (ex.: #13374 devolve 2.605 além das
  6.049 distintas). Para contar registros como o painel em Python, que deduplica pela chave, conte 1 por linha.
- **Período:** o Klingo ignora, sem erro, um filtro com nome errado e devolve o dia de hoje (ou a tabela inteira).
  Por isso `dim_relatorio.filtro_periodo` guarda o nome certo de cada relatório (`periodo0`, `periodo`, `PERIODO`,
  `para`...; NULL = sem filtro de data) e a coleta confere na resposta que o período foi aplicado. Só depois dessa
  confirmação (`periodo_validado_em`) o relatório recebe mais de 1 dia de histórico. `v_qualidade_relatorios` e a
  auditoria diária (`auditar_qualidade_relatorios`) apontam relatório que repete as mesmas linhas em vários dias.
- **Números:** o Klingo alterna `1` e `"1"` entre chamadas iguais; a coleta grava tudo como texto.
- **Guias:** use sempre o `Guia - Id` como chave. O "Número da Guia Atribuído pela Operadora" vem vazio em ~40% das
  guias e, em centenas, preenchido com valores falsos (`00`, `00000000`...) para pacientes diferentes; cruzar por
  ele junta guias que não têm nada a ver. O `Atendimento - Id` e o paciente batem entre os relatórios #13374, #52 e
  #319 (189 atendimentos em comum, nenhuma divergência).

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
  chave privilegiada existe no site (Next.js); as funções Python dos painéis são a exceção (ver "Painéis em Python"). O secret `cron_service_role_key`
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

> **Configurações → usuários:** criar usuário e redefinir senha usam `SUPABASE_SERVICE_ROLE_KEY` (só no servidor, Production **e** Preview na Vercel).
