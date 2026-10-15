# Relatório: o que existe para criar a aba "Tempo"

Data da pesquisa: 15/10/2026. Números do banco são de consultas só de agregados (nenhuma linha com nome de paciente foi lida).

## 1. Conclusão em 6 linhas

1. **Dá para fazer, e já há dado com segundos**: o relatório #13404 (fluxo na recepção) traz início e fim de cada etapa em `hh:mm:ss`; o #13402 (atendimentos) também (no banco os horários vêm com segundos, embora o `relatorios.json` diga `hh:mm`).
2. **A aba Atendimento já faz uma parte**: espera, permanência, tempo por etapa e espera por hora do Check-In, com cortes fixos (`parametros.json`). A aba nova deve **somar**, não repetir: ociosidade de equipamento, pico de gargalo por dia, TAT por janela e outliers estatísticos.
3. **Falta o log de status do equipamento** (ligado, livre, em exame, manutenção). Não existe em nenhum relatório. A ociosidade só pode ser **estimada pelo buraco entre um exame e o seguinte**.
4. **Essa estimativa hoje cobre pouco**: em setembro, só 9% das linhas de RM/TC têm o equipamento na coluna "Profissional / Equipamento" (124 de 1.374); nas outras a coluna traz o nome do profissional. Antes de mostrar ociosidade é preciso decidir como saber **em qual máquina** cada exame foi (ver seção 5).
5. **Outliers**: os "encerramentos esquecidos" existem e são enormes (Pagamento chega a 34 dias). Uma regra estatística (IQR em escala log) pega bem as etapas de fila e pagamento, mas **sozinha falha** em etapas de poucos segundos e em etapas bimodais. A solução testada combina cerca estatística + piso + teto por etapa.
6. **Código pronto e testado** em `Tempo/metricas_tempo.py` (24 testes novos e a suíte inteira do repositório passando; pandas 2.2.3 e 3.0.5). **Só foi rodado com dados sintéticos**; o código não leu as linhas reais, só as consultas SQL de agregados abaixo.

Nome sugerido: **"Tempo"** (id `tempo`; subtítulo: "Ciclo do atendimento, espera, ociosidade e horário de pico"). Alternativas: "Fluxo" (já é o nome de uma seção do Atendimento) ou "Gargalos".

## 2. O que existe hoje nos dados (medido no banco em 15/10/2026)

| Relatório | Linhas vigentes | Período | Grão |
| --- | --- | --- | --- |
| #13402 Atendimentos | 10.494 | 01/09 a 13/10 | um procedimento atendido: setor, profissional/equipamento, convênio, status, registro, início, fim |
| #13404 Fluxo na recepção | 47.313 | 30/08 a 14/10 | uma **etapa** de cada atendimento: Check-In, início e fim da etapa (em segundos) |

Nenhum dos dois traz o **Id do atendimento** nem o paciente. O painel Atendimento liga as etapas por `Data do Atendimento + Profissional + Convênio` (`CHAVE_VISITA`); o adaptador `adaptar_fluxo_klingo` usa a mesma chave.

Tempo por etapa no #13404 (minutos, só linhas com início e fim; nenhuma etapa sem fim, nenhuma negativa):

| Etapa | Linhas | Mediana | p90 | p99 | Máximo | > 24 h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Em Atendimento | 7.445 | 0,2 | 43,5 | 111,6 | 4.304 | 3 |
| Finalizado | 7.132 | 13,2 | 39,7 | 112,0 | 47.412 | 18 |
| Cadastro | 7.114 | 1,1 | 3,8 | 11,9 | 56 | 0 |
| Procedimentos | 7.069 | 1,0 | 4,3 | 32,3 | 40.324 | 2 |
| Chamado (fila) | 7.023 | 31,2 | 106,3 | 226,1 | 19.696 | 12 |
| Guia | 5.905 | 0,2 | 0,8 | 5,8 | 23.184 | 1 |
| Pagamento | 1.433 | 1,5 | 6,6 | **16.822** | **49.770** | 24 |

