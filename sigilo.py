"""Tira o dinheiro da pagina de um painel para quem nao tem "Dados financeiros" (Configuracoes).

Os paineis sao paginas prontas e iguais para todos, com os dados escritos dentro (`<script id="dados">`). Esconder um grafico com CSS ou
JavaScript nao basta: o valor continuaria no codigo da pagina. Por isso, antes de entregar a pagina a quem nao pode ver dinheiro, o servidor
REMOVE do JSON os campos de valor e os alertas que falam de dinheiro; o modelo da pagina (window.PAINEL_SEM_FIN) cuida de nao desenhar o que
sobrou sem dado. Se um campo escapar, a pagina mostra "—" ou "NaN", nunca o valor.

O modulos.json diz o que cada painel e ("financeiro"): "total" (so dinheiro: nem abre sem a permissao, ver portal_nuvem.conferir_acesso) ou
"parcial" (misto: passa por aqui). Painel sem o campo conta como "total".

PADRAO SEGURO, para campos e relatorios novos ja nascerem protegidos. Num painel misto, a limpeza tem tres camadas:
  1. a lista EXPLICITA do que e dinheiro (CHAVES em qualquer nivel, RAIZ so na raiz): e onde o dev decide e documenta;
  2. QUALQUER campo cujo nome parece dinheiro (DINHEIRO: receita, ticket, valor, custo, saldo, glosa...) e sai tambem, a menos que esteja em MANTER
     (nome parecido, mas que nao e dinheiro, ja conferido: contagens, quantidades);
  3. todo valor em R$ que sobrar num texto vira "R$ •••".
As camadas 2 e 3 so existem para o que ninguem previu; em producao elas protegem, e os testes (tests/test_sigilo.py) rodam so a camada 1 e FALHAM se
sobrar algo para as camadas 2 e 3 pegarem: um campo novo com cara de dinheiro obriga a escolher, por escrito, entre CHAVES/RAIZ (e o modelo) ou MANTER.
"""
import json
import re

import guia_pendencias as gp

# ---- camada 1: o que e dinheiro, por painel misto
# CHAVES vale em qualquer nivel (inclusive dentro de "por_visao", que repete o painel por pessoa); RAIZ so na raiz do JSON (blocos inteiros de dinheiro).
CHAVES: dict[str, frozenset[str]] = {
    "atendimento": frozenset({"receita", "ticket"}),
    "suprimentos": frozenset({"valor", "custo_unit"}),
    # receita e ticket (do mes, dos grupos, dos dias, do perfil), a conferencia com o Faturamento (producao, conferencia), a receita por tipo de exame
    # (modalidades) e a venda cruzada em R$ (potencial)
    "cesta": frozenset({"receita", "ticket", "var_ticket", "ticket_com_exame", "ticket_sozinha", "potencial", "producao", "conferencia", "modalidades"}),
}
RAIZ: dict[str, frozenset[str]] = {
    "suprimentos": frozenset({"valor", "itens", "exame"}),   # valor do estoque, a aba "Item a item" (custos e compras por item) e o material por atendimento (custo)
}

# ---- camada 2: nome com cara de dinheiro
DINHEIRO = re.compile(
    r"receita|ticket|valor|custo|pre[cç]o|fatur|glosa|repasse|saldo|pag(o|amento)|despesa|compra|venda|lucro|margem|honor[aá]rio|taxa|reais|brl|dinheiro|"
    r"potencial|produ[cç][aã]o|produzid|recebid|arrecad|caixa|financ|em_jogo|efeito|(^|_)dif($|_)", re.I)
# nomes parecidos com dinheiro que JA FORAM CONFERIDOS e nao sao: quantidades e contagens
MANTER: dict[str, frozenset[str]] = {
    "atendimento": frozenset({"valor_zero"}),             # quantos registros estao com valor R$ 0,00: problema de cadastro, nao mostra dinheiro
    "suprimentos": frozenset({"compras", "com_saldo"}),   # "compras" = lancamentos de compra/doacao (quantidades, fornecedor, local); "com_saldo" = itens com saldo
    "cesta": frozenset(),
}

