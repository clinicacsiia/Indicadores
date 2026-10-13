"""Indicadores CSI - SERVIDOR (lancador): um clique abre tudo e resolve sozinho os problemas comuns.

No Windows ele vira o "Indicadores CSI - Servidor.exe" AUTONOMO: o Python, o pandas, o openpyxl, o numpy, o playwright e o proprio
portal (Metas, Faturamento, Financeiro, Cesta...) vao dentro do .exe. Nao precisa instalar nada no computador: so o token da API do
Klingo (arquivo klingo_token.txt, uma linha) e, apenas para exportar PDF, o Google Chrome ou o Edge. Nao ha mais login no Klingo.

Este e o programa que fica SO no computador de quem cuida dos dados: ele guarda o banco, as planilhas, o log e o token, consulta o
Klingo e atende os colegas pela rede (HTTPS, so redes internas, com login). Os colegas usam o "Indicadores CSI.exe" (cliente,
cliente_portal.py, na pasta "Compartilhar"), que nao guarda nada: so abre o portal deste servidor no navegador deles.

Onde ficam os arquivos (planilhas, metas.json, config.json, backups, log)
  - .exe dentro da pasta do projeto (onde esta o servidor_portal.py): usa os arquivos dessa pasta e so leva o Python dentro.
  - .exe sozinho em qualquer pasta: cria "Dados do Indicadores CSI" ao lado dele (ou, se a pasta nao permitir gravar, em
    %LOCALAPPDATA%\\Indicadores CSI) e coloca la o portal e as configuracoes iniciais. O que o .exe traz de novo e atualizado
    sozinho a cada abertura; planilhas, metas.json e config.json nunca sao sobrescritos.

O que ele faz, nesta ordem
  1. Confere os arquivos, os .json e (fora do .exe) o Python 3.10+ e os pacotes; no .exe isso ja vem pronto.
  2. Fecha outro lancador que ja esteja aberto e cuida das planilhas: apaga restos de gravacao interrompida,
     restaura do backup uma planilha corrompida e guarda um backup por dia (pasta "backups", ultimos 7 dias).
  3. Se o portal ja estiver aberto, FECHA e abre de novo do zero (pega o codigo mais novo e desfaz travamentos).
     Se a porta 8765 for de outro programa, usa a proxima porta livre.
  4. Abre o portal, espera ele responder e abre o navegador.
  5. Fica de olho: se o portal cair ou parar de responder, reinicia sozinho (com espera crescente) e explica o motivo.

Uso:  Indicadores CSI - Servidor.exe  (ou python iniciar_portal.py)   abre (ou reinicia) o portal e fica vigiando
      --sem-abrir            nao abre o navegador
      --verificar            so confere o ambiente e as planilhas, sem abrir nada
      --sem-pausa            nao espera Enter ao terminar com erro
      --teste-chrome         abre e fecha um Chrome invisivel para testar a exportacao de PDF
      --rede                 mostra como esta o acesso pela rede (porta, certificado, firewall) sem abrir nada
      --liberar-rede         cria a regra do Firewall do Windows para os colegas entrarem (pede permissao de administrador, uma vez)
      --iniciar-com-windows  o servidor abre sozinho (minimizado) quando voce entra no Windows;  --nao-iniciar-com-windows desfaz
Teclas com a janela aberta:  R reinicia o portal · A abre o navegador · L mostra o log · Q fecha tudo
Para fechar tudo, feche esta janela. Fora do Windows: python iniciar_portal.py (precisa de Python 3.10+). Logs: "Indicadores CSI.log".
Enquanto esta janela estiver aberta o computador nao entra em suspensao (a tela pode apagar), senao os colegas perderiam o acesso.
"""
from __future__ import annotations

import atexit
import collections
import ctypes
import json
import os
import re
import runpy
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import date, datetime
from pathlib import Path

CONGELADO = getattr(sys, "frozen", False)   # True dentro do .exe
WINDOWS = os.name == "nt"
EXE_DIR = Path(sys.executable).resolve().parent if CONGELADO else Path(__file__).resolve().parent
PASTA_AUTONOMA = "Dados do Indicadores CSI"


