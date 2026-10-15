"""Guia dos alertas: onde achar o problema no Klingo, como resolver e quando o painel considera resolvido.

Cada painel monta seus alertas (nivel, titulo, texto) e chama `anotar(painel, alertas, escopo)` no fim.
Aqui ficam as instrucoes de cada tipo de alerta, em um lugar so. O alerta ganha:
  id       identifica o TIPO de alerta (estavel; o titulo muda com numeros e meses);
  escopo   "" = vale para hoje (posicao atual); "AAAA-MM" = vale so para o mes mostrado (ids em ESCOPO_MES);
  guia     {"relatorios": [{id, nome, url}], "passos": [...], "resolve": "..."}.
O que o alerta ja traz em "itens" (tabela dos registros afetados, ver `tabela`) segue junto.

O link leva ao RELATORIO no Klingo (mesmo padrao do "Link dos dados das meta relatorio.txt"); o Klingo nao tem
link direto para uma fatura ou lancamento, por isso os itens vao numa tabela com o numero para voce procurar.
Alerta sem guia (so informativo, ou nivel "ok") nao ganha botoes. Alerta de problema (critico/atencao) sem guia
e avisado no log: acrescente a regra abaixo.
"""
import json
import re
import sys
from datetime import date, datetime

KLINGO = "https://clinicacsi.klingo.app/#/relatorio/"
RELATORIOS = {
    26: "Receita Produzida", 798: "Acompanhamento de Lançamento", 13280: "Base Cesta de Exames",
    13295: "Identificações de Créditos de Fatura", 13297: "Recebimentos Particulares",
    13328: "Faturas Não Baixadas", 13329: "Controle de Produção por Convênio", 13355: "Faturamento Consulta - Fatura",
    13374: "Faturamento - Guias com Situação", 13375: "Faturamento - Glosas e Recursos", 13376: "Financeiro - Conciliação de Créditos",
    13385: "Suprimentos - Movimentações", 13387: "Suprimentos - Solicitações",
    13404: "Atendimentos - Tempos de Espera e Fluxo na Recepção - Mensal",
    13505: "Financeiro - Evolução das Despesas por Categoria e Mês - Mensal", 13509: "Financeiro - Despesas Detalhadas por Lançamento (Valor Líquido) - Mensal",
    13339: "Base das Metas (exames realizados)", 13402: "Atendimentos - Visão Gerencial de Produtividade, Espera e Receita - Mensal",
}
# alertas que dependem do mes escolhido na tela; os demais descrevem a posicao de hoje, igual em qualquer mes
ESCOPO_MES = {"fat_sem_fatura", "fat_falta_faturar", "fat_pouco_recebido", "fat_glosa", "fat_receita_queda", "fat_producao_diverge",
              "fin_pagar_maior", "des_zero", "des_repetidas", "des_sem_fornecedor", "sup_encerrados", "sup_parciais", "sup_sem_setor",
              "cesta_menor_fat", "cesta_atend_queda", "cesta_ticket_queda", "cesta_multi_queda", "cesta_valor_zero", "cesta_poucos_multi",
              "ate_abertos", "ate_sem_horario", "ate_valor_zero", "ate_horario", "ate_fim_junto", "ate_espera", "ate_duracao", "ate_producao", "ate_queda",
              "ate_metas", "ate_metas_revisar", "ate_sem_meta", "ate_dif_metas", "ate_fora_expediente", "ate_teste",
              "ate_sem_checkin", "ate_etapa_aberta", "ate_ea_curta", "ate_sem_final", "ate_dif_fluxo"}
MAX_ITENS = 25   # linhas da tabela "quais são" (o resto se procura no relatorio)
# alertas que a clinica pode ACEITAR com justificativa (cortesia, retorno, queda sazonal, meta decidida...): o problema nao e um erro de cadastro que
# some ao corrigir. Na aba Avisos eles ficam fechados enquanto continuarem aparecendo e so reabrem se piorarem (ver aviso_sincronizar no banco).
# Os demais (erro de cadastro, lancamento esquecido...) sao conferidos na atualizacao seguinte: se fechou com justificativa e continua nos dados, reabre.
PERSISTENTES = {"fat_glosa", "fat_receita_queda", "des_repetidas", "sup_encerrados", "sup_parciais", "sup_baixas_bloco", "fin_pagar_maior",
                "cesta_atend_queda", "cesta_ticket_queda", "cesta_multi_queda", "cesta_valor_zero", "cesta_poucos_multi",
                "ate_abertos", "ate_valor_zero", "ate_espera", "ate_duracao", "ate_producao", "ate_queda", "ate_metas", "ate_metas_revisar",
                "ate_fora_expediente"}

# Dica e nota de atualizacao de alguns alertas (aparecem no guia do alerta, no painel e na aba Avisos). `ATUALIZACOES` registra quando a regra do painel mudou
# por causa de um aviso ja tratado: {"em": "AAAA-MM-DD", "texto": ...}.
DICAS = {
    "fat_espera_envio": "O envio já tem data marcada (portal do convênio que só abre em certo dia, lote mensal...)? Ao justificar, informe a data prevista: o aviso "
                        "fica como informação até lá e só reabre se a data passar sem a fatura sair. Cada convênio tem o seu prazo, aprendido de quanto ele costuma levar para enviar "
                        "(o SUS leva bem mais que os outros: veja o gráfico do SUS e a tabela de prazos no painel).",
}
ATUALIZACOES = {
    "fat_espera_envio": {"em": "2026-10-15", "texto": "Cada convênio passou a ter o seu prazo de envio, aprendido da média de dias que ele leva da emissão ao envio "
                                                      "(o SUS tem ainda uma análise mês a mês no painel de Faturamento); o aviso passou a aceitar a data prevista de envio."},
}

