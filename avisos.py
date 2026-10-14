"""Aba Avisos: leva para o banco os alertas que cada painel calcula, para a clinica acompanhar as pendencias num lugar so.

Quando a pagina de um painel e refeita (dados novos ou novo dia), `sincronizar` pega os alertas com guia dela e chama `aviso_sincronizar`
no Supabase (supabase/migrations/20261014210000_avisos.sql). Quem decide o que e novo, o que foi corrigido e o que VOLTOU a acontecer e o banco:
  * apareceu pela primeira vez -> aviso aberto;  * deixou de aparecer -> resolvido;  * resolvido e voltou -> aberto de novo (recorrencia);
  * fechado com justificativa e continua nos dados depois de uma atualizacao -> aberto de novo (a justificativa nao resolveu).
Aqui so se monta a lista do que o painel mostra agora, e em quais escopos ela vale.

Escopos: o alerta de "hoje" tem escopo "" e os do mes valem so para aquele mes (ver guia_pendencias.ESCOPO_MES). Conferimos o mes atual e o anterior
(`JANELA_MESES`); um aviso de um mes que saiu da janela fica como estava (nao e dado como resolvido so porque o painel deixou de olhar para ele).
"""
import html
import re

import armazenamento as arm
import guia_pendencias as gp

JANELA_MESES = 2
PADRAO_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_TAGS = re.compile(r"<[^>]+>")


def texto_simples(trecho) -> str:
    """O texto do alerta vem com <b> e afins; no aviso fica so o texto."""
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", str(trecho or "")))).strip()


def _e_alerta(no: dict) -> bool:
    return isinstance(no.get("id"), str) and isinstance(no.get("guia"), dict) and "titulo" in no and "nivel" in no


def _achar(no, saida: list) -> None:
    if isinstance(no, dict):
        if _e_alerta(no):
            saida.append(no)
            return
        for v in no.values():
            _achar(v, saida)
    elif isinstance(no, list):
        for v in no:
            _achar(v, saida)


def janela(payload: dict) -> list[str]:
    """Os meses (AAAA-MM) que o painel tem e que entram na conferencia: o mes padrao e o anterior."""
    meses = sorted(m for m in (payload.get("meses") or {}) if PADRAO_MES.match(str(m)))
    fim = meses.index(payload["mes_padrao"]) + 1 if payload.get("mes_padrao") in meses else len(meses)
    return meses[max(0, fim - JANELA_MESES):fim]


def coletar(payload: dict, painel: str = "") -> tuple[list[dict], list[str]]:
    """(alertas, escopos) do que o painel mostra agora. Alertas sao os que tem guia e nao sao do nivel 'ok'; escopos, onde a conferencia vale."""
    meses_janela = janela(payload)
    escopos = ["", *meses_janela]
    achados: list[dict] = []
    for chave, valor in payload.items():
        if chave == "meses" and isinstance(valor, dict):
            for ym in meses_janela:   # em ordem: o mes mais novo vence quando o mesmo alerta aparece em mais de um
                _achar(valor.get(ym), achados)
        else:
            _achar(valor, achados)
    por_chave: dict[str, dict] = {}
    for a in achados:
        if a.get("nivel") not in ("critico", "atencao", "info"):
            continue
        escopo = a.get("escopo") or ""
        if escopo not in escopos:
            continue
        itens = a.get("itens") if isinstance(a.get("itens"), dict) else None
        chave = f"{escopo}|{a['id']}"
        por_chave[chave] = {
            "chave": chave, "tipo": a["id"], "escopo": escopo, "titulo": str(a["titulo"])[:300], "texto": texto_simples(a.get("texto")),
            "nivel": a["nivel"], "persistente": gp.persistente(a["id"]), "guia": a["guia"],
            "itens": itens, "itens_total": int(itens["total"]) if itens and itens.get("total") is not None else None,
            "sensivel": gp.sensivel(painel, a),   # mostra dinheiro: so quem tem "Dados financeiros" ve na aba Avisos
        }
    return list(por_chave.values()), escopos


def sincronizar(painel: str, payload: dict, versao: int) -> dict | None:
    """Registra os avisos do painel. Sem meses no payload (painel sem dados) nao ha o que conferir: devolve None e nada e dado como resolvido."""
    if not payload.get("meses"):
        return None
    alertas, escopos = coletar(payload, painel)
    return arm.sincronizar_avisos(painel, escopos, versao, alertas)
