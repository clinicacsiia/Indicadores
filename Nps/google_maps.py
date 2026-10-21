"""Nota e avaliações da Clínica CSI no Google Maps, pela API oficial (Places API, "New").

Por que a API e não a página: a lista de avaliações do Google carrega por JavaScript e raspá-la viola os termos do Google; a API é o caminho
permitido e estável. Ela devolve a **nota média**, o **total de avaliações** e **até 5 avaliações** (as que o Google considera mais relevantes,
não as mais novas). Por isso o painel guarda, a cada atualização:
- um **resumo do dia** (nota e total) na aba "Google": é ele que forma o histórico, porque o Google não entrega a nota de ontem;
- as **avaliações** vistas, uma vez cada (aba "Google avaliações"): com o tempo elas se acumulam, mas nunca são todas.

Fica no mesmo armazenamento dos outros painéis (`painel_dados` do painel `nps`), então a página pronta se refaz sozinha quando entra dado novo.
Só funciona na nuvem (precisa do Supabase); no programa local, sem Google, o painel mostra só o NPS.

Configuração (Vercel > Settings > Environment Variables):
- `GOOGLE_PLACES_API_KEY` (obrigatória): chave do Google Cloud com a "Places API (New)" ativada.
- `GOOGLE_PLACE_ID` (opcional): o id do perfil (ChIJ...). Sem ele o perfil é achado pela busca "Clínica CSI" e conferido pelo CID do parametros.json.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

import armazenamento as arm

PAINEL = "nps"
ABA_RESUMO, ABA_AVALIACOES = "Google", "Google avaliações"
API = "https://places.googleapis.com/v1"
INTERVALO_MIN_S = 5 * 3600          # entre duas consultas automáticas (o botão "Atualizar agora" pode repetir depois de 30 min)
INTERVALO_BOTAO_S = 30 * 60
TIMEOUT = 25
MAX_AVALIACOES = 500                # teto do que fica guardado


class GoogleErro(RuntimeError):
    """A API do Google recusou ou não respondeu (chave, cota, rede). A mensagem diz o que fazer."""


def chave() -> str:
    return os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()


def configurado() -> bool:
    return bool(chave())


def disponivel() -> bool:
    """Há onde guardar (nuvem) ? Fora dela o painel mostra só o NPS."""
    return arm.ativo()


# ---------------------------------------------------------------- chamadas à API
def _http(metodo: str, caminho: str, campos: str, corpo: dict | None = None) -> dict:
    cab = {"X-Goog-Api-Key": chave(), "X-Goog-FieldMask": campos, "Accept": "application/json"}
    dados = None
    if corpo is not None:
        dados, cab["Content-Type"] = json.dumps(corpo).encode("utf-8"), "application/json"
    req = urllib.request.Request(API + caminho, data=dados, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detalhe = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detalhe = ""
        dica = {400: "a chave ou o pedido foi recusado", 403: "a chave não tem a Places API (New) ativada ou tem restrição que barra a Vercel",
                429: "a cota do Google acabou por agora"}.get(e.code, "o Google recusou o pedido")
        raise GoogleErro(f"Google Maps: {dica} (HTTP {e.code}). {detalhe}".strip()) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GoogleErro(f"Google Maps: sem resposta ({type(e).__name__}).") from e


def achar_perfil(busca: str, cid: str | None) -> str:
    """Id do perfil da clínica: GOOGLE_PLACE_ID, ou a busca por texto conferida pelo CID (o número que está no link do Maps)."""
    fixo = os.environ.get("GOOGLE_PLACE_ID", "").strip()
    if fixo:
        return fixo
    res = _http("POST", "/places:searchText", "places.id,places.displayName,places.googleMapsUri",
                {"textQuery": busca, "languageCode": "pt-BR", "regionCode": "BR", "pageSize": 10})
    lugares = res.get("places") or []
    if cid:
        for p in lugares:
            if re.search(rf"[?&]cid={re.escape(str(cid))}\b", p.get("googleMapsUri", "")):
                return p["id"]
        raise GoogleErro(f"Google Maps: a busca por “{busca}” não achou o perfil de CID {cid}. Defina GOOGLE_PLACE_ID na Vercel com o id do perfil (ChIJ...).")
    if not lugares:
        raise GoogleErro(f"Google Maps: a busca por “{busca}” não achou nenhum perfil. Defina GOOGLE_PLACE_ID na Vercel.")
    return lugares[0]["id"]


def consultar_perfil(place_id: str) -> dict:
    return _http("GET", f"/places/{place_id}?languageCode=pt-BR", "id,displayName,rating,userRatingCount,googleMapsUri,reviews")


# ---------------------------------------------------------------- o que fica guardado
def ler() -> dict:
    """{'resumos': [{dia, coletado_em, nota, total, place_id, nome}] por dia, 'avaliacoes': [{id, dia, nota, texto, ...}] mais novas primeiro}.
    Vazio fora da nuvem ou se o banco não responder (o painel segue só com o NPS)."""
    vazio = {"resumos": [], "avaliacoes": []}
    if not disponivel():
        return vazio
    try:
        resumos = sorted(arm.ler_aba(PAINEL, ABA_RESUMO), key=lambda r: r.get("coletado_em") or r.get("dia") or "")
        avaliacoes = arm.ler_aba(PAINEL, ABA_AVALIACOES)
    except arm.ErroArmazenamento as e:
        print(f">>> AVISO: não consegui ler os dados do Google: {e}", flush=True)
        return vazio
    por_dia = {r["dia"]: r for r in resumos if r.get("dia")}   # um por dia: vale o último do dia
    avaliacoes.sort(key=lambda r: (r.get("dia") or "", r.get("id") or ""), reverse=True)
    return {"resumos": [por_dia[d] for d in sorted(por_dia)], "avaliacoes": avaliacoes}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _texto(av: dict) -> str:
    t = av.get("originalText") or av.get("text") or {}
    return (t.get("text") if isinstance(t, dict) else str(t or "")).strip()


def _dia_local(iso: str | None, padrao: str) -> str:
    """'2026-10-20T14:03:11Z' -> dia no horário de Brasília (UTC-3, sem horário de verão desde 2019)."""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (d.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)).date().isoformat()
    except (ValueError, TypeError):
        return padrao


def atualizar(cfg: dict, forcar: bool = False) -> dict:
    """Consulta o Google (se a chave existe e a última consulta é velha) e guarda o resumo do dia e as avaliações novas.
    Devolve {'atualizou', 'mensagem', 'avisos'}; falha do Google nunca derruba a atualização do NPS: vira aviso."""
    if not disponivel():
        return {"atualizou": False, "mensagem": "", "avisos": []}
    if not configurado():
        return {"atualizou": False, "avisos": [],
                "mensagem": "Google Maps: falta a variável GOOGLE_PLACES_API_KEY na Vercel (veja “Como ler este painel”); por enquanto o painel mostra só o NPS."}
    atual = ler()
    ultimo = atual["resumos"][-1] if atual["resumos"] else None
    if ultimo and ultimo.get("coletado_em"):
        try:
            idade = (_agora() - datetime.fromisoformat(ultimo["coletado_em"])).total_seconds()
            if idade < (INTERVALO_BOTAO_S if forcar else INTERVALO_MIN_S):
                return {"atualizou": False, "avisos": [], "mensagem": f"Google Maps: consultado há {idade / 3600:.1f} h; não consultei de novo."}
        except ValueError:
            pass
    try:
        place_id = (ultimo or {}).get("place_id") or achar_perfil(cfg.get("google_busca") or "Clínica CSI", cfg.get("google_cid"))
        perfil = consultar_perfil(place_id)
    except GoogleErro as e:
        return {"atualizou": False, "mensagem": str(e), "avisos": [str(e)]}
    if perfil.get("rating") is None or perfil.get("userRatingCount") is None:
        msg = "Google Maps: o perfil não trouxe nota nem total de avaliações."
        return {"atualizou": False, "mensagem": msg, "avisos": [msg]}

    agora = _agora()
    hoje = _dia_local(agora.isoformat(), date.today().isoformat())
    resumo = {"dia": hoje, "coletado_em": agora.isoformat(), "nota": float(perfil["rating"]), "total": int(perfil["userRatingCount"]), "place_id": place_id,
              "nome": (perfil.get("displayName") or {}).get("text", ""), "url": perfil.get("googleMapsUri", "")}
    ym = hoje[:7]
    do_mes = [r for r in arm.ler_aba(PAINEL, ABA_RESUMO) if str(r.get("dia", ""))[:7] == ym and r.get("dia") != hoje]
    arm.gravar_mes(PAINEL, ABA_RESUMO, ym, do_mes + [resumo])

    conhecidas = {r["id"] for r in atual["avaliacoes"] if r.get("id")}
    novas = []
    for av in perfil.get("reviews") or []:
        rid = av.get("name") or ""
        if not rid or rid in conhecidas or av.get("rating") is None:
            continue
        novas.append({"id": rid, "dia": _dia_local(av.get("publishTime"), hoje), "publicado_em": av.get("publishTime"), "nota": int(av["rating"]),
                      "texto": _texto(av), "relativo": av.get("relativePublishTimeDescription", ""), "visto_em": agora.isoformat()})
    if novas:
        guardadas = [r for r in arm.ler_aba(PAINEL, ABA_AVALIACOES) if str(r.get("visto_em", ""))[:7] == ym]
        arm.gravar_mes(PAINEL, ABA_AVALIACOES, ym, (guardadas + novas)[-MAX_AVALIACOES:])
    msg = f"Google Maps: nota {resumo['nota']:.1f} com {resumo['total']} avaliações" + (f", {len(novas)} avaliação(ões) nova(s) guardada(s)." if novas else ".")
    return {"atualizou": True, "mensagem": msg, "avisos": []}