# ---- camada 3: valor em R$ solto num texto (R$ 0,00 passa: nao e dinheiro de verdade)
REAIS = re.compile(r"R\$(?:&nbsp;|\s)*(?!0(?:[,.]0+)?(?![\d.,]))\d[\d.,]*")
MASCARA = "R$ •••"

# ---- relatorios novos: colunas de dinheiro que os relatorios.json dos paineis mistos JA declaram (e que o gerador/modelo ja tratam acima).
# tests/test_sigilo.py confere cada coluna numerica de relatorios.json com nome de dinheiro contra esta lista: coluna nova de dinheiro num painel misto
# faz o teste falhar ate alguem decidir o que fazer com ela (escrever em CHAVES/RAIZ e esconder no modelo, ou conferir que nao e dinheiro).
COLUNAS_DE_DINHEIRO: dict[str, frozenset[str]] = {
    "atendimento": frozenset({"Valor do Atendimento", "Ticket Médio"}),
    "cesta": frozenset({"Valor"}),
    "suprimentos": frozenset({"Movimentação - Valor Total", "Movimentação - Valor Unitário", "Solicitação - Valor Atendido"}),
}

_DADOS = re.compile(r'(<script id="dados" type="application/json">)(.*?)(</script>)', re.S)


def _e_alerta(no: dict) -> bool:
    return "titulo" in no and "nivel" in no


def _tira(painel: str, chave: str, chaves: frozenset[str], generico: bool) -> bool:
    if chave in chaves:
        return True
    return generico and bool(DINHEIRO.search(chave)) and chave not in MANTER.get(painel, frozenset())


def limpar_dados(painel: str, no, chaves: frozenset[str], generico: bool = True):
    """Copia de `no` sem os campos de dinheiro e sem os alertas sensiveis. `generico=False` roda so a camada 1 (usado pelos testes)."""
    if isinstance(no, dict):
        return {k: limpar_dados(painel, v, chaves, generico) for k, v in no.items() if not _tira(painel, k, chaves, generico)}
    if isinstance(no, list):
        return [limpar_dados(painel, v, chaves, generico) for v in no if not (isinstance(v, dict) and _e_alerta(v) and gp.sensivel(painel, v))]
    if isinstance(no, str) and generico:
        return REAIS.sub(MASCARA, no)
    return no


def limpar_json(painel: str, dados, generico: bool = True):
    if isinstance(dados, dict):
        dados = {k: v for k, v in dados.items() if k not in RAIZ.get(painel, frozenset())}
    return limpar_dados(painel, dados, CHAVES.get(painel, frozenset()), generico)


def suspeitos(painel: str, dados) -> list[str]:
    """O que a camada 1 deixou passar e as camadas 2 e 3 pegariam em producao: caminhos de campos com cara de dinheiro e textos com valor em R$.
    Vazio = a lista explicita ja cobre tudo. Os testes exigem vazio."""
    achados: list[str] = []

    def anda(no, caminho):
        if isinstance(no, dict):
            for k, v in no.items():
                if DINHEIRO.search(k) and k not in MANTER.get(painel, frozenset()):
                    achados.append(".".join([*caminho, f"{k} (nome)"]))
                anda(v, [*caminho, k])
        elif isinstance(no, list):
            for i, v in enumerate(no[:50]):
                anda(v, [*caminho, f"[{i}]"] if i == 0 else caminho)
        elif isinstance(no, str) and REAIS.search(no):
            achados.append(".".join([*caminho, f"texto com R$: {no[:60]!r}"]))
    anda(limpar_json(painel, dados, generico=False), [])
    return achados


def limpar_html(html: str, painel: str) -> str:
    """A pagina do painel misto sem dinheiro. Levanta erro se nao achar os dados da pagina: melhor nao entregar do que entregar com valores."""
    m = _DADOS.search(html)
    if not m:
        raise RuntimeError(f"Não encontrei os dados da página de {painel} para ocultar os valores.")
    dados = limpar_json(painel, json.loads(m.group(2)))
    novo = json.dumps(dados, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return html[:m.start(2)] + novo + html[m.end(2):]
