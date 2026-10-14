"""POST /api/renovar?id=faturamento: a tela do painel pede a renovacao (copiar do banco + refazer a pagina) quando abriu com dados vencidos."""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_nuvem as pn  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        pn.rota_renovar(self)

    def log_message(self, *args):   # o log da Vercel ja registra cada pedido
        pass
