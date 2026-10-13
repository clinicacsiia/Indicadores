"""Painel local com o botão "Atualizar agora".

Sobe um servidor só neste computador (http://127.0.0.1:8765) que mostra o dashboard e, quando
você clica em "Atualizar agora", consulta o Klingo, grava na planilha e recarrega a página.
Também confere sozinho de tempos em tempos (config.json: verificacao_automatica_minutos), direto na
API do Klingo; se o token da API faltar ou for recusado, o painel avisa na tela.

Uso:  python servidor_painel.py          (uso avulso; o normal é abrir o "Indicadores CSI.exe")
      python servidor_painel.py --sem-abrir   (não abre o navegador)
"""
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import extrair_laudo as ex
import gerar_dashboard as gd

HOST, PORTA = "127.0.0.1", 8765
URL_PAINEL = f"http://{HOST}:{PORTA}/"


class ServidorExclusivo(ThreadingHTTPServer):
    """No Windows, SO_REUSEADDR deixa dois servidores abrirem a mesma porta sem erro; aqui a porta é exclusiva."""
    allow_reuse_address = os.name != "nt"

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):  # o navegador fechou a conexão no meio: não é erro
            return
        super().handle_error(request, client_address)


TRAVA = threading.Lock()
ESTADO = {"atualizando": False, "aviso": None}


def versao_dos_dados() -> int:
    return int(ex.PLANILHA.stat().st_mtime) if ex.PLANILHA.exists() else 0


def executar(forcar: bool) -> dict:
    """Roda uma atualização, uma de cada vez. Nunca levanta erro: devolve {"ok", "mensagem", ...}."""
    if not TRAVA.acquire(blocking=False):
        return {"ok": True, "atualizou": False, "mensagem": "Já existe uma atualização em andamento."}
    ESTADO["atualizando"] = True
    try:
        resultado = ex.atualizar(forcar=forcar)
        ESTADO["aviso"] = None
        return {"ok": True, **resultado}
    except ex.TokenInvalido as e:   # token ausente ou recusado: fica o aviso na tela até alguém corrigir
        ESTADO["aviso"] = str(e)
        return {"ok": False, "mensagem": str(e)}
    except Exception as e:  # inclui PlanilhaEmUso, rede fora do ar, resposta fora do formato
        print(">>> ERRO:", e, flush=True)
        return {"ok": False, "mensagem": f"Não consegui atualizar: {e}"}
    finally:
        ESTADO["atualizando"] = False
        TRAVA.release()


def verificacao_automatica(minutos: float):
    while True:
        time.sleep(minutos * 60)
        r = executar(forcar=False)
        print(f">>> Verificação automática: {r['mensagem']}", flush=True)


class Painel(BaseHTTPRequestHandler):
    def _enviar(self, codigo: int, corpo: bytes, tipo: str):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, codigo: int, obj: dict):
        self._enviar(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho in ("/", "/index.html"):
            try:
                consulta = parse_qs(urlsplit(self.path).query)   # ?de=AAAA-MM&ate=AAAA-MM: filtro de periodo (varios meses)
                de, ate = (consulta.get("de") or [""])[0], (consulta.get("ate") or [""])[0]
                if de != ate and gd.pc.PADRAO_YM.match(de) and gd.pc.PADRAO_YM.match(ate) and not ESTADO["atualizando"]:
                    return self._enviar(200, gd.gerar(de, ate, devolver_html=True).encode("utf-8"), "text/html; charset=utf-8")
                if not ESTADO["atualizando"]:  # durante a gravação, serve a última versão pronta
                    gd.gerar()
                self._enviar(200, gd.SAIDA.read_bytes(), "text/html; charset=utf-8")
            except Exception as e:
                self._enviar(500, f"Não consegui montar o painel: {e}".encode("utf-8"), "text/plain; charset=utf-8")
        elif caminho == "/estado":
            self._json(200, {"versao": versao_dos_dados(), "atualizando": ESTADO["atualizando"], "aviso": ESTADO["aviso"]})
        else:
            self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain")

    def do_POST(self):
        if self.path.split("?")[0] != "/atualizar":
            return self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain")
        if self.headers.get("X-Painel") != "1":  # barra páginas de outros sites chamando o painel
            return self._enviar(403, b"Proibido", "text/plain")
        self._json(200, executar(forcar=True))

    def log_message(self, *args):  # sem poluir o terminal com cada requisição
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # acentos corretos no terminal do Windows
    try:
        servidor = ServidorExclusivo((HOST, PORTA), Painel)
    except OSError:
        print(f">>> O painel já está rodando em {URL_PAINEL}")
        if "--sem-abrir" not in sys.argv:
            webbrowser.open(URL_PAINEL)
        return

    gd.gerar()
    minutos = ex.ler_config().get("verificacao_automatica_minutos", 30)
    if minutos and minutos > 0:
        threading.Thread(target=verificacao_automatica, args=(minutos,), daemon=True).start()
    print(f">>> Painel em {URL_PAINEL}  (verificação automática a cada {minutos} min; Ctrl+C para fechar)", flush=True)
    if "--sem-abrir" not in sys.argv:
        webbrowser.open(URL_PAINEL)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print(">>> Painel encerrado.")


if __name__ == "__main__":
    main()
