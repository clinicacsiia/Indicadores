"""Indicadores CSI - CLIENTE: abre, no navegador, o portal que roda no computador do servidor.

Este programa NAO guarda dados, banco, planilhas nem o token do Klingo: tudo isso fica so no computador do servidor
("Indicadores CSI - Servidor.exe"). Aqui so ha o necessario para chegar la com seguranca:

  1. Descobre o servidor: servidor.json ao lado deste .exe (a pasta "Compartilhar" do servidor o mantem atualizado), senao o
     endereco embutido na hora de gerar este .exe, senao o ultimo que funcionou neste computador.
  2. Abre um tunel local  http://127.0.0.1:8780  ->  https://SERVIDOR:8766  e confere o certificado do servidor pela impressao
     digital (SHA-256) que vem no servidor.json. Assim a senha e os dados viajam criptografados pela rede e o navegador fala com
     "localhost", sem nenhum aviso de certificado. Quem nao tem a impressao digital certa nao conversa com este tunel.
  3. Abre o navegador no tunel e fica de olho. Se o servidor cair, a pagina avisa e tenta de novo sozinha. Fechar esta janela
     encerra o acesso.

Uso:  Indicadores CSI.exe            abre o portal
      --testar                       so testa a conexao com o servidor e mostra o diagnostico
      --sem-abrir  --sem-pausa       nao abre o navegador / nao espera Enter ao terminar com erro
      --servidor NOME  --porta N  --impressao HEX     endereco na mao (normalmente vem do servidor.json)
Teclas com a janela aberta:  A abre o navegador · Q fecha.   Log: %LOCALAPPDATA%\\Indicadores CSI Cliente\\cliente.log
So biblioteca padrao do Python.
"""
from __future__ import annotations

import hashlib
import http.client
import http.server
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

CONGELADO = getattr(sys, "frozen", False)
WINDOWS = os.name == "nt"
EXE_DIR = Path(sys.executable).resolve().parent if CONGELADO else Path(__file__).resolve().parent
PASTA_CLIENTE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Indicadores CSI Cliente"
ARQUIVO_SERVIDOR, ARQUIVO_EMBUTIDO, ARQUIVO_ULTIMO = "servidor.json", "servidor_padrao.json", "ultimo_servidor.json"
LOG = PASTA_CLIENTE / "cliente.log"
PORTA_LOCAL_PADRAO = 8780
ESPERA_CONEXAO = 3.0          # segundos por endereco candidato
ESPERA_RESPOSTA = 1800        # uma atualizacao ou um PDF pode demorar minutos: o tunel espera
VALIDADE_FALHA = 5.0          # depois de falhar em todos os enderecos, nao tenta de novo por alguns segundos (a pagina insiste sozinha)
MAX_CORPO = 25_000_000
OK, INFO, AVISO, ERRO = "[ok]", "[..]", "[! ]", "[x ]"
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}
SEM_NAVEGADOR = "--sem-abrir" in sys.argv
SEM_PAUSA = "--sem-pausa" in sys.argv


# ---------------------------------------------------------------- console e log
def preparar_console():
    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleTitleW("Indicadores CSI - feche esta janela para encerrar o acesso")
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(texto: str = "", marca: str = "    "):
    print(f"{marca} {texto}" if texto else "", flush=True)
    try:
        PASTA_CLIENTE.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 500_000:
            LOG.replace(LOG.with_suffix(".log.1"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {marca} {texto}\n")
    except OSError:
        pass


def pausar(msg: str = "Pressione Enter para fechar esta janela..."):
    if SEM_PAUSA:
        return
    try:
        input(f"\n{msg}")
    except (EOFError, KeyboardInterrupt):
        pass


# ---------------------------------------------------------------- onde fica o servidor
def _ler_json(caminho: Path) -> dict | None:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
        return dados if isinstance(dados, dict) else None
    except (OSError, ValueError):
        return None


def config_valida(cfg: dict | None) -> bool:
    try:
        return (isinstance(cfg, dict) and 1 <= int(cfg["porta"]) <= 65535 and bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(cfg["impressao_digital"])))
                and any(isinstance(cfg.get(k), list) and cfg[k] for k in ("nomes", "ips")))
    except (KeyError, TypeError, ValueError):
        return False


