"""Portal com o menu: Metas, Faturamento, Financeiro, Indicadores, Cesta, Suprimentos e Atendimento (modulos.json).

Sobe DOIS servidores no mesmo processo (mesmos dados, mesmas travas):
  - http://127.0.0.1:8765  so deste computador (o dono, o lancador, a exportacao de PDF);
  - https://0.0.0.0:8766   para a rede interna (rede.json; ver seguranca_rede.py). Os outros computadores usam o cliente
                           "Indicadores CSI.exe" e nunca guardam dados nem token: tudo fica aqui. Atualizacoes continuam
                           uma de cada vez, e quem nao e administrador espera alguns minutos entre "Atualizar agora".
Cada item do menu e uma pasta ao lado deste arquivo:
  - "metas":      a pasta "Acompanhamento de META" (dashboard de metas, com o botao Atualizar agora);
  - "relatorios": uma pasta com "relatorios.json" e um gerar_*.py (Faturamento e Financeiro), que baixam
                  relatorios do Klingo, acumulam em Excel e geram o dashboard, tambem com o botao;
  - "pagina":     uma pasta com um index.html (para menus simples).

Todas as atualizacoes passam por uma unica trava: nunca rodam duas ao mesmo tempo. A verificacao
automatica (config.json: verificacao_automatica_minutos) confere cada painel em sequencia, direto na API do
Klingo (so consulta se os dados estiverem velhos); se o token da API faltar ou for recusado, o painel avisa.

Uso:  python servidor_portal.py          (ou abra o "Indicadores CSI.exe")
      python servidor_portal.py --sem-abrir   (nao abre o navegador)

Para criar mais um menu: crie a pasta e acrescente um bloco em modulos.json.
"""
import importlib
import json
import math
import mimetypes
import os
import re
import socket
import socketserver
import ssl
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import date, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

RAIZ = Path(__file__).parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import autenticacao as auth  # noqa: E402
import banco_dados  # noqa: E402
import klingo_relatorios as klingo  # noqa: E402
import painel_comum as pc  # noqa: E402
import seguranca_rede as rede  # noqa: E402

try:    # sem o pypdf o portal abre normalmente; so o botao de PDF avisa
    import exportar_pdf
    ERRO_PDF = None
except ImportError as e:
    exportar_pdf, ERRO_PDF = None, str(e)

CONFIG = RAIZ / "modulos.json"
PAGINA = RAIZ / "portal.html"
HOST = "127.0.0.1"
PORTA = int(os.environ.get("PORTAL_PORTA", "8765"))  # o lancador (iniciar_portal.py) usa outra porta se a 8765 for de outro programa
URL_PORTAL = f"http://{HOST}:{PORTA}/"