# (painel, regex do titulo, id, relatorios, passos, resolve)
REGRAS = [
    # ------------------------------------------------------------------ Faturamento
    ("faturamento", r"^Faturas (paradas|esperando envio)", "fat_espera_envio", [13355],
     ["Abra o relatório de Faturas Emitidas no Klingo e use o período livre de Data de Emissão (do mês da fatura mais antiga da lista até hoje).",
      "Deixe só o status “A Enviar”. Procure cada fatura da lista pelo número (coluna Fatura - Id); a mais antiga atrasa mais o prazo de pagamento do convênio.",
      "Envie a fatura. Se o envio é feito pelo portal do convênio, marque a fatura como enviada no Klingo."],
     "Some quando nenhuma fatura estiver “A enviar” há mais de 7 dias (cada convênio tem o seu prazo habitual, aprendido do histórico: o SUS, por exemplo, leva bem mais), na próxima atualização."),
    ("faturamento", r"^Convênios com faturas emitidas e nenhuma enviada", "fat_nunca_enviou", [13355],
     ["No relatório de Faturas Emitidas, filtre a Operadora do convênio e o status “A Enviar”.",
      "Pergunte ao faturamento se o envio desse convênio é feito fora do Klingo (portal do convênio).",
      "Se for, registre o envio no Klingo para a fatura passar a “Enviada”; senão, ela não entra em “Faturas em aberto”."],
     "Some quando o convênio tiver ao menos uma fatura enviada."),
    ("faturamento", r"^Muitas faturas canceladas", "fat_canceladas", [13355],
     ["No relatório de Faturas Emitidas, filtre o status “Cancelada” e olhe as colunas Operadora e Fatura - Usuário Responsável: é por elas que se vê quem ou qual convênio concentra os cancelamentos.",
      "Confira se a fatura cancelada foi refeita (mesma operadora e período com uma fatura ativa). Se não foi, o produzido ficou sem fatura."],
     "Some quando as canceladas ficarem abaixo de 20% das faturas emitidas."),
    ("faturamento", r"^Faturas ativas sem valor", "fat_sem_valor", [13355],
     ["No relatório de Faturas Emitidas, procure as faturas que não estão canceladas e estão com Fatura - Valor vazio ou zero (use o número da lista).",
      "Abra a fatura no Klingo: se não tem guias, cancele; se tem, o valor precisa ser recalculado."],
     "Some quando nenhuma fatura ativa estiver sem valor."),
    ("faturamento", r"^Faturas enviadas sem protocolo", "fat_sem_protocolo", [13355],
     ["No relatório de Faturas Emitidas, filtre os status Enviada e Movimentada e procure as faturas da lista (coluna Fatura - Id) com Fatura - Envio - Protocolo vazio.",
      "Informe o número do protocolo do envio na fatura, para conseguir conciliar o pagamento com o convênio."],
     "Some quando toda fatura enviada tiver protocolo."),
    ("faturamento", r"^Convênios com produção em .* e nenhuma fatura", "fat_sem_fatura", [13329, 13355],
     ["No relatório de Produção por Convênio confira o Produzido do convênio no mês (use o período do mês).",
      "No relatório de Faturas Emitidas, filtre a Operadora e a Data Inicial do mês: se não aparece fatura (nem cancelada), ela ainda não foi emitida.",
      "Emita a fatura do convênio para esse período."],
     "Some quando o convênio tiver ao menos uma fatura emitida com início no mês."),
    ("faturamento", r"^Produzido de .* que ainda não virou fatura", "fat_falta_faturar", [13329, 13355],
     ["No relatório de Produção por Convênio, compare por convênio o Produzido do mês com o valor das faturas dele no relatório de Faturas Emitidas (Data Inicial no mês).",
      "Os convênios da lista são os que têm mais produzido sem fatura: emita ou complete a fatura do período."],
     "Some quando o produzido sem fatura ficar abaixo de 10% do produzido do mês."),
    ("faturamento", r"^Faturas vencidas e ainda não baixadas", "fat_vencidas", [13328],
     ["Abra o relatório de Faturas em Aberto (Faturas Não Baixadas) e ordene por Vencimento: as vencidas ficam no topo. Procure pelo Nº do Lote.",
      "Confirme com o convênio (ou no extrato) se foi pago. Se foi, dê a baixa do recebimento no Klingo; se não foi, cobre o convênio."],
     "Some quando a fatura for baixada e não constar mais no relatório de Faturas em Aberto."),
    ("faturamento", r"^Quase nada de convênio aparece como recebido", "fat_pouco_recebido", [13329],
     ["No relatório de Produção por Convênio, compare por convênio Produzido e Recebido do mês fechado.",
      "Confira no extrato do banco ou no portal do convênio o que já entrou e lance a baixa (identificação de crédito) no Klingo."],
     "Some quando o recebido passar de 10% do produzido do mês de referência."),
    ("faturamento", r"^Glosa registrada", "fat_glosa", [13329],
     ["No relatório de Produção por Convênio, veja as colunas Glosa e Glosa Acatada por convênio.",
      "Decida entre recorrer ou aceitar a glosa de cada convênio da lista."],
     "Não some sozinho: a glosa fica no mês. Marque como resolvido quando todas tiverem recurso ou aceite."),
    ("faturamento", r"^Faturas em aberto sem valor", "fat_aberto_sem_valor", [13328],
     ["No relatório de Faturas em Aberto, procure as faturas com Valor Bruto vazio ou zero (use a lista abaixo).", "Corrija o valor da fatura no Klingo."],
     "Some quando nenhuma fatura em aberto estiver sem valor."),
    ("faturamento", r"^Receita abaixo do mês anterior", "fat_receita_queda", [26],
     ["No relatório de Faturamento, compare dia a dia (e por Operadora, Categoria e Unidade) o mês com o anterior.",
      "Veja se algum dia ficou sem lançamentos (dia sem atendimento ou sem registro) ou se algum convênio parou de aparecer."],
     "Não é erro de cadastro: some quando a receita voltar ao nível do mês anterior."),
    ("faturamento", r"^Relatórios de produção não batem", "fat_producao_diverge", [26, 13329],
     ["Compare, convênio a convênio, o total do relatório de Faturamento (Operadora, mês) com o Produzido do relatório de Produção por Convênio.",
      "A diferença costuma ser de guias lançadas depois do fechamento ou de valores alterados; procure no convênio que mais difere."],
     "Some quando a diferença entre os dois relatórios ficar abaixo de 2%."),

    # ------------------------------------------------------------------ Financeiro
    ("financeiro", r"^Mais a pagar do que a receber", "fin_pagar_maior", [798, 13328],
     ["No relatório de Lançamentos Financeiros, veja as despesas do mês por Vencimento (a tabela abaixo traz as maiores) e as receitas lançadas.",
      "No relatório de Faturas em Aberto veja as faturas de convênio que vencem no mês: se algum recebimento for adiantado ou cobrado, o saldo muda."],
     "Some quando o previsto a receber passar do que há a pagar no mês."),
    ("financeiro", r"^Contas vencidas sem baixa", "fin_vencidas", [798],
     ["Abra o relatório de Lançamentos Financeiros. Atenção: o período do relatório filtra pela data de EMISSÃO, então use um período que comece antes da emissão (a lista abaixo traz o número do lançamento e o vencimento).",
      "Procure o lançamento pelo número. Se já foi pago, dê a baixa informando a Conta; se não foi, está em atraso."],
     "Some quando o lançamento tiver Conta preenchida (baixa dada)."),
    ("financeiro", r"^Vencimentos nos próximos 7 dias", "fin_proximos_7", [798],
     ["No relatório de Lançamentos Financeiros, procure os lançamentos da lista pelo número (período que inclua a emissão deles).", "Programe o pagamento ou confirme o caixa."],
     "Some depois do vencimento ou da baixa dos lançamentos."),
    ("financeiro", r"^Convênios: quase nenhum crédito identificado", "fin_creditos_convenio", [13295, 13329],
     ["No relatório de Créditos de Convênio (Identificações de Créditos de Fatura) veja os créditos já identificados do mês.",
      "No extrato do banco, procure os depósitos de convênios e identifique cada crédito no Klingo contra a fatura paga."],
     "Some quando os créditos identificados passarem de 10% do produzido de convênios do mês anterior."),
    ("financeiro", r"^Lançamentos com data inválida", "fin_data_invalida", [798],
     ["No relatório de Lançamentos Financeiros, procure o lançamento pelo número (tabela abaixo) e veja a data de Vencimento: o ano veio errado (ex.: 0206).",
      "Corrija a data no lançamento."],
     "Some quando todos os lançamentos tiverem datas válidas."),
    ("financeiro", r"^Nenhum lançamento conciliado", "fin_sem_conciliacao", [798, 13376],
     ["A conciliação é feita no Klingo (o painel só lê a coluna Conciliado do relatório de Lançamentos Financeiros). Concilie os lançamentos com o extrato do banco.",
      "No relatório de Baixas você acompanha as baixas e o que ficou conciliado."],
     "Some quando houver lançamentos conciliados."),

    # ------------------------------------------------------------------ Despesas
    ("despesas", r"^Despesas lançadas com valor zero", "des_zero", [13509, 13505],
     ["Abra o relatório de Despesas Detalhadas por Lançamento (Valor Líquido) e use o período livre do mês indicado (o filtro é Lançamento - Competência). A tabela abaixo traz o número do lançamento (coluna ID do Lançamento do relatório).",
      "Para editar, procure esse número no relatório de Lançamentos Financeiros e abra o lançamento.",
      "Preencha o valor, ou exclua o lançamento se ele não é mais necessário."],
     "Some quando nenhuma despesa do mês tiver valor zero."),
    ("despesas", r"^Possíveis lançamentos repetidos", "des_repetidas", [13509, 13505],
     ["Abra o relatório de Despesas Detalhadas por Lançamento (Valor Líquido) no mês indicado e procure os números de lançamento da última coluna da tabela abaixo (mesma categoria, fornecedor, descrição e valor, com números diferentes).",
      "Confira no Klingo se são parcelas ou itens iguais de verdade. Se um lançamento foi feito duas vezes por engano, exclua o repetido.",
      "O painel não decide sozinho: quando for legítimo, use “Marcar como resolvido”."],
     "Some quando não houver mais lançamentos idênticos no mês. Se forem legítimos, marque como resolvido."),
    ("despesas", r"^Despesas sem fornecedor", "des_sem_fornecedor", [13509, 13505],
     ["No relatório de Despesas Detalhadas por Lançamento (Valor Líquido), filtre o mês indicado e procure os números de lançamento da tabela abaixo (a coluna Fornecedor está vazia).",
      "No Klingo, abra o lançamento (pelo relatório de Lançamentos Financeiros, procurando esse número) e informe o fornecedor."],
     "Some quando todas as despesas do mês tiverem fornecedor."),

    # ------------------------------------------------------------------ Suprimentos
    ("suprimentos", r"^Pedidos encerrados sem entrega", "sup_encerrados", [13387],
     ["No relatório de Solicitações de Estoque, filtre o mês e procure os itens com Atendida vazia e “Item - Pendente” = N.",
      "Pergunte ao setor e ao estoque se foi cancelamento ou falta de material."],
     "Não some sozinho: marque como resolvido depois de saber o motivo."),
    ("suprimentos", r"^Pedidos atendidos pela metade", "sup_parciais", [13387],
     ["No relatório de Solicitações de Estoque, compare as colunas de quantidade pedida e atendida do mês.", "Veja com o estoque o que ficou faltando entregar."],
     "Não some sozinho: marque como resolvido depois de conferir."),
    ("suprimentos", r"^Pedidos sem centro de custo", "sup_sem_setor", [13387],
     ["No relatório de Solicitações de Estoque, procure as solicitações da tabela abaixo pelo número e veja o Centro de Custo vazio.",
      "Peça ao solicitante que informe o setor nos próximos pedidos (e corrija os antigos, se o Klingo permitir)."],
     "Some quando as solicitações do mês tiverem setor."),
    ("suprimentos", r"^Pedidos de material parados sem atendimento", "sup_pendentes", [13387, 13385],
     ["Abra o relatório de Solicitações de Estoque e filtre os itens com “Item - Pendente” = S. A tabela abaixo traz as solicitações mais antigas (número, setor, solicitante).",
      "Se o material já foi entregue, registre o atendimento da solicitação; se não foi, entregue ou encerre o pedido.",
      "O saldo do estoque está no relatório de Movimentações de Estoque: confira se o item tem saldo antes de atender."],
     "Some quando os itens deixarem de constar como pendentes."),
    ("suprimentos", r"^Setores em que quase nada é atendido", "sup_setores", [13387],
     ["No relatório de Solicitações de Estoque, filtre o Centro de Custo do setor e veja os itens pendentes.", "Converse com o setor e com o estoque sobre o fluxo de atendimento."],
     "Some quando o setor passar a ter menos de 90% dos itens pendentes."),
    ("suprimentos", r"^(Sem baixa de consumo há dias|Nenhuma baixa de consumo registrada)", "sup_sem_baixa", [13385],
     ["No relatório de Movimentações de Estoque, filtre o tipo “Consumo” e veja a data da última baixa.", "Lance as baixas dos materiais usados desde então (por procedimento ou por setor)."],
     "Some quando houver baixa de consumo recente."),
    ("suprimentos", r"^Baixas de consumo que não baixam nada", "sup_baixa_zero", [13385],
     ["No relatório de Movimentações de Estoque, filtre o tipo “Consumo” e procure as saídas com quantidade zero (itens na tabela abaixo).", "Corrija a quantidade das baixas desses itens."],
     "Some quando as baixas com quantidade zero ficarem abaixo de 10."),
    ("suprimentos", r"^Material entregue aos setores que nunca foi baixado", "sup_entregue_sem_baixa", [13387, 13385],
     ["No relatório de Solicitações de Estoque, veja a quantidade atendida de cada item da tabela e o setor que recebeu.",
      "No relatório de Movimentações, filtre o tipo “Consumo” para o mesmo item: não deve haver nenhuma linha.",
      "Peça ao setor que passou a usar o item para lançar a baixa de consumo (com a quantidade real) no dia do uso."],
     "Some quando todo item entregue aos setores tiver ao menos uma baixa de consumo."),
    ("suprimentos", r"^Itens pedidos que nunca tiveram estoque lançado","sup_sem_lancamento", [13385, 13387],
     ["No relatório de Movimentações de Estoque, procure cada item da tabela: não há entrada, inventário nem saída dele.", "Lance a entrada (compra) ou o inventário inicial do item no estoque."],
     "Some quando o item tiver ao menos um lançamento de estoque."),
    ("suprimentos", r"^Itens pedidos com estoque zerado", "sup_zerado", [13385, 13387],
     ["No relatório de Movimentações de Estoque, veja o saldo do item (soma de entradas menos saídas por local).", "Se há material físico, falta lançar a entrada ou o inventário; se não há, falta comprar."],
     "Some quando o item voltar a ter saldo."),
    ("suprimentos", r"^Pedidos em aberto maiores que o estoque", "sup_falta", [13385, 13387],
     ["Compare o pedido em aberto com o saldo do item.", "Reponha o estoque ou atenda parcialmente."],
     "Some quando o estoque cobrir os pedidos em aberto."),
    ("suprimentos", r"^Estoque principal para poucos dias", "sup_baixo", [13385],
     ["No relatório de Movimentações de Estoque, veja o saldo do local principal dos itens da tabela.", "Programe a compra pelo ritmo de pedidos dos últimos 30 dias."],
     "Some quando o estoque principal cobrir 15 dias de pedidos."),
    ("suprimentos", r"^Valor do estoque concentrado em um item", "sup_valor_concentrado", [13385],
     ["No relatório de Movimentações de Estoque, procure o item e veja o valor unitário da entrada.", "Se o custo foi cadastrado por frasco ou caixa e a quantidade está em mL (ou unidade menor), corrija o custo para a mesma unidade."],
     "Some quando o valor do item deixar de passar de 90% do estoque."),
    ("suprimentos", r"^Custo registrado nas movimentações", "sup_sem_custo", [13385],
     ["No relatório de Movimentações de Estoque, veja as movimentações com valor unitário vazio (a maioria).", "Cadastre o custo unitário nos itens principais para o painel calcular o custo do consumo."],
     "Some quando metade das movimentações tiver valor."),
    ("suprimentos", r"^Nenhum saldo negativo por local", "sup_saldo_negativo", [13385],
     ["No relatório de Movimentações de Estoque, some por item e local: saída maior que entrada indica entrada não lançada.", "Lance a entrada que falta ou corrija a baixa."],
     "Some quando nenhum item ficar com saldo negativo."),
    ("suprimentos", r"^Transferências entre estoques fecham", "sup_transferencias", [13385],
     ["No relatório de Movimentações de Estoque, filtre o tipo “Transferência”: cada uma deve ter uma saída e uma entrada iguais, no mesmo dia e item.", "Complete o lançamento que ficou sem par."],
     "Some quando toda transferência tiver saída e entrada iguais."),
    ("suprimentos", r"^Baixas de consumo lançadas em bloco", "sup_baixas_bloco", [13385],
     ["No relatório de Movimentações de Estoque, filtre o tipo “Consumo” e veja o dia do bloco.", "Passe a lançar as baixas no dia do uso, para o saldo refletir o estoque real."],
     "Não some sozinho: marque como resolvido depois de combinar o lançamento diário."),
    ("suprimentos", r"^Quase tudo foi lançado por um só usuário", "sup_um_usuario", [13385],
     ["No relatório de Movimentações de Estoque, veja a coluna de usuário.", "Treine uma segunda pessoa para lançar movimentações."],
     "Some quando nenhum usuário tiver mais de 80% dos lançamentos."),

    # ------------------------------------------------------------------ Indicadores
    ("indicadores", r"^Guias pendentes de correção", "ind_guias_pendentes", [13374],
     ["No relatório de Guias, filtre a situação “Pendente Recepção” (PR). A coluna Pendência / Motivo diz o que corrigir (tabela abaixo traz as guias).",
      "Corrija a guia no Klingo e reenvie ao convênio."],
     "Some quando nenhuma guia estiver “Pendente recepção”."),
    ("indicadores", r"^Faturas enviadas sem protocolo", "ind_sem_protocolo", [13355],
     ["No relatório de Faturas Emitidas, filtre Enviada e Movimentada e procure as faturas da tabela (coluna Fatura - Id) sem Fatura - Envio - Protocolo.", "Informe o protocolo do envio."],
     "Some quando toda fatura enviada tiver protocolo."),
    ("indicadores", r"^Nenhuma baixa conciliada", "ind_sem_conciliacao", [13376],
     ["No relatório de Baixas, veja a coluna Baixa - Conciliado.", "Concilie as baixas com o extrato do banco no Klingo."],
     "Some quando houver baixa conciliada."),
    ("indicadores", r"^O relatório de baixas mistura", "ind_baixas_mistura", [13376],
     ["Edite o relatório de Baixas no Klingo e inclua a coluna “Lançamento - Tipo”.", "Atualize o painel: ele passa a separar recebimentos de pagamentos."],
     "Some depois que o relatório trouxer o tipo do lançamento."),
    ("indicadores", r"^Relatório de glosas e recursos ainda sem linhas", "ind_glosas_vazio", [13375],
     ["Nada a corrigir no Klingo: o relatório de Glosas e Recursos só traz linhas quando houver glosa lançada.", "Quando a primeira glosa for registrada, confira se as colunas foram reconhecidas."],
     "Some quando o relatório de Glosas e Recursos devolver linhas."),
    ("indicadores", r"^Recebido das guias não bate com o relatório de Produção por Convênio", "ind_recebido_diverge", [13374, 13329],
     ["Compare o valor recebido por convênio no relatório de Guias (guias) e no relatório de Produção por Convênio.", "Procure o convênio com diferença e a guia lançada fora do mês."],
     "Some quando os dois valores forem iguais."),
    ("indicadores", r"^Sem fonte no Klingo: Bloqueado e Antecipado", "ind_sem_fonte", [13376],
     ["Bloqueado só existe no portal da operadora; Antecipado precisa de um campo de antecipação no relatório de baixas.", "Peça ao Klingo para incluir esse campo."],
     "Some quando as duas fontes existirem."),

    # ------------------------------------------------------------------ Cesta
    ("cesta", r"^A receita da Cesta é menor que a do Faturamento", "cesta_menor_fat", [13280, 26],
     ["A tabela abaixo traz, por convênio e exame, o valor do relatório de Base da Cesta e do relatório de Faturamento nos dias completos do mês; as maiores diferenças estão no topo.",
      "Exame repetido no mesmo dia: no relatório de Faturamento, filtre o exame e o convênio e veja se o mesmo paciente aparece mais de uma vez no dia. O relatório de Base da Cesta traz só uma linha para essas repetições.",
      "Valor maior no relatório de Faturamento (histerossalpingografia, RX contrastado e RM com contraste são os mais afetados): confira se o relatório de Faturamento soma contraste ou material ao exame, que o relatório de Base da Cesta não traz. "
      "Se for isso, a correção é no relatório (pedir ao Klingo para incluir esses itens no valor do relatório de Base da Cesta)."],
     "Some quando o relatório de Base da Cesta entregue pelo Klingo medir mais de 98% do Faturamento. Enquanto isso o painel já usa o valor do Faturamento: o alerta só mostra de onde vem a diferença."),
    ("cesta", r"^Atendimentos abaixo do mês anterior", "cesta_atend_queda", [13280],
     ["No relatório de Base da Cesta, compare os dias do mês com os do mês anterior e procure dias sem atendimento lançado."], "Some quando os atendimentos se aproximarem do mês anterior."),
    ("cesta", r"^Ticket médio caiu", "cesta_ticket_queda", [13280],
     ["No relatório de Base da Cesta, veja os exames e convênios com valor menor que no mês anterior (tabelas de preço) e as linhas de R$ 0."], "Some quando o ticket se aproximar do mês anterior."),
    ("cesta", r"^Menos pacientes fazendo mais de um exame", "cesta_multi_queda", [13280],
     ["No relatório de Base da Cesta, veja os pacientes atendidos em um dia com um só exame e quais exames costumam sair juntos."], "Some quando a taxa voltar ao nível do mês anterior."),
    ("cesta", r"^Linhas com valor zero", "cesta_valor_zero", [13280],
     ["No relatório de Base da Cesta, filtre o Valor igual a zero e olhe Procedimento e Operadora (a tabela abaixo traz o preço usual e o valor em jogo).",
      "Retorno e cortesia: nada a fazer, e o painel já deixa essas linhas fora do ticket médio. Marque o alerta como resolvido.",
      "Convênio ou particular que deveria pagar (por exemplo, uma consulta que aparece sempre com R$ 0 no mesmo convênio): falta o preço do procedimento na tabela do convênio no Klingo."],
     "Some quando as linhas de R$ 0 ficarem abaixo de 1%. Se forem retornos e cortesias, marque como resolvido."),
    ("cesta", r"quase nenhum atendimento com 2\+ exames", "cesta_poucos_multi", [13280],
     ["No relatório de Base da Cesta, filtre a Operadora e veja se cada exame foi registrado em um atendimento separado.", "Confira se é regra do convênio."],
     "Some quando a taxa de 2+ exames do convênio passar de 2%."),
    ("cesta", r"^Combos e grupos de procedimento vazios", "cesta_combos_vazios", [13280],
     ["No Klingo, cadastre os combos e o Grupo do Procedimento (as colunas Combo e Grupo do relatório de Base da Cesta vêm vazias).",
      "Enquanto isso, o painel deduz os combos pelo que os pacientes fazem juntos."],
     "Some quando o relatório de Base da Cesta trouxer combos."),
    ("cesta", r"^Paciente com \d+ anos", "cesta_idade", [13280],
     ["No relatório de Base da Cesta, procure o paciente pelo Paciente - Id citado no alerta.", "Corrija a data de nascimento no cadastro do paciente."],
     "Some quando nenhuma idade passar de 110 anos."),
    ("cesta", r"^\d+ linhas sem sexo informado", "cesta_sem_sexo", [13280],
     ["No relatório de Base da Cesta, filtre Sexo vazio (N/I) e corrija no cadastro dos pacientes."], "Some quando todas as linhas tiverem sexo."),

    # ------------------------------------------------------------------ Atendimento (#13402; o relatório não traz Id do atendimento nem paciente: procure pela data e hora do registro)
    ("atendimento", r"^Atendimentos que nunca foram encerrados", "ate_abertos", [13402],
     ["No relatório de Atendimentos, use o período livre do mês e veja a coluna Status do Atendimento: todas as linhas aparecem como “Aberta”.",
      "Pergunte ao suporte do Klingo (ou a quem fecha a conta) em que momento o atendimento muda de “Aberta” para outro status e se a recepção precisa encerrá-lo."],
     "Some quando menos de 20% dos atendimentos com mais de 7 dias estiverem “Aberta”. Se o Klingo nunca muda esse status, marque como resolvido."),
    ("atendimento", r"^Atendimentos sem horário de início ou de fim", "ate_sem_horario", [13402],
     ["No relatório de Atendimentos, filtre o mês e procure, pela data e hora do registro da tabela abaixo, as linhas com Início do Atendimento ou Fim do Atendimento vazio.",
      "Esses horários são marcados quando o profissional começa e termina o atendimento no Klingo. Peça a quem registrou (coluna Usuário Responsável) que não pule essa etapa.",
      "Atendimentos de hoje não entram: ainda podem estar em andamento."],
     "Some quando todo atendimento com mais de 1 dia tiver início e fim."),
    ("atendimento", r"^Atendimentos com valor R\$ 0,00", "ate_valor_zero", [13402],
     ["No relatório de Atendimentos, procure pela data e hora da tabela abaixo as linhas com Valor do Atendimento igual a zero e veja Convênio e Procedimento.",
      "Se é cortesia ou retorno, nada a fazer. Se o procedimento deveria ter preço, falta cadastrar o valor na tabela do convênio (ou do particular) no Klingo."],
     "Some quando o atendimento com valor zero ficar abaixo de 1%. Se for cortesia, marque como resolvido."),
    ("atendimento", r"^Horários incoerentes nos atendimentos", "ate_horario", [13402],
     ["No relatório de Atendimentos, procure pela data e hora da tabela abaixo as linhas: veja Data do Atendimento (registro), Início e Fim do Atendimento.",
      "O início deve ser depois do registro, e o fim depois do início. Corrija o horário no atendimento do Klingo ou oriente quem registrou (coluna Usuário Responsável)."],
     "Some quando os horários incoerentes ficarem abaixo de 0,5% dos atendimentos."),
    ("atendimento", r"^Início e fim marcados no mesmo minuto", "ate_fim_junto", [13402],
     ["No relatório de Atendimentos, procure pela data e hora da tabela abaixo as linhas em que Início do Atendimento e Fim do Atendimento são quase iguais (menos de 1 minuto).",
      "Quando alguém marca o início e o fim no mesmo clique, o Klingo guarda a duração como se fosse instantânea. Oriente o profissional a marcar o início quando começa e o fim quando termina.",
      "O Klingo atribui o atendimento ao Usuário Responsável (quem o abriu); o clique no início e no fim pode ter sido de outra pessoa."],
     "Some quando menos de 3% dos atendimentos tiverem início e fim no mesmo minuto."),
    ("atendimento", r"^Atendimentos sem Check-In", "ate_sem_checkin", [13404],
     ["No relatório de Fluxo do Paciente, procure pela data e hora da tabela abaixo as linhas com a coluna Check-In vazia.",
      "O Check-In é marcado quando o paciente chega à recepção. Sem ele o Klingo não sabe desde quando o paciente espera: oriente a recepção a fazer o check-in antes do cadastro."],
     "Some quando menos de 3% dos atendimentos (com mais de 1 dia) estiverem sem Check-In."),
    ("atendimento", r"^Etapas deixadas em aberto no fluxo", "ate_etapa_aberta", [13404],
     ["No relatório de Fluxo do Paciente, procure pela data e hora da tabela abaixo a etapa citada (Pagamento, Finalizado, Chamado...): o Início da Etapa e o Fim da Etapa estão separados por dias.",
      "Uma etapa só termina quando a próxima é registrada. Peça a quem atende que avance o atendimento até o fim; essas etapas ficam de fora das médias."],
     "Some quando menos de 1% dos atendimentos tiver etapa aberta por mais de 24 horas."),
    ("atendimento", r"^Etapa Em Atendimento dura só segundos", "ate_ea_curta", [13404],
     ["No relatório de Fluxo do Paciente, filtre a Etapa “Em Atendimento” e olhe o Tempo na Etapa (coluna do Klingo): a maioria fica em segundos.",
      "Combine com a equipe o que “Em Atendimento” significa: se é para marcar o início do exame, o profissional precisa avançar para Finalizado só no fim. Enquanto isso, a duração é medida de Em Atendimento até o fim de Finalizado."],
     "Some quando menos de 30% dos atendimentos tiver Em Atendimento com menos de 1 minuto."),
    ("atendimento", r"^Atendimentos sem a etapa Finalizado", "ate_sem_final", [13404],
     ["No relatório de Fluxo do Paciente, procure pela data e hora da tabela abaixo: o atendimento tem Em Atendimento mas não tem a etapa Finalizado.",
      "Abra o atendimento no Klingo e finalize (ou confirme que o paciente não foi atendido)."],
     "Some quando menos de 3% dos atendimentos começados (com mais de 1 dia) estiverem sem Finalizado."),
    ("atendimento", r"^Fluxo e atendimento não batem", "ate_dif_fluxo", [13402, 13404],
     ["O relatório de Atendimentos e o relatório de Fluxo do Paciente são ligados por data do registro, profissional e convênio. Atualize o painel e compare de novo.",
      "Se persistir, compare os filtros dos dois relatórios (Atendimento - Data) e procure os atendimentos da tabela abaixo no relatório de Atendimentos."],
     "Some quando menos de 5% dos atendimentos ficar sem par no outro relatório."),
    ("atendimento", r"^Espera acima do aceitável", "ate_espera", [13404, 13402],
     ["No relatório de Fluxo do Paciente, compare por Setor, Fila e Etapa: espera = do Check-In ao início da etapa Em Atendimento. A etapa Chamado é o tempo na fila para ser chamado.",
      "Veja se a espera se concentra num horário (agenda lotada ou falta de gente na recepção) ou numa especialidade (atraso do profissional ou do equipamento).",
      "O aceitável (30 min) e o crítico (60 min) são limites escolhidos por mim e ficam em Atendimento\\parametros.json."],
     "Some quando a mediana de espera de todos os setores ficar abaixo de 30 minutos."),
    ("atendimento", r"^Duração muito maior que a dos colegas", "ate_duracao", [13402],
     ["No relatório de Atendimentos, filtre o Profissional / Equipamento da tabela abaixo e compare Início e Fim do Atendimento com os colegas da mesma Especialidade.",
      "Pode ser exame mais demorado por natureza (ex.: RM de várias regiões) ou horário de início/fim marcado depois do real."],
     "Some quando ninguém passar de 1,5 vez a mediana da especialidade."),
    ("atendimento", r"^Profissionais abaixo do ritmo dos colegas", "ate_producao", [13402],
     ["No relatório de Atendimentos, filtre o Profissional da tabela abaixo e conte os atendimentos por dia (Data do Atendimento).",
      "Compare com a agenda dele: poucos dias de atendimento, agenda com buracos ou demanda baixa explicam a diferença. Não é meta: serve para olhar a agenda."],
     "Não é erro de cadastro: some quando a produção por dia chegar a 60% da mediana dos colegas. Marque como resolvido depois de conferir a agenda."),
    ("atendimento", r"^Atendimentos abaixo do mês anterior", "ate_queda", [13402],
     ["No relatório de Atendimentos, compare o mês com o anterior, dia a dia e por Setor, e procure dias sem atendimento registrado."],
     "Some quando o ritmo por dia útil chegar a 90% do mês anterior."),
    ("atendimento", r"^Metas de atendimento abaixo do ritmo", "ate_metas", [13339],
     ["No relatório de Base das Metas, conte os atendimentos do mês por Unidade, Especialidade e Procedimento para ver o que está faltando.",
      "A coluna “Por dia útil para bater” diz quantos atendimentos por dia são necessários para fechar a meta no mês."],
     "Some quando as metas atrasadas chegarem ao ritmo esperado do mês."),
    ("atendimento", r"^Metas que parecem desalinhadas com o volume", "ate_metas_revisar", [13339, 13402],
     ["Compare a meta com o que o serviço realmente faz por mês (coluna Referência). Meta muito abaixo do realizado perde força; muito acima do realizado vira número fora da realidade.",
      "Ajuste a meta no arquivo metas.json do painel de Metas (campo “meta”, ou “metas_por_mes” para um mês só)."],
     "Não some sozinho: marque como resolvido depois de decidir manter ou mudar as metas."),
    ("atendimento", r"^Atendimentos sem nenhuma meta", "ate_sem_meta", [13339],
     ["No relatório de Base das Metas, conte os atendimentos por Unidade, Especialidade e Procedimento: a tabela abaixo traz os que não entram em nenhuma meta.",
      "Se algum merece meta, inclua uma regra no metas.json do painel de Metas."],
     "Some quando os atendimentos sem meta ficarem abaixo de 10%."),
    ("atendimento", r"^Atendimento e Metas não batem", "ate_dif_metas", [13402, 13339],
     ["Atualize o Atendimento e as Metas e compare de novo: as duas bases são baixadas em horários diferentes.",
      "Se continuar diferente, compare os filtros do relatório de Atendimentos e do relatório de Base das Metas (período, unidade, status)."],
     "Some quando a diferença entre os dois relatórios ficar abaixo de 5% em cada setor."),
    ("atendimento", r"^Atendimentos fora do expediente", "ate_fora_expediente", [13402],
     ["No relatório de Atendimentos, procure pela data e hora da tabela abaixo as linhas registradas antes das 07h, a partir das 18h ou em domingo e feriado.",
      "Se a clínica atende nesses horários, ajuste o horário e os dias de atendimento no metas.json (para o ritmo esperado); se foi erro de data, corrija o registro."],
     "Some quando menos de 1% dos atendimentos ficar fora do expediente."),
    ("atendimento", r"^Registros de teste nos atendimentos", "ate_teste", [13402],
     ["No relatório de Atendimentos, procure pela data e hora da tabela abaixo o registro de teste (profissional, usuário ou convênio com “teste”).",
      "Cancele ou exclua o atendimento de teste no Klingo, para ele não contar nos totais e nas metas."],
     "Some quando não houver mais registro de teste."),
]
_COMPILADAS = [(p, re.compile(rx), i, rels, passos, res) for p, rx, i, rels, passos, res in REGRAS]


