"""Função Python: conferência dos números entre relatórios. Só o servidor Next.js chama (x-interno = CRON_SECRET); a rota admin /api/conferir checa o perfil."""
import hmac
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "painel_py"
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


class handler(BaseHTTPRequestHandler):
    def _responder(self, codigo: int, corpo: dict):
        dados = json.dumps(corpo, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        segredo = os.environ.get("CRON_SECRET", "")
        if not segredo or not hmac.compare_digest(self.headers.get("x-interno", ""), segredo):
            return self._responder(404, {"erro": "nao encontrado"})
        try:
            from conferir import conferir
            return self._responder(200, {"checagens": conferir()})
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return self._responder(500, {"erro": "nao foi possivel conferir"})
