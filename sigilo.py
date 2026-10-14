"""Tira o dinheiro da pagina de um painel para quem nao tem "Dados financeiros" (Configuracoes).

Os paineis sao paginas prontas e iguais para todos, com os dados escritos dentro (`<script id="dados">`). Esconder um grafico com CSS ou
JavaScript nao basta: o valor continuaria no codigo da pagina. Por isso, antes de entregar a pagina a quem nao pode ver dinheiro, o servidor
REMOVE do JSON os campos de valor (`CHAVES`, por painel) e os alertas que falam de dinheiro (guia_pendencias.sensivel); o modelo da pagina
(window.PAINEL_SEM_FIN) cuida de nao desenhar o que sobrou sem dado. Se um campo escapar da lista, a pagina mostra "—" ou "NaN", nunca o valor.

O modulos.json diz o que cada painel e: "total" (so dinheiro: nem abre sem a permissao, ver portal_nuvem.conferir_acesso) ou "parcial" (misto: passa por aqui).
"""
import json
import re

import guia_pendencias as gp

# Campos do JSON de cada painel misto que carregam dinheiro. CHAVES vale em qualquer nivel (inclusive dentro de "por_visao", que repete o painel por pessoa);
# RAIZ so na raiz do JSON (para blocos inteiros de dinheiro, cujo nome pode aparecer em outro lugar com outro sentido).
CHAVES: dict[str, frozenset[str]] = {
    "atendimento": frozenset({"receita", "ticket"}),
    "suprimentos": frozenset({"valor", "custo_unit"}),
    # receita e ticket (do mes, dos grupos, dos dias, do perfil), a conferencia com o Faturamento (producao, conferencia), a receita por tipo de exame (modalidades) e a venda cruzada em R$
    "cesta": frozenset({"receita", "ticket", "var_ticket", "ticket_com_exame", "ticket_sozinha", "potencial", "producao", "conferencia", "modalidades"}),
}
RAIZ: dict[str, frozenset[str]] = {
    "suprimentos": frozenset({"valor", "itens", "exame"}),   # valor do estoque, a aba "Item a item" (custos e compras por item) e o material por atendimento (custo)
}

_DADOS = re.compile(r'(<script id="dados" type="application/json">)(.*?)(</script>)', re.S)


def _e_alerta(no: dict) -> bool:
    return "titulo" in no and "nivel" in no


def limpar_dados(painel: str, no, chaves: frozenset[str]):
    """Copia de `no` sem os campos de dinheiro e sem os alertas sensiveis."""
    if isinstance(no, dict):
        return {k: limpar_dados(painel, v, chaves) for k, v in no.items() if k not in chaves}
    if isinstance(no, list):
        return [limpar_dados(painel, v, chaves) for v in no if not (isinstance(v, dict) and _e_alerta(v) and gp.sensivel(painel, v))]
    return no


def limpar_html(html: str, painel: str) -> str:
    """A pagina do painel misto sem dinheiro. Levanta erro se nao achar os dados da pagina: melhor nao entregar do que entregar com valores."""
    m = _DADOS.search(html)
    if not m:
        raise RuntimeError(f"Não encontrei os dados da página de {painel} para ocultar os valores.")
    dados = json.loads(m.group(2))
    if isinstance(dados, dict):
        dados = {k: v for k, v in dados.items() if k not in RAIZ.get(painel, frozenset())}
    dados = limpar_dados(painel, dados, CHAVES.get(painel, frozenset()))
    novo = json.dumps(dados, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return html[:m.start(2)] + novo + html[m.end(2):]