def argumento(nome: str) -> str | None:
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def escolher_config() -> tuple[str, dict] | None:
    """A configuracao mais recente entre: linha de comando, servidor.json ao lado do .exe, a embutida e a ultima que funcionou."""
    manual = argumento("--servidor")
    if manual:
        cfg = {"nomes": [manual], "ips": [], "porta": int(argumento("--porta") or 8766), "impressao_digital": argumento("--impressao") or "", "atualizado_em": "9999"}
        return ("linha de comando", cfg) if config_valida(cfg) else None
    embutido = Path(getattr(sys, "_MEIPASS", EXE_DIR)) / ARQUIVO_EMBUTIDO
    origens = [(f"{ARQUIVO_SERVIDOR} ao lado do programa", EXE_DIR / ARQUIVO_SERVIDOR), ("endereço embutido no programa", embutido),
               ("último servidor que funcionou", PASTA_CLIENTE / ARQUIVO_ULTIMO)]
    achados = [(nome, cfg) for nome, caminho in origens if config_valida(cfg := _ler_json(caminho))]
    return max(achados, key=lambda x: str(x[1].get("atualizado_em", ""))) if achados else None


def candidatos(cfg: dict) -> list[str]:
    vistos: list[str] = []
    for h in [*cfg.get("nomes", []), *cfg.get("ips", [])]:
        h = str(h).strip()
        if h and h not in vistos:
            vistos.append(h)
    return vistos


# ---------------------------------------------------------------- conexao segura com o servidor
class ErroServidor(Exception):
    """Nao deu para falar com o servidor; a mensagem ja e para o usuario."""


class CertificadoDiferente(OSError):
    pass


def resolver_ipv4(host: str) -> list[str]:
    """Enderecos IPv4 do nome. Sempre IPv4: o servidor so escuta nele, e no Windows tentar primeiro o IPv6 do nome (fe80::...) custa
    ~2 s de 'conexao recusada' em CADA conexao."""
    return list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)))


def conectar_tls(host: str, porta: int, impressao: str, espera: float = ESPERA_CONEXAO, ips: list[str] | None = None) -> ssl.SSLSocket:
    """Conecta e so devolve se o certificado do servidor tiver a impressao digital esperada (sem confiar em nome nem autoridade)."""
    ultimo: OSError | None = None
    bruto = None
    for ip in (ips or resolver_ipv4(host)):
        try:
            bruto = socket.create_connection((ip, porta), espera)
            break
        except OSError as e:
            ultimo = e
    if bruto is None:
        raise ultimo or socket.gaierror(f"sem endereço para {host}")
    try:
        bruto.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if WINDOWS:   # avisa a rede, de 30 em 30 s, que a conexao esta viva: uma atualizacao demorada nao pode ser derrubada por inatividade
            try:
                bruto.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30_000, 10_000))
            except (OSError, AttributeError, ValueError):
                pass
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # a conferencia e feita pela impressao digital, logo abaixo
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        tls = ctx.wrap_socket(bruto, server_hostname=host)
    except BaseException:
        bruto.close()
        raise
    try:
        achada = hashlib.sha256(tls.getpeercert(binary_form=True) or b"").hexdigest()
    except BaseException:
        tls.close()
        raise
    if achada.lower() != impressao.lower():
        tls.close()
        raise CertificadoDiferente(f"{host}:{porta} respondeu com outro certificado")
    return tls


