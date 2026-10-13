"""De onde os paineis leem os dados: Supabase (producao) ou uma pasta de arquivos JSON (testes e conferencia local).

Producao (variaveis de ambiente do servidor, nunca no navegador):
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
Teste/local:
  DADOS_DIR=<pasta> com um arquivo <menu>.json = {"versao": <epoch s>, "blocos": [{"aba","mes","colunas","linhas"}]} e, opcionalmente,
  custos.json = [{"item","unidade","custo"}] e pendencias.json.

Formato de um bloco (uma aba de um mes): "colunas" = titulos do Klingo; "linhas" = lista de listas na mesma ordem; numeros como numero e
datas como texto ISO ("AAAA-MM-DD" ou "AAAA-MM-DD HH:MM:SS"). No Supabase o bloco fica em dados_blocos com as linhas em JSON + gzip + base64.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_CACHE: dict = {}


def _dir() -> Path | None:
    d = os.environ.get("DADOS_DIR")
    return Path(d) if d else None


# ---------------------------------------------------------------- Supabase (PostgREST)
def _rest(caminho: str, params: dict | None = None, metodo: str = "GET", corpo=None, extra: dict | None = None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    chave = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not chave:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY no servidor.")
    url = f"{base}/rest/v1/{caminho}" + (("?" + urllib.parse.urlencode(params)) if params else "")
    cab = {"apikey": chave, "Authorization": f"Bearer {chave}", "Accept": "application/json", "Content-Type": "application/json", **(extra or {})}
    req = urllib.request.Request(url, method=metodo, headers=cab, data=json.dumps(corpo).encode() if corpo is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read()
    except urllib.error.HTTPError as e:   # nunca devolve o corpo do erro ao navegador: so ao log
        raise RuntimeError(f"Supabase respondeu HTTP {e.code} em {caminho}") from None
    return json.loads(txt) if txt else None


def rest(caminho: str, params: dict | None = None, metodo: str = "GET", corpo=None, extra: dict | None = None):
    return _rest(caminho, params, metodo, corpo, extra)


# ---------------------------------------------------------------- dados
def versao_dados(menu: str) -> float | None:
    """Segundos (epoch) da ultima vez que o menu recebeu dados novos; None se nunca recebeu."""
    d = _dir()
    if d:
        f = d / f"{menu}.json"
        if not f.exists():
            return None
        return float(json.loads(f.read_text(encoding="utf-8")).get("versao") or f.stat().st_mtime)
    chave = ("versao", menu)
    agora = time.time()
    if chave in _CACHE and agora - _CACHE[chave][0] < 10:   # vale so durante uma geracao de pagina (uma funcao "quente" nao pode guardar para sempre)
        return _CACHE[chave][1]
    linhas = _rest("dados_versao", {"select": "atualizado_em", "menu": f"eq.{menu}"})
    v = None
    if linhas:
        from datetime import datetime
        v = datetime.fromisoformat(linhas[0]["atualizado_em"].replace("Z", "+00:00")).timestamp()
    _CACHE[chave] = (agora, v)
    return v


def contador_versao(menu: str) -> int:
    """Contador que sobe a cada gravacao de dados do menu (chave do cache dos paineis)."""
    d = _dir()
    if d:
        return int(versao_dados(menu) or 0)
    linhas = _rest("dados_versao", {"select": "versao", "menu": f"eq.{menu}"})
    return int(linhas[0]["versao"]) if linhas else 0


def blocos(menu: str) -> list[dict]:
    d = _dir()
    if d:
        f = d / f"{menu}.json"
        return json.loads(f.read_text(encoding="utf-8")).get("blocos", []) if f.exists() else []
    contador = contador_versao(menu)
    guardado = _CACHE.get(("blocos", menu))
    if guardado and guardado[0] == contador:   # um bloco por menu na memoria; troca quando o contador muda
        return guardado[1]
    out = []
    for r in _rest("dados_blocos", {"select": "aba,mes,colunas,conteudo", "menu": f"eq.{menu}", "order": "aba,mes"}) or []:
        linhas = json.loads(gzip.decompress(base64.b64decode(r["conteudo"]))) if r.get("conteudo") else []
        out.append({"aba": r["aba"], "mes": r["mes"], "colunas": r["colunas"], "linhas": linhas})
    _CACHE[("blocos", menu)] = (contador, out)
    return out


def custos_itens() -> list[dict]:
    """Custos informados pelo admin (Suprimentos): [{"item","unidade","custo"}]."""
    d = _dir()
    if d:
        f = d / "custos.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    return _rest("custos_itens", {"select": "item,unidade,custo"}) or []


def registrar_itens_custo(itens: list[dict]) -> None:
    """Garante uma linha em custos_itens para cada item do estoque, atualizando so grupo/unidade/embalagem/custo do Klingo (nunca o custo digitado)."""
    if not itens or _dir():
        return
    cab = {"Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(itens), 500):
        _rest("custos_itens", {"on_conflict": "item"}, "POST", itens[i:i + 500], cab)