class ServidorExclusivo(ThreadingHTTPServer):
    """No Windows, SO_REUSEADDR deixa dois servidores abrirem a mesma porta sem erro (o segundo fica 'fantasma'
    e duplica as verificacoes automaticas). Aqui a porta e exclusiva: se estiver em uso, da erro."""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True
    e_rede = False   # True so no servidor HTTPS da rede (ServidorRede)

    def handle_error(self, request, client_address):
        erro = sys.exc_info()[1]
        # o navegador (ou o lancador) fechou a conexao no meio, ou um programa de rede falou sem TLS: nao e erro do portal
        if isinstance(erro, (ConnectionError, TimeoutError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


class ServidorRede(ServidorExclusivo):
    """Servidor HTTPS para a rede interna. Tres cuidados:
      - o endereco de quem conecta e conferido ANTES de qualquer coisa (verify_request): fora das redes liberadas, a conexao e fechada;
      - o aperto de mao TLS e feito na thread de cada conexao (e nao no accept), com prazo: um cliente parado nao trava os demais;
      - so TLS 1.2+ com o certificado deste servidor (seguranca_rede.contexto_tls)."""
    e_rede = True
    request_queue_size = 64

    def __init__(self, endereco, handler, contexto: ssl.SSLContext, redes: list):
        self.contexto, self.redes, self._negados = contexto, redes, {}
        super().__init__(endereco, handler)

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)   # sem o getfqdn() do HTTPServer: em 0.0.0.0 ele pode demorar segundos na rede da empresa
        self.server_name, self.server_port = "servidor", self.server_address[1]

    def get_request(self):
        soquete, endereco = self.socket.accept()
        if not rede.ip_permitido(endereco[0], self.redes):
            soquete.close()
            agora = time.time()
            if agora - self._negados.get(endereco[0], 0.0) > 60:   # uma linha por minuto por endereco, para nao encher o log
                self._negados[endereco[0]] = agora
                print(f">>> Acesso pela rede RECUSADO: {endereco[0]} não está nas redes liberadas (rede.json).", flush=True)
            raise OSError("endereço fora das redes liberadas")   # o loop do servidor ignora OSError do accept e segue
        return self.contexto.wrap_socket(soquete, server_side=True, do_handshake_on_connect=False), endereco


def ler_modulos() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8-sig"))


def _visoes_pdf(modulo: dict) -> list[dict]:
    """Visoes que o menu de exportacao oferece para um painel ("visoes_pdf" do modulos.json), com nome e area vindos do
    responsaveis.json da pasta do painel. Sem o arquivo, a visao aparece pelo proprio id."""
    ids = modulo.get("visoes_pdf") or []
    if not ids:
        return []
    try:
        arq = RAIZ / modulo["pasta"] / "responsaveis.json"
        lista = json.loads(arq.read_text(encoding="utf-8-sig")).get("responsaveis", [])
    except (OSError, ValueError):
        lista = []
    por_id = {str(r.get("id") or r.get("nome", "")).strip().lower(): r for r in lista}
    return [{"id": i, "nome": por_id.get(i, {}).get("nome", i), "area": por_id.get(i, {}).get("area", "")} for i in ids]


# O modulo de Metas ja traz o servidor dele (botao, estado, verificacao); o portal so o reaproveita.
_metas = next(m for m in ler_modulos()["modulos"] if m["tipo"] == "metas")
sys.path.insert(0, str(RAIZ / _metas["pasta"]))
import servidor_painel as sp  # noqa: E402

TRAVA = threading.Lock()
sp.TRAVA = TRAVA                      # Metas e os demais menus disputam a mesma trava
TRAVA_PDF = threading.Lock()          # Uma geracao de PDF por vez
CODIGOS: dict[str, object] = {}       # id do menu -> modulo gerar_*.py
ESTADOS: dict[str, dict] = {}         # id do menu -> {"atualizando", "aviso"}
ERROS_MODULOS: dict[str, str] = {}    # id do menu -> por que nao carregou (um menu quebrado nao derruba o portal)
META = {"chave": None, "quando": 0.0, "trava": threading.Lock()}   # copia da pagina de Metas (ver Portal._metas_pagina)


def carregar_codigos():
    for m in ler_modulos()["modulos"]:
        if m["tipo"] == "relatorios":
            sys.path.insert(0, str(RAIZ / m["pasta"]))
            try:
                CODIGOS[m["id"]] = importlib.import_module(m["codigo"])
                ESTADOS[m["id"]] = {"atualizando": False, "aviso": None, "chave": None, "trava_pagina": threading.Lock()}
            except Exception as e:
                ERROS_MODULOS[m["id"]] = f"{type(e).__name__}: {e}"
                print(f">>> ERRO: o menu {m['nome']} não carregou ({ERROS_MODULOS[m['id']]}). Os outros menus continuam funcionando.", flush=True)


def _mtime(caminho) -> float:
    try:
        return caminho.stat().st_mtime
    except (OSError, AttributeError):
        return 0.0


def _chave_pagina(codigo) -> tuple:
    """O que, se mudar, obriga a refazer a pagina do menu: planilhas de qualquer menu, modelo HTML, visual comum ou o dia."""
    return (tuple(_mtime(c.arquivo_dados()) for c in CODIGOS.values()), _mtime(getattr(codigo, "MODELO", None)),
            _mtime(RAIZ / "painel_base.js"), _mtime(RAIZ / "painel_base.css"), date.today().isoformat(),
            _mtime(sp.ex.PLANILHA), _mtime(sp.gd.METAS),   # o Atendimento le as metas (planilha e metas.json) do menu Metas
            tuple(_mtime(f) for f in getattr(codigo, "ARQUIVOS_EXTRAS", ())))   # configuracoes do proprio menu (ex.: responsaveis.json)


def pagina_pronta(modulo_id: str):
    """Gera a pagina do menu so quando algo mudou (planilhas de qualquer menu, modelo HTML ou o dia); senao reaproveita a ultima.
    Antes ela era refeita a cada abertura (a Cesta levava de 15 s a mais de 1 min)."""
    codigo, est = CODIGOS[modulo_id], ESTADOS[modulo_id]
    with est["trava_pagina"]:   # duas aberturas ao mesmo tempo esperam a mesma geracao, em vez de repetir
        chave = _chave_pagina(codigo)
        if est["chave"] != chave or not codigo.SAIDA.exists():
            codigo.gerar()
            est["chave"] = chave


PAGINAS_PERIODO: dict[tuple, tuple] = {}   # (menu, de, ate) -> (chave_pagina, bytes): paginas de periodos ja calculados
MAX_PAGINAS_PERIODO = 40
PADRAO_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def periodo_da_url(consulta: str) -> tuple[str, str] | None:
    """('2026-09', '2026-10') se a URL pede um periodo de VARIOS meses (?de=&ate=), ou ('2026-09-10', '2026-10-25') se pede dias exatos;
    um mes inteiro so e a pagina de sempre (o proprio painel escolhe)."""
    q = parse_qs(consulta)
    return pc.periodo_da_consulta((q.get("de") or [""])[0], (q.get("ate") or [""])[0])


def pagina_do_periodo(modulo_id: str, de: str, ate: str) -> bytes:
    """Pagina do menu calculada para o periodo (varios meses juntos). Guardada em memoria enquanto os dados nao mudam."""
    codigo, est = CODIGOS[modulo_id], ESTADOS[modulo_id]
    with est["trava_pagina"]:
        chave = _chave_pagina(codigo)
        guardada = PAGINAS_PERIODO.get((modulo_id, de, ate))
        if guardada and guardada[0] == chave:
            return guardada[1]
        pagina = codigo.gerar(de, ate, devolver_html=True).encode("utf-8")
        while len(PAGINAS_PERIODO) >= MAX_PAGINAS_PERIODO:
            PAGINAS_PERIODO.pop(next(iter(PAGINAS_PERIODO)))
        PAGINAS_PERIODO[(modulo_id, de, ate)] = (chave, pagina)
        return pagina


def metas_do_periodo(de: str, ate: str) -> bytes:
    """Pagina de Metas calculada para o periodo, guardada em memoria como as dos outros menus (e refeita depois de 1 min: o 'esperado ate agora' depende da hora)."""
    chave = (_mtime(sp.ex.PLANILHA), _mtime(sp.gd.METAS), _mtime(sp.gd.MODELO), _mtime(RAIZ / "painel_base.js"), _mtime(RAIZ / "painel_base.css"), date.today().isoformat())
    with META["trava"]:
        guardada = PAGINAS_PERIODO.get(("metas", de, ate))
        if not guardada or guardada[0] != chave or time.time() - guardada[2] > 60:
            while len(PAGINAS_PERIODO) >= MAX_PAGINAS_PERIODO:
                PAGINAS_PERIODO.pop(next(iter(PAGINAS_PERIODO)))
            guardada = (chave, sp.gd.gerar(de, ate, devolver_html=True).encode("utf-8"), time.time())
            PAGINAS_PERIODO[("metas", de, ate)] = guardada
        return guardada[1]


def preparar_periodo(ids: list[str], de: str, ate: str) -> None:
    """Calcula em paralelo as paginas de um periodo de varios meses (uma linha de trabalho por menu) para o PDF nao esperar uma depois da outra.
    Um menu que falhar aqui falha de novo, com a mensagem de sempre, quando o PDF abrir a pagina dele."""
    def um(i: str):
        try:
            if i == "metas":
                metas_do_periodo(de, ate)
            elif i in CODIGOS:
                pagina_do_periodo(i, de, ate)
        except Exception as e:
            print(f">>> AVISO: não consegui preparar {i} para {de} a {ate} ({e})", flush=True)
    fios = [threading.Thread(target=um, args=(i,), daemon=True) for i in dict.fromkeys(ids)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()


def meses_do_portal() -> list[str]:
    """Meses que o menu de exportacao oferece: do primeiro mes de qualquer painel ate o mes atual."""
    primeiros = []
    for m in ler_modulos()["modulos"]:
        try:
            if m["tipo"] == "metas":
                primeiros.append(str(json.loads((RAIZ / m["pasta"] / "metas.json").read_text(encoding="utf-8-sig")).get("primeiro_mes", "")))
            elif m["id"] in CODIGOS:
                primeiros.append(str(klingo.ler_definicao(RAIZ / m["pasta"]).get("primeiro_mes", "")))
        except Exception:
            continue
    primeiros = [p for p in primeiros if PADRAO_MES.match(p)]
    atual = date.today().strftime("%Y-%m")
    return pc.meses_entre(min(primeiros), atual) if primeiros and min(primeiros) <= atual else [atual]


def preparar_paginas():
    """Logo depois de abrir, gera as paginas dos menus em segundo plano: quando voce clicar, ja estao prontas.
    Cada menu num thread proprio, porque um so (ex.: Cesta, que pode levar até 1 min) nao deve atrasar os outros."""
    def preparar_um(m):
        try:
            pagina_pronta(m["id"])
        except Exception as e:
            print(f">>> AVISO: não consegui preparar o painel {m['nome']} ({e})", flush=True)

    threads = [threading.Thread(target=preparar_um, args=(m,), daemon=True)
               for m in ler_modulos()["modulos"] if m["tipo"] == "relatorios" and m["id"] in CODIGOS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(">>> Painéis prontos.", flush=True)


AUTOMATICA = "verificação automática"
REDE_CFG = rede.ler_config(RAIZ)                   # rede.json (porta, redes liberadas, intervalo entre atualizacoes manuais...)
ATUAL = {"modulo": None, "quem": "", "inicio": 0.0}   # a atualizacao em andamento (para avisar quem clicar junto)
ULTIMA: dict[str, dict] = {}                        # id do menu -> {"quem", "quando"} da ultima atualizacao que de fato consultou o Klingo


def _nome_do_modulo(modulo_id: str) -> str:
    return next((m["nome"] for m in ler_modulos()["modulos"] if m["id"] == modulo_id), modulo_id)


def _planilha_do_menu(modulo: dict):
    if modulo["tipo"] == "metas":
        return sp.ex.PLANILHA
    codigo = CODIGOS.get(modulo["id"])
    return codigo.arquivo_dados() if codigo else None


def _em_andamento() -> dict:
    a = dict(ATUAL)
    quem = f" ({a['quem']} está atualizando {_nome_do_modulo(a['modulo'])})" if a["modulo"] else ""
    return {"ok": True, "atualizou": False,
            "mensagem": f"Já existe uma atualização em andamento{quem}. Os painéis recarregam sozinhos quando ela terminar."}


def _bloqueio_manual(modulo: dict, usuario: str) -> dict | None:
    """'Atualizar agora' de quem nao e administrador: se os dados foram atualizados ha pouco (por qualquer pessoa, ou pela verificacao
    automatica), NAO consulta o Klingo de novo. Protege a cota da API e evita varias pessoas refazendo a mesma planilha.
    Devolve a resposta pronta, ou None se pode seguir."""
    minimo = REDE_CFG["intervalo_minimo_atualizar_agora_minutos"]
    gravada = _mtime(_planilha_do_menu(modulo))
    if not minimo or not gravada or auth.eh_admin(usuario):
        return None
    idade = (time.time() - gravada) / 60
    if idade >= minimo:
        return None
    ultima = ULTIMA.get(modulo["id"])
    quem = f" por {ultima['quem']}" if ultima and ultima["quem"] != AUTOMATICA else (" pela verificação automática" if ultima else "")
    ha = "agora há pouco" if idade < 1 else f"há {idade:.0f} min"
    return {"ok": True, "atualizou": False,
            "mensagem": f"Os dados de {modulo['nome']} foram atualizados {ha}{quem}, então já estão em dia. Para não sobrecarregar o Klingo, "
                        f"o botão só atualiza de novo depois de {minimo:g} min (faltam {max(1, math.ceil(minimo - idade))}). "
                        f"Administradores podem atualizar a qualquer momento."}


def executar(modulo: dict, forcar: bool, usuario: str = "") -> dict:
    """Atualiza um menu, um de cada vez. Nunca levanta erro: devolve {"ok", "mensagem", ...}.
    'usuario' = quem clicou em Atualizar agora ('' = verificacao automatica): fica no historico e na mensagem de quem clicar junto."""
    inicio = time.time()
    quem = usuario or AUTOMATICA
    if modulo["tipo"] != "metas" and modulo["id"] in ERROS_MODULOS:
        msg = f"O menu {modulo['nome']} não carregou: {ERROS_MODULOS[modulo['id']]}"
        banco_dados.registrar_atualizacao(modulo["id"], "erro", msg, time.time() - inicio, usuario)
        return {"ok": False, "mensagem": msg}
    if forcar and usuario:
        bloqueio = _bloqueio_manual(modulo, usuario)
        if bloqueio:
            return bloqueio
    if TRAVA.locked():
        return _em_andamento()

    def terminou(resultado: dict):
        if resultado.get("atualizou"):
            ULTIMA[modulo["id"]] = {"quem": quem, "quando": time.time()}
            if usuario:
                print(f">>> {usuario} atualizou {modulo['nome']}: {resultado.get('mensagem', '')}", flush=True)

    if modulo["tipo"] == "metas":
        ATUAL.update(modulo=modulo["id"], quem=quem, inicio=inicio)
        try:
            res = sp.executar(forcar=forcar)
        finally:
            if ATUAL["modulo"] == modulo["id"]:
                ATUAL.update(modulo=None, quem="", inicio=0.0)
        terminou(res)
        banco_dados.registrar_atualizacao(modulo["id"], "sucesso" if res.get("ok", True) else "aviso", res.get("mensagem", ""), time.time() - inicio, usuario)
        return res
    est, codigo = ESTADOS[modulo["id"]], CODIGOS[modulo["id"]]
    if not TRAVA.acquire(blocking=False):
        return _em_andamento()
    est["atualizando"] = True
    ATUAL.update(modulo=modulo["id"], quem=quem, inicio=inicio)
    try:
        resultado = codigo.atualizar(forcar=forcar)
        est["aviso"] = None
        terminou(resultado)
        banco_dados.registrar_atualizacao(modulo["id"], "sucesso", resultado.get("mensagem", "Atualizado com sucesso"), time.time() - inicio, usuario)
        return {"ok": True, **resultado}
    except sp.ex.TokenInvalido as e:   # token ausente ou recusado: fica o aviso na tela ate alguem corrigir
        est["aviso"] = str(e)
        banco_dados.registrar_atualizacao(modulo["id"], "token_invalido", str(e), time.time() - inicio, usuario)
        return {"ok": False, "mensagem": str(e)}
    except Exception as e:  # inclui PlanilhaEmUso, rede fora do ar, resposta fora do formato
        print(f">>> ERRO ({modulo['nome']}):", e, flush=True)
        banco_dados.registrar_atualizacao(modulo["id"], "erro", str(e), time.time() - inicio, usuario)
        return {"ok": False, "mensagem": f"Não consegui atualizar: {e}"}
    finally:
        est["atualizando"] = False
        ATUAL.update(modulo=None, quem="", inicio=0.0)
        TRAVA.release()


def verificacao_automatica(minutos: float, primeira_agora: bool = True):
    """Confere todos os paineis em sequencia (so consulta o Klingo se os dados estiverem velhos)."""
    primeira = primeira_agora
    while True:
        if not primeira:
            time.sleep(minutos * 60)
        primeira = False
        for m in ler_modulos()["modulos"]:
            if m["tipo"] in ("metas", "relatorios"):
                r = executar(m, forcar=False)
                print(f">>> Verificação automática ({m['nome']}): {r['mensagem']}", flush=True)


REDE_ESTADO: dict = {"ativa": False, "motivo": "ainda não iniciada"}   # o que o /estado local conta ao lancador sobre o acesso pela rede
ANFITRIOES = rede.Anfitrioes(REDE_CFG["nomes_aceitos"])   # nomes/enderecos pelos quais a rede pode chamar este servidor (cabecalho Host)
MAX_CORPO = 1_000_000                                       # nenhum pedido do portal tem mais de 1 MB: barra quem manda lixo para encher a memoria
CABECALHOS_SEGURANCA = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "SAMEORIGIN"),        # o portal mostra cada menu num iframe do proprio portal; ninguem mais pode embutir
    ("Referrer-Policy", "no-referrer"),
]


def _limpo(texto, limite: int = 80) -> str:
    """Texto digitado por alguem, seguro para o log (sem quebra de linha nem caractere de controle)."""
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(texto))[:limite]


