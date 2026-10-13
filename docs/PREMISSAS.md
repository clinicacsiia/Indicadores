# Premissas, dúvidas e o que foi reconstruído

Regra do projeto: **não mudar regra de negócio, limite, definição, texto de alerta ou número**. Onde faltou informação, o comportamento do legado
foi mantido ou, se o arquivo não veio, está registrado aqui como **reconstrução** para você conferir.

## 1. O que veio do legado e o que NÃO veio

Veio (copiado sem alteração de regra em `legado/`, e usado em `painel_py/`): os 8 `gerar_*.py`, `equivalencias.py`, `extrair_laudo.py`,
`gerar_dashboard.py` (Metas), os 8 `dashboard_modelo.html`, os `relatorios.json`, `metas.json`, `parametros.json`, `responsaveis.json`, `config.json`.

**Não veio** (e foi reconstruído a partir de como os `gerar_*.py` os usam e da descrição do prompt):

| Arquivo ausente | Reconstruído em | Como | Risco |
|---|---|---|---|
| `painel_comum.py` | `painel_py/painel_comum.py` | `Periodo`, `periodo_pedido`, `reagrupar`, `acrescentar_periodo`, `agrupar`, `limpo`, `montar_html`, `rotulo_mes`… a partir dos usos e dos comentários dos `gerar_*.py` | **Médio.** `nome_curto_unidade` só tira espaços (o legado pode encurtar nomes). `agrupar` ordena do maior para o menor e devolve `{nome, valor, pct}` |
| `klingo_relatorios.py` | `painel_py/klingo_relatorios.py` (leitura) + `src/klingo/` (sincronização) | Leitura: `carregar`, `ler_definicao`, `planilha_de`, `mes_mais`, `meses_entre`, `COL_MES = "Mês (filtro)"`. Sincronização: reescrita em TypeScript a partir de `extrair_laudo.py` e das armadilhas do prompt | Médio. `COL_EM = "Atualizado em"` é um palpite (só é usado para ignorar colunas de controle) |
| `guia_pendencias.py` | `painel_py/guia_pendencias.py` + `guia_regras.py` | `tabela`, `reais`, `dbr`, `anotar`, `MAX_ITENS = 25` | **Alto para os textos:** os passos de "Como achar o problema" e "quando considero resolvido" foram **escritos de novo** (uma regra por alerta). Revise com quem opera o Klingo |
| `painel_base.js` / `.css` | `painel_py/painel_base.js` / `.css` | API deduzida das chamadas nos modelos: `kpi`, `comp`, `linhas`, `barras`, `donut`, `empilhada`, `miniLinha`, `tabela`, `acordeao`, `tier`, `alertasTopo`, `iniciarPeriodo`… | **Alto para o visual:** a aparência é nova (mesma estrutura Resumo → Análise → Detalhes). Para ficar idêntico, envie os arquivos originais e eles substituem estes |
| `servidor_portal.py`, `autenticacao.py`, `exportar_pdf.py`, `banco_dados.py`, `conferir_numeros.py`, `portal.html`, `login.html`, `modulos.json`, `LEIA-ME.md`, `Documentacao/` | site novo (`src/`) | Reescritos a partir da descrição do prompt | Regras de senha (`_validar_senha`/`_validar_nome`) são **minhas**: nome 2–32 caracteres `[A-Za-z0-9._-]`; senha ≥ 8, com letra e número, sem o nome do usuário, fora de uma lista de senhas comuns |

> **Golden master (paridade campo a campo com o legado) ainda não foi possível**: faltam os `.xlsx` reais e os módulos acima. O script
> `scripts/gerar_fixtures_legado.py` fica para quando os arquivos chegarem. Hoje só há testes com dados **sintéticos**
> (`tests/python/`, `scripts/gerar_dados_sinteticos.py`). Até lá, **nenhum número foi conferido contra o programa atual**.

Os menus **Financeiro, Despesas, Cesta** foram testados só até "importa e abre sem dados"; com dados sintéticos aleatórios rodaram Metas,
Faturamento, Indicadores, Suprimentos e Atendimento. Os três primeiros precisam dos dados reais para exercitar todos os caminhos.

## 2. Divergências deliberadas em relação ao prompt (e por quê)

1. **Cálculo em Python (pandas) na Vercel, não portado para TypeScript.** Os 8 `gerar_*.py` somam ~5 mil linhas de pandas com regras finas.
   Portar sem os dados reais para comparar seria arriscado; manter o código reduz a chance de mudar um número. Contrato mantido: mesmas
   entradas → mesmo `D` (o JSON dentro da página). O prompt aceita essa alternativa desde que justificada; confirmar na primeira implantação que
   pandas+numpy cabem no limite de tamanho da função (≈ 130 MB, limite 500 MB).
2. **Dados do Klingo em blocos (`dados_blocos`), não uma tabela tipada por aba.** Um bloco = uma aba de um mês (JSON + gzip + base64, com os
   títulos originais das colunas). Motivos: o painel lê o mês inteiro de uma vez (≈ 45 mil linhas de Atendimento), a API do Supabase devolve
   1.000 linhas por pedido, e o Klingo muda colunas sem avisar. Substituir o mês continua sendo uma transação (`gravar_bloco`). Tipos
   (número/data) vêm das listas `numeros`/`datas` do `relatorios.json`, como no legado.
3. **Configuração dos relatórios em `painel_py/<Menu>/relatorios.json`** (fonte única, lida pelo Python e pelo TypeScript), não em
   `config/<menu>/`: o cálculo em Python precisa dos mesmos arquivos ao lado dos `gerar_*.py`.