def _relatorio(rid: int) -> dict:
    return {"id": rid, "nome": RELATORIOS.get(rid, f"Relatório #{rid}"), "url": f"{KLINGO}{rid}"}


def dbr(v) -> str:
    """Data em dd/mm/aaaa (aceita Timestamp, date, texto ISO ou vazio)."""
    if v is None or (not isinstance(v, str) and v != v):   # None ou NaN/NaT
        return ""
    if isinstance(v, (datetime, date)) or hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    s = str(v)[:10]
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}" if re.fullmatch(r"\d{4}-\d\d-\d\d", s) else str(v)


def reais(v) -> str:
    if v is None or v != v:
        return ""
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tabela(colunas: list[str], linhas: list[list], total: int | None = None, numericas: tuple[int, ...] = ()) -> dict:
    """Registros afetados, ja formatados em texto. `total` = quantos existem de verdade (a tabela mostra os primeiros).
    `numericas` = indices das colunas alinhadas a direita."""
    def texto(c):
        if c is None or (not isinstance(c, str) and c != c):   # vazio ou NaN
            return ""
        if isinstance(c, float) and c.is_integer():            # numero de lote/id que veio como 123.0
            return str(int(c))
        return str(c)

    linhas = [[texto(c) for c in l] for l in linhas[:MAX_ITENS]]
    return {"colunas": colunas, "linhas": linhas, "total": int(total if total is not None else len(linhas)), "numericas": list(numericas)}