def explicar(erros: list[tuple[str, BaseException]], porta: int) -> str:
    """Resume por que nenhum endereco respondeu, em portugues claro."""
    if not erros:
        return "Nenhum endereço de servidor configurado."
    tipos = [e for _, e in erros]
    nome = erros[0][0]
    if any(isinstance(e, CertificadoDiferente) for e in tipos):
        return (f"O computador respondeu, mas com um certificado diferente do esperado. O servidor pode ter sido reinstalado: peça a quem cuida do "
                f"portal a pasta “Compartilhar” atualizada (com o novo servidor.json).")
    if all(isinstance(e, socket.gaierror) for e in tipos):
        return f"Não encontrei o computador “{nome}” na rede (nome não reconhecido). Confira se você está na rede da empresa/VPN e se o servidor.json está atualizado."
    if any(isinstance(e, ConnectionRefusedError) for e in tipos):
        return (f"O computador do servidor respondeu, mas o “Indicadores CSI - Servidor” não está aberto nele (ou usa outra porta que não a {porta}). "
                f"Peça para abrirem o servidor.")
    if any(isinstance(e, (TimeoutError, socket.timeout)) for e in tipos):
        return (f"O computador do servidor não respondeu. Ele pode estar desligado ou fora da rede, ou o Firewall dele está bloqueando a porta {porta} "
                f"(quem cuida do servidor resolve com:  Indicadores CSI - Servidor.exe --liberar-rede).")
    if any(isinstance(e, ssl.SSLError) for e in tipos):
        return f"A conversa segura (TLS) com o servidor falhou: {tipos[0]}. Algo diferente do Indicadores CSI pode estar respondendo na porta {porta}."
    return f"Não consegui falar com o servidor: {type(tipos[0]).__name__}: {tipos[0]}"


class Alvo:
    """O servidor: quais enderecos tentar, qual funcionou por ultimo e a impressao digital esperada."""

    def __init__(self, cfg: dict):
        self.cfg, self.candidatos, self.porta = cfg, candidatos(cfg), int(cfg["porta"])
        self.impressao = str(cfg["impressao_digital"]).lower()
        self.ativo: str | None = None
        self._falha: tuple[float, str] | None = None
        self._trava = threading.Lock()

    @property
    def nome(self) -> str:
        return (self.cfg.get("nomes") or self.candidatos or ["servidor"])[0]

    def abrir(self) -> ssl.SSLSocket:
        """Conexao TLS ja conferida. Tenta o ultimo endereco que funcionou e depois os outros; levanta ErroServidor se nenhum responder."""
        if self._falha and time.time() - self._falha[0] < VALIDADE_FALHA:
            raise ErroServidor(self._falha[1])
        ordem = ([self.ativo] if self.ativo else []) + [c for c in self.candidatos if c != self.ativo]
        erros: list[tuple[str, BaseException]] = []
        tentados: set[str] = set()     # o nome curto e o nome completo costumam ser o mesmo computador: nao espera o timeout duas vezes
        for host in ordem:
            try:
                ips = [i for i in resolver_ipv4(host) if i not in tentados]
                if not ips:
                    continue
                tentados.update(ips)
                tls = conectar_tls(host, self.porta, self.impressao, ips=ips)
            except (OSError, ssl.SSLError) as e:
                erros.append((host, e))
                continue
            with self._trava:
                self.ativo, self._falha = host, None
            return tls
        mensagem = explicar(erros, self.porta)
        with self._trava:
            self._falha = (time.time(), mensagem)
        raise ErroServidor(mensagem)

    def testar(self) -> str | None:
        """None se o servidor responde; senao, o motivo."""
        try:
            self.abrir().close()
            return None
        except ErroServidor as e:
            return str(e)


class ConexaoServidor(http.client.HTTPConnection):
    """HTTP por cima do soquete TLS conferido (em vez de abrir o proprio)."""

    def __init__(self, alvo: Alvo):
        super().__init__(alvo.nome, alvo.porta)
        self.alvo = alvo

    def connect(self):
        self.sock = self.alvo.abrir()
        self.sock.settimeout(ESPERA_RESPOSTA)


# ---------------------------------------------------------------- o tunel local
class ServidorLocal(http.server.ThreadingHTTPServer):
    allow_reuse_address = not WINDOWS   # no Windows isso deixaria dois tuneis abrirem a mesma porta
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):   # o navegador fechou a conexao no meio
            return
        super().handle_error(request, client_address)