class Portal(sp.Painel):
    timeout = 120   # segundos sem ler/escrever no soquete: conexao parada nao fica presa para sempre (a atualizacao, que demora, nao usa o soquete)

    def setup(self):
        if self.server.e_rede:
            self.request.settimeout(10)    # aperto de mao TLS, aqui na thread da conexao e com prazo
            self.request.do_handshake()
        super().setup()

    @property
    def _rede(self) -> bool:
        return self.server.e_rede

    def _ip(self) -> str:
        return self.client_address[0]

    def _nome_cookie(self) -> str:
        return auth.COOKIE_REDE if self._rede else auth.COOKIE

    def _auditar(self, texto: str):
        print(f">>> [{self._ip()}] {texto}", flush=True)

    def _erro_interno(self, e: Exception):
        print(f">>> ERRO interno em {_limpo(self.path.split('?')[0])}: {type(e).__name__}: {e}", flush=True)
        self._json(500, {"ok": False, "mensagem": "Erro interno." if self._rede else f"Erro interno: {e}"})

    def _liberado(self) -> bool:
        """Pela rede, so atende quem chama o servidor pelo nome/endereco dele (barra DNS rebinding)."""
        if self._rede and not ANFITRIOES.aceita(self.headers.get("Host", "")):
            self._enviar(421, "Endereço não reconhecido por este servidor.".encode("utf-8"), "text/plain; charset=utf-8")
            return False
        return True

    def _enviar(self, codigo: int, corpo: bytes, tipo: str, cabecalhos: list[tuple[str, str]] | None = None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in CABECALHOS_SEGURANCA:
            self.send_header(k, v)
        if cabecalhos:
            for k, v in cabecalhos:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, codigo: int, obj: dict, cabecalhos: list[tuple[str, str]] | None = None):
        self._enviar(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", cabecalhos=cabecalhos)

    def _redirecionar(self, destino: str, cabecalhos: list[tuple[str, str]] | None = None):
        self.send_response(302)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for k, v in CABECALHOS_SEGURANCA:
            self.send_header(k, v)
        if cabecalhos:
            for k, v in cabecalhos:
                self.send_header(k, v)
        self.end_headers()

    def _ler_json(self) -> dict:
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
            if not tamanho or tamanho > MAX_CORPO:
                return {}
            return json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except Exception:
            return {}

    def _usuario(self) -> str | None:
        return auth.usuario_da_sessao(self.headers.get("Cookie"), self._nome_cookie())

    def _painel_valido(self, usuario: str, painel: str) -> bool:
        """O painel existe no portal (e e de relatorios) e o usuario tem acesso a ele."""
        return any(m["id"] == painel and m["tipo"] == "relatorios" for m in ler_modulos()["modulos"]) and auth.tem_permissao(usuario, painel)

    def _modulo(self, caminho: str):
        """('/metas/estado') -> (modulo, '/estado'); (modulo, None) se faltou a barra final; (None, None) se nao for de um modulo."""
        partes = caminho.split("/", 2)  # ['', 'metas', 'estado']
        for m in ler_modulos()["modulos"]:
            if len(partes) >= 2 and partes[1] == m["id"]:
                return m, ("/" + partes[2] if len(partes) > 2 else None)
        return None, None

    def _pagina_portal(self, usuario: str) -> bytes:
        cfg = ler_modulos()
        e_admin = auth.eh_admin(usuario)
        permitidos = auth.modulos_permitidos(usuario, cfg["modulos"])
        dados = {
            "titulo": cfg["titulo"],
            "usuario": usuario,
            "e_admin": e_admin,
            "trocar_senha": auth.senha_padrao_em_uso(usuario),
            "modulos": [{**{k: m.get(k) for k in ("id", "nome", "descricao")}, "visoes": _visoes_pdf(m)} for m in permitidos],
            "todos_modulos": [{k: m.get(k) for k in ("id", "nome", "descricao")} for m in cfg["modulos"]] if e_admin else []
        }
        json_txt = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
        return PAGINA.read_text(encoding="utf-8").replace("__DADOS__", json_txt).encode("utf-8")

    def _arquivo(self, modulo: dict, resto: str):
        pasta = (RAIZ / modulo["pasta"]).resolve()
        alvo = (pasta / (unquote(resto).lstrip("/") or "index.html")).resolve()
        if not alvo.is_relative_to(pasta) or not alvo.is_file():  # barra "../" para fora da pasta do modulo
            return self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        if tipo.startswith("text/"):
            tipo += "; charset=utf-8"
        self._enviar(200, alvo.read_bytes(), tipo)

    def _metas_pagina(self, periodo: tuple[str, str] | None = None):
        """Pagina de Metas: refeita se a planilha, as metas ou o dia mudaram, ou se a copia tem mais de 1 min (o 'esperado ate agora' depende da hora).
        Com `periodo` (varios meses), a pagina e calculada para ele e guardada em memoria pelo mesmo criterio."""
        try:
            if periodo:
                return self._enviar(200, metas_do_periodo(*periodo), "text/html; charset=utf-8")
            chave = (_mtime(sp.ex.PLANILHA), _mtime(sp.gd.METAS), date.today().isoformat())
            with META["trava"]:
                velha = time.time() - META["quando"] > 60
                if (META["chave"] != chave or velha or not sp.gd.SAIDA.exists()) and (not sp.ESTADO["atualizando"] or not sp.gd.SAIDA.exists()):
                    sp.gd.gerar()
                    META.update(chave=chave, quando=time.time())
            self._enviar(200, sp.gd.SAIDA.read_bytes(), "text/html; charset=utf-8")
        except Exception as e:
            self._enviar(500, f"Não consegui montar o painel: {e}".encode("utf-8"), "text/plain; charset=utf-8")

    def _relatorios_get(self, modulo: dict, resto: str):
        if modulo["id"] in ERROS_MODULOS:
            return self._enviar(500, f"O menu {modulo['nome']} não carregou: {ERROS_MODULOS[modulo['id']]}".encode("utf-8"), "text/plain; charset=utf-8")
        est, codigo = ESTADOS[modulo["id"]], CODIGOS[modulo["id"]]
        if resto in ("/", "/index.html"):
            try:
                periodo = periodo_da_url(urlsplit(self.path).query)   # ?de=AAAA-MM&ate=AAAA-MM com varios meses
                if periodo and (not est["atualizando"] or not codigo.SAIDA.exists()):
                    return self._enviar(200, pagina_do_periodo(modulo["id"], *periodo), "text/html; charset=utf-8")
                if not est["atualizando"] or not codigo.SAIDA.exists():  # durante a gravacao, serve a ultima versao pronta
                    pagina_pronta(modulo["id"])
                return self._enviar(200, codigo.SAIDA.read_bytes(), "text/html; charset=utf-8")
            except Exception as e:
                return self._enviar(500, f"Não consegui montar o painel: {e}".encode("utf-8"), "text/plain; charset=utf-8")
        if resto == "/estado":
            arq = codigo.arquivo_dados()
            return self._json(200, {"versao": int(arq.stat().st_mtime) if arq.exists() else 0,
                                    "atualizando": est["atualizando"], "aviso": est["aviso"]})
        self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain; charset=utf-8")

    def _gerar_pdf(self):
        usuario = self._usuario()
        if not usuario:
            return self._json(401, {"ok": False, "mensagem": "Sessão expirada. Entre novamente."})
        if not TRAVA_PDF.acquire(blocking=False):
            return self._json(409, {"ok": False, "mensagem": "A geração de PDF já está em andamento. Aguarde alguns instantes."})
        try:
            if exportar_pdf is None:
                return self._json(500, {"ok": False, "mensagem": f"Falta o pacote 'pypdf' para gerar o PDF. Rode:  python -m pip install pypdf  ({ERRO_PDF})"})
            cfg = ler_modulos()
            modulos_usuario = [m for m in auth.modulos_permitidos(usuario, cfg["modulos"]) if m["id"] not in ERROS_MODULOS]
            if not modulos_usuario:
                return self._json(403, {"ok": False, "mensagem": "Nenhum relatório liberado para este usuário exportar."})
            # Corpo opcional: {"itens": [{"modulo": "atendimento", "visao": "carla"}, ...]}; sem ele, sai tudo (como sempre foi)
            corpo = self._ler_json()
            pedidos = corpo.get("itens")
            de, ate = str(corpo.get("de") or ""), str(corpo.get("ate") or "")   # periodo do relatorio (meses AAAA-MM); sem ele, o mes mais recente de cada painel
            if de or ate:
                if not (PADRAO_MES.match(de) and PADRAO_MES.match(ate)):
                    return self._json(400, {"ok": False, "mensagem": "Período inválido: escolha o mês inicial e o final."})
                de, ate = min(de, ate), max(de, ate)
            itens, nomes = None, []
            if isinstance(pedidos, list):
                por_id = {m["id"]: m for m in modulos_usuario}
                itens = []
                for p in pedidos:
                    m = por_id.get(str(p.get("modulo", ""))) if isinstance(p, dict) else None
                    visao = str(p.get("visao") or "").strip().lower() if isinstance(p, dict) else ""
                    if m is None or (visao and visao not in (m.get("visoes_pdf") or [])):
                        return self._json(400, {"ok": False, "mensagem": "Pedido de exportação inválido: relatório ou responsável desconhecido (ou sem permissão)."})
                    if (m, visao) not in itens:
                        itens.append((m, visao))
                        nomes.append(m["id"] + (f"-{visao}" if visao else ""))
                if not itens:
                    return self._json(400, {"ok": False, "mensagem": "Escolha ao menos um relatório para exportar."})
            # o Chrome do PDF sempre visita o servidor LOCAL (http://127.0.0.1), mesmo quando o pedido veio pela rede: com a sessao de quem pediu
            base = f"http://{HOST}:{PORTA}"
            token = auth.token_do_pedido(self.headers.get("Cookie"), self._nome_cookie()) or ""
            self._auditar(f"{usuario} pediu a exportação em PDF" + (f" (período {de} a {ate})." if de else "."))
            if de and de != ate:   # varios meses: calcula as paginas de todos os paineis ao mesmo tempo antes de o Chrome abrir cada uma
                preparar_periodo([m["id"] for m, _ in (itens if itens is not None else exportar_pdf.plano_completo(modulos_usuario))], de, ate)
            pdf_bytes, avisos = exportar_pdf.exportar(
                modulos_usuario,
                base=base,
                token=token,
                titulo=cfg["titulo"],
                cookie=auth.COOKIE,
                itens=itens,
                de=de or None, ate=ate or None
            )
            data_str = datetime.now().strftime("%Y%m%d_%H%M")
            sufixo = f"_{nomes[0]}" if len(nomes) == 1 else (f"_{len(nomes)}_relatorios" if nomes else "")
            periodo_txt = f"_{de.replace('-', '')}" + (f"_a_{ate.replace('-', '')}" if ate != de else "") if de else ""
            nome_arquivo = f"Relatorios_CSI{sufixo}{periodo_txt}_{data_str}.pdf"
            cabecalhos = [
                ("Content-Disposition", f'attachment; filename="{nome_arquivo}"'),
                ("X-Avisos", quote(" | ".join(avisos))),   # paineis que ficaram de fora (o portal mostra ao usuario)
            ]
            self._enviar(200, pdf_bytes, "application/pdf", cabecalhos=cabecalhos)
        except Exception as e:
            print(f">>> ERRO ao exportar PDF: {e}", flush=True)
            self._json(500, {"ok": False, "mensagem": f"Não foi possível gerar o PDF: {e}"})
        finally:
            TRAVA_PDF.release()

    def do_GET(self):
        if not self._liberado():
            return
        caminho = self.path.split("?")[0]

        # 1. Rota de estado do servidor (usada pelo iniciar_portal.py para saber se o portal subiu). Pela rede, sem nenhum detalhe
        #    (caminhos, banco...): so serve para o cliente saber que o portal esta de pe.
        if caminho == "/estado":
            if self._rede:
                return self._json(200, {"portal": True})
            return self._json(200, {"portal": True, "pid": os.getpid(), "raiz": str(RAIZ), "banco": str(banco_dados.obter_caminho_banco()),
                                    "banco_ok": banco_dados.situacao(testar=False)["ok"], "rede": REDE_ESTADO})

        # 2. Favicon / icone
        if caminho in ("/portal_csi.ico", "/favicon.ico"):
            ico = RAIZ / "portal_csi.ico"
            if ico.exists():
                return self._enviar(200, ico.read_bytes(), "image/x-icon")
            return self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain; charset=utf-8")

        # 3. Pagina de login
        if caminho == "/login":
            if self._usuario():
                return self._redirecionar("/")
            cfg = ler_modulos()
            dados = {"titulo": cfg["titulo"], "primeiro_acesso": not auth.tem_usuarios()}
            json_txt = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
            corpo = (RAIZ / "login.html").read_text(encoding="utf-8").replace("__DADOS__", json_txt).encode("utf-8")
            return self._enviar(200, corpo, "text/html; charset=utf-8")

        # 4. Sair (logout)
        if caminho == "/sair":
            token = auth.token_do_pedido(self.headers.get("Cookie"), self._nome_cookie())
            auth.encerrar_sessao(token)
            return self._redirecionar("/login", cabecalhos=[("Set-Cookie", auth.cookie_de_saida(self._nome_cookie(), self._rede))])

        # 5. Conferir sessao ativa
        usuario = self._usuario()
        if not usuario:
            if caminho in ("/", "/index.html") or not ("." in caminho.split("/")[-1] and not caminho.endswith(".html")):
                return self._redirecionar("/login")
            return self._enviar(401, "Não autorizado".encode("utf-8"), "text/plain; charset=utf-8")

        # 6. Portal principal autenticado
        if caminho in ("/", "/index.html"):
            return self._enviar(200, self._pagina_portal(usuario), "text/html; charset=utf-8")

        # 7. Listar usuarios e permissoes (apenas administradores recebem detalhes)
        if caminho == "/conta/usuarios":
            e_admin = auth.eh_admin(usuario)
            cfg = ler_modulos()
            modulos_info = [{k: m.get(k) for k in ("id", "nome", "descricao")} for m in cfg["modulos"]]
            if e_admin:
                try:
                    pedidos = auth.listar_pedidos()
                except auth.ErroConta:
                    pedidos = []
                return self._json(200, {
                    "ok": True,
                    "atual": usuario,
                    "e_admin": True,
                    "usuarios": auth.listar_detalhes(),
                    "pedidos": pedidos,
                    "modulos": modulos_info
                })
            return self._json(200, {
                "ok": True,
                "atual": usuario,
                "e_admin": False,
                "usuarios": [],
                "modulos": []
            })

        # 8. Exportar PDF
        if caminho == "/exportar-pdf":
            return self._gerar_pdf()

        # 8a. Meses que o menu de exportacao oferece no filtro de periodo
        if caminho == "/periodos":
            meses = meses_do_portal()
            return self._json(200, {"ok": True, "padrao": meses[-1], "meses": [{"ym": m, "rotulo": pc.rotulo_mes(m)} for m in meses]})

        # 8b. Alertas que alguem marcou como resolvidos (?painel=faturamento)
        if caminho == "/pendencias":
            painel = parse_qs(urlsplit(self.path).query).get("painel", [""])[0]
            if not self._painel_valido(usuario, painel):
                return self._json(403, {"ok": False, "mensagem": "Painel inválido ou sem permissão."})
            try:
                return self._json(200, {"ok": True, "resolvidas": banco_dados.listar_pendencias(painel)})
            except Exception as e:
                return self._json(200, {"ok": False, "resolvidas": [], "mensagem": f"Não consegui ler as marcações: {e}"})

        # 9. Modulos do portal com validacao de permissao
        modulo, resto = self._modulo(caminho)
        if modulo is None:
            return self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain; charset=utf-8")
        if not auth.tem_permissao(usuario, modulo["id"]):
            return self._enviar(403, "Acesso restrito: você não tem permissão para visualizar este relatório.".encode("utf-8"), "text/plain; charset=utf-8")
        if resto is None:
            return self._redirecionar(f"/{modulo['id']}/")
        if modulo["tipo"] == "metas":
            if resto in ("/", "/index.html"):
                return self._metas_pagina(periodo_da_url(urlsplit(self.path).query))
            self.path = resto
            return super().do_GET()
        if modulo["tipo"] == "relatorios":
            return self._relatorios_get(modulo, resto)
        self._arquivo(modulo, resto)

    def do_POST(self):
        if not self._liberado():
            return
        caminho = self.path.split("?")[0]
        if self.headers.get("X-Painel") != "1":  # barra paginas de outros sites chamando o portal
            return self._enviar(403, b"Proibido", "text/plain")

        # Login normal
        if caminho == "/login":
            dados = {}
            try:
                dados = self._ler_json()
                nome = auth.entrar(dados.get("usuario", ""), dados.get("senha", ""), ip=self._ip(), rede=self._rede)
                token = auth.abrir_sessao(nome)
                self._auditar(f"Entrou: {_limpo(nome)}")
                return self._json(200, {"ok": True, "usuario": nome},
                                  cabecalhos=[("Set-Cookie", auth.cookie_de_entrada(token, self._nome_cookie(), self._rede))])
            except auth.ErroConta as e:
                self._auditar(f"Login recusado para '{_limpo(dados.get('usuario', ''))}': {e}")
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Criar primeiro usuario
        if caminho == "/login/criar":
            try:
                dados = self._ler_json()
                nome = auth.criar_primeiro(dados.get("usuario", ""), dados.get("senha", ""))
                token = auth.abrir_sessao(nome)
                self._auditar(f"Primeiro usuário criado: {_limpo(nome)}")
                return self._json(200, {"ok": True, "usuario": nome},
                                  cabecalhos=[("Set-Cookie", auth.cookie_de_entrada(token, self._nome_cookie(), self._rede))])
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Pedido de cadastro (tela de login, sem estar logado): so registra o pedido, quem libera e o administrador
        if caminho == "/login/solicitar":
            try:
                dados = self._ler_json()
                auth.solicitar_cadastro(dados.get("usuario", ""), dados.get("senha", ""), dados.get("mensagem", ""), ip=self._ip())
                self._auditar(f"Pedido de cadastro de '{_limpo(dados.get('usuario', ''))}'.")
                return self._json(200, {"ok": True, "mensagem": "Pedido enviado! Avise o administrador: você poderá entrar assim que ele aprovar."})
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Requer autenticacao para os demais POSTs
        usuario = self._usuario()
        if not usuario:
            return self._json(401, {"ok": False, "mensagem": "Sessão expirada. Entre novamente."})

        # Sair via POST
        if caminho == "/sair":
            token = auth.token_do_pedido(self.headers.get("Cookie"), self._nome_cookie())
            auth.encerrar_sessao(token)
            return self._json(200, {"ok": True}, cabecalhos=[("Set-Cookie", auth.cookie_de_saida(self._nome_cookie(), self._rede))])

        # Troca da propria senha (qualquer usuario autenticado)
        if caminho == "/conta/trocar-senha":
            try:
                dados = self._ler_json()
                auth.trocar_senha(usuario, dados.get("atual", ""), dados.get("nova", ""),
                                  manter=auth.token_do_pedido(self.headers.get("Cookie"), self._nome_cookie()))
                self._auditar(f"{_limpo(usuario)} trocou a própria senha (as outras sessões dele foram encerradas).")
                return self._json(200, {"ok": True, "mensagem": "Senha alterada com sucesso!"})
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Cadastrar novo usuario (apenas administrador)
        if caminho == "/conta/adicionar-usuario":
            if not auth.eh_admin(usuario):
                return self._json(403, {"ok": False, "mensagem": "Apenas administradores podem cadastrar novos usuários."})
            try:
                dados = self._ler_json()
                auth.adicionar(
                    dados.get("usuario", ""),
                    dados.get("senha", ""),
                    admin=bool(dados.get("admin", False)),
                    relatorios=dados.get("relatorios")
                )
                self._auditar(f"{_limpo(usuario)} cadastrou o usuário '{_limpo(dados.get('usuario'))}'" + (" (administrador)." if dados.get("admin") else "."))
                return self._json(200, {"ok": True, "mensagem": f"Usuário '{dados.get('usuario')}' cadastrado com sucesso!"})
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Editar permissoes / relatorios do usuario (apenas administrador)
        if caminho == "/conta/editar-usuario":
            if not auth.eh_admin(usuario):
                return self._json(403, {"ok": False, "mensagem": "Apenas administradores podem editar usuários."})
            try:
                dados = self._ler_json()
                auth.editar(
                    nome=dados.get("usuario", ""),
                    admin=dados.get("admin"),
                    relatorios=dados.get("relatorios"),
                    nova_senha=dados.get("nova_senha") or None,
                    quem_pede=usuario
                )
                self._auditar(f"{_limpo(usuario)} alterou o usuário '{_limpo(dados.get('usuario'))}'" + (" (com nova senha)." if dados.get("nova_senha") else "."))
                return self._json(200, {"ok": True, "mensagem": f"Permissões de '{dados.get('usuario')}' atualizadas com sucesso!"})
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Aprovar / recusar pedido de cadastro (apenas administrador)
        if caminho in ("/conta/aprovar-pedido", "/conta/recusar-pedido"):
            if not auth.eh_admin(usuario):
                return self._json(403, {"ok": False, "mensagem": "Apenas administradores podem responder pedidos de cadastro."})
            try:
                dados = self._ler_json()
                nome = dados.get("usuario", "")
                if caminho.endswith("/aprovar-pedido"):
                    auth.aprovar_pedido(nome, admin=bool(dados.get("admin", False)), relatorios=dados.get("relatorios"))
                    self._auditar(f"{_limpo(usuario)} aprovou o pedido de '{_limpo(nome)}'.")
                    return self._json(200, {"ok": True, "mensagem": f"'{nome}' aprovado. Já pode entrar com a senha que escolheu."})
                auth.recusar_pedido(nome)
                self._auditar(f"{_limpo(usuario)} recusou o pedido de '{_limpo(nome)}'.")
                return self._json(200, {"ok": True, "mensagem": f"Pedido de '{nome}' recusado."})
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Remover usuario (apenas administrador)
        if caminho == "/conta/remover-usuario":
            if not auth.eh_admin(usuario):
                return self._json(403, {"ok": False, "mensagem": "Apenas administradores podem remover usuários."})
            try:
                dados = self._ler_json()
                auth.remover(dados.get("usuario", ""), usuario)
                self._auditar(f"{_limpo(usuario)} removeu o usuário '{_limpo(dados.get('usuario'))}'.")
                return self._json(200, {"ok": True, "mensagem": "Usuário removido com sucesso."})
            except auth.ErroConta as e:
                return self._json(200, {"ok": False, "mensagem": str(e)})
            except Exception as e:
                return self._erro_interno(e)

        # Exportar PDF via POST
        if caminho == "/exportar-pdf":
            return self._gerar_pdf()

        # Marcar um alerta como resolvido / reabrir (qualquer usuario com acesso ao painel)
        if caminho in ("/pendencias/resolver", "/pendencias/reabrir"):
            dados = self._ler_json()
            painel, chave = str(dados.get("painel", "")), str(dados.get("chave", ""))[:200]
            if not self._painel_valido(usuario, painel) or not chave:
                return self._json(403, {"ok": False, "mensagem": "Painel inválido ou sem permissão."})
            try:
                if caminho.endswith("/resolver"):
                    banco_dados.marcar_pendencia(painel, chave, str(dados.get("titulo", ""))[:300], usuario, int(dados.get("versao") or 0))
                else:
                    banco_dados.desmarcar_pendencia(painel, chave)
                return self._json(200, {"ok": True, "resolvidas": banco_dados.listar_pendencias(painel)})
            except Exception as e:
                return self._json(200, {"ok": False, "mensagem": f"Não consegui gravar (o banco de dados está acessível?): {e}"})

        # Atualizar modulo
        modulo, resto = self._modulo(caminho)
        if modulo is None or resto != "/atualizar" or modulo["tipo"] not in ("metas", "relatorios"):
            return self._enviar(404, "Não encontrado".encode("utf-8"), "text/plain; charset=utf-8")
        if not auth.tem_permissao(usuario, modulo["id"]):
            return self._json(403, {"ok": False, "mensagem": "Você não tem permissão para este relatório."})
        self._auditar(f"{_limpo(usuario)} clicou em Atualizar agora ({modulo['nome']}).")
        resposta = executar(modulo, forcar=True, usuario=usuario)
        if self._rede and not auth.eh_admin(usuario):   # quem nao e administrador nao precisa ver pastas do computador do servidor
            resposta = {**resposta, "mensagem": re.sub(r"[A-Za-z]:\\[^\s\"']+", "(pasta do servidor)", str(resposta.get("mensagem", "")))}
        self._json(200, resposta)


def _publicar_endereco(publicacao: dict):
    """Grava o servidor.json (endereco + impressao digital) onde os clientes o leem. Em segundo plano: uma pasta de rede fora do ar
    nao pode atrasar a abertura do portal."""
    pastas = [RAIZ / rede.PASTA_SEGURANCA]
    if os.environ.get("PORTAL_CSI_PUBLICAR"):                 # a pasta "Compartilhar", ao lado do .exe do servidor (o lancador informa)
        pastas.append(Path(os.environ["PORTAL_CSI_PUBLICAR"]))
    extra = REDE_CFG["pasta_compartilhada"]
    if extra:
        if Path(extra).is_dir():
            pastas.append(Path(extra))
        else:
            print(f">>> AVISO: a pasta compartilhada de rede.json não existe ou está fora do ar: {extra}", flush=True)
    for pasta, erro in rede.publicar(publicacao, pastas):
        if erro:
            print(f">>> AVISO: não consegui gravar o endereço do servidor em {pasta}: {erro}", flush=True)
        elif pasta != pastas[0]:
            print(f">>> Endereço do servidor publicado para os clientes em {pasta}", flush=True)


def iniciar_rede():
    """Sobe o servidor HTTPS da rede (se o rede.json deixar) e publica o endereco para os clientes. Nunca derruba o portal:
    se nao der, so o acesso neste computador continua e o motivo aparece no log e no /estado local."""
    cfg = REDE_CFG
    for aviso in cfg["_avisos"]:
        print(f">>> AVISO (rede.json): {aviso}", flush=True)
    REDE_ESTADO.clear()
    REDE_ESTADO.update(ativa=False, motivo="")
    if not cfg["ativar_rede"]:
        REDE_ESTADO["motivo"] = 'desligado em rede.json ("ativar_rede": false)'
    elif cfg["porta_rede"] == PORTA:
        REDE_ESTADO["motivo"] = f'"porta_rede" de rede.json não pode ser igual à porta local ({PORTA})'
    else:
        try:
            cert, chave, impressao, criou = rede.garantir_certificado(RAIZ)
            contexto = rede.contexto_tls(cert, chave)
        except Exception as e:
            REDE_ESTADO["motivo"] = f"não consegui preparar o certificado de segurança ({type(e).__name__}: {e})"
        else:
            if criou:
                print(">>> Gerei o certificado de segurança deste servidor (vale 10 anos). Os clientes recebem a impressão digital dele pelo servidor.json.", flush=True)
            try:
                servidor = ServidorRede(("0.0.0.0", cfg["porta_rede"]), Portal, contexto, cfg["_redes"])
            except OSError as e:
                REDE_ESTADO["motivo"] = f"não consegui abrir a porta {cfg['porta_rede']} ({e}). Se outro programa a usa, troque \"porta_rede\" em rede.json"
            else:
                threading.Thread(target=servidor.serve_forever, daemon=True, name="servidor-rede").start()
                publicacao = rede.montar_publicacao(cfg, impressao, ler_modulos().get("titulo", ""))
                threading.Thread(target=_publicar_endereco, args=(publicacao,), daemon=True).start()
                REDE_ESTADO.update(ativa=True, porta=cfg["porta_rede"], nomes=publicacao["nomes"], ips=publicacao["ips"],
                                   url=f"https://{publicacao['nomes'][0]}:{cfg['porta_rede']}", impressao_digital=impressao,
                                   firewall=rede.regra_firewall(cfg["porta_rede"]), redes=[str(r) for r in cfg["_redes"]],
                                   intervalo_atualizar_minutos=cfg["intervalo_minimo_atualizar_agora_minutos"])
                print(f">>> Rede: https://{publicacao['nomes'][0]}:{cfg['porta_rede']}  (HTTPS, só as redes {', '.join(REDE_ESTADO['redes'])}, com login). "
                      f"Impressão digital: {rede.formatar_impressao(impressao)}", flush=True)
                return servidor
    print(f">>> Rede: DESLIGADA — {REDE_ESTADO['motivo']}. O portal funciona só neste computador.", flush=True)
    return None


def quem_usa_a_porta() -> str:
    try:
        with urllib.request.urlopen(f"{URL_PORTAL}estado", timeout=3) as r:
            j = json.loads(r.read())
    except Exception:
        return "outro"
    return "portal" if j.get("portal") else "metas" if "versao" in j else "outro"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # acentos corretos no terminal do Windows
    try:
        servidor = ServidorExclusivo((HOST, PORTA), Portal)
    except OSError:
        quem = quem_usa_a_porta()
        if quem == "portal":
            print(f">>> O portal já está rodando em {URL_PORTAL}")
            if "--sem-abrir" not in sys.argv:
                webbrowser.open(URL_PORTAL)
        elif quem == "metas":
            print(">>> O painel de Metas avulso (servidor_painel.py) está aberto e usa a mesma porta. "
                  "Feche aquela janela e abra o portal de novo.")
        else:
            print(f">>> A porta {PORTA} está em uso por outro programa. Feche-o e tente de novo.")
        return

    sit = banco_dados.situacao()
    onde = "em outro computador" if sit["em_rede"] else "neste computador"
    if sit["ok"]:
        try:
            banco_dados.inicializar_banco()
            print(f">>> Banco de dados ({onde}): {sit['caminho']}", flush=True)
        except Exception as e:
            print(f">>> AVISO: o banco {sit['caminho']} abriu, mas não consegui prepará-lo ({e}).", flush=True)
    else:
        print(f">>> AVISO: banco de dados fora do ar ({onde}): {sit['caminho']} — {sit['erro']}. "
              f"O portal abre mesmo assim: o login usa a cópia local (usuarios.json) e o histórico não é gravado. "
              f"Alterar usuários só depois que o banco voltar.", flush=True)
    carregar_codigos()
    try:
        sp.gd.gerar()
    except Exception as e:  # ex.: planilha de Metas ainda nao existe: o portal abre e o botao "Atualizar agora" cria
        print(f">>> AVISO: não consegui gerar o painel de Metas agora ({e}). Os outros menus funcionam; use “Atualizar agora” em Metas.", flush=True)
    threading.Thread(target=preparar_paginas, daemon=True).start()
    minutos = sp.ex.ler_config().get("verificacao_automatica_minutos", 30)
    if minutos and minutos > 0:
        threading.Thread(target=verificacao_automatica, args=(minutos,), daemon=True).start()
    servidor_rede = iniciar_rede()   # so depois de tudo carregado: o primeiro colega a chegar nao pode pegar o portal pela metade
    print(f">>> Portal em {URL_PORTAL}  (confere o Klingo a cada {minutos} min; Ctrl+C para fechar)", flush=True)
    if "--sem-abrir" not in sys.argv:
        webbrowser.open(URL_PORTAL)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print(">>> Portal encerrado.")
    finally:
        if servidor_rede is not None:
            servidor_rede.server_close()


if __name__ == "__main__":
    main()