Dois sinais: (a) a mediana é muito menor que o p90 e o p99 explode, então **média não serve**; (b) "Em Atendimento" tem mediana de 0,2 min (12 segundos) com p90 de 43 min: é **bimodal** (o painel Atendimento já alerta "etapa curta", `ea_curta`).

Configuração que o repositório já tem e a aba pode reaproveitar: expediente 07h–18h, segunda a sábado e feriados em `Acompanhamento de META/metas.json`; lista de equipamentos em `Atendimento/parametros.json`; fuso `TZ=BRT3` nas funções da Vercel.

## 3. O que não existe

| Falta | Efeito | Saída |
| --- | --- | --- |
| Log de status do equipamento | Ociosidade real (livre × em manutenção × desligado) não é medida | Pedir ao fornecedor do RIS/PACS os eventos do equipamento (ex.: início/fim de procedimento por modalidade). Até lá, estimar pelo buraco entre exames (`intervalos_de_uso`) |
| Qual máquina fez o exame | Só 9% das linhas de RM/TC trazem o equipamento (ver abaixo) | Usar a **classe do exame** como "recurso" (RM, TC, USG, densitometria, mamografia): é a mesma classificação que `metas.json` já usa para as metas. Classe não é máquina física: com duas máquinas iguais a ociosidade fica subestimada |
| Id do atendimento | A visita é inferida por data + profissional + convênio; dois pacientes do mesmo convênio no mesmo minuto se confundem | Pedir o Id ao Klingo no relatório, se possível |
| Duração confiável no Klingo | "Duração" e "Espera após Check-In" vêm erradas | Já resolvido no repositório: tudo é recalculado dos horários |