class Tunel(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 120
    alvo: Alvo = None            # preenchidos por criar_tunel
    porta_local: int = 0

    def log_message(self, *args):
        pass

    def _pagina_erro(self, mensagem: str):
        json_ = bool(self.headers.get("X-Painel")) or "json" in (self.headers.get("Accept") or "")
        if json_:   # chamada do proprio portal (botao Atualizar, login...): ele mostra a mensagem
            corpo = json.dumps({"ok": False, "mensagem": mensagem}, ensure_ascii=False).encode("utf-8")
            tipo = "application/json; charset=utf-8"
        else:
            html = ("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<meta http-equiv='refresh' content='8'><title>Indicadores CSI</title>"
                    "<body style='font-family:system-ui,Segoe UI,sans-serif;max-width:640px;margin:12vh auto;padding:0 20px;color:#1c2733'>"
                    "<h2 style='margin:0 0 12px'>O servidor do portal não respondeu</h2>"
                    f"<p style='line-height:1.5'>{mensagem.replace('<', '&lt;')}</p>"
                    "<p style='color:#5b6b7a;font-size:14px'>Esta página tenta de novo sozinha a cada 8 segundos.</p></body></html>")
            corpo, tipo = html.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(503)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _encaminhar(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in (f"127.0.0.1:{self.porta_local}", f"localhost:{self.porta_local}"):   # barra DNS rebinding: so o proprio navegador deste PC
            self.send_response(421)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/__csi_cliente__":     # como outro Indicadores CSI deste computador descobre que este tunel ja existe
            corpo = json.dumps({"cliente": True, "servidor": self.alvo.nome, "pid": os.getpid()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = 0
        if tamanho > MAX_CORPO:
            self.send_response(413)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        corpo = self.rfile.read(tamanho) if tamanho else None
        cabecalhos = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() not in ("host", "content-length")}
        cabecalhos["Connection"] = "close"
        conexao = ConexaoServidor(self.alvo)
        try:
            conexao.connect()
            cabecalhos["Host"] = f"{self.alvo.ativo}:{self.alvo.porta}"   # o servidor so atende pelo nome/endereco dele
            if corpo is not None:
                cabecalhos["Content-Length"] = str(len(corpo))
            conexao.request(self.command, self.path, body=corpo, headers=cabecalhos, encode_chunked=False)
            resposta = conexao.getresponse()
            self.send_response_only(resposta.status, resposta.reason)
            for k, v in resposta.msg.items():
                if k.lower() in HOP:
                    continue
                if k.lower() == "set-cookie":
                    v = re.sub(r";\s*Secure\b", "", v, flags=re.I)   # o navegador fala http com o tunel local: cookie "Secure" nao seria guardado
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                bloco = resposta.read(65536)
                if not bloco:
                    break
                self.wfile.write(bloco)
        except ErroServidor as e:
            self._pagina_erro(str(e))
        except (ConnectionError, TimeoutError, socket.timeout, ssl.SSLError, http.client.HTTPException) as e:
            if getattr(self, "wfile", None) and not self.wfile.closed:
                try:
                    self._pagina_erro(f"A conexão com o servidor caiu no meio do pedido ({type(e).__name__}). Tente de novo.")
                except OSError:
                    pass
        finally:
            conexao.close()

    do_GET = do_POST = _encaminhar

    def _recusar(self):
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _recusar


def porta_e_nossa(porta: int, nome_servidor: str) -> bool | None:
    """True se a porta tem um tunel deste programa para ESTE servidor; False se tem outro tunel/programa; None se esta livre."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/__csi_cliente__", timeout=2) as r:
            j = json.loads(r.read())
            return bool(j.get("cliente")) and str(j.get("servidor", "")).lower() == nome_servidor.lower()
    except urllib.error.HTTPError:
        return False
    except Exception:
        pass
    with socket.socket() as s:
        s.settimeout(1)
        return False if s.connect_ex(("127.0.0.1", porta)) == 0 else None


def criar_tunel(alvo: Alvo, inicial: int) -> tuple[ServidorLocal | None, int, bool]:
    """(servidor, porta, ja_existia). Usa a porta inicial; se for de outro programa, a proxima livre. Se ja houver um tunel
    deste programa para o mesmo servidor, nao cria outro (so reabre o navegador)."""
    for porta in range(inicial, inicial + 10):
        dono = porta_e_nossa(porta, alvo.nome)
        if dono:
            return None, porta, True
        if dono is False:
            continue
        Tunel.alvo, Tunel.porta_local = alvo, porta
        try:
            return ServidorLocal(("127.0.0.1", porta), Tunel), porta, False
        except OSError:
            continue
    raise OSError(f"Não achei porta livre entre {inicial} e {inicial + 9} neste computador.")


# ---------------------------------------------------------------- principal
def abrir_navegador(porta: int):
    if SEM_NAVEGADOR:
        return
    try:
        webbrowser.open(f"http://127.0.0.1:{porta}/")
    except Exception:
        log(f"Não consegui abrir o navegador. Abra você mesmo: http://127.0.0.1:{porta}/", AVISO)


def ler_tecla(espera: float) -> str | None:
    if WINDOWS:
        import msvcrt
        fim = time.time() + espera
        while time.time() < fim:
            if msvcrt.kbhit():
                return msvcrt.getwch().lower()
            time.sleep(0.05)
        return None
    time.sleep(espera)
    return None


def lembrar_servidor(cfg: dict):
    """Guarda o endereco que funcionou: se um dia o servidor.json e o endereco embutido nao estiverem a mao, este ainda serve."""
    try:
        PASTA_CLIENTE.mkdir(parents=True, exist_ok=True)
        (PASTA_CLIENTE / ARQUIVO_ULTIMO).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    preparar_console()
    log("=" * 62)
    log("  Indicadores CSI  ·  acesso ao servidor da clínica")
    log("=" * 62)
    escolhida = escolher_config()
    if not escolhida:
        log(f"Não encontrei o endereço do servidor. O arquivo {ARQUIVO_SERVIDOR} precisa estar na mesma pasta deste programa "
            f"(ele vem na pasta “Compartilhar” do servidor).", ERRO)
        pausar()
        return 2
    origem, cfg = escolhida
    alvo = Alvo(cfg)
    log(f"Servidor: {alvo.nome} (porta {alvo.porta}) — endereço vindo de: {origem}.", INFO)
    erro = alvo.testar()
    if erro:
        log(erro, ERRO)
    else:
        log(f"Conectado a {alvo.ativo}: certificado conferido, conversa criptografada.", OK)
        if origem not in ("último servidor que funcionou", "linha de comando"):
            lembrar_servidor(cfg)
    if "--testar" in sys.argv:
        for host in alvo.candidatos:
            try:
                conectar_tls(host, alvo.porta, alvo.impressao).close()
                log(f"  {host}:{alvo.porta}  responde e o certificado confere.", OK)
            except (OSError, ssl.SSLError) as e:
                log(f"  {host}:{alvo.porta}  {type(e).__name__}: {e}", AVISO)
        pausar()
        return 1 if erro else 0
    try:
        servidor, porta, ja_existia = criar_tunel(alvo, int(argumento("--porta-local") or PORTA_LOCAL_PADRAO))
    except OSError as e:
        log(str(e), ERRO)
        pausar()
        return 2
    if ja_existia:
        log(f"Este computador já tem o acesso aberto (porta {porta}). Só abri o navegador nele.", OK)
        abrir_navegador(porta)
        return 0
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    log(f"Portal disponível neste computador em http://127.0.0.1:{porta}/", OK)
    log("Pode minimizar esta janela, mas não a feche: fechar a janela encerra o acesso. Teclas: A abre o navegador · Q fecha.", INFO)
    abrir_navegador(porta)
    ultimo_ok, proxima = erro is None, time.time() + 15
    try:
        while True:
            tecla = ler_tecla(1.0)
            if tecla == "q":
                return 0
            if tecla == "a":
                abrir_navegador(porta)
            if time.time() >= proxima:
                proxima = time.time() + 15
                problema = alvo.testar()
                if (problema is None) != ultimo_ok:   # so conta quando muda: servidor caiu ou voltou
                    log("O servidor voltou a responder." if problema is None else problema, OK if problema is None else AVISO)
                    ultimo_ok = problema is None
    except KeyboardInterrupt:
        return 0
    finally:
        servidor.shutdown()


if __name__ == "__main__":
    codigo = main()
    sys.exit(codigo)
