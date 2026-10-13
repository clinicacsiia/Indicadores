"""A leitura pelo Supabase (PostgREST) dá o MESMO painel que a leitura local: servidor falso com o formato real de dados_blocos/dados_versao/painel_cache."""
import base64
import gzip
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parents[2]

DIR = tempfile.mkdtemp(prefix="dados_sinteticos_")
subprocess.run([sys.executable, str(RAIZ / "scripts" / "gerar_dados_sinteticos.py"), DIR], check=True, stdout=subprocess.DEVNULL)

ARQUIVOS = {m: json.loads((Path(DIR) / f"{m}.json").read_text(encoding="utf-8")) for m in ("metas", "faturamento")}
CACHE: dict = {}


class Falso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, corpo, codigo=200):
        dados = json.dumps(corpo).encode()
        self.send_response(codigo); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(dados))); self.end_headers(); self.wfile.write(dados)

    def do_GET(self):
        assert self.headers["apikey"] and self.headers["Authorization"].startswith("Bearer ")
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        tabela = u.path.rsplit("/", 1)[-1]
        menu = q.get("menu", "").replace("eq.", "")
        if tabela == "dados_versao":
            a = ARQUIVOS.get(menu)
            return self._json([{"atualizado_em": "2026-10-13T15:00:00+00:00", "versao": 7}] if a else [])
        if tabela == "dados_blocos":
            blocos = ARQUIVOS.get(menu, {}).get("blocos", [])
            return self._json([{"aba": b["aba"], "mes": b["mes"], "colunas": b["colunas"],
                                "conteudo": base64.b64encode(gzip.compress(json.dumps(b["linhas"]).encode())).decode()} for b in blocos])
        if tabela == "painel_cache":
            return self._json([CACHE[(menu, q["periodo"].replace("eq.", ""))]] if (menu, q.get("periodo", "").replace("eq.", "")) in CACHE else [])
        self._json([])

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.split("?")[0].endswith("painel_cache"):
            CACHE[(corpo["menu"], corpo["periodo"])] = {"chave_versao": corpo["chave_versao"], "conteudo": corpo["conteudo"]}
        self._json([], 201)

    def do_DELETE(self):
        self._json([], 204)


def aproximados(a, b, tol=1e-3) -> bool:
    """Igual, exceto números que dependem do relógio (fração do expediente de hoje): tolerância relativa."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(aproximados(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(aproximados(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b


def gerar_em_processo(menu: str, env_extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("DADOS_DIR", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")}
    env.update(env_extra)
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("_gerar_fonte.py")), menu], env=env, capture_output=True, text=True, timeout=100)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


class FonteSupabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Falso)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_mesmo_painel_local_e_supabase(self):
        remoto = {"SUPABASE_URL": f"http://127.0.0.1:{self.srv.server_port}", "SUPABASE_SERVICE_ROLE_KEY": "chave-de-teste"}
        for menu in ("metas", "faturamento"):
            local = gerar_em_processo(menu, {"DADOS_DIR": DIR})
            via_supabase = gerar_em_processo(menu, remoto)
            self.assertTrue(aproximados(local, via_supabase), f"{menu}: o painel muda conforme a fonte")

    def test_cache_do_painel_guarda_e_devolve_o_mesmo_html(self):
        remoto = {"SUPABASE_URL": f"http://127.0.0.1:{self.srv.server_port}", "SUPABASE_SERVICE_ROLE_KEY": "chave-de-teste"}
        codigo = ("import sys; sys.path.insert(0, %r)\nimport painel_cache\nv = painel_cache.chave_versao('metas')\n"
                  "painel_cache.gravar('metas', '', v, '<html>ok</html>')\nassert painel_cache.ler('metas', '', v) == '<html>ok</html>'\n"
                  "assert painel_cache.ler('metas', '', v + 'x') is None\nprint('ok')") % str(RAIZ / "painel_py")
        env = {k: v for k, v in os.environ.items() if k != "DADOS_DIR"}
        env.update(remoto)
        r = subprocess.run([sys.executable, "-c", codigo], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