4. **Pedido de cadastro não guarda senha.** O usuário é criado no Supabase Auth já bloqueado ("banido") e só é liberado quando um admin aprova.
5. **Sessão de 8 h por cookie assinado** (o Supabase Pro tem "sessão com prazo"; no plano gratuito não). Trocar/redefinir a senha derruba as
   outras sessões (`perfis.sessoes_validas_desde`).
6. **Bloqueio de login em tabela do Supabase** (`tentativas_acesso`), sem Redis: 5 erros do usuário → 1 min; 12 erros do mesmo IP em 10 min → 5 min.
7. **PDF:** `puppeteer-core` + `@sparticuz/chromium`; a tela pede um painel por chamada e junta com `pdf-lib` no navegador (marcadores por
   painel). Não há fila no Storage nem progresso por Realtime (o progresso é por painel, na própria tela).
8. **Não reaproveitado de propósito:** servidores `.exe`, `servidor.json`, `rede.json`, TLS próprio, firewall, lista de IPs, `.pid`, backups em
   pasta, cache `.pkl` (Atendimento ainda tenta gravar um e ignora a falha em pasta somente-leitura), SQLite, Excel como armazenamento,
   Playwright na captura, login por Chrome, senha padrão. O app antigo (Next.js com `profiles`/`dim_relatorio`) foi substituído (ver `OPERACAO.md`).

## 3. Reconstruções que merecem conferência (comportamento do site novo escolhido por mim)

- **Período De/até:** `periodo_pedido` recorta ao que existe e diz qual (`aviso`); sem dados nenhum, avisa. O período anterior só é calculado se
  **todos** os meses dele existem. O período escolhido vale para as outras abas (guardado no navegador e repassado ao abrir cada painel).
- **`Mês (filtro)` de relatório sem filtro de data** (Guias, Baixas): é o mês em que foi baixado.
- **Número que vem como texto**: com vírgula = formato brasileiro (`1.234,56`); sem vírgula, o ponto é decimal (`1234.5`).
- **Metas:** mês corrente = código `m`, anterior = `ma` (como `extrair_laudo.py`); meses antigos = intervalo livre `l` com datas (não confirmado
  que o #13339 aceita `l`; se recusar, o histórico anterior vem das planilhas na importação).
- **Atualizar agora:** não-admin precisa de dados com mais de 5 min; admin sempre. "Indicadores" atualiza também Faturamento e Financeiro.
  Verificação automática a cada 30 min só atualiza menu com dados mais velhos que 30 min (não grava histórico quando pula).
- **Realtime** avisa por `dados_versao`; os painéis abertos recarregam sozinhos; o painel não recarrega quando a resposta é `atualizou: false`.

## 4. Premissas do usuário ainda NÃO confirmadas (mantidas como estão no código/config, sem mudar critério)

Ajustáveis nos arquivos indicados:

- Klingo em uso desde 09/2026 → `primeiro_mes: 2026-09` (cada `relatorios.json`), Metas/Atendimento ignoram meses anteriores.
- Despesas: `inicio_confiavel: 2026-09` (jun–ago fora de médias/previsão); recorrente = 2+ meses; previsão por mediana; tendência com 3 meses fechados.
- Cesta: `ajustar_ao_faturamento: true` (chave que desliga o ajuste); SUS CURSO incluído; fator > 60× ignorado; faixas 90–99 e 120–129 → "90+".
- Metas (`metas.json`): neuropediatria, ortopediatria, endocrinopediatria, cardiopediátrica e puericultura **não** entram em Consultas Pediátricas
  (só especialidade = PEDIATRIA e procedimento = CONSULTA); "Coleta de material cérvico-vaginal" **não** entra no Preventivo (só procedimento que contém PREVENTIVO).
  Pendente (você pediu para NÃO mexer): esperado ponderado por dia da semana.
- Atendimento (`parametros.json`, copiado intacto): espera 30/60 min, válida ≤ 480, exame válido ≤ 360, duração × 1,5 dos pares (≥ 20),
  produtividade < 60% da mediana (≥ 3 dias, ≥ 3 colegas), registro com problema 3%/10%, meta baixa ≥ 130% / alta ≤ 60%, diferença entre relatórios 5%.
- Faturamento: limites 7/30 dias de espera, 10% de falta faturar, 20% de cancelamento; Financeiro: despesa "paga" = lançamento com Conta preenchida.
- Suprimentos: pedido pendente > 15/30 dias, sem baixa > 7/15 dias, cobertura < 15 dias; registros de fev/jun/jul/ago são testes de implantação.

## 5. Decisões de negócio abertas (responda quando puder)

1. Faturado com 28 faturas enviadas **sem protocolo** (hoje ficam à parte).
2. Pré-fatura = fatura "A Enviar" (aproximação) — confirmar.
3. Antecipado: sem fonte no Klingo hoje.
4. Previsto de pagamento, glosa acatada e fontes novas (as 6 do `Mapeamento de Indicadores.md`, que **não veio** — envie para `docs/`).
5. Metas: pediátricas e preventivo (acima).
6. **Call center (Juliana):** nenhuma coluna identifica o canal; a visão dela cobre só CSI 2.
7. A Cesta deve mesmo ser ajustada ao Faturamento? R$ 0 na Cesta é retorno/cortesia?
8. A retenção do Honorário Médico não está sendo lançada?
9. Custo por frasco do Ultravist (Suprimentos).
