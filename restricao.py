"""Limita a pagina de um painel a UMA parte da clinica para quem foi restrito em Configuracoes (hoje: Atendimento, por responsavel).

O painel Atendimento ja traz a clinica inteira e, junto, uma visao por responsavel (Atendimento/responsaveis.json: cada pessoa so com os setores dela).
Esconder "Todos" no navegador nao bastaria: os numeros dos outros setores continuariam no codigo da pagina (`<script id="dados">`). Por isso, antes de
entregar a pagina a quem esta restrito, o servidor TROCA os dados da clinica pelos da visao dele e apaga as demais, e o modelo (D.visao_fixa) so
precisa abrir direto nessa visao, sem a opcao "Todos". Mesmo desenho do sigilo.py.

A restricao mora em profiles.permissions.<painel>_visao (texto = id do responsavel; vazio ou ausente = sem restricao). Administrador nunca e restrito.
"""
import json
import re

CHAVE_SUFIXO = "_visao"
PAINEIS_COM_VISAO = frozenset({"atendimento"})

_DADOS = re.compile(r'(<script id="dados" type="application/json">)(.*?)(</script>)', re.S)


class VisaoInexistente(Exception):
    """A pessoa esta restrita a uma visao que a pagina nao tem (responsaveis.json mudou?). Nao entrega nada: melhor negar do que mostrar a clinica toda."""


def chave_da_permissao(painel: str) -> str:
    return painel + CHAVE_SUFIXO


def visao_do_perfil(permissoes: dict, painel: str) -> str | None:
    """O id da visao a que o perfil esta restrito neste painel, ou None. So vale texto nao vazio e so em painel que tem visoes."""
    if painel not in PAINEIS_COM_VISAO:
        return None
    v = (permissoes or {}).get(chave_da_permissao(painel))
    return v.strip().lower() if isinstance(v, str) and v.strip() else None


def limpar_dados(painel: str, dados: dict, visao: str) -> dict:
    """Copia dos dados da pagina so com a visao `visao`: `meses` passa a ser os meses dela, `por_visao` some e `visao_fixa` diz ao modelo para nao oferecer outra."""
    visoes = dados.get("visoes") or []
    if not visoes:   # painel sem nenhum dado ainda: nao ha o que vazar (a pagina so mostra "Ainda nao ha dados")
        return {**dados, "meses": {}, "por_visao": {}, "visoes": [], "visao_fixa": visao, "mes_padrao": None}
    escolhida = next((v for v in visoes if v.get("id") == visao), None)
    if escolhida is None:
        raise VisaoInexistente(visao)
    meses = (dados.get("por_visao") or {}).get(visao) or {}
    mes_padrao = dados.get("mes_padrao")
    if mes_padrao not in meses:
        simples = sorted(k for k in meses if ".." not in k)
        mes_padrao = simples[-1] if simples else None
    return {**dados, "meses": meses, "por_visao": {}, "visoes": [escolhida], "visao_fixa": visao, "mes_padrao": mes_padrao}


def limpar_html(html: str, painel: str, visao: str) -> str:
    """A pagina so com a visao `visao`. Levanta erro se nao achar os dados da pagina: melhor nao entregar do que entregar a clinica toda."""
    m = _DADOS.search(html)
    if not m:
        raise RuntimeError(f"Não encontrei os dados da página de {painel} para limitar a visão.")
    dados = limpar_dados(painel, json.loads(m.group(2)), visao)
    novo = json.dumps(dados, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return html[:m.start(2)] + novo + html[m.end(2):]
