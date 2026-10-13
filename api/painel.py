"""Entrega a pagina de um painel (GET /api/painel?id=faturamento[&de=AAAA-MM&ate=AAAA-MM])."""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_nuvem as pn  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        pn.rota_pagina(self)

    def log_message(self, *args):   # o log da Vercel ja registra cada pedido
        pass
