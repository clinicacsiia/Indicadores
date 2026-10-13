"""Login do portal: usuarios, senhas, permissoes por relatorio e sessoes.

  - Os usuarios ficam no banco de dados (banco_dados.py; pode estar em outro computador, igual para todos) e o
    usuarios.json, ao lado do portal, e a copia local. A senha nunca e gravada: so o "hash" PBKDF2-SHA256, com um sal
    proprio de cada usuario.
  - Usuario mestre inicial: 'csi admin' com senha 'sci@123456' e acesso total (admin).
  - Cada usuario pode ser administrador ou ter permissoes especificas por relatorio.
  - A sessao fica so na memoria do portal: fechou o portal, pede a senha de novo. Sem uso por 8 horas, tambem expira.
  - Errou a senha 5 vezes seguidas: aquele usuario fica 1 minuto bloqueado (segura tentativas automaticas).
  - Pela REDE: o mesmo computador que errar a senha 12 vezes em 10 minutos fica 5 minutos sem poder tentar, e a senha
    padrao do 'csi admin' (que esta escrita no programa) nao entra de jeito nenhum: so no proprio servidor, para trocar.
  - A conferencia da senha (PBKDF2, lenta de proposito) roda FORA da trava global: quem tenta senhas nao atrasa os demais.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import deque
from datetime import date
from http.cookies import SimpleCookie
from pathlib import Path

try:
    import banco_dados
except Exception:
    banco_dados = None

PASTA = Path(os.environ.get("PORTAL_CSI_PASTA") or Path(__file__).parent)
ARQUIVO = PASTA / "usuarios.json"
COOKIE = "csi_sessao"             # cookie do acesso neste computador (127.0.0.1)
COOKIE_REDE = "csi_sessao_rede"   # cookie do acesso pela rede: nome diferente, para os dois nunca se atropelarem no mesmo navegador
ITERACOES = 240_000
MIN_SENHA, MIN_USUARIO, MAX_USUARIO = 6, 3, 40
VALIDADE_SESSAO = 8 * 3600
TENTATIVAS, BLOQUEIO = 5, 60
MAX_FALHAS_IP, JANELA_IP, BLOQUEIO_IP = 12, 600, 300     # erros de senha por computador: 12 em 10 min = 5 min sem tentar
MAX_PEDIDOS_IP, JANELA_PEDIDOS_IP = 3, 3600              # pedidos de cadastro por computador por hora

ADMIN_PADRAO = "csi admin"
SENHA_PADRAO = "sci@123456"

TRAVA = threading.Lock()
SESSOES: dict[str, dict] = {}     # token -> {"usuario", "expira", "validade"}
FALHAS: dict[str, list] = {}      # usuario (minusculo) -> [erros seguidos, bloqueado ate]
FALHAS_IP: dict[str, deque] = {}  # ip -> instantes dos erros de senha recentes
PEDIDOS_IP: dict[str, deque] = {} # ip -> instantes dos pedidos de cadastro recentes
BLOQUEADOS_IP: dict[str, float] = {}   # ip -> bloqueado ate


def _recentes(fila: deque, agora: float, janela: float) -> deque:
    while fila and agora - fila[0] > janela:
        fila.popleft()
    return fila


def _ip_bloqueado(ip: str, agora: float) -> int:
    """Segundos que faltam para este computador poder tentar de novo (0 = liberado). Chamar com TRAVA."""
    ate = BLOQUEADOS_IP.get(ip, 0.0)
    if ate > agora:
        return int(ate - agora) + 1
    BLOQUEADOS_IP.pop(ip, None)
    return 0


def _falha_do_ip(ip: str, agora: float):
    """Conta um erro de senha deste computador. Chamar com TRAVA."""
    if not ip:
        return
    fila = _recentes(FALHAS_IP.setdefault(ip, deque()), agora, JANELA_IP)
    fila.append(agora)
    if len(fila) >= MAX_FALHAS_IP:
        BLOQUEADOS_IP[ip] = agora + BLOQUEIO_IP
        fila.clear()
    if len(FALHAS_IP) > 2000:   # nao deixa a tabela crescer sem fim
        for k in [k for k, f in FALHAS_IP.items() if not f or agora - f[-1] > JANELA_IP]:
            FALHAS_IP.pop(k, None)


class ErroConta(Exception):
    """Problema que o usuario precisa ver (senha errada, usuario repetido...). A mensagem ja e para a tela."""


# ---------------------------------------------------------------- usuarios: banco (manda) + usuarios.json (copia local)
# O banco de dados e o mesmo para todos os computadores (ver banco_dados.py), entao e ele que manda. O usuarios.json fica
# como copia: serve para entrar se o banco estiver fora do ar e para semear um banco novo (vazio).
VALIDADE_CACHE = 5.0   # segundos: a lista e lida a cada pedido; sem isso cada clique iria ao banco (que pode estar em outro PC)
_CACHE_BANCO: dict = {"quando": 0.0, "usuarios": None}


def _do_banco() -> list[dict] | None:
    """Usuarios do banco (cache de poucos segundos). None se nao ha banco, esta fora do ar ou vazio."""
    if not banco_dados:
        return None
    agora = time.time()
    if _CACHE_BANCO["usuarios"] is not None and agora - _CACHE_BANCO["quando"] < VALIDADE_CACHE:
        return _CACHE_BANCO["usuarios"]
    usuarios = banco_dados.carregar_usuarios() or None
    _CACHE_BANCO.update(quando=agora, usuarios=usuarios)
    return usuarios


def _espelhar_no_json(usuarios: list[dict]):
    """Mantem o usuarios.json igual ao banco (so grava se mudou; pasta sem permissao de escrita e ignorada)."""
    novo = json.dumps({"usuarios": usuarios}, ensure_ascii=False, indent=2)
    try:
        if ARQUIVO.exists() and ARQUIVO.read_text(encoding="utf-8") == novo:
            return
        tmp = ARQUIVO.with_suffix(".tmp")
        tmp.write_text(novo, encoding="utf-8")
        os.replace(tmp, ARQUIVO)
    except OSError:
        pass


def _semear_banco(usuarios: list[dict]):
    """Banco novo (sem usuarios): copia para ele os usuarios do usuarios.json. Nunca sobrescreve um banco que ja tem usuarios."""
    if banco_dados and banco_dados.contar_usuarios() == 0:
        try:
            banco_dados.salvar_usuarios(usuarios)
            _CACHE_BANCO["usuarios"] = None
        except Exception:
            pass


def _ler() -> list[dict]:
    do_banco = _do_banco()
    if do_banco:
        _espelhar_no_json(do_banco)
        return do_banco
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8-sig"))
        usuarios = [u for u in dados.get("usuarios", []) if isinstance(u, dict) and u.get("usuario")]
        if not usuarios:
            usuarios = [_novo(ADMIN_PADRAO, SENHA_PADRAO, admin=True, relatorios=["*"])]
            _gravar(usuarios, estrito=False)
        else:
            _semear_banco(usuarios)
        return usuarios
    except FileNotFoundError:
        usuarios = [_novo(ADMIN_PADRAO, SENHA_PADRAO, admin=True, relatorios=["*"])]
        _gravar(usuarios, estrito=False)
        return usuarios
    except (OSError, ValueError) as e:
        raise ErroConta(f"Não consegui ler {ARQUIVO.name} ({e}). Corrija ou apague o arquivo para criar o acesso de novo.")


def _gravar(usuarios: list[dict], estrito: bool = True):
    """Grava no banco e no usuarios.json. 'estrito' (alteracoes feitas por um administrador): se o banco central esta fora
    do ar, recusa, porque a mudanca ficaria so neste computador e sumiria quando o banco voltasse."""
    if banco_dados:
        try:
            banco_dados.salvar_usuarios(usuarios)
        except banco_dados.BancoIndisponivel as e:
            if estrito:
                raise ErroConta(f"O banco de dados não está acessível agora ({banco_dados.obter_caminho_banco()}). "
                                f"Não dá para alterar usuários até ele voltar. Quem já tem acesso continua entrando.") from e
        except Exception:
            pass
        _CACHE_BANCO["usuarios"] = None
    tmp = ARQUIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps({"usuarios": usuarios}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ARQUIVO)


def _hash(senha: str, sal: bytes, iteracoes: int = ITERACOES) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes).hex()


def _chave(nome: str) -> str:
    return " ".join((nome or "").strip().casefold().split())


def _achar(usuarios: list[dict], nome: str) -> dict | None:
    chave = _chave(nome)
    # Busca exata (ignorando caixa e espacos extras)
    u = next((x for x in usuarios if _chave(x.get("usuario", "")) == chave), None)
    if u:
        return u
    # Se procurou por "admin" ou "csi" e nao ha usuario proprio com esse nome, mapeia para o admin padrao
    if chave in ("admin", "csi"):
        return next((x for x in usuarios if _chave(x.get("usuario", "")) == _chave(ADMIN_PADRAO)), None)
    return None


def _validar_nome(nome: str) -> str:
    nome = " ".join((nome or "").strip().split())
    if not MIN_USUARIO <= len(nome) <= MAX_USUARIO:
        raise ErroConta(f"O nome de usuário precisa ter de {MIN_USUARIO} a {MAX_USUARIO} caracteres.")
    if any(ord(c) < 32 for c in nome):
        raise ErroConta("O nome de usuário contém caracteres inválidos.")
    return nome


def _validar_senha(senha: str):
    if not isinstance(senha, str) or len(senha) < MIN_SENHA:
        raise ErroConta(f"A senha precisa ter pelo menos {MIN_SENHA} caracteres.")
    if len(senha) > 200:
        raise ErroConta("A senha é longa demais.")


def _novo(nome: str, senha: str, admin: bool = False, relatorios: list[str] | None = None) -> dict:
    sal = secrets.token_bytes(16)
    e_master = _chave(nome) == _chave(ADMIN_PADRAO)
    is_admin = True if e_master else bool(admin)
    rels = ["*"] if is_admin else (list(relatorios) if relatorios is not None else ["*"])
    return {
        "usuario": nome,
        "sal": sal.hex(),
        "iteracoes": ITERACOES,
        "hash": _hash(senha, sal),
        "criado_em": date.today().isoformat(),
        "admin": is_admin,
        "relatorios": rels
    }


def garantir_admin_padrao():
    with TRAVA:
        try:
            usuarios = _ler()
            if not _achar(usuarios, ADMIN_PADRAO):
                usuarios.insert(0, _novo(ADMIN_PADRAO, SENHA_PADRAO, admin=True, relatorios=["*"]))
                _gravar(usuarios)
        except Exception:
            pass


# ---------------------------------------------------------------- usuarios e permissoes
def tem_usuarios() -> bool:
    with TRAVA:
        return bool(_ler())


def listar() -> list[str]:
    with TRAVA:
        return sorted((u["usuario"] for u in _ler()), key=str.casefold)


def listar_detalhes() -> list[dict]:
    with TRAVA:
        usuarios = _ler()
        resultado = []
        for u in usuarios:
            e_master = _chave(u.get("usuario", "")) == _chave(ADMIN_PADRAO)
            is_admin = True if e_master else bool(u.get("admin", False))
            rels = ["*"] if is_admin else list(u.get("relatorios", []))
            resultado.append({
                "usuario": u.get("usuario", ""),
                "admin": is_admin,
                "master": e_master,
                "relatorios": rels,
                "criado_em": u.get("criado_em", "")
            })
        return sorted(resultado, key=lambda x: (not x["master"], not x["admin"], x["usuario"].casefold()))


def eh_admin(nome: str) -> bool:
    with TRAVA:
        u = _achar(_ler(), nome)
        if not u:
            return False
        if _chave(u.get("usuario", "")) == _chave(ADMIN_PADRAO):
            return True
        return bool(u.get("admin", False))


def relatorios_do_usuario(nome: str) -> list[str]:
    with TRAVA:
        u = _achar(_ler(), nome)
        if not u:
            return []
        if _chave(u.get("usuario", "")) == _chave(ADMIN_PADRAO) or u.get("admin"):
            return ["*"]
        return list(u.get("relatorios", []))


def tem_permissao(nome: str, relatorio_id: str) -> bool:
    with TRAVA:
        u = _achar(_ler(), nome)
        if not u:
            return False
        if _chave(u.get("usuario", "")) == _chave(ADMIN_PADRAO) or u.get("admin"):
            return True
        rels = u.get("relatorios", [])
        return "*" in rels or relatorio_id in rels


def modulos_permitidos(nome: str, modulos: list[dict]) -> list[dict]:
    with TRAVA:
        u = _achar(_ler(), nome)
        if not u:
            return []
        if _chave(u.get("usuario", "")) == _chave(ADMIN_PADRAO) or u.get("admin"):
            return modulos
        rels = set(u.get("relatorios", []))
        if "*" in rels:
            return modulos
        return [m for m in modulos if m.get("id") in rels]


def criar_primeiro(nome: str, senha: str) -> str:
    """Primeiro acesso: so funciona enquanto nao existe nenhum usuario."""
    with TRAVA:
        if _ler():
            raise ErroConta("Já existe um usuário cadastrado. Entre com ele.")
        nome = _validar_nome(nome)
        _validar_senha(senha)
        _gravar([_novo(nome, senha, admin=True, relatorios=["*"])])
        return nome


def adicionar(nome: str, senha: str, admin: bool = False, relatorios: list[str] | None = None):
    with TRAVA:
        usuarios = _ler()
        nome = _validar_nome(nome)
        _validar_senha(senha)
        if _achar(usuarios, nome):
            raise ErroConta("Já existe um usuário com esse nome.")
        usuarios.append(_novo(nome, senha, admin=admin, relatorios=relatorios))
        _gravar(usuarios)


def editar(nome: str, admin: bool | None = None, relatorios: list[str] | None = None, nova_senha: str | None = None, quem_pede: str = ""):
    with TRAVA:
        usuarios = _ler()
        u = _achar(usuarios, nome)
        if not u:
            raise ErroConta("Esse usuário não existe.")
        e_master = _chave(u.get("usuario", "")) == _chave(ADMIN_PADRAO)

        if e_master and admin is False:
            raise ErroConta("O administrador principal 'csi admin' não pode perder os privilégios de administrador.")

        if admin is not None:
            u["admin"] = True if e_master else bool(admin)

        if relatorios is not None:
            u["relatorios"] = ["*"] if (e_master or u.get("admin")) else list(relatorios)

        if nova_senha:
            _validar_senha(nova_senha)
            sal = secrets.token_bytes(16)
            u.update({
                "sal": sal.hex(),
                "iteracoes": ITERACOES,
                "hash": _hash(nova_senha, sal)
            })

        _gravar(usuarios)
        if nova_senha and _chave(u["usuario"]) != _chave(quem_pede):   # senha de OUTRA pessoa redefinida (talvez porque vazou): quem estava logado com a antiga cai
            _encerrar_sessoes_de(u["usuario"], None)


def _encerrar_sessoes_de(nome: str, manter: str | None = None):
    """Derruba as sessoes abertas deste usuario (menos a de 'manter'). Chamar com TRAVA."""
    for token in [t for t, s in SESSOES.items() if _chave(s["usuario"]) == _chave(nome) and t != manter]:
        SESSOES.pop(token, None)


def trocar_senha(nome: str, atual: str, nova: str, manter: str | None = None):
    """'manter' = token da sessao de quem esta trocando: continua entrando; qualquer outra sessao com a senha antiga cai."""
    with TRAVA:
        usuarios = _ler()
        u = _achar(usuarios, nome)
        if not u or not _confere(u, atual):
            raise ErroConta("A senha atual não confere.")
        _validar_senha(nova)
        sal = secrets.token_bytes(16)
        u.update({
            "sal": sal.hex(),
            "iteracoes": ITERACOES,
            "hash": _hash(nova, sal)
        })
        _gravar(usuarios)
        _encerrar_sessoes_de(u["usuario"], manter)


def remover(nome: str, quem_pede: str):
    with TRAVA:
        usuarios = _ler()
        if _chave(nome) == _chave(quem_pede):
            raise ErroConta("Você não pode remover o próprio usuário.")
        if _chave(nome) == _chave(ADMIN_PADRAO):
            raise ErroConta("O administrador principal 'csi admin' não pode ser removido.")
        restantes = [u for u in usuarios if _chave(u.get("usuario", "")) != _chave(nome)]
        if len(restantes) == len(usuarios):
            raise ErroConta("Esse usuário não existe.")
        _gravar(restantes)
    with TRAVA:
        for token in [t for t, s in SESSOES.items() if _chave(s["usuario"]) == _chave(nome)]:
            SESSOES.pop(token, None)


# ---------------------------------------------------------------- pedidos de cadastro
# Quem nao tem acesso pede um cadastro na tela de login; o pedido fica no banco (a senha ja em hash) e a pessoa so entra
# depois que um administrador aprova e escolhe os relatorios dela.
MAX_PEDIDOS = 50       # pedidos pendentes ao mesmo tempo (a tela de login e aberta: sem teto, qualquer um encheria o banco)
MAX_MENSAGEM = 200
ERRO_PEDIDO_BANCO = "Não consegui registrar o pedido agora (o banco de dados não está acessível). Tente de novo mais tarde."


def _pedidos() -> list[dict]:
    if not banco_dados:
        raise ErroConta(ERRO_PEDIDO_BANCO)
    try:
        return banco_dados.listar_solicitacoes()
    except Exception as e:
        raise ErroConta(ERRO_PEDIDO_BANCO) from e


def solicitar_cadastro(nome: str, senha: str, mensagem: str = "", ip: str = "") -> str:
    """Registra um pedido de cadastro. Nao cria acesso nenhum. A recusa por nome repetido nao diz se o nome e de um usuario ou de um pedido.
    'ip': o mesmo computador so pode pedir MAX_PEDIDOS_IP vezes por hora (a tela e aberta; sem isso um so encheria os 50 lugares)."""
    with TRAVA:
        nome = _validar_nome(nome)
        _validar_senha(senha)
        mensagem = " ".join((mensagem or "").split())[:MAX_MENSAGEM]
        if ip:
            agora = time.time()
            if len(_recentes(PEDIDOS_IP.setdefault(ip, deque()), agora, JANELA_PEDIDOS_IP)) >= MAX_PEDIDOS_IP:
                raise ErroConta("Este computador já enviou pedidos demais. Fale com o administrador para liberar o seu acesso.")
            PEDIDOS_IP[ip].append(agora)
        pedidos = _pedidos()
        if len(pedidos) >= MAX_PEDIDOS:
            raise ErroConta("Há pedidos demais aguardando o administrador. Fale com ele para liberar o seu acesso.")
        if _achar(_ler(), nome) or _chave(nome) in ("admin", "csi") or any(_chave(p["usuario"]) == _chave(nome) for p in pedidos):
            raise ErroConta("Esse nome de usuário não está disponível. Escolha outro.")
        sal = secrets.token_bytes(16)
        try:
            banco_dados.criar_solicitacao(nome, _hash(senha, sal), sal.hex(), ITERACOES, mensagem)
        except Exception as e:
            raise ErroConta(ERRO_PEDIDO_BANCO) from e
        return nome


def listar_pedidos() -> list[dict]:
    """Pedidos pendentes para a tela do administrador (sem senha/hash)."""
    with TRAVA:
        return [{"usuario": p["usuario"], "mensagem": p.get("mensagem") or "", "solicitado_em": p["solicitado_em"]} for p in _pedidos()]


def aprovar_pedido(nome: str, admin: bool = False, relatorios: list[str] | None = None):
    """Transforma o pedido em usuario, com o perfil escolhido pelo administrador. A senha e a que a pessoa digitou no pedido."""
    with TRAVA:
        pedido = next((p for p in _pedidos() if _chave(p["usuario"]) == _chave(nome)), None)
        if not pedido:
            raise ErroConta("Esse pedido não existe mais (outro administrador pode ter respondido).")
        usuarios = _ler()
        if _achar(usuarios, pedido["usuario"]):
            banco_dados.remover_solicitacao(pedido["usuario"])
            raise ErroConta("Já existe um usuário com esse nome. O pedido foi descartado.")
        usuarios.append({
            "usuario": pedido["usuario"], "sal": pedido["sal"], "iteracoes": pedido["iteracoes"], "hash": pedido["hash"],
            "criado_em": date.today().isoformat(), "admin": bool(admin),
            "relatorios": ["*"] if admin else list(relatorios or []),
        })
        _gravar(usuarios)
        banco_dados.remover_solicitacao(pedido["usuario"])


def recusar_pedido(nome: str):
    with TRAVA:
        pedido = next((p for p in _pedidos() if _chave(p["usuario"]) == _chave(nome)), None)
        if not pedido:
            raise ErroConta("Esse pedido não existe mais.")
        banco_dados.remover_solicitacao(pedido["usuario"])


def _confere(u: dict, senha: str) -> bool:
    try:
        esperado = _hash(senha or "", bytes.fromhex(u["sal"]), int(u.get("iteracoes", ITERACOES)))
    except (ValueError, KeyError, TypeError):
        return False
    return hmac.compare_digest(esperado, u.get("hash", ""))


def entrar(nome: str, senha: str, ip: str = "", rede: bool = False) -> str:
    """Confere usuario e senha e devolve o nome cadastrado (ErroConta se nao der).
    'ip' = computador que esta tentando (limita tentativas por computador); 'rede' = veio pela rede, e nao do proprio servidor."""
    nome_original = (nome or "").strip()
    chave = _chave(nome_original)
    with TRAVA:
        agora = time.time()
        restante = _ip_bloqueado(ip, agora) if ip else 0
        if restante:
            raise ErroConta(f"Muitas tentativas erradas deste computador. Aguarde {restante} segundos.")
        erros, ate = FALHAS.get(chave, [0, 0.0])
        if ate > agora:
            raise ErroConta(f"Muitas tentativas erradas. Aguarde {int(ate - agora) + 1} segundos.")
        u = _achar(_ler(), nome_original)
        u = dict(u) if u else None
    # a conferencia (PBKDF2, ~0,2 s) fica FORA da trava: quem tenta senhas nao atrasa os outros usuarios
    ok = _confere(u, senha) if u else (_hash(senha or "", b"\0" * 16) == "x")
    with TRAVA:
        if not ok:
            agora = time.time()
            erros, _ate = FALHAS.get(chave, [0, 0.0])
            erros += 1
            FALHAS[chave] = [0, agora + BLOQUEIO] if erros >= TENTATIVAS else [erros, 0.0]
            _falha_do_ip(ip, agora)
            raise ErroConta("Usuário ou senha incorretos.")
        FALHAS.pop(chave, None)
    if rede and senha == SENHA_PADRAO:
        raise ErroConta("A senha padrão não pode ser usada pela rede. Entre no computador do servidor (http://127.0.0.1:8765), "
                        "abra Conta › Minha Senha e troque a senha. Depois entre normalmente por aqui.")
    return u["usuario"]


# ---------------------------------------------------------------- sessoes
def abrir_sessao(usuario: str, validade: float = VALIDADE_SESSAO) -> str:
    token = secrets.token_urlsafe(32)
    with TRAVA:
        agora = time.time()
        for t in [t for t, s in SESSOES.items() if s["expira"] < agora]:
            SESSOES.pop(t, None)
        SESSOES[token] = {"usuario": usuario, "expira": agora + validade, "validade": validade}
    return token


def encerrar_sessao(token: str | None):
    with TRAVA:
        SESSOES.pop(token or "", None)


def token_do_pedido(cabecalho_cookie: str | None, nome: str = COOKIE) -> str | None:
    if not cabecalho_cookie:
        return None
    try:
        c = SimpleCookie(cabecalho_cookie)
    except Exception:
        return None
    return c[nome].value if nome in c else None


def usuario_da_sessao(cabecalho_cookie: str | None, nome: str = COOKIE) -> str | None:
    token = token_do_pedido(cabecalho_cookie, nome)
    if not token:
        return None
    with TRAVA:
        s = SESSOES.get(token)
        if not s or s["expira"] < time.time():
            SESSOES.pop(token, None)
            return None
        s["expira"] = time.time() + s["validade"]
        return s["usuario"]


def cookie_de_entrada(token: str, nome: str = COOKIE, seguro: bool = False) -> str:
    return f"{nome}={token}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if seguro else "")


def cookie_de_saida(nome: str = COOKIE, seguro: bool = False) -> str:
    return f"{nome}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if seguro else "")


_CACHE_PADRAO: dict[tuple[str, str], bool] = {}   # (usuario, hash da senha) -> ainda e a senha padrao?


def senha_padrao_em_uso(nome: str) -> bool:
    """True se este usuario ainda usa a senha padrao (que esta escrita no programa): o portal pede para trocar.
    Chamada a cada abertura do portal: o PBKDF2 (~0,2 s) nao pode rodar de novo toda vez nem segurar a trava global, senao 20 pessoas
    abrindo o portal juntas paravam o servidor inteiro. O resultado so muda se a senha mudar, e a senha mudar muda o hash (a chave)."""
    with TRAVA:
        u = _achar(_ler(), nome)
        u = dict(u) if u else None
    if not u:
        return False
    chave = (_chave(u["usuario"]), u.get("hash", ""))
    if chave not in _CACHE_PADRAO:
        resultado = _confere(u, SENHA_PADRAO)
        if len(_CACHE_PADRAO) > 500:
            _CACHE_PADRAO.clear()
        _CACHE_PADRAO[chave] = resultado
    return _CACHE_PADRAO[chave]


# Assegura que o administrador csi admin esteja pronto
garantir_admin_padrao()
