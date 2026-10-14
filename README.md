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
- `app/login/` — tela de login (usuário/senha via Supabase Auth).
- `app/(app)/layout.tsx` — menu lateral (Relatórios / Configurações) das
  telas logadas; vira barra no topo no celular. "Configurações" só aparece
  para quem tem `role = admin`.
- `app/(app)/page.tsx` — aba "Relatórios": filtro de período (padrão: últimos
  30 dias, com atalhos 7/30/90 dias e "Este ano"), cards de totais com
  tendência, gráfico agendados × realizados e tabela por dia (com total).
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
  aviso de sucesso/erro. Protegida tanto na página quanto por RLS.
- `supabase/functions/sync-indicadores/` — Edge Function que busca a API
  externa e grava os dados no banco.
- `supabase/functions/sync-relatorios-dw/` — Edge Function genérica que
  sincroniza qualquer relatório cadastrado em `dim_relatorio` (ver seção
  "Data warehouse de relatórios" abaixo).

## Painéis em Python (Faturamento, Financeiro, Despesas, Indicadores, Cesta, Suprimentos, Atendimento)

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
- **Atualização (do banco):** os painéis **não consultam mais o Klingo**. Uma coleta só (Edge Function `sync-relatorios-dw`,
  pg_cron a cada 5 min) guarda os relatórios em `fact_relatorio_linha`; `fonte_banco.py` copia dali para `painel_dados`, no
  formato que os geradores já liam. O relatório dos painéis é coletado **por mês** (`dim_relatorio.granularidade = 'mes'`,
  com `primeiro_mes`, `meses_a_frente` e `revisar_meses` vindos do `relatorios.json`), exatamente como o painel pedia ao
  Klingo; as Metas (#13339) vêm dia a dia. Cada mês coletado por inteiro **substitui o mês inteiro** guardado (troca atômica);
  mês que o banco ainda não coletou, relatório sem filtro de período comprovado, desativado ou sem título de coluna ficam
  como estavam e viram aviso. Só regrava o mês cujo dado no banco é mais novo que o do painel. O botão **Atualizar agora**
  (só administrador) copia na hora; além disso, quando alguém abre um painel cuja última atualização tem mais de **5 h**, ele
  copia sozinho (`portal_nuvem.sincronizar_se_vencido`, também no cron diário). `PAINEL_FONTE=klingo` (variável da Vercel)
  volta ao caminho antigo, que consulta o Klingo direto.
- **Horário:** as funções rodam com fuso de Brasília (`TZ=BRT3`), senão "hoje" viraria amanhã depois das 21h.
- **Cron (opcional):** `vercel.json` agenda `/api/preaquecer` todo dia às 06:30 (Brasília) para refazer as páginas e o primeiro
  acesso do dia não esperar a conta (a Cesta chega a levar mais de 1 min). Só funciona se existir a variável `CRON_SECRET`.
- **Não existe na Vercel:** exportar PDF (precisa do Chromium do `exportar_pdf.py`), acesso em rede/`.exe`, usuários próprios
  do portal e as "visões" em PDF do Atendimento. A aba **Metas** continua sendo a do site (abaixo); a base das Metas em Python
  só existe para o Atendimento.

### Visual e filtros padronizados

Todas as abas (Início, Metas, Configurações e os 7 painéis em Python) seguem o mesmo padrão do site:

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

### Para colocar no ar

1. **Banco:** aplicar `supabase/migrations/20261013130000_paineis_python.sql` e, para a aba Avisos,
   `supabase/migrations/20261014210000_avisos.sql` (SQL Editor do Supabase).
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

### Testes

`python -m unittest discover -s tests -v` — sobe um Supabase e um Klingo simulados (`tests/mock_nuvem.py`) e confere login,
permissões, atualização (mês substituído, não somado), tipos das colunas, página pronta guardada e invalidada, avisos e
corte por tempo. A regra da aba Avisos dentro do banco (novo / resolvido / voltou / justificado, permissões e RLS) é testada num
Postgres de verdade: `createdb avisos_teste && psql -v ON_ERROR_STOP=1 -d avisos_teste -f supabase/tests/avisos.sql`. Os 7 painéis também foram gerados de ponta a ponta com dados de mentira e o botão **Atualizar agora**
foi exercitado no Chromium. **Não foi testado:** o deploy na Vercel de verdade (funções Python junto do Next.js, tamanho do
pacote com pandas, tempo da carga inicial) nem o Klingo/Supabase reais — confira o primeiro deploy e o log das funções.

## Aba Avisos

Todas as pendências dos painéis num lugar só (menu **Avisos**, com o contador de abertos). Cada alerta com guia que um painel calcula
(os mesmos de "Como achar o problema") vira um **aviso**. **O administrador vê tudo; os demais só os avisos dos painéis liberados
em Configurações** (RLS: `can_view_painel`, a mesma regra de `profiles.permissions.<painel>`).

**Como os avisos nascem e se atualizam.** Quando a página de um painel é refeita (dados novos, novo dia ou **Atualizar agora**),
`portal_nuvem.registrar_avisos` pega os alertas dela (`avisos.py`) e chama `aviso_sincronizar` no Supabase. Só a página padrão
conta (não um período escolhido no filtro) e, para os alertas de um mês, o mês atual e o anterior (`JANELA_MESES`); aviso de um mês
que saiu da janela fica como estava. Painel sem dados não resolve nada. Falhar aqui nunca impede de abrir o painel.

| O que o painel mostra agora | O que acontece com o aviso |
| --- | --- |
| alerta novo | aviso **aberto** (histórico: "apareceu nos dados") |
| continua aparecendo | segue aberto |
| deixou de aparecer | **resolvido** (o painel segue conferindo) |
| estava resolvido e **voltou** | aberto de novo, selo **"Voltou a acontecer N×"** |
| fechado com justificativa, os dados foram atualizados e **continua** | aberto de novo, selo **"Reaberto N×"** (a justificativa não resolveu) |
| fechado com justificativa e **some** | resolvido e confirmado |

**Fechar exige justificativa** (mínimo de 15 e máximo de 1000 caracteres; conferido no formulário, na action e no banco). O aviso
fica "fechado com justificativa" até a próxima atualização dos dados: se o problema sumiu, vira resolvido; se continuar, reabre.
"Ainda não resolvi" desfaz o fechamento. Quem justificou, quando e o texto ficam no aviso e em todo o **histórico**.

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
