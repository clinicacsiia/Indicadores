# Plano: auditoria dos números em R$ (todas as abas)

Só o plano. Nada no sistema foi alterado. As consultas ao banco foram de leitura (somas e contagens, sem dados de paciente), feitas em 22/10/2026.

## 1. O problema, em português de TI

Hoje o mesmo dinheiro aparece com nomes e valores diferentes porque **cada relatório do Klingo conta o dinheiro por uma data diferente**.
O "filtro" que você percebe mudando o valor não é um botão de Receita × Faturamento: é a **data-base** do relatório, que decide em que mês a linha cai.

| Data-base | Pergunta que ela responde | Relatórios / abas |
| --- | --- | --- |
| Data do atendimento (*competência* da produção) | Quanto a clínica **realizou** no mês? | #26, #13402, #13280, #13285 (Faturamento, Indicadores, Cesta, Atendimento) |
| Emissão do lançamento | O que foi **lançado** no mês | #798 (Financeiro) |
| Vencimento | O que **vence** no mês (a pagar / a receber) | Financeiro, Despesas (depois de cruzar com o #798) |
| Competência da despesa | A que mês a despesa **pertence** | #13505, #13509 (Despesas) |
| Emissão da fatura | O que foi **faturado** ao convênio | #13355 (Faturamento) |
| Recebimento | O que **entrou** | #13295, #13297, #13329 |

Um mesmo ID (lançamento, fatura, atendimento) cai em meses e valores diferentes conforme o relatório e a data-base. O painel então **cruza** relatórios (ex.: Despesas busca o vencimento no #798 pelo ID do lançamento). Se o cruzamento falha, o valor vai para o mês errado ou some.
Também há valor diferente para o mesmo ID por **bruto × líquido** (retenções) e por **mais de uma linha por ID** (um lançamento com várias contas ou categorias).

## 2. O que já foi encontrado (confirmado no banco)

1. **Quatro relatórios dão quatro "produções" para o mesmo mês** (setembro/2026):
   #26 = R$ 1.433.947 · #13402 = R$ 1.398.266 · #13280 = R$ 1.342.400 · #13285 = R$ 1.083.149.
   A diferença vai de 2,5% a 24%. Cada painel usa um deles e chama de "receita" ou "produção". É a causa mais provável de você não confiar nos números.
2. **Financeiro: coleta por emissão, tela por vencimento.** O #798 é baixado por mês de **emissão**, mas o painel agrupa por **vencimento**.
   Em setembro há R$ 5,0 milhões de despesas *emitidas* (financiamento, folha etc., com vencimentos futuros), contra R$ 0,6 milhão de despesas por competência no #13505 (Despesas).
   Quem foi emitido antes de setembro e vence depois **não está no banco**. Os meses a vencer ficam incompletos sem aviso na tela.
3. **Coleta avulsa de 13/10 sobreposta ao mês.** Os 12 relatórios mensais têm um período extra `2026-10-13` dentro de outubro (ex.: #26 com 329 linhas, #798 com 142).
   No #798, 142 IDs estão nos dois períodos e 6 deles têm **valores diferentes** (soma das diferenças: R$ 1.015). Os painéis em Python leem só o período `-01` e não são afetados, mas qualquer consulta SQL ou tela que some o mês inteiro conta em dobro.
4. **Meses futuros repetidos.** Despesas (#13505/#13509) de jan a abr/2027 têm o **mesmo total** (R$ 373.118,65) em cada mês. Parece previsão de recorrentes, e precisa estar rotulada como previsão, não como realizado.
5. **Relatórios com pouco ou nenhum dado.** O #13295 (créditos de convênio) tem **1 linha** em setembro e o #13375 (glosas) tem **0 linhas** (filtro nunca comprovado). Os cartões de "recebido" e "glosa" saem subestimados ou zerados. O #13329 mostra "A Receber (Saldo)" em poucas linhas.
6. **Mesmo ID com mais de uma linha** (#798: 191 IDs). O `relatorios.json` deduplica pela chave `Lançamento` (`keep="last"`), então pode estar **descartando contas legítimas** ou somando duas vezes, conforme o relatório. Precisa ser provado, não presumido.
7. **O `conferir_numeros.py` está desatualizado.** Ele lê planilhas Excel de uma pasta do computador da clínica, e hoje os dados vêm do Supabase. Cobre só 4 painéis (não Indicadores, Despesas, Atendimento, Suprimentos).

O que **não** consegui confirmar: o botão/filtro exato que você viu trocando o valor. As telas só têm seletor de mês (o rótulo diz competência ou vencimento) e, em Despesas, "Medida" e bruto × líquido. Veja a pergunta 1 na seção 6.

## 3. Princípios da auditoria

- **Primeiro medir, depois corrigir.** As fases 1 a 5 não mudam nenhum dado nem tela.
- **Fonte da verdade = o Klingo.** Para cada indicador, o número tem que bater com o que a pessoa da área vê no Klingo, ou ter uma explicação escrita da diferença.
- **Uma conta independente.** O recálculo da auditoria é feito direto do banco, com lógica separada da dos painéis, como o `conferir_numeros.py` já faz.
- **Todo achado vira teste.** Corrigiu uma vez, não volta.

## 4. Fases

### Fase 0: Preparar (meio dia)
- Congelar um retrato: salvar os totais atuais de cada cartão em R$ de cada aba, por mês (set e out/2026), como "linha de base" para comparar depois das correções.
- Combinar com 1 pessoa do faturamento e 1 do financeiro (ou contabilidade) para 2 sessões de validação (fases 5 e 6).

### Fase 1: Inventário de todos os valores em R$ (1 a 2 dias)
Montar uma planilha/tabela única, uma linha por indicador em R$ de cada aba:
**aba → cartão/gráfico → nome na tela → campo no JSON → relatório e coluna do Klingo → data-base → conta (soma, média, saldo) → filtros aplicados → quem usa o mesmo número em outra aba.**
- Gerar o rascunho automaticamente (lista de campos de dinheiro: `sigilo.CHAVES`, `RAIZ`, `COLUNAS_DE_DINHEIRO`, mais as chamadas `brl()` dos `dashboard_modelo.html`).
- Marcar cada indicador com o termo oficial da nomenclatura do README (produção, faturado, recebido, receita, despesa, custo, repasse) e apontar onde a tela usa outro nome. Esse é o "erro de nomenclatura" que você suspeita.
- Entregável: `docs/auditoria/inventario-dinheiro.md` (ou CSV).

### Fase 2: Auditoria da carga, banco e coleta (2 dias)
Consultas SQL de leitura, todas viram verificações permanentes depois:
1. **Cobertura por relatório e mês:** período coletado, atraso da última coleta, meses sem dado, filtro de período comprovado (`periodo_validado_em`), relatórios ativos sem linhas (#13375, #13295).
2. **Períodos avulsos:** qualquer `periodo` fora do padrão (dia ≠ 1 em relatório mensal) e sobreposição com o mês cheio (caso `2026-10-13`).
3. **Duplicatas:** linhas idênticas repetidas (`repeticoes > 1`), IDs repetidos entre períodos, **mesmo ID com valores diferentes** (#798 e outros que têm ID: #13509, #13355, #13328).
4. **Versões antigas:** confirmar que `v_relatorio_linha_vigente` descarta mesmo as versões velhas e que nenhuma tela soma a tabela crua.
5. **Meses futuros e valores constantes:** achar totais iguais em meses seguidos (caso jan a abr/2027).
6. **Tipagem:** valores de dinheiro que vêm como texto, nulos, negativos, zero, datas absurdas (ano < 1900), moeda com vírgula.
- Entregável: relatório de achados com gravidade (P0 número errado hoje, P1 pode errar, P2 limpeza).

### Fase 3: Auditoria das contas, painel × recálculo (3 dias)
- Reescrever o `conferir_numeros.py` para ler do **Supabase** (não do Excel) e cobrir **todos os painéis**: Faturamento, Indicadores, Financeiro, Despesas, Cesta, Atendimento, Suprimentos e Metas.
- Para cada indicador do inventário, recalcular do banco com outra lógica e comparar com o JSON do painel, por mês, no filtro de mês, no período livre (De/Até) e **com e sem "Dados financeiros"**.
- Testar os filtros de forma sistemática: mês, 7/30/90 dias, período livre cortando mês no meio (os relatórios só por mês entram com o mês inteiro), meses antes do Klingo, bruto × líquido, unidade, responsável (Atendimento).
- Entregável: o script novo, com saída "FALHA / AVISO / INFO" como o atual, e a lista de diferenças.

### Fase 4: Reconciliação entre relatórios (3 dias)
Verificar se relatórios que falam do mesmo dinheiro fecham entre si, e **documentar a diferença esperada** ou marcá-la como erro:
- **Produção:** #26 × #13402 × #13280 × #13285 (hoje 4 valores). Descobrir o que cada um inclui ou exclui (cancelados, cortesias, particular × convênio, SUS, status do atendimento, linhas de pacote/combo, dia 31) e **escolher um único relatório oficial**.
- **Produzido × faturado × recebido:** #13329 (produzido, recebido, glosa, saldo) × #13355 (faturas) × #13328 (faturas em aberto) × #13374 (guias) × #13295 (créditos). Conferir a "escada": produzido ≥ faturado ≥ recebido + glosa + saldo.
- **Caixa:** #798 (receitas e despesas lançadas) × #13505/#13509 (despesas) × #13297 (recebimento particular) × #13376 (baixas/conciliação).
- **Despesas:** bruto (#13505) × líquido (#13509) e o cruzamento por ID com o #798. Medir quantas despesas ficaram **sem vencimento** e quantas "mudaram de mês" (o painel já calcula, mas confira o resultado).
- **Cesta** com a receita "ajustada ao faturamento" × #26.
- Entregável: matriz "relatório A × relatório B, mês, diferença em R$ e %, explicação".

### Fase 5: Validação humana contra o Klingo (2 sessões de 1 a 2 h)
Com a pessoa do faturamento e a do financeiro:
- **Amostra de IDs:** 20 a 30 IDs por tipo (atendimento, fatura, lançamento de receita, lançamento de despesa, crédito), com valor, mês e status no Klingo × no nosso banco × na tela.
- **Fechamento de um mês cheio (setembro/2026):** os totais "oficiais" de produção, faturado, recebido, glosa, receitas e despesas que a pessoa usa, lado a lado com os nossos.
- **Decisões de negócio:** o que conta como receita; competência × caixa; o que é produção (ver perguntas na seção 6).
- Entregável: ata com as definições oficiais (vira o glossário do sistema).

### Fase 6: Correções (ordem pela gravidade, cada uma com teste)
Candidatos já visíveis (a lista final sai das fases 2 a 5):
1. **Produção com um relatório oficial só**; os outros viram "conferência" e a divergência fica explicada na tela.
2. **Financeiro:** baixar o #798 por **vencimento** (ou garantir o histórico completo por emissão) para que o mês de vencimento fique completo. Se o Klingo não permitir, avisar na tela que o mês é parcial. Hoje um mês pode parecer "fechado" sem estar.
3. **Remover ou isolar a coleta avulsa** `-13` (e travar a criação de período fora do padrão em relatório mensal); a leitura sempre por `periodo = AAAA-MM-01`.
4. **Meses futuros** rotulados como **previsão**, fora dos totais de realizado.
5. **Relatórios vazios** (#13295, #13375): corrigir a coleta (filtro, tabela de colunas) ou esconder o cartão com "dado indisponível" em vez de mostrar R$ 0 ou um valor subestimado.
6. **Regras de ID:** onde a chave de deduplicação descarta ou duplica dinheiro, trocar por chave que inclua o que diferencia a linha (conta, categoria, parcela).
7. **Nomenclatura:** aplicar os termos oficiais em todas as telas, avisos e tooltips; todo cartão em R$ mostra *o que é, data-base, fonte (relatório #) e última coleta* ("selo de confiança").
8. **Cuidado:** as migrations seguem as regras do `CLAUDE.md` (sem `drop`/`delete` pelo MCP, em chamadas pequenas, conferindo com `execute_sql`; o que sobrar vai para uma pessoa rodar no SQL Editor).

### Fase 7: Monitoramento contínuo (2 dias)
- As verificações da fase 2 (períodos avulsos, duplicatas, relatório vazio, ID com valor divergente, total constante) viram **avisos automáticos** na aba Avisos (hoje só existe o aviso de "período suspeito").
- A conferência da fase 3 entra em `tests/` e roda antes de cada publicação.
- Painel "Saúde dos dados": para cada relatório, última coleta, linhas, cobertura e se o filtro foi comprovado.

## 5. Ordem e tamanho

Fases 0 a 2 primeiro (cerca de 4 dias): dão a lista de erros reais. As fases 3 e 4 rodam em paralelo depois. A fase 5 precisa de agenda das duas pessoas da área, então marque cedo. A fase 6 só começa depois da 5, para não corrigir na direção errada. Total estimado: **2 a 3 semanas** de trabalho, a maior parte esperando decisões de negócio.

## 6. Perguntas para a pessoa de faturamento / financeiro

1. Pode mandar um exemplo (print) de um filtro que muda o valor de um mesmo ID, com a aba e o ID? Hoje vejo o seletor de mês, bruto × líquido e "Medida" (Despesas).
2. Qual é o número **oficial** de produção de um mês: o do #26 (Receita Produzida por Centro de Resultado), o do #13402 (Visão Gerencial) ou outro? Cancelados, cortesias, glosados e atendimentos sem convênio contam?
3. "Receita" para a diretoria é **produção** (realizado), **faturado** ou **recebido** (caixa)? Em cada aba, qual?
4. O Financeiro deve mostrar o que **vence** no mês (caixa previsto) ou o que **pertence** ao mês (competência)? Pode ser os dois, mas cada um com nome diferente.
5. Despesa recorrente futura (financiamento, folha) deve aparecer nos meses a vencer como previsão?
6. Existe um fechamento mensal oficial (contabilidade ou DRE) para comparar com setembro/2026?
7. Quem deve decidir quando dois relatórios divergem?

## 7. Quando considerar a auditoria pronta

- Todo indicador em R$ está no inventário, com data-base, fonte e termo oficial.
- Setembro e outubro/2026 batem com o Klingo e com o fechamento da área (ou a diferença está explicada por escrito na tela).
- Nenhum período avulso, duplicata ou relatório vazio alimenta um cartão sem aviso.
- O conferidor roda sozinho e falha a publicação quando algo diverge.

---
Gerado a partir da leitura do código (`Faturamento/`, `Financeiro/`, `Despesas/`, `fonte_banco.py`, `klingo_relatorios.py`, Edge Function `sync-relatorios-dw`) e de consultas de leitura ao Supabase em 22/10/2026.
