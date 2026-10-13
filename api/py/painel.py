"""Funcao Python da Vercel: calcula (ou le do cache) a pagina de um painel. So o servidor Next.js chama (cabecalho x-interno = CRON_SECRET):
o navegador nunca fala direto com esta rota; a sessao e a permissao do menu sao checadas antes, em src/app/api/painel/[menu]/route.ts.

GET /api/py/painel?menu=faturamento&de=2026-09&ate=2026-10[&aquecer=1]
"""
import hmac
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parents[2] / "painel_py"
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

MENUS = {"metas", "faturamento", "financeiro", "despesas", "indicadores", "cesta", "suprimentos", "atendimento"}


def _autorizado(cabecalho: str) -> bool:
    segredo = os.environ.get("CRON_SECRET", "")
    return bool(segredo) and hmac.compare_digest(cabecalho or "", segredo)


class handler(BaseHTTPRequestHandler):
    def _responder(self, codigo: int, corpo: bytes, tipo: str = "application/json; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if not _autorizado(self.headers.get("x-interno", "")):
            return self._responder(404, b'{"erro":"nao encontrado"}')
        q = parse_qs(urlparse(self.path).query)
        menu = (q.get("menu") or [""])[0]
        de, ate = (q.get("de") or [""])[0], (q.get("ate") or [""])[0]
        if menu not in MENUS:
            return self._responder(400, b'{"erro":"menu invalido"}')
        try:
            import painel_cache
            from painel_runtime import gerar_html

            periodo = f"{de}..{ate}" if (de or ate) else ""
            versao = painel_cache.chave_versao(menu)
            html = painel_cache.ler(menu, periodo, versao)
            cache = html is not None
            if html is None:
                html = gerar_html(menu, de or None, ate or None)
                painel_cache.gravar(menu, periodo, versao, html)
                painel_cache.limpar_antigos(menu)
            if (q.get("aquecer") or [""])[0]:
                return self._responder(200, json.dumps({"ok": True, "cache": cache}).encode())
            return self._responder(200, html.encode("utf-8"), "text/html; charset=utf-8")
        except Exception:   # o detalhe vai so para o log do servidor, nunca para o navegador
            traceback.print_exc(file=sys.stderr)
            return self._responder(500, '{"erro":"nao foi possivel montar o painel"}'.encode())