def anotar(painel: str, alertas: list[dict], escopo: str = "") -> list[dict]:
    """Poe id, escopo e guia nos alertas que tem regra. Devolve a mesma lista."""
    for a in alertas:
        if a.get("nivel") == "ok":
            continue
        achou = next((r for r in _COMPILADAS if r[0] == painel and r[1].search(a["titulo"])), None)
        if not achou:
            if a.get("nivel") in ("critico", "atencao"):
                print(f">>> AVISO (guia_pendencias): alerta sem guia em {painel}: {a['titulo']!r}", file=sys.stderr, flush=True)
            continue
        _, _, ident, rels, passos, resolve = achou
        a["id"], a["escopo"] = ident, (escopo if ident in ESCOPO_MES else "")
        a["guia"] = {"relatorios": [_relatorio(r) for r in rels], "passos": passos, "resolve": resolve}
        if ident in DICAS:
            a["guia"]["dica"] = DICAS[ident]
        if ident in ATUALIZACOES:
            a["guia"]["atualizacao"] = ATUALIZACOES[ident]
    return alertas


# ---------------------------------------------------------------- dinheiro: quem pode ver o alerta
# "Dados financeiros" (Configuracoes): sem essa permissao o usuario nao ve receita, despesa nem valores em R$. Vale para os alertas tambem (na pagina do
# painel e na aba Avisos): um alerta de dinheiro mostraria justamente o que a permissao esconde. O modulos.json diz o que cada painel e:
# "total" (so dinheiro: todo alerta dele e sensivel) ou "parcial" (misto: so os alertas de dinheiro, abaixo).
SENSIVEIS_PARCIAIS = {"cesta_menor_fat", "cesta_ticket_queda", "cesta_valor_zero", "sup_valor_concentrado", "sup_sem_custo"}
# problema de CADASTRO que cita "R$ 0,00" mas nao mostra dinheiro (so quantos registros estao com valor zerado): continua visivel
LIBERADOS = {"ate_valor_zero"}
# o resto e pego pelo texto: citar R$, receita, ticket, custo (que nao seja "centro de custo")... Errar para o lado de esconder: pior ficar sem um aviso
_TEXTO_DINHEIRO = re.compile(r"R\$|receita|ticket|faturament|glosa|(?<!centro de )custo|pre[cç]o|despesa|compras?\b|pagamento|reais\b", re.I)
_REAIS_CELULA = re.compile(r"R\$(?:&nbsp;|\s)*(?!0(?:[,.]0+)?(?![\d.,]))\d")
_COLUNA_DINHEIRO = re.compile(r"R\$|valor|receita|ticket|custo|pre[cç]o|total", re.I)