def pasta_gravavel(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        teste = p / ".teste_gravacao"
        teste.write_text("ok")
        teste.unlink()
        return True
    except OSError:
        return False


def escolher_app() -> Path:
    """Pasta onde roda o portal e ficam os dados. Fora do .exe: a pasta deste arquivo."""
    forcada = os.environ.get("PORTAL_CSI_PASTA")
    if forcada:
        Path(forcada).mkdir(parents=True, exist_ok=True)
        return Path(forcada).resolve()
    if not CONGELADO or (EXE_DIR / "servidor_portal.py").exists():
        return EXE_DIR
    for pasta in (EXE_DIR / PASTA_AUTONOMA, Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Indicadores CSI"):
        if pasta_gravavel(pasta):
            return pasta
    return EXE_DIR / PASTA_AUTONOMA


APP = escolher_app()
RAIZ = APP
AUTONOMO = CONGELADO and APP != EXE_DIR   # .exe sozinho: o portal vem de dentro dele e e copiado para a pasta de dados
EMBUTIDO = "app_embutido.zip"
HOST, PORTA_PADRAO = "127.0.0.1", 8765
SERVIDOR = RAIZ / "servidor_portal.py"
COMPUTADOR = re.sub(r"[^\w.-]", "_", os.environ.get("COMPUTERNAME") or socket.gethostname() or "pc")
# A pasta de dados pode ser a MESMA para varios computadores (exe numa pasta compartilhada): a marca de "quem esta rodando"
# e um PID, que so vale no computador que o gerou. Uma marca por computador evita que um PC feche o portal do outro.
LOG, PIDFILE, BACKUPS = RAIZ / "Indicadores CSI.log", RAIZ / f".portal_csi.{COMPUTADOR}.pid", RAIZ / "backups"
ARQUIVO_BANCO = EXE_DIR / "banco.txt"   # ao lado do .exe: caminho do banco de dados (uma linha). Ver escolher_banco()


def escolher_banco():
    """Define PORTAL_CSI_BANCO (o portal e o backup leem dela) a partir do banco.txt que fica ao lado do .exe, se existir e se a
    variavel ainda nao foi definida. Assim, o .exe numa pasta compartilhada aponta TODOS os computadores para o mesmo banco
    (por exemplo \\\\MEU-PC\\Portal\\portal_csi.db) sem mexer em cada um."""
    global ORIGEM_BANCO
    if os.environ.get("PORTAL_CSI_BANCO"):
        ORIGEM_BANCO = "variável de ambiente PORTAL_CSI_BANCO"
        return
    try:
        for linha in ARQUIVO_BANCO.read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip().strip('"')
            if linha and not linha.startswith("#"):
                os.environ["PORTAL_CSI_BANCO"] = linha
                ORIGEM_BANCO = f"{ARQUIVO_BANCO.name} ao lado do .exe"
                return
    except OSError:
        pass


ORIGEM_BANCO = "config.json do portal"
escolher_banco()
DIAS_DE_BACKUP = 7
PACOTES = ["pandas", "openpyxl", "numpy", "playwright", "pypdf"]
MIN_PYTHON = (3, 10)
ARQUIVOS = ["servidor_portal.py", "modulos.json", "portal.html", "klingo_relatorios.py", "painel_comum.py", "painel_base.css", "painel_base.js", "autenticacao.py", "login.html", "exportar_pdf.py", "banco_dados.py", "seguranca_rede.py"]
NOME_EXE = "Indicadores CSI - Servidor"
MAX_QUEDAS, JANELA_QUEDAS = 5, 600           # mais de 5 quedas em 10 minutos: desiste e explica
CHECA_A_CADA, FALHAS_PARA_TRAVADO = 15, 3    # segundos entre conferencias; falhas seguidas para considerar travado
SEM_NAVEGADOR, SO_VERIFICAR, SEM_PAUSA = "--sem-abrir" in sys.argv, "--verificar" in sys.argv, "--sem-pausa" in sys.argv
CREATE_NO_WINDOW, CREATE_NEW_PROCESS_GROUP = 0x08000000, 0x00000200
OK, INFO, AVISO, ERRO, SAIDA = "[ok]", "[..]", "[! ]", "[x ]", "  | "


# ---------------------------------------------------------------- console e log
def preparar_console():
    if WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
            ctypes.windll.kernel32.SetConsoleTitleW("Indicadores CSI - Servidor - feche esta janela para encerrar")
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(texto: str = "", marca: str = "    "):
    print(f"{marca} {texto}" if texto else "", flush=True)
    try:
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
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


def perguntar(msg: str, padrao_sim: bool = True) -> bool:
    if SEM_PAUSA or not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        r = input(f"     {msg} [{'S/n' if padrao_sim else 's/N'}] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return padrao_sim if not r else r.startswith(("s", "y"))


# ---------------------------------------------------------------- processos
def rodar(cmd: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW if WINDOWS else 0)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def processo_vivo(pid: int) -> bool:
    if WINDOWS:
        return f'"{pid}"' in rodar(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])[1]
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def info_processo(pid: int) -> tuple[str, str]:
    """(nome, linha de comando) do processo; vazios se nao achar."""
    if WINDOWS:
        ps = f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if ($p) {{ $p.Name; $p.CommandLine }}"
        linhas = rodar(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], 25)[1].strip().splitlines()
        return (linhas[0].strip(), " ".join(linhas[1:])) if linhas else ("", "")
    saida = rodar(["ps", "-p", str(pid), "-o", "command="])[1].strip()
    return (saida.split()[0] if saida else ""), saida


def encerrar(pid: int):
    """Fecha o processo e tudo que ele abriu."""
    if WINDOWS:
        rodar(["taskkill", "/PID", str(pid), "/T", "/F"], 25)
    else:
        for sinal in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(pid), sinal)
            except OSError:
                try:
                    os.kill(pid, sinal)
                except OSError:
                    pass
            for _ in range(10):
                if not processo_vivo(pid):
                    return
                time.sleep(0.3)
    for _ in range(20):
        if not processo_vivo(pid):
            return
        time.sleep(0.25)


_JOB = None


