"""Textos do "Como achar o problema" de cada alerta de problema (critico/atencao).

ATENCAO: o guia_pendencias.py do legado (que tinha as REGRAS) nao veio na copia recebida. Estes textos foram ESCRITOS de novo a partir do
que cada alerta mede no codigo dos gerar_*.py. Revise com quem opera o Klingo (ver docs/PREMISSAS.md, "Guia dos alertas").

Cada regra: relatorio (nome mostrado; o numero fica so no link), id (do Klingo), passos (lista), resolvido (quando o painel considera resolvido).
O casamento e por trecho do titulo (sem acento e em minusculas), do mais especifico para o mais geral.
"""
from __future__ import annotations

import re
import unicodedata


def _n(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


R = {  # nome do relatorio, id no Klingo
    "producao": ("Receita Produzida por Centro de Resultado", 26),
    "controle": ("Controle de Produção do Faturamento por Convênio", 13329),
    "abertas": ("Faturas Não Baixadas (Faturas em Aberto)", 13328),
    "emitidas": ("Faturamento Consulta - Fatura (Faturas Emitidas)", 13355),
    "lancamentos": ("Lançamentos Financeiros", 798),
    "creditos": ("Créditos de Convênio", 13295),
    "recebimento": ("Recebimento Particular", 13297),
    "despesas": ("Despesas", 13505),
    "guias": ("Guias", 13374),
    "baixas": ("Baixas", 13376),
    "cesta": ("Base da Cesta", 13280),
    "movimentacoes": ("Movimentações de Estoque", 13385),
    "solicitacoes": ("Solicitações de Estoque", 13387),
    "atendimentos": ("Atendimentos", 13402),
    "fluxo": ("Fluxo na Recepção", 13404),
}


def _r(chave: str, passos: list[str], resolvido: str) -> dict:
    nome, id_ = R[chave]
    return {"relatorio": nome, "id": id_, "passos": passos, "resolvido": resolvido}


_LISTA_DO_ALERTA = "A tabela deste alerta já lista os casos (até 25 linhas, com o total real). "

REGRAS: dict[str, list[tuple[str, dict]]] = {
    "faturamento": [
        ("paradas ha mais de", _r("emitidas", ["Abra o relatório de Faturas Emitidas e filtre o período de emissão.", "Deixe só o status “A Enviar”.", "Ordene pela data de emissão: as mais antigas são as paradas.", "Envie a fatura ao convênio no Klingo (ou cancele, se foi emitida por engano)."], "a fatura deixa de estar “A Enviar” (foi enviada ou cancelada).")),
        ("esperando envio ha mais de", _r("emitidas", ["Abra o relatório de Faturas Emitidas e filtre o período de emissão.", "Deixe só o status “A Enviar” e veja a data de emissão.", "Envie as faturas mais antigas ao convênio."], "a fatura sai do status “A Enviar”.")),
        ("nenhuma enviada", _r("emitidas", ["No relatório de Faturas Emitidas, procure o convênio da tabela.", "Confira se alguma fatura dele já foi enviada: se nunca foi, pode ser o primeiro envio (protocolo/portal) ou um cadastro incompleto."], "o convênio passa a ter ao menos uma fatura enviada.")),
        ("faturas canceladas", _r("emitidas", ["No relatório de Faturas Emitidas, filtre pelo convênio da tabela e pelo status “Cancelada”.", "Veja o usuário responsável: muitos cancelamentos de um mesmo usuário ou convênio indicam erro de processo."], "a taxa de cancelamento do convênio volta abaixo do limite.")),
        ("ativas sem valor", _r("emitidas", ["No relatório de Faturas Emitidas, procure as faturas da tabela (pelo Id).", "Confira os itens da fatura no Klingo: o valor está vazio ou zero.", "Corrija o valor ou cancele a fatura."], "a fatura passa a ter valor maior que zero ou é cancelada.")),
        ("nenhuma fatura", _r("controle", ["Abra o Controle por Convênio e veja o produzido do mês de referência.", "No relatório de Faturas Emitidas, confira se o convênio tem fatura com início naquele mês.", "Se não tem, gere a fatura do período no Klingo."], "existe fatura emitida do convênio para o mês de referência.")),
        ("ainda nao virou fatura", _r("controle", ["Compare, por convênio, o produzido (Controle por Convênio) com o faturado (Faturas Emitidas) do mesmo mês.", "Gere as faturas que faltam no Klingo."], "o faturado se aproxima do produzido (falta menos de 10%).")),
        ("faturas vencidas e ainda nao baixadas", _r("abertas", ["Abra o relatório de Faturas em Aberto e ordene pelo vencimento.", "Para cada lote vencido, confira no financeiro do convênio se foi pago.", "Se foi pago, dê a baixa no Klingo; se não, cobre o convênio."], "o lote é baixado ou deixa de estar vencido.")),
        ("quase nada de convenio", _r("controle", ["Abra o Controle por Convênio do mês de referência e compare Produzido × Recebido.", "Confira se as baixas dos convênios estão sendo lançadas no Klingo."], "o recebido passa de 10% do produzido.")),
        ("glosa registrada", _r("controle", ["No Controle por Convênio, veja a coluna Glosa de cada convênio da tabela.", "Abra o detalhe do lote no Klingo e confira o motivo da glosa."], "a glosa é revertida ou tratada (recurso/baixa).")),
        ("faturas em aberto sem valor", _r("abertas", ["No relatório de Faturas em Aberto, filtre Valor Bruto vazio ou zero.", "Abra o lote no Klingo e corrija o valor."], "o lote passa a ter Valor Bruto maior que zero.")),
        ("receita abaixo do mes anterior", _r("producao", ["No relatório de Receita Produzida, compare o mês com o anterior por Operadora e por Categoria.", "Veja onde a queda se concentra."], "a receita volta a ficar a menos de 10% abaixo do mês anterior.")),
        ("relatorios de producao nao batem", _r("controle", ["Compare o total de convênios da Receita Produzida com o Produzido do Controle por Convênio.", "Diferenças pequenas (~0,1%) são normais; acima de 2%, procure convênios que aparecem em um e não no outro."], "a diferença entre os dois relatórios fica abaixo de 2%.")),
    ],
    "financeiro": [
        ("contas vencidas sem baixa", _r("lancamentos", ["Abra o relatório de Lançamentos Financeiros e filtre os vencidos sem Conta.", "Se a despesa foi paga, preencha a Conta (baixa) no Klingo; se não foi, programe o pagamento."], "o lançamento passa a ter Conta preenchida.")),
        ("vencimentos nos proximos 7 dias", _r("lancamentos", ["Abra o relatório de Lançamentos Financeiros e filtre os vencimentos dos próximos 7 dias sem Conta.", "Programe o pagamento."], "o lançamento é pago (Conta preenchida) ou passa do prazo.")),
        ("mais a pagar do que a receber", _r("lancamentos", ["Veja no painel o bloco “Por que o saldo está negativo”.", "Confira no relatório de Lançamentos as maiores despesas do mês e se alguma está duplicada ou com data errada."], "o a receber do mês passa do a pagar.")),
        ("quase nenhum credito", _r("creditos", ["Abra o relatório de Créditos de Convênio e compare com o Controle por Convênio.", "Confira se os créditos dos convênios estão sendo lançados."], "os créditos identificados se aproximam do recebido.")),
        ("data invalida", _r("lancamentos", ["No relatório de Lançamentos Financeiros, procure o lançamento da tabela (pelo número).", "Corrija o vencimento (ano digitado errado, por exemplo 0206)."], "o vencimento passa a ser uma data válida.")),
    ],
    "despesas": [
        ("valor zero", _r("despesas", ["No relatório de Despesas, procure os lançamentos da tabela.", "Corrija o valor ou cancele o lançamento."], "o lançamento passa a ter valor maior que zero.")),
        ("repetidos", _r("despesas", ["No relatório de Despesas, abra os pares da tabela (mesma categoria, fornecedor, data e valor).", "Se for duplicidade, exclua um deles."], "os lançamentos deixam de aparecer como repetidos.")),
        ("sem fornecedor", _r("despesas", ["No relatório de Despesas, procure os lançamentos da tabela.", "Preencha o fornecedor."], "o lançamento passa a ter fornecedor.")),
        ("honorario medico", _r("despesas", ["Confira no relatório de Despesas se o Honorário Médico do mês foi lançado.", "Compare com a produção por médico (Receita Produzida)."], "o Honorário Médico do mês é lançado.")),
    ],
    "indicadores": [
        ("guias pendentes de correcao", _r("guias", ["Abra o relatório de Guias e filtre as guias com Pendência.", "Corrija o motivo da pendência na guia (a tabela lista as mais antigas)."], "a guia deixa de ter pendência.")),
        ("recebido das guias nao bate", _r("baixas", ["Compare o total de Baixas com o Recebido do Controle por Convênio.", "Procure baixas sem guia ou guias baixadas em duplicidade."], "a diferença entre os relatórios fica dentro do limite.")),
    ],
    "cesta": [
        ("menos pacientes fazendo mais de um exame", _r("cesta", ["Compare no relatório da Base da Cesta os atendimentos com 2 ou mais exames dos últimos meses.", "Veja se mudou a forma de lançar os exames (exames lançados em atendimentos separados)."], "a proporção de atendimentos com 2+ exames volta ao nível anterior.")),
        ("linhas com valor zero", _r("cesta", ["No relatório da Base da Cesta, filtre Valor igual a zero.", "Confira se é retorno/cortesia ou preço não cadastrado."], "a linha passa a ter valor ou é confirmada como cortesia.")),
        ("combos e grupos", _r("cesta", ["No cadastro de procedimentos do Klingo, preencha Combo e Grupo dos exames.", "Hoje o painel deduz os combos pelo comportamento dos atendimentos."], "as colunas Combo/Grupo passam a vir preenchidas no relatório.")),
        ("paciente com", _r("cesta", ["No relatório da Base da Cesta, procure o paciente da tabela.", "Corrija a data de nascimento no cadastro."], "a idade passa a ser plausível.")),
    ],
    "suprimentos": [
        ("nunca foi baixado", _r("movimentacoes", ["No relatório de Movimentações, veja as entregas ao setor (transferências) do item.", "Confira se o setor dá baixa no consumo."], "o setor registra baixa de consumo do item.")),
        ("quase nada e atendido", _r("solicitacoes", ["No relatório de Solicitações, filtre o setor da tabela e veja os itens pendentes.", "Atenda ou encerre os pedidos."], "o setor passa a ter menos de 90% dos itens pendentes.")),
        ("sem baixa de consumo", _r("movimentacoes", ["No relatório de Movimentações, veja a última baixa (saída por consumo).", "Confira se os atendimentos estão dando baixa no estoque."], "uma nova baixa de consumo é registrada.")),
        ("nenhuma baixa de consumo", _r("movimentacoes", ["No relatório de Movimentações, procure saídas por consumo no período.", "Ative ou revise o lançamento de consumo no Klingo."], "aparece ao menos uma baixa de consumo.")),
        ("baixas de consumo que nao baixam", _r("movimentacoes", ["No relatório de Movimentações, procure baixas com quantidade zero.", "Corrija o lançamento."], "as baixas passam a ter quantidade.")),
        ("nunca tiveram estoque", _r("movimentacoes", ["Confira os itens da tabela no relatório de Movimentações: não há entrada de estoque.", "Lance a entrada/inventário do item."], "o item passa a ter estoque lançado.")),
        ("estoque zerado", _r("solicitacoes", ["Veja os itens da tabela: pedidos pendentes com saldo zero.", "Providencie a compra ou a entrada."], "o item volta a ter saldo.")),
        ("maiores que o estoque", _r("solicitacoes", ["Compare, por item, o pedido pendente com o saldo.", "Providencie a compra."], "o saldo passa a cobrir os pedidos em aberto.")),
        ("concentrado em um item", _r("movimentacoes", ["Confira o custo informado do item que concentra o valor (Custos dos Itens).", "Corrija se o custo estiver por frasco/caixa errado."], "o item deixa de passar de 50% do valor do estoque ou o custo é corrigido.")),
    ],
    "atendimento": [
        ("espera", _r("atendimentos", ["Abra o relatório de Atendimentos e compare Check-In e início do atendimento.", "Procure os horários com mais espera."], "a espera mediana volta abaixo da meta.")),
        ("registro", _r("atendimentos", ["No relatório de Atendimentos e no Fluxo na Recepção, procure registros sem horário ou com horário incoerente.", "Oriente a recepção a registrar todas as etapas."], "a proporção de registros com problema fica abaixo do limite.")),
    ],
}

# regra generica por painel (usada quando nenhum trecho casa): aponta o relatorio principal e a lista do proprio alerta
GENERICAS = {
    "faturamento": "emitidas", "financeiro": "lancamentos", "despesas": "despesas", "indicadores": "guias",
    "cesta": "cesta", "suprimentos": "movimentacoes", "atendimento": "atendimentos",
}


def regra(painel: str, titulo: str) -> dict | None:
    t = _n(titulo)
    for trecho, r in REGRAS.get(painel, []):
        if trecho in t:
            return r
    g = GENERICAS.get(painel)
    if g:   # sem texto proprio: guia generico (o log avisa em guia_pendencias.anotar)
        r = _r(g, [_LISTA_DO_ALERTA + "Procure os mesmos casos no relatório indicado e corrija no Klingo."], "o caso deixa de aparecer no painel após a próxima atualização.")
        r["generica"] = True
        return r
    return None