def financeiro_do_painel(painel: str) -> str | None:
    """'total', 'parcial' ou None ("nenhum"), conforme o modulos.json. Painel sem o campo conta como 'total'."""
    from pathlib import Path
    cfg = json.loads((Path(__file__).parent / "modulos.json").read_text(encoding="utf-8-sig"))
    modulo = next((m for m in cfg["modulos"] if m["id"] == painel), None)
    if modulo is None or modulo.get("tipo") != "relatorios":   # as Metas tem tela propria e nao passam por aqui
        return None
    modo = modulo.get("financeiro", "total")   # sem o campo: so dinheiro (mesma regra de portal_nuvem.modo_financeiro)
    return None if modo == "nenhum" else modo


def sensivel(painel: str, alerta: dict) -> bool:
    """O alerta mostra dinheiro (ou e de um painel so de dinheiro)? Entao so quem tem 'Dados financeiros' pode ve-lo."""
    modo = financeiro_do_painel(painel)
    if modo == "total":
        return True
    if modo != "parcial":
        return False
    if alerta.get("id") in LIBERADOS:
        return False
    if alerta.get("id") in SENSIVEIS_PARCIAIS:
        return True
    itens = alerta.get("itens") if isinstance(alerta.get("itens"), dict) else {}
    colunas = " ".join(str(c) for c in itens.get("colunas", []))
    texto = " ".join(re.sub(r"<[^>]+>", " ", str(alerta.get(k) or "")) for k in ("titulo", "texto"))
    celulas = json.dumps(itens.get("linhas", []), ensure_ascii=False)   # um valor em R$ numa celula, mesmo de coluna com outro nome
    return bool(_TEXTO_DINHEIRO.search(texto) or _COLUNA_DINHEIRO.search(colunas) or _REAIS_CELULA.search(celulas))


def persistente(ident: str) -> bool:
    """O alerta pode ser aceito com justificativa (so reabre se piorar)?"""
    return ident in PERSISTENTES


def sem_guia(painel: str, titulo: str) -> bool:
    """Para testes: o titulo tem regra?"""
    return not any(p == painel and rx.search(titulo) for p, rx, *_ in _COMPILADAS)