Cobertura do equipamento em setembro (#13402): setor RM/TC tem 1.374 linhas; só `RM` (104) e `TC` (20) aparecem na coluna "Profissional / Equipamento". A meta de ressonâncias é 1.090/mês, então "RM" literal cobre uma fração pequena. O restante vem com 12 nomes de profissional.

## 4. Como a aba nova se diferencia da aba Atendimento

| Já existe no Atendimento | Novo na aba Tempo |
| --- | --- |
| Espera, permanência, tempo por etapa (mediana e p90 por mês) | TAT e espera **por hora e por dia**, e **hora de pico de cada dia** |
| Espera por hora do Check-In (barras) | Pico por dia e setor, com mínimo de atendimentos para contar |
| Cortes fixos (`etapa_aberta_max_min` 1.440, `espera_valida_max_min` 480...) | Cerca estatística por etapa e setor, com piso e teto; mostra quantos casos foram descartados e a cerca usada |
| Alerta de etapa curta | Ociosidade de equipamento (estimada) |

## 5. Outliers: o que a análise dos dados reais mostrou

Apliquei em SQL a regra do código (IQR do log do tempo por etapa, cerca = Q3 + 1,5·IQR) às etapas do #13404:

| Etapa | Cerca (min) | Acima da cerca | Dessas, até 24 h | Veredito |
| --- | ---: | ---: | ---: | --- |
| Finalizado | 146 | 51 | 33 | boa: 33 candidatos a esquecimento entre 2,5 h e 24 h que o corte de 24 h deixava passar (confirmar com a operação) |
| Pagamento | 37 | 46 | 22 | boa: 22 candidatos entre 37 min e 24 h que o corte de 24 h não pega (confirmar com a operação) |
| Chamado | 658 | 14 | 2 | boa: fila longa real continua dentro; só 12 casos > 24 h |
| Cadastro | 20 | 15 | 15 | razoável |
| Procedimentos | 15 | 167 | 165 | **ruim**: etapa de ~1 min, a cerca fica baixa e pega gente normal |
| Pré-Atendimento Iniciado | 0 | 215 | 215 | **ruim**: mediana de 6 s, cerca perto de zero |
| Em Atendimento | 30.331 | 0 | 0 | **inútil**: bimodal, o IQR é enorme e não pega nem os 3 casos > 24 h |

Por isso `sinalizar_outliers` tem três travas além da estatística: **`piso_limite`** (nunca sinalizar abaixo de N minutos), **`teto`** (limite duro, aceita um valor por etapa: `tetos_por_etapa`) e **`n_min`** (grupo com poucas linhas usa a cerca global). Valores iniciais sugeridos, a confirmar com a operação: piso 5 min, teto 1.440 min, e para "Em Atendimento" o teto de 360 min que o painel Atendimento já usa (`exame_valido_max_min`).

O z-score clássico fica no código só para comparação: a própria cauda infla média e desvio e **esconde** os outliers menores (efeito *masking*; há um teste que prova isso). Para "z-score", use a versão robusta (`metodo="mad"`).

## 6. Como o código responde às suas 4 perguntas

Arquivo: `Tempo/metricas_tempo.py` (funções pequenas, comentários só onde o porquê não é óbvio). Demonstração: `python Tempo/exemplo_tempo.py`.

1. **TAT e ociosidade vetorizados** (`ciclo_por_atendimento`, `intervalos_de_uso`, `intervalos_de_status`, `para_timedelta`):
   - `pd.to_timedelta` converte segundos ou `HH:MM:SS` e lixo vira `NaT`; tudo é calculado em `timedelta` e só vira minutos (float) na saída.
   - `groupby(id).shift()` dá o fim da etapa anterior; **`cummax` antes do `shift`** trata etapas sobrepostas (o repasse nunca fica negativo).
   - Ociosidade: sentinelas de comprimento zero no início e no fim do período fazem o buraco antes do primeiro exame e depois do último contar; `unir_sobrepostos` (cummax + shift + cumsum, sem laço) impede "120 min ocupados numa hora".
   - Com log de status, `intervalos_de_status` usa `shift(-1)`: o estado vale até a próxima transição.
2. **`resample` / `pd.Grouper`** (`ratear_por_janela`, `resumo_por_janela`, `ocupacao_diaria`, `pico_de_gargalo`):
   - `resample` põe o intervalo inteiro na janela do início (exame de 10:50 às 11:20 contaria 30 min às 10h). `ratear_por_janela` reparte os segundos exatos por hora com `np.repeat`, sem laço.
   - O corte do expediente é feito **depois** de ratear: um buraco de 17:30 a 08:10 do dia seguinte vira 30 min às 17h, zero à noite e 60 min às 7h.
   - Atendimento pertence à janela em que **chegou** (coorte de chegada): a espera das 10h é a de quem chegou às 10h.
   - `pd.Grouper(key=..., freq=...)` dentro do `groupby` permite várias chaves (setor, métrica). **Minutos somam** de hora para dia (`ocupacao_diaria`); **mediana e p90 não somam**: o dia é recalculado dos atendimentos (`freq="D"`), nunca da média das horas.
   - Pico do dia: `groupby([dia, setor]).idxmax()` na tabela por hora, com mínimo de 10 atendimentos para a hora disputar.
3. **Outliers** (`sinalizar_outliers`): `iqr` (cerca de Tukey), `mad` (z-score robusto) e `zscore` (clássico, para comparar), em escala log, por grupo, com piso, teto e fallback global. Devolve `outlier` e `limite`; nada é apagado.
4. **Saída para BI e front-end** (`preparar_saida`, `exportar`): ver seção 7.

## 7. Saída: tabelas planas, grão explícito

`construir_tabelas` devolve sete DataFrames; `exportar` grava CSV (UTF-8 com BOM, abre certo no Excel), JSON colunar (`{"meta", "columns", "data"}`, o formato `orient="split"`, bem menor que lista de objetos) e Parquet quando houver `pyarrow` (não está nas `requirements.txt`).

| Tabela | Grão | Para quê |
| --- | --- | --- |
| `janelas_hora` | hora × setor × métrica (`tat_min`, `espera_min`, `fila_min`) | curva do dia, mapa de calor dia da semana × hora |
| `janelas_dia` | dia × setor × métrica | tendência (calculada dos atendimentos, não das horas) |
| `gargalo_dia` | dia × setor | "hora de pico" de cada dia |
| `ocupacao_hora` / `ocupacao_dia` | hora ou dia × recurso | % de ociosidade (`min_ocupado + min_ocioso + min_outros = min_disponivel`) |
| `limites` | etapa × setor | a cerca usada e quantos casos foram descartados |
| `atendimentos` | atendimento | detalhe; **não envie ao navegador** sem necessidade |

Regras seguidas (testadas): sem MultiIndex nem índice com significado; **nenhum Timedelta** (BI não entende; tempos em minutos `float32` com 2 casas, contagens `int32`); datas sem fuso mais `dia`, `hora`, `dia_semana` (0 = segunda) prontos; texto repetido como `category`; chaves nunca nulas e sem linha repetida; `janela_fechada` marca a janela ainda em andamento; ordenado pelas chaves. Formato **longo** (coluna `metrica`) nas janelas de atendimento, para somar métricas sem mudar o esquema; **largo** na ocupação, onde as medidas são sempre as mesmas.

## 8. A aba no site (feito depois deste relatório)

A aba **Tempo** foi criada (`Tempo/gerar_tempo.py`, `Tempo/dashboard_modelo.html`, `Tempo/parametros.json`) e descrita no README, seção "Aba Tempo". Decisões:

1. `modulos.json`: módulo `tempo` com `"financeiro": "nenhum"` (a aba não tem R$). Painel novo nasce bloqueado; liberar por usuário em Configurações.
2. **Sem `relatorios.json` próprio**: lê as abas do Atendimento (já guardadas no banco), para não duplicar dado (o plano gratuito do Supabase tem 500 MB e o #13404 é podado em 46 dias no banco de coleta) e para a página se refazer quando o Atendimento atualiza (`armazenamento.DEPENDENCIAS`).
3. `vercel.json`: `Tempo/**` nas quatro funções que geram páginas; `construir_exe.py`: arquivos da aba no programa local.
4. A **hora** é o eixo da tela: espera e tempo total por hora de chegada, mapa dia da semana × hora, pacientes na clínica/fila/atendimento por hora, gargalo de cada dia e ocupação dos equipamentos por hora.
5. Definições mudaram em relação ao módulo do relatório: **espera** = Check-In até o início de Em Atendimento (como o painel Atendimento), **fila** = etapa Chamado, e a chegada é o **Check-In** (não o início da primeira etapa).

Desempenho: com dados sintéticos, 104 mil etapas (26 mil atendimentos) levam 0,6 s em `construir_tabelas`. **Não foi medido** com as linhas reais nem na Vercel (que também faz a leitura do banco e a página).

## 9. Decisões que dependem de você

1. **Recurso da ociosidade**: classe do exame (rápido, aproximado) ou conseguir o log do equipamento (correto, depende do fornecedor)?
2. **Expediente por equipamento**: 07h–18h vale para tudo? Sábado inteiro? A RM e a tomografia trabalham mais cedo ou mais tarde?
3. **Teto de "Em Atendimento"** (360 min?) e piso (5 min?): confirmar com quem opera.
4. **Aba separada ou seção do Atendimento?** A parte de fluxo do Atendimento ficaria duplicada.

## 10. Como rodar

```bash
python3 Tempo/exemplo_tempo.py          # dados sintéticos; grava Tempo/saida_exemplo/ (ignorada pelo git)
python3 -m unittest tests.test_tempo -v # 24 testes do módulo
```

Uso com dados reais (depois de ler as linhas do #13404 em um DataFrame com os títulos do Klingo):

```python
import sys
from pathlib import Path
sys.path.insert(0, "Tempo")
import metricas_tempo as mt
etapas, usos = mt.adaptar_fluxo_klingo(df_13404, ["RM", "TC", "RX", "DENSITOMETRIA", "MAMOGRAFIA"], ["ULTRASSONOGRAFIA ", "ELETRO"], {"CSI": "CSI 1", "CSI - 2": "CSI 2", "PEDIATRIA": "CSI Pediatria"})
tabelas = mt.construir_tabelas(etapas, usos, ("2026-09-01", "2026-10-14"), tetos_por_etapa={"Em Atendimento": 360})
mt.exportar({k: v for k, v in tabelas.items() if k != "atendimentos"}, Path("saida"))
```