def vincular_ao_lancador(proc: subprocess.Popen):
    """Windows: o servidor fecha junto com este lancador, mesmo que a janela seja fechada no X (Job Object)."""
    global _JOB
    if not WINDOWS:
        return
    try:
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _JOB is None:
            class Basico(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

            class Estendido(ctypes.Structure):
                _fields_ = [("Basico", Basico), ("IO", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            _JOB = k32.CreateJobObjectW(None, None)
            info = Estendido()
            info.Basico.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(_JOB, 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(_JOB, wintypes.HANDLE(int(proc._handle)))
    except Exception:
        pass   # sem o Job Object o lancador ainda fecha o servidor ao sair; so a janela fechada no X deixaria ele aberto (a proxima abertura resolve)


# ---------------------------------------------------------------- porta e portal
def url(porta: int, caminho: str = "/") -> str:
    return f"http://{HOST}:{porta}{caminho}"


def ler_estado(porta: int, timeout: float = 3) -> dict | None:
    try:
        with urllib.request.urlopen(url(porta, "/estado"), timeout=timeout) as r:
            j = json.loads(r.read())
            return j if isinstance(j, dict) else None
    except Exception:
        return None


def porta_ocupada(porta: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((HOST, porta)) == 0


def pid_na_porta(porta: int) -> int | None:
    if WINDOWS:   # le as colunas sem depender do idioma do Windows: "TCP  127.0.0.1:8765  0.0.0.0:0  <estado>  <pid>"
        for linha in rodar(["netstat", "-ano", "-p", "TCP"])[1].splitlines():
            c = linha.split()
            if len(c) >= 5 and c[1].endswith(f":{porta}") and c[2].rsplit(":", 1)[-1] == "0" and c[4].isdigit():
                return int(c[4])
        return None
    pids = rodar(["lsof", "-nP", f"-iTCP:{porta}", "-sTCP:LISTEN", "-t"])[1].split()
    if pids and pids[0].isdigit():
        return int(pids[0])
    m = re.search(rf":{porta}\b.*pid=(\d+)", rodar(["ss", "-ltnp"])[1])
    return int(m.group(1)) if m else None


def preparar_porta() -> int:
    """Devolve a porta para usar: libera a 8765 se for do portal (reinicia do zero) ou escolhe outra se for de outro programa."""
    porta = PORTA_PADRAO
    for _ in range(30):
        if not porta_ocupada(porta):
            return porta
        estado = ler_estado(porta)
        pid = (estado or {}).get("pid") or pid_na_porta(porta)
        nosso = bool(estado and ("portal" in estado or "versao" in estado))
        if not nosso and pid:   # nao respondeu: pode ser um portal travado; so mexe se for nosso mesmo
            nosso = bool(re.search(r"servidor_(portal|painel)|Indicadores CSI.*--servidor", info_processo(pid)[1]))
        if nosso and pid:
            log(f"O portal já estava aberto na porta {porta} (processo {pid}): fechando para abrir de novo do zero.", INFO)
            encerrar(pid)
            for _ in range(20):
                if not porta_ocupada(porta):
                    return porta
                time.sleep(0.5)
            log(f"A porta {porta} não liberou.", AVISO)
        else:
            log(f"A porta {porta} está em uso por outro programa (não mexo nele).", AVISO)
        porta += 1
    raise RuntimeError("Não achei nenhuma porta livre entre 8765 e 8794.")


class Servidor:
    """O processo do portal (python servidor_portal.py) e as últimas linhas que ele escreveu."""

    def __init__(self, py: dict, porta: int):
        self.py, self.porta, self.proc, self.estado = py, porta, None, None
        self.ultimas: collections.deque = collections.deque(maxlen=80)

    def iniciar(self):
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "PORTAL_PORTA": str(self.porta)}
        if CONGELADO:   # o servidor grava o servidor.json (endereco + impressao digital) na pasta Compartilhar, ao lado deste .exe
            env["PORTAL_CSI_PUBLICAR"] = str(EXE_DIR / "Compartilhar")
        extra = {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
        # no .exe o servidor e o proprio .exe rodando com --servidor; fora dele, o Python roda o servidor_portal.py
        comando = self.py["cmd"] + ["--servidor"] if CONGELADO else self.py["cmd"] + ["-u", str(SERVIDOR), "--sem-abrir"]
        self.proc = subprocess.Popen(comando, cwd=str(RAIZ), env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1, **extra)
        vincular_ao_lancador(self.proc)
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        try:
            for linha in self.proc.stdout:
                linha = linha.rstrip()
                if linha:
                    self.ultimas.append(linha)
                    log(linha, SAIDA)
        except (OSError, ValueError):
            pass

    def vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def parar(self):
        if self.proc is not None and self.proc.poll() is None:
            encerrar(self.proc.pid)
        if self.proc is not None:
            try:
                self.proc.stdout.close()
            except Exception:
                pass

    def esperar_pronto(self, timeout: float = 90) -> bool:
        inicio = time.time()
        while time.time() - inicio < timeout:
            if not self.vivo():
                return False
            estado = ler_estado(self.porta, 6)   # na partida o portal esta ocupado carregando as planilhas
            if estado and estado.get("portal"):
                self.estado = estado
                return True
            time.sleep(0.5)
        return False


PADROES = [
    (r"No module named '([\w.]+)'", lambda m: (f"O .exe foi gerado sem o módulo '{m.group(1)}'. Gere o .exe de novo (Gerar EXE.bat) ou me avise." if CONGELADO
                                                else f"Falta o pacote '{m.group(1).split('.')[0]}' no Python. Rode:  python -m pip install {m.group(1).split('.')[0]}")),
    (r"PermissionError|Feche o arquivo", lambda m: "Uma planilha está aberta no Excel. Feche-a e tente de novo."),
    (r"JSONDecodeError", lambda m: "Um arquivo .json (metas, config, relatorios ou modulos) está com erro de digitação. Rode com --verificar para ver qual."),
    (r"SyntaxError|IndentationError", lambda m: "Um arquivo .py foi alterado e ficou com erro de sintaxe. O erro aparece nas linhas acima ou em \"Indicadores CSI.log\"."),
    (r"WinError 10048|Address already in use|10013", lambda m: "A porta do portal estava em uso por outro programa."),
    (r"FileNotFoundError", lambda m: "Falta um arquivo do projeto. Confira se a pasta está completa."),
]


def diagnosticar(linhas) -> list[str]:
    texto = "\n".join(linhas)
    return [f(m) for padrao, f in PADROES if (m := re.search(padrao, texto))]


# ---------------------------------------------------------------- .exe autonomo: portal embutido, temporarios, teste do Chrome
def sincronizar_app(destino: Path = APP) -> int:
    """Copia o portal que vem dentro do .exe para a pasta de dados. 'codigo' (programas e modelos) e atualizado quando muda;
    'semente' (metas.json, config.json...) so e criado se ainda nao existir, para nunca desfazer o que voce editou."""
    zip_embutido = Path(getattr(sys, "_MEIPASS", EXE_DIR)) / EMBUTIDO
    if not zip_embutido.exists():
        raise FileNotFoundError(f"O .exe está incompleto: falta {EMBUTIDO} dentro dele. Gere o .exe de novo (Gerar EXE.bat).")
    mudou = 0
    with zipfile.ZipFile(zip_embutido) as z:
        manifesto = json.loads(z.read("manifesto.json").decode("utf-8"))
        for rel, categoria in manifesto["arquivos"].items():
            alvo, dados = destino / rel, z.read(rel)
            if alvo.exists() and (categoria == "semente" or alvo.read_bytes() == dados):
                continue
            alvo.parent.mkdir(parents=True, exist_ok=True)
            novo = alvo.with_name(alvo.name + ".novo")
            novo.write_bytes(dados)
            novo.replace(alvo)
            mudou += 1
            if categoria == "semente":
                log(f"Criei {rel} com o valor inicial.", INFO)
    return mudou


def limpar_temporarios_antigos():
    """O .exe de arquivo unico se abre numa pasta _MEIxxxx do Temp e a apaga ao fechar; se a janela for fechada no X ela sobra
    (centenas de MB). Apaga as sobras deste programa que ninguem esta usando."""
    atual = Path(getattr(sys, "_MEIPASS", ""))
    liberados = 0
    for pasta in Path(tempfile.gettempdir()).glob("_MEI*"):
        try:
            if pasta.name.endswith("_limpar") and pasta.is_dir():   # ja marcada por nos numa limpeza que nao terminou (arquivo ainda preso)
                shutil.rmtree(pasta, ignore_errors=True)
                continue
            if pasta == atual or not pasta.is_dir() or not (pasta / EMBUTIDO).exists():
                continue
            if time.time() - pasta.stat().st_mtime < 600:   # recem criada: pode ser outro Indicadores CSI ainda abrindo
                continue
            # o Windows nega escrita na DLL do Python enquanto algum Indicadores CSI a usa (renomear a pasta NAO serve: ele deixa)
            dll = next(pasta.glob("python3*.dll"), None)
            if dll is not None:
                open(dll, "r+b").close()
            livre = pasta.with_name(pasta.name + "_limpar")
            pasta.rename(livre)
        except OSError:
            continue
        tamanho = sum(f.stat().st_size for f in livre.rglob("*") if f.is_file())
        shutil.rmtree(livre, ignore_errors=True)
        if not livre.exists():
            liberados += tamanho
    if liberados:
        log(f"Limpei {liberados / 1_000_000:.0f} MB de arquivos temporários de aberturas anteriores.", OK)


def executar_servidor():
    """Processo filho do .exe (--servidor): roda o portal que esta na pasta de dados."""
    sys.path.insert(0, str(APP))
    sys.argv = [str(SERVIDOR), "--sem-abrir"]
    runpy.run_path(str(SERVIDOR), run_name="__main__")


def testar_chrome() -> int:
    """Abre um Chrome invisivel (perfil temporario, sem mexer no seu) para provar que a exportacao de PDF funciona."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log(f"O playwright não está disponível: {type(e).__name__}: {e}", ERRO)
        return 1
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as perfil, sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(perfil, channel="chrome", headless=True)
            pagina = ctx.new_page()
            pagina.goto("about:blank")
            agente = pagina.evaluate("navigator.userAgent")
            ctx.close()
        log(f"Chrome aberto e fechado sem problema: {agente}", OK)
        return 0
    except Exception as e:
        log(f"Não consegui abrir o Chrome: {type(e).__name__}: {str(e).splitlines()[0][:200]}", ERRO)
        log("Instale o Google Chrome (https://www.google.com/chrome/). Ele só é necessário para exportar PDF.", AVISO)
        return 1


# ---------------------------------------------------------------- ambiente: Python, pacotes, arquivos
SONDA =("import importlib.util, sys\nprint(sys.version_info[0], sys.version_info[1])\n"
         f"print(','.join(p for p in {PACOTES!r} if importlib.util.find_spec(p) is None))\n")


def candidatos_python() -> list[list[str]]:
    vistos, saida = set(), []

    def add(c):
        if tuple(c) not in vistos and not any("WindowsApps" in p for p in c):   # WindowsApps = atalho da Microsoft Store, nao e Python de verdade
            vistos.add(tuple(c))
            saida.append(list(c))

    if not CONGELADO:
        add([sys.executable])
    for nome in ("python", "python3"):
        if shutil.which(nome):
            add([shutil.which(nome)])
    if WINDOWS:
        if shutil.which("py"):
            add(["py", "-3"])
        for base, padrao in ((os.environ.get("LOCALAPPDATA"), "Programs/Python/Python3*/python.exe"), (os.environ.get("ProgramFiles"), "Python3*/python.exe"), ("C:/", "Python3*/python.exe")):
            if base:
                for p in sorted(Path(base).glob(padrao), reverse=True):
                    add([str(p)])
    else:
        for p in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"):
            if Path(p).exists():
                add([p])
    return saida


def sondar(cmd: list[str]) -> dict | None:
    cod, saida = rodar(cmd + ["-c", SONDA], 25)
    linhas = saida.strip().splitlines()
    if cod != 0 or not linhas:
        return None
    try:
        versao = tuple(int(x) for x in linhas[0].split()[:2])
    except ValueError:
        return None
    return {"cmd": cmd, "versao": versao, "faltam": [p for p in (linhas[1].split(",") if len(linhas) > 1 else []) if p]}


def escolher_python() -> dict | None:
    """Primeiro Python 3.10+ que ja tenha todos os pacotes; senao, o primeiro 3.10+ (faltarao pacotes)."""
    parcial = None
    for cmd in candidatos_python():
        s = sondar(cmd)
        if s and s["versao"] >= MIN_PYTHON:
            if not s["faltam"]:
                return s
            parcial = parcial or s
    return parcial


def garantir_pacotes(py: dict) -> bool:
    if not py["faltam"]:
        return True
    log(f"Faltam pacotes no Python: {', '.join(py['faltam'])}.", AVISO)
    if not perguntar("Posso instalar agora? (precisa de internet)"):
        log(f"Para instalar depois:  python -m pip install {' '.join(py['faltam'])}", ERRO)
        return False
    if subprocess.call(py["cmd"] + ["-m", "pip", "install", *py["faltam"]]) != 0:
        log("A instalação falhou. Confira a internet e tente de novo.", ERRO)
        return False
    novo = sondar(py["cmd"])
    py["faltam"] = novo["faltam"] if novo else py["faltam"]
    return not py["faltam"]


def conferir_arquivos(raiz: Path = RAIZ) -> list[str]:
    problemas = [f"Falta o arquivo {a}" for a in ARQUIVOS if not (raiz / a).exists()]
    try:
        modulos = json.loads((raiz / "modulos.json").read_text(encoding="utf-8-sig"))["modulos"]
        problemas += [f"Falta a pasta do menu {m['nome']}: {m['pasta']}" for m in modulos if not (raiz / m["pasta"]).is_dir()]
    except (OSError, ValueError, KeyError):
        pass   # modulos.json com defeito aparece em validar_json
    for p in raiz.rglob("*.json"):
        if "backups" in p.parts:
            continue
        try:
            # utf-8-sig: o Bloco de Notas e o PowerShell gravam "UTF-8" com BOM, e o portal le assim; so utf-8 recusaria um arquivo bom
            json.loads(p.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            continue
        except ValueError as e:
            problemas.append(f"{p.relative_to(raiz).as_posix()} está com erro de digitação ({e})")
    return problemas


def dados_locais() -> Path:
    if os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "ExtratorLaudo"


def mostrar_token():
    """Diz no log se este computador tem o token da API do Klingo (nunca mostra o token). Mesma busca do extrair_laudo.ler_token."""
    if os.environ.get("KLINGO_APP_TOKEN", "").strip():
        log("Token da API do Klingo: definido na variável de ambiente KLINGO_APP_TOKEN.", OK)
        return
    onde = dados_locais() / "klingo_token.txt"
    for caminho in (onde, RAIZ / "klingo_token.txt"):
        try:
            if any(l.strip() and not l.strip().startswith("#") for l in caminho.read_text(encoding="utf-8-sig").splitlines()):
                log(f"Token da API do Klingo: encontrado em {caminho}.", OK)
                return
        except OSError:
            continue
    log(f"Token da API do Klingo: NÃO encontrado, e sem ele os painéis não atualizam. Salve o token (uma linha) em {onde}.", AVISO)


def chrome_instalado() -> bool:
    """Chrome ou Edge: o PDF usa um deles (exportar_pdf._abrir_chrome). A atualizacao dos dados nao usa navegador."""
    if WINDOWS:
        bases = [os.environ.get(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        return any(b and ((Path(b) / "Google/Chrome/Application/chrome.exe").exists() or (Path(b) / "Microsoft/Edge/Application/msedge.exe").exists()) for b in bases)
    return (Path("/Applications/Google Chrome.app").exists() or any(shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chrome")))


# ---------------------------------------------------------------- planilhas: restos, corrupcao e backup
def listar_planilhas(raiz: Path = RAIZ) -> list[Path]:
    return [p for p in raiz.rglob("*.xlsx") if "backups" not in p.parts and not p.name.startswith("~$") and not p.name.endswith(".tmp.xlsx")]


def planilha_valida(p: Path) -> bool:
    try:
        with zipfile.ZipFile(p) as z:
            return z.testzip() is None and "xl/workbook.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def nome_no_backup(p: Path, raiz: Path) -> str:
    return p.relative_to(raiz).as_posix().replace("/", "__")


def restaurar_do_backup(p: Path, raiz: Path, backups: Path) -> bool:
    for dia in sorted((d for d in backups.iterdir() if d.is_dir()), reverse=True) if backups.exists() else []:
        copia = dia / nome_no_backup(p, raiz)
        if copia.exists() and planilha_valida(copia):
            shutil.copy2(copia, p)
            log(f"Restaurei {p.name} com o backup de {dia.name}.", OK)
            return True
    return False


def caminho_do_banco(raiz: Path = RAIZ) -> Path:
    """Local do banco SQLite: variavel PORTAL_CSI_BANCO (vinda do banco.txt ao lado do .exe), depois a chave "banco_dados" do
    config.json (relativa a pasta do portal ou absoluta); padrao portal_csi.db.
    Mesma regra do banco_dados.py (que nao da para importar aqui: no .exe sozinho o portal ainda nao foi copiado)."""
    valor = os.environ.get("PORTAL_CSI_BANCO")
    if not valor:
        try:
            valor = json.loads((raiz / "config.json").read_text(encoding="utf-8-sig")).get("banco_dados")
        except (OSError, ValueError, AttributeError):
            valor = None
    if valor:
        p = Path(os.path.expandvars(os.path.expanduser(str(valor).strip().strip('"'))))
        return p if p.is_absolute() else raiz / p
    return raiz / "portal_csi.db"


def testar_banco(caminho: Path, espera: float = 6.0, criar: bool = True) -> str | None:
    """None se o banco abre e responde; senao, o motivo. Com prazo: um caminho de rede de um computador desligado pode demorar
    minutos para falhar sozinho. criar=False: nao cria pasta nem arquivo (so confere um banco que ja existe)."""
    resultado: dict = {}

    def teste():
        try:
            if not caminho.exists():
                if not criar:
                    resultado["erro"] = "o arquivo ainda não existe"
                    return
                caminho.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(caminho), timeout=5)
            try:
                conn.execute("PRAGMA schema_version").fetchone()
            finally:
                conn.close()
            resultado["ok"] = True
        except Exception as e:
            resultado["erro"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=teste, daemon=True)
    t.start()
    t.join(espera)
    if resultado.get("ok"):
        return None
    return resultado.get("erro") or f"sem resposta em {espera:.0f}s (o computador está desligado ou a rede fora do ar?)"


def mostrar_banco():
    """Diz no log qual banco este computador vai usar e se ele esta acessivel agora."""
    banco = caminho_do_banco()
    origem, texto = ORIGEM_BANCO, str(banco)
    onde = "em outro computador" if texto.startswith("\\\\") or texto.startswith("//") else "neste computador"
    erro = testar_banco(banco)
    if erro is None:
        log(f"Banco de dados ({onde}, conforme {origem}): {texto}", OK)
    else:
        log(f"Banco de dados FORA DO AR ({onde}, conforme {origem}): {texto} — {erro}", AVISO)
        log("O portal abre mesmo assim (o login usa a cópia local dos usuários e o histórico não é gravado). "
            "Se o banco fica no computador de alguém, ele precisa estar ligado e com a pasta compartilhada.", AVISO)


def definir_banco(caminho: str) -> int:
    """--banco CAMINHO: testa o caminho e grava em banco.txt, ao lado do .exe. Vale para todo computador que abrir este .exe."""
    caminho = caminho.strip().strip('"')
    if not caminho:
        log("Informe o caminho do banco. Exemplo:  \"Indicadores CSI.exe\" --banco \"\\\\MEU-PC\\Portal\\portal_csi.db\"", ERRO)
        return 2
    erro = testar_banco(Path(os.path.expandvars(caminho)), criar=False)   # só aceita banco que já existe (evita criar um vazio por engano)
    if erro:
        log(f"Não consegui abrir o banco em {caminho}: {erro}", ERRO)
        log("Confira se a pasta existe, está compartilhada (para outros computadores) e se você tem permissão de gravar nela.", AVISO)
        return 1
    try:
        ARQUIVO_BANCO.write_text("# Caminho do banco de dados do Indicadores CSI (uma linha). Apague este arquivo para voltar ao padrão.\n"
                                 f"{caminho}\n", encoding="utf-8")
    except OSError as e:
        log(f"O banco funciona, mas não consegui gravar {ARQUIVO_BANCO}: {e}", ERRO)
        return 1
    log(f"Pronto: o banco é {caminho}. Gravado em {ARQUIVO_BANCO}.", OK)
    return 0


# ---------------------------------------------------------------- acesso pela rede (servidor para os colegas)
def carregar_seguranca():
    """Carrega o seguranca_rede.py da pasta de dados (o portal copiado do .exe). Por caminho, e nao por 'import', para o PyInstaller
    nao congelar uma copia dele dentro do .exe (valeria a copia velha, nao a da pasta)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("seguranca_rede", RAIZ / "seguranca_rede.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def preparar_pasta_de_dados():
    if AUTONOMO:
        sincronizar_app()


def mostrar_rede(estado: dict | None):
    """Conta no log como ficou o acesso dos colegas (o servidor informa pelo /estado local)."""
    r = (estado or {}).get("rede") or {}
    if not r.get("ativa"):
        log(f"Rede: DESLIGADA — {r.get('motivo') or 'sem informação'}. Só este computador acessa o portal.", AVISO)
        return
    log(f"Os colegas entram por: {r['url']}  (IP {', '.join(r.get('ips') or ['?'])}) — HTTPS, só redes internas, sempre com login.", OK)
    imp = r.get("impressao_digital", "")
    if imp:
        log("Impressão digital do certificado: " + ":".join(imp[i:i + 2] for i in range(0, len(imp), 2)).upper(), INFO)
    if r.get("firewall") == "ativa":
        log("Firewall do Windows: regra “Indicadores CSI” ativa.", OK)
    else:
        log(f"Firewall do Windows: ainda falta liberar a porta {r.get('porta')} para os colegas. Uma vez só, rode:  "
            f"\"{NOME_EXE}.exe\" --liberar-rede   (se o Windows perguntar se permite o acesso, clique em Permitir).", AVISO)
    if CONGELADO:
        log(f"Para os colegas: copie a pasta “Compartilhar” (ao lado deste programa) para a pasta corporativa. Eles abrem só o “Indicadores CSI.exe”.", INFO)
    log(f"Quem não é administrador só consegue clicar em “Atualizar agora” de novo {r.get('intervalo_atualizar_minutos', 0):g} min depois da última atualização.", INFO)


def manter_acordado():
    """Windows: enquanto o servidor estiver aberto o computador nao entra em suspensao (a tela pode apagar). Sem isso os colegas
    perderiam o acesso quando o PC dormisse. Vale so para esta thread/processo e some quando o servidor fecha."""
    if not WINDOWS:
        return
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        log("O computador não vai dormir enquanto o servidor estiver aberto (a tela pode apagar).", INFO)
    except Exception:
        pass


def status_rede() -> int:
    """--rede: mostra a situacao do acesso pela rede sem abrir nada."""
    preparar_console()
    try:
        preparar_pasta_de_dados()
        seg = carregar_seguranca()
    except Exception as e:
        log(f"Não consegui preparar o portal: {type(e).__name__}: {e}", ERRO)
        return 2
    cfg = seg.ler_config(RAIZ)
    for aviso in cfg["_avisos"]:
        log(aviso, AVISO)
    porta = cfg["porta_rede"]
    log(f"Rede {'ligada' if cfg['ativar_rede'] else 'DESLIGADA'} em rede.json — porta HTTPS {porta}; redes liberadas: {', '.join(str(r) for r in cfg['_redes'])}.",
        INFO if cfg["ativar_rede"] else AVISO)
    nomes, ips = seg.nomes_do_computador(), seg.ips_locais()
    log(f"Este computador: {', '.join(nomes)}  (IP {', '.join(ips) or 'não achei'})", INFO)
    cert = RAIZ / seg.PASTA_SEGURANCA / "servidor.crt"
    impressao = seg.impressao_digital(cert) if cert.exists() else ""
    log("Certificado: " + (f"existe. Impressão digital {seg.formatar_impressao(impressao)}" if impressao else "ainda não foi criado (nasce na primeira abertura do servidor)."), OK if impressao else INFO)
    regra = seg.regra_firewall(porta)
    log({"ativa": f"Firewall do Windows: regra “{seg.NOME_REGRA}” liberando a porta {porta}.",
         "ausente": f"Firewall do Windows: SEM regra para a porta {porta}. Rode:  \"{NOME_EXE}.exe\" --liberar-rede",
         "desconhecida": "Firewall do Windows: não consegui consultar."}[regra], OK if regra == "ativa" else AVISO)
    estado = ler_estado(PORTA_PADRAO)
    if not (estado and estado.get("portal")):
        log("O servidor NÃO está aberto agora neste computador.", AVISO)
        return 0
    log("O servidor está aberto.", OK)
    if impressao and ips:
        import socket as _s, ssl as _ssl, hashlib as _h
        try:
            with _s.create_connection((ips[0], porta), 4) as bruto:
                ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname, ctx.verify_mode = False, _ssl.CERT_NONE
                with ctx.wrap_socket(bruto) as tls:
                    achada = _h.sha256(tls.getpeercert(True)).hexdigest()
            log(f"Teste pela rede em {ips[0]}:{porta}: " + ("responde com o certificado certo." if achada == impressao else "RESPONDE COM OUTRO CERTIFICADO (algo diferente está nessa porta)."),
                OK if achada == impressao else ERRO)
        except OSError as e:
            log(f"Teste pela rede em {ips[0]}:{porta}: não conectou ({e}).", ERRO)
    return 0


def liberar_rede() -> int:
    """--liberar-rede: cria a regra de entrada do Firewall do Windows (so redes internas, so a porta do portal)."""
    preparar_console()
    try:
        preparar_pasta_de_dados()
        seg = carregar_seguranca()
    except Exception as e:
        log(f"Não consegui preparar o portal: {type(e).__name__}: {e}", ERRO)
        return 2
    porta = seg.ler_config(RAIZ)["porta_rede"]
    log(f"Liberando a porta {porta} (TCP, só para as redes internas) no Firewall do Windows. O Windows vai pedir permissão de administrador.", INFO)
    ok, saida = seg.liberar_firewall(porta)
    if ok:
        log(f"Pronto: regra “{seg.NOME_REGRA}” criada. Os colegas já conseguem entrar.", OK)
        return 0
    log("Não consegui criar a regra" + (f" ({saida[:200]})" if saida else "") + ". Provavelmente este usuário não é administrador deste computador.", ERRO)
    log("Peça a quem cuida da rede:  " + seg.texto_para_ti(porta), AVISO)
    return 1


def iniciar_com_windows(ativar: bool) -> int:
    """--iniciar-com-windows: atalho na pasta Inicializar do usuario (nao precisa de administrador)."""
    preparar_console()
    atalho = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup" / f"{NOME_EXE}.lnk"
    if not ativar:
        existia = atalho.exists()
        atalho.unlink(missing_ok=True)
        log("Atalho de inicialização removido." if existia else "Não havia atalho de inicialização.", OK)
        return 0
    if not (WINDOWS and CONGELADO):
        log("Isto só vale para o .exe no Windows.", ERRO)
        return 2
    q = lambda s: str(s).replace("'", "''")
    atalho.parent.mkdir(parents=True, exist_ok=True)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(atalho)}'); $s.TargetPath='{q(sys.executable)}'; $s.Arguments='--sem-abrir'; "
          f"$s.WorkingDirectory='{q(EXE_DIR)}'; $s.WindowStyle=7; $s.Description='Indicadores CSI - Servidor'; $s.Save()")
    cod, saida = rodar(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], 30)
    if cod != 0 or not atalho.exists():
        log(f"Não consegui criar o atalho em {atalho}: {saida.strip()[:200]}", ERRO)
        return 1
    log(f"Pronto: o servidor vai abrir sozinho (minimizado) quando você entrar no Windows. Atalho: {atalho}", OK)
    return 0


def backup_do_dia(raiz: Path = RAIZ, backups: Path = BACKUPS) -> int:
    """Uma copia de cada planilha por dia; guarda os ultimos DIAS_DE_BACKUP dias. Devolve quantas copiou."""
    dia = backups / f"{date.today():%Y-%m-%d}"
    copiadas = 0
    for nome in ("servidor.crt", "servidor.key"):   # trocar o certificado obriga todos os clientes a receberem um servidor.json novo: guarda copia
        origem, destino = raiz / "seguranca" / nome, dia / f"seguranca__{nome}"
        if origem.exists() and not destino.exists():
            try:
                dia.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem, destino)
            except OSError:
                pass
    for p in listar_planilhas(raiz):
        destino = dia / nome_no_backup(p, raiz)
        if destino.exists() or not planilha_valida(p):
            continue
        try:
            dia.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, destino)
            copiadas += 1
        except OSError:
            pass   # planilha em uso naquele instante: tenta de novo na proxima conferencia
    banco = caminho_do_banco(raiz)
    destino_banco = dia / "portal_csi.db"
    # testar_banco antes: .exists() direto num caminho de rede de um PC desligado prenderia o lancador por muito tempo
    if not destino_banco.exists() and testar_banco(banco, criar=False) is None:
        try:
            # backup do proprio SQLite: copiar o arquivo solto perderia o que ainda esta no -wal
            origem, saida = sqlite3.connect(str(banco), timeout=10), None
            try:
                dia.mkdir(parents=True, exist_ok=True)
                saida = sqlite3.connect(str(destino_banco))
                origem.backup(saida)
                copiadas += 1
            finally:
                if saida is not None:
                    saida.close()
                origem.close()
        except (OSError, sqlite3.Error):
            destino_banco.unlink(missing_ok=True)   # copia pela metade nao serve; tenta de novo na proxima conferencia
    if backups.exists():
        for velho in sorted(d for d in backups.iterdir() if d.is_dir())[:-DIAS_DE_BACKUP]:
            shutil.rmtree(velho, ignore_errors=True)
    return copiadas


def cuidar_das_planilhas(raiz: Path = RAIZ, backups: Path = BACKUPS) -> bool:
    """Devolve False se alguma planilha esta corrompida e nao deu para restaurar."""
    for resto in raiz.rglob("*.tmp.xlsx"):   # sobra de uma gravacao interrompida
        try:
            resto.unlink()
            log(f"Apaguei {resto.name} (sobra de uma gravação interrompida).", INFO)
        except OSError:
            pass
    tudo_certo = True
    for p in listar_planilhas(raiz):
        if planilha_valida(p):
            continue
        log(f"A planilha {p.name} está corrompida.", ERRO)
        guardada = p.with_name(f"{p.stem}.corrompida-{datetime.now():%Y%m%d-%H%M%S}.bak")
        try:
            p.replace(guardada)
        except OSError:
            log(f"Não consegui mexer em {p.name}: feche o Excel e abra de novo.", ERRO)
            tudo_certo = False
            continue
        if restaurar_do_backup(p, raiz, backups):
            log(f"O arquivo ruim ficou guardado como {guardada.name}.", INFO)
        else:
            log(f"Não há backup para restaurar. Guardei o arquivo ruim como {guardada.name}; "
                f"o portal recria a planilha no próximo “Atualizar agora”.", AVISO)
    novas = backup_do_dia(raiz, backups)
    if novas:
        log(f"Backup de hoje: {novas} planilha(s) copiadas para a pasta backups.", OK)
    for aberto in raiz.rglob("~$*.xlsx"):
        log(f"O Excel está com {aberto.name[2:]} aberto: feche antes de clicar em Atualizar agora.", AVISO)
    return tudo_certo


# ---------------------------------------------------------------- uma instancia so e vigilancia
def unica_instancia():
    """Fecha outro lancador aberto (e o portal dele) e registra este."""
    try:
        antigo = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        antigo = None
    if antigo and antigo != os.getpid() and processo_vivo(antigo):
        nome, cmd = info_processo(antigo)
        if "Indicadores CSI" in nome or "iniciar_portal" in cmd or "Indicadores CSI" in cmd:
            log(f"Havia outro lançador aberto (processo {antigo}): fechando para não ter dois.", INFO)
            encerrar(antigo)
    try:
        PIDFILE.write_text(str(os.getpid()))
    except OSError:
        pass
    atexit.register(lambda: PIDFILE.unlink(missing_ok=True) if sou_a_instancia_atual() else None)


def sou_a_instancia_atual() -> bool:
    """A marca do lancador (.portal_csi.pid) ainda e a minha? Se dois .exe abrirem juntos, o ultimo a gravar vence e o outro sai."""
    try:
        return int(PIDFILE.read_text().strip()) == os.getpid()
    except (OSError, ValueError):
        return True   # sem marca legivel: nao desiste por isso


def ler_tecla(espera: float) -> str | None:
    if WINDOWS:
        import msvcrt
        fim = time.time() + espera
        while time.time() < fim:
            if msvcrt.kbhit():
                return msvcrt.getwch().lower()
            time.sleep(0.05)
        return None
    if sys.stdin and sys.stdin.isatty():
        import select
        if select.select([sys.stdin], [], [], espera)[0]:
            return sys.stdin.readline().strip().lower()[:1]
        return None
    time.sleep(espera)
    return None


def abrir_navegador(porta: int):
    if SEM_NAVEGADOR:
        return
    try:
        webbrowser.open(url(porta))
    except Exception:
        log(f"Não consegui abrir o navegador. Abra você mesmo: {url(porta)}", AVISO)


def vigiar(srv: Servidor) -> str:
    """Fica de olho no portal. Devolve por que parou: 'caiu', 'travou', 'reiniciar' ou 'sair'."""
    falhas, proxima, ultimo_backup = 0, time.time() + CHECA_A_CADA, time.time()
    while True:
        if not sou_a_instancia_atual():   # outro Indicadores CSI assumiu (aberto depois deste): sai sem brigar pela porta
            log("Outro Indicadores CSI assumiu o comando: este aqui encerra.", INFO)
            return "sair"
        if not srv.vivo():
            log(f"O portal fechou sozinho (código {srv.proc.returncode}).", ERRO)
            return "caiu"
        tecla = ler_tecla(1.0)
        if tecla == "r":
            log("Reiniciando o portal a pedido.", INFO)
            return "reiniciar"
        if tecla == "q":
            return "sair"
        if tecla == "a":
            abrir_navegador(srv.porta)
        if tecla == "l":
            log("--- últimas linhas do portal ---")
            for linha in list(srv.ultimas)[-25:]:
                print(SAIDA + linha)
        agora = time.time()
        if agora >= proxima:
            proxima = agora + CHECA_A_CADA
            if ler_estado(srv.porta, 8):
                falhas = 0
            else:
                falhas += 1
                if falhas >= FALHAS_PARA_TRAVADO:
                    log("O portal parou de responder.", ERRO)
                    return "travou"
        if agora - ultimo_backup > 1800:
            ultimo_backup = agora
            backup_do_dia()


def supervisionar(py: dict) -> int:
    quedas: collections.deque = collections.deque()
    porta, aberto_em = preparar_porta(), None
    while True:
        srv = Servidor(py, porta)
        log(f"Abrindo o portal (porta {porta})...", INFO)
        srv.iniciar()
        if srv.esperar_pronto():
            log(f"Portal no ar: {url(porta)}", OK)
            mostrar_rede(srv.estado)
            log("Pode minimizar esta janela, mas não a feche: fechar a janela encerra o portal (e tira o acesso dos colegas). Teclas: R reinicia · A abre o navegador · L mostra o log · Q fecha tudo.", INFO)
            if aberto_em != porta:
                abrir_navegador(porta)
                aberto_em = porta
            motivo = vigiar(srv)
        else:
            log("O portal não ficou pronto." if srv.vivo() else "O portal fechou logo ao abrir.", ERRO)
            motivo = "nao_subiu"
        causas = diagnosticar(srv.ultimas) if motivo in ("caiu", "nao_subiu", "travou") else []
        srv.parar()
        if motivo == "sair":
            return 0
        for c in causas:
            log(c, AVISO)
        if motivo == "nao_subiu" and any("Falta o pacote" in c for c in causas):
            novo = sondar(py["cmd"])
            if novo and novo["faltam"]:
                py["faltam"] = novo["faltam"]
                if not garantir_pacotes(py):
                    return 1
        agora = time.time()
        if motivo != "reiniciar":
            quedas.append(agora)
        while quedas and agora - quedas[0] > JANELA_QUEDAS:
            quedas.popleft()
        if len(quedas) > MAX_QUEDAS:
            log(f"O portal caiu {len(quedas)} vezes em 10 minutos: parei de tentar. O motivo está nas linhas acima e em \"{LOG.name}\".", ERRO)
            return 1
        espera = 1 if motivo == "reiniciar" else min(2 ** len(quedas), 30)
        log(f"Abrindo de novo em {espera}s...", INFO)
        time.sleep(espera)
        if not sou_a_instancia_atual():
            log("Outro Indicadores CSI assumiu o comando: este aqui encerra.", INFO)
            return 0
        cuidar_das_planilhas()
        porta = preparar_porta()


def main() -> int:
    preparar_console()
    log("=" * 62)
    log("  Indicadores CSI · SERVIDOR  ·  dados e atualizações ficam aqui")
    log("=" * 62)
    if not SO_VERIFICAR:
        unica_instancia()   # logo no inicio: o mais novo fecha o mais antigo
        time.sleep(1.5)     # dois .exe abertos ao mesmo tempo gravam a marca quase juntos: espera para ver quem ficou como dono
        if not sou_a_instancia_atual():
            log("Outro Indicadores CSI foi aberto ao mesmo tempo e ficou no comando: este aqui fecha sem mexer em nada.", INFO)
            return 0
    if CONGELADO:
        limpar_temporarios_antigos()
    if AUTONOMO:
        log(f"Dados e configurações ficam em: {APP}", INFO)
        try:
            mudou = sincronizar_app()
        except (OSError, ValueError, KeyError) as e:
            log(f"Não consegui preparar o portal na pasta de dados: {e}", ERRO)
            pausar()
            return 2
        if mudou:
            log(f"Portal atualizado na pasta de dados ({mudou} arquivo(s)).", OK)
    else:
        log(f"Pasta: {RAIZ}", INFO)
    problemas = conferir_arquivos()
    if problemas:
        for p in problemas:
            log(p, ERRO)
        log("Corrija isso e abra de novo. Dica: este programa precisa ficar dentro da pasta do projeto.", ERRO)
        pausar()
        return 2
    log("Arquivos do portal: tudo no lugar.", OK)
    if CONGELADO:   # tudo vem dentro do .exe: nao procura nem instala Python
        py = {"cmd": [sys.executable], "versao": sys.version_info[:2], "faltam": []}
        log(f"Python {py['versao'][0]}.{py['versao'][1]}, pandas, openpyxl, numpy e playwright: já vêm dentro do .exe.", OK)
    else:
        py = escolher_python()
        if py is None:
            log(f"Não achei o Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou mais novo neste computador. Instale em https://www.python.org/downloads/ "
                f"(marque “Add python.exe to PATH”) e abra de novo.", ERRO)
            pausar()
            return 2
        log(f"Python {py['versao'][0]}.{py['versao'][1]} encontrado ({' '.join(py['cmd'])}).", OK)
        if not garantir_pacotes(py):
            pausar()
            return 2
        log(f"Pacotes: {', '.join(PACOTES)} instalados.", OK)
    if not chrome_instalado():
        log("Nem o Google Chrome nem o Edge foram encontrados: os menus funcionam, mas o botão de exportar PDF precisa de um deles.", AVISO)
    mostrar_banco()
    mostrar_token()
    if SO_VERIFICAR:   # so leitura: nao fecha nada, nao restaura nem copia planilhas
        for p in listar_planilhas():
            log(f"Planilha {p.relative_to(RAIZ).as_posix()}: " + ("íntegra." if planilha_valida(p) else "CORROMPIDA (o lançador restauraria do backup)."), OK if planilha_valida(p) else ERRO)
        estado = ler_estado(PORTA_PADRAO)
        log(f"Porta {PORTA_PADRAO}: " + ("portal aberto agora (seria reiniciado)." if estado and estado.get("portal") else "ocupada por outro programa." if porta_ocupada(PORTA_PADRAO) else "livre."), INFO)
        log("Verificação concluída. Nada foi aberto nem alterado.", OK)
        return 0
    if not cuidar_das_planilhas():
        log("Há planilha com problema que não consegui resolver (veja acima).", AVISO)
    manter_acordado()
    try:
        return supervisionar(py)
    except KeyboardInterrupt:
        return 0
    except Exception as e:   # o lancador nao pode morrer em silencio
        log(f"Erro inesperado no lançador: {type(e).__name__}: {e}", ERRO)
        return 1


if __name__ == "__main__":
    if "--servidor" in sys.argv:      # processo filho: so roda o portal (o lancador abre este mesmo .exe com esta opcao)
        executar_servidor()
        sys.exit(0)
    if "--teste-chrome" in sys.argv:
        preparar_console()
        sys.exit(testar_chrome())
    for opcao, funcao in (("--rede", status_rede), ("--liberar-rede", liberar_rede),
                          ("--iniciar-com-windows", lambda: iniciar_com_windows(True)), ("--nao-iniciar-com-windows", lambda: iniciar_com_windows(False))):
        if opcao in sys.argv:         # comandos de uma vez so: fazem o que pediram, mostram o resultado e saem sem abrir o portal
            codigo = funcao()
            pausar()
            sys.exit(codigo)
    if "--banco" in sys.argv:         # --banco "\\MEU-PC\Portal\portal_csi.db": escolhe o banco de todos os computadores que usam este .exe
        preparar_console()
        i = sys.argv.index("--banco")
        codigo = definir_banco(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        pausar()
        sys.exit(codigo)
    codigo = main()
    if codigo not in (0,):
        pausar()
    sys.exit(codigo)
