"""Banco de dados local (SQLite) do Indicadores CSI.

Armazena usuarios, permissoes, configuracoes gerais do sistema, historico
de execucoes/atualizacoes e cache de indicadores.

O local do banco, em ordem de prioridade:
  1. variavel de ambiente PORTAL_CSI_BANCO (o lancador a preenche com o conteudo de "banco.txt", ao lado do .exe);
  2. chave "banco_dados" do config.json (ou do modulos.json) da pasta do portal;
  3. portal_csi.db na pasta do portal.
O jeito recomendado de varios computadores usarem os mesmos dados NAO e dividir este arquivo pela rede: o SQLite nao e confiavel
em pasta compartilhada (travas de arquivo falham e o banco corrompe). Quem cuida do banco e o servidor (seguranca_rede.py,
servidor_portal.py), que roda so no computador do dono; os outros entram pelo cliente "Indicadores CSI.exe" e nunca tocam no arquivo.
Mesmo assim o banco continua sem WAL e, se o caminho configurado estiver fora do ar, o portal avisa e segue em vez de travar.
Um caminho configurado de proposito (variavel / banco.txt) NUNCA e criado do zero: se o arquivo nao existe, e erro, nao banco novo.
"""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

PASTA = Path(os.environ.get("PORTAL_CSI_PASTA") or Path(__file__).resolve().parent)
CONFIG_JSON = PASTA / "config.json"
MODULOS_JSON = PASTA / "modulos.json"
BANCO_PADRAO = "portal_csi.db"
LIMITE_HISTORICO = 5000
ESPERA_TESTE = 6.0       # segundos que esperamos o banco responder antes de considerar fora do ar
VALIDADE_OK, VALIDADE_FALHA = 30.0, 10.0   # quanto tempo vale o ultimo teste (falha e retestada logo)

_TRAVA_BANCO = threading.Lock()
_TRAVA_TESTE = threading.Lock()
_ULTIMO_TESTE: dict = {"quando": 0.0, "ok": False, "erro": "ainda nao testado", "caminho": ""}


class BancoIndisponivel(OSError):
    """O arquivo do banco nao pode ser aberto agora (maquina desligada, pasta sem permissao, rede fora do ar...)."""


def _caminho_de(valor) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(str(valor).strip().strip('"'))))
    return p if p.is_absolute() else (PASTA / p)


def _valor_no_json(arquivo: Path) -> str | None:
    if arquivo.exists():
        try:
            valor = json.loads(arquivo.read_text(encoding="utf-8-sig")).get("banco_dados")
            return valor or None
        except (OSError, ValueError, AttributeError):
            pass
    return None


def obter_caminho_banco() -> Path:
    """Caminho do banco de dados: variavel PORTAL_CSI_BANCO, depois config.json, depois modulos.json, depois o padrao."""
    valor = os.environ.get("PORTAL_CSI_BANCO") or _valor_no_json(CONFIG_JSON) or _valor_no_json(MODULOS_JSON)
    return _caminho_de(valor) if valor else PASTA / BANCO_PADRAO


def banco_em_rede(caminho: Path | None = None) -> bool:
    """True se o banco esta em outro computador (\\\\servidor\\pasta ou unidade de rede mapeada)."""
    caminho = caminho or obter_caminho_banco()
    texto = str(caminho)
    if texto.startswith("\\\\") or texto.startswith("//"):
        return True
    if os.name == "nt" and len(texto) > 1 and texto[1] == ":":
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(texto[:3]) == 4   # DRIVE_REMOTE
        except Exception:
            return False
    return False


def _testar_acesso(caminho: Path, resultado: dict):
    try:
        if not caminho.exists():
            if os.environ.get("PORTAL_CSI_BANCO"):
                # caminho escolhido de propósito (banco.txt / --banco): NUNCA criar um banco vazio no lugar do central
                resultado["erro"] = "o banco central não foi encontrado nesse caminho (computador desligado, pasta não compartilhada ou caminho errado)"
                return
            caminho.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(caminho), timeout=5.0)
        try:
            conn.execute("PRAGMA schema_version").fetchone()
        finally:
            conn.close()
        resultado["ok"] = True
    except Exception as e:
        resultado["erro"] = f"{type(e).__name__}: {e}"


def disponivel(forcar: bool = False) -> bool:
    """O banco responde agora? O teste roda numa thread com prazo (ESPERA_TESTE) para um caminho de rede fora do ar nao
    segurar o portal por minutos; o resultado vale por alguns segundos."""
    caminho = obter_caminho_banco()
    with _TRAVA_TESTE:
        u = _ULTIMO_TESTE
        mesmo_caminho = u["caminho"] == str(caminho)
        validade = VALIDADE_OK if u["ok"] else VALIDADE_FALHA
        if not forcar and mesmo_caminho and time.time() - u["quando"] < validade:
            return u["ok"]
        if not forcar and mesmo_caminho and not u["ok"]:
            # estava fora do ar: reconfere em segundo plano e responde "fora do ar" na hora, para cada clique no portal
            # nao esperar o prazo do teste enquanto o outro computador estiver desligado
            if not u.get("retestando"):
                u["retestando"] = True
                threading.Thread(target=_retestar_em_segundo_plano, args=(caminho,), daemon=True).start()
            return False
        _testar_com_prazo(caminho)
        return u["ok"]


def _testar_com_prazo(caminho: Path):
    resultado = {"ok": False, "erro": f"sem resposta em {ESPERA_TESTE:.0f}s (computador desligado ou rede fora do ar?)"}
    t = threading.Thread(target=_testar_acesso, args=(caminho, resultado), daemon=True)
    t.start()
    t.join(ESPERA_TESTE)
    _ULTIMO_TESTE.update(quando=time.time(), ok=bool(resultado["ok"]), erro="" if resultado["ok"] else resultado["erro"],
                         caminho=str(caminho), retestando=False)


def _retestar_em_segundo_plano(caminho: Path):
    try:
        _testar_com_prazo(caminho)
    finally:
        _ULTIMO_TESTE["retestando"] = False


def situacao(testar: bool = True) -> dict:
    """Onde esta o banco e se esta acessivel. testar=False so repete o ultimo teste (nunca espera: o /estado e consultado a
    cada 15 s pelo lancador e demorar para responder o faria achar que o portal travou)."""
    ok = disponivel() if testar else _ULTIMO_TESTE["ok"]
    caminho = obter_caminho_banco()
    return {"caminho": str(caminho), "em_rede": banco_em_rede(caminho), "ok": ok, "erro": _ULTIMO_TESTE["erro"]}


@contextmanager
def conectar():
    """Abre uma conexao com o banco SQLite; confirma (ou desfaz, se deu erro) e FECHA ao sair do 'with'.
    (O 'with' do proprio sqlite3 so confirma: sem fechar, o arquivo ficava preso no Windows.)
    Levanta BancoIndisponivel (rapido) se o arquivo nao responde."""
    caminho = obter_caminho_banco()
    if not disponivel():
        raise BancoIndisponivel(f"Banco de dados fora do ar: {caminho} ({_ULTIMO_TESTE['erro']})")
    conn = sqlite3.connect(str(caminho), timeout=30.0, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        try:
            # rollback journal (nao WAL): o WAL exige que todos usem o arquivo no MESMO computador e corrompe em pasta compartilhada
            conn.execute("PRAGMA journal_mode = DELETE")
        except sqlite3.OperationalError:
            pass   # alguem esta usando o banco agora; o modo e trocado na proxima vez
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def copiar_banco(destino: Path) -> bool:
    """Copia consistente do banco (inclui o que ainda esta no arquivo -wal), para o backup diario."""
    origem = obter_caminho_banco()
    if not disponivel() or not origem.exists():
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    with _TRAVA_BANCO:
        com = sqlite3.connect(str(origem), timeout=30.0)
        saida = sqlite3.connect(str(destino))
        try:
            com.backup(saida)
        finally:
            saida.close()
            com.close()
    return True


def criar_tabelas():
    """Cria a estrutura das tabelas no banco de dados local se ainda nao existirem."""
    with _TRAVA_BANCO:
        with conectar() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS configuracoes (
                    chave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    hash TEXT NOT NULL,
                    sal TEXT NOT NULL,
                    iteracoes INTEGER NOT NULL DEFAULT 240000,
                    admin INTEGER NOT NULL DEFAULT 0,
                    relatorios TEXT NOT NULL DEFAULT '["*"]',
                    criado_em TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS modulos (
                    id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    descricao TEXT,
                    pasta TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    codigo TEXT,
                    ativo INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS historico_atualizacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mensagem TEXT,
                    duracao_segundos REAL DEFAULT 0.0,
                    data_hora TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS indicadores_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo TEXT NOT NULL,
                    competencia TEXT,
                    chave TEXT NOT NULL,
                    valor REAL,
                    detalhes_json TEXT,
                    atualizado_em TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pendencias_resolvidas (
                    painel TEXT NOT NULL,
                    chave TEXT NOT NULL,
                    titulo TEXT,
                    usuario TEXT NOT NULL,
                    quando TEXT NOT NULL,
                    versao INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (painel, chave)
                );

                CREATE TABLE IF NOT EXISTS solicitacoes_cadastro (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    hash TEXT NOT NULL,
                    sal TEXT NOT NULL,
                    iteracoes INTEGER NOT NULL DEFAULT 240000,
                    mensagem TEXT,
                    solicitado_em TEXT NOT NULL
                );
            """)
            # banco criado antes do acesso em rede: o historico passa a dizer QUEM pediu a atualizacao
            if "usuario" not in {r[1] for r in conn.execute("PRAGMA table_info(historico_atualizacoes)")}:
                conn.execute("ALTER TABLE historico_atualizacoes ADD COLUMN usuario TEXT")


def sincronizar_dados_iniciais():
    """Importa modulos, usuarios e configuracoes para o banco de dados SQLite."""
    with _TRAVA_BANCO:
        with conectar() as conn:
            agora = datetime.now().isoformat()
            caminho_banco = str(obter_caminho_banco())

            # 1. Registra o caminho do banco de dados na tabela de configuracoes
            conn.execute(
                "INSERT INTO configuracoes (chave, valor, atualizado_em) VALUES (?, ?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em",
                ("caminho_banco", caminho_banco, agora)
            )

            # 2. Sincronizar modulos
            if MODULOS_JSON.exists():
                try:
                    dados_mod = json.loads(MODULOS_JSON.read_text(encoding="utf-8-sig"))
                    for m in dados_mod.get("modulos", []):
                        conn.execute(
                            "INSERT INTO modulos (id, nome, descricao, pasta, tipo, codigo, ativo) "
                            "VALUES (?, ?, ?, ?, ?, ?, 1) "
                            "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, descricao = excluded.descricao, "
                            "pasta = excluded.pasta, tipo = excluded.tipo, codigo = excluded.codigo",
                            (m["id"], m["nome"], m.get("descricao", ""), m["pasta"], m["tipo"], m.get("codigo"))
                        )
                except Exception as e:
                    print(f">>> AVISO (banco): não consegui sincronizar modulos: {e}")

            # 3. Usuarios: o BANCO manda (ele e o mesmo para todos os computadores). O usuarios.json so e copiado
            #    para dentro do banco quando o banco ainda esta vazio; senao um usuarios.json velho, de outro
            #    computador, desfaria usuarios e senhas ja alterados no banco central.
            arquivo_usr = PASTA / "usuarios.json"
            ja_tem_usuarios = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0
            if arquivo_usr.exists() and not ja_tem_usuarios:
                try:
                    dados_usr = json.loads(arquivo_usr.read_text(encoding="utf-8-sig"))
                    for u in dados_usr.get("usuarios", []):
                        conn.execute(
                            "INSERT INTO usuarios (usuario, hash, sal, iteracoes, admin, relatorios, criado_em) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(usuario) DO UPDATE SET hash = excluded.hash, sal = excluded.sal, "
                            "iteracoes = excluded.iteracoes, admin = excluded.admin, relatorios = excluded.relatorios",
                            (
                                u["usuario"],
                                u["hash"],
                                u["sal"],
                                int(u.get("iteracoes", 240000)),
                                1 if u.get("admin") else 0,
                                json.dumps(u.get("relatorios", ["*"]), ensure_ascii=False),
                                u.get("criado_em", agora[:10])
                            )
                        )
                except Exception as e:
                    print(f">>> AVISO (banco): não consegui sincronizar usuarios: {e}")

            conn.commit()


def inicializar_banco():
    """Garante que as tabelas existam e os dados iniciais estejam sincronizados."""
    criar_tabelas()
    sincronizar_dados_iniciais()


def registrar_atualizacao(modulo_id: str, status: str, mensagem: str, duracao_segundos: float = 0.0, usuario: str = ""):
    """Registra uma execucao/atualizacao de relatorio no historico. 'usuario' = quem clicou em Atualizar agora ('' = verificacao automatica)."""
    try:
        with _TRAVA_BANCO:
            with conectar() as conn:
                conn.execute(
                    "INSERT INTO historico_atualizacoes (modulo_id, status, mensagem, duracao_segundos, data_hora, usuario) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (modulo_id, status, mensagem, float(duracao_segundos), datetime.now().isoformat(), usuario or None)
                )
                conn.execute(   # mantem so os ultimos registros: a verificacao automatica grava a cada conferencia
                    "DELETE FROM historico_atualizacoes WHERE id <= (SELECT MAX(id) FROM historico_atualizacoes) - ?",
                    (LIMITE_HISTORICO,)
                )
    except Exception as e:
        print(f">>> AVISO (banco): falha ao registrar atualizacao: {e}")


def listar_historico(limite: int = 50) -> list[dict]:
    """Retorna as ultimas atualizacoes registradas."""
    try:
        with conectar() as conn:
            cursor = conn.execute(
                "SELECT * FROM historico_atualizacoes ORDER BY id DESC LIMIT ?", (limite,)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def marcar_pendencia(painel: str, chave: str, titulo: str, usuario: str, versao: int):
    """Registra que 'usuario' diz ter resolvido o alerta 'chave' do painel; 'versao' = versao dos dados que ele estava vendo.
    Marcar de novo atualiza quem marcou, quando e a versao. Levanta BancoIndisponivel se o banco esta fora do ar."""
    with _TRAVA_BANCO:
        with conectar() as conn:
            conn.execute(
                "INSERT INTO pendencias_resolvidas (painel, chave, titulo, usuario, quando, versao) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(painel, chave) DO UPDATE SET titulo = excluded.titulo, usuario = excluded.usuario, "
                "quando = excluded.quando, versao = excluded.versao",
                (painel, chave, titulo, usuario, datetime.now().isoformat(timespec="seconds"), int(versao))
            )


def desmarcar_pendencia(painel: str, chave: str):
    with _TRAVA_BANCO:
        with conectar() as conn:
            conn.execute("DELETE FROM pendencias_resolvidas WHERE painel = ? AND chave = ?", (painel, chave))


def listar_pendencias(painel: str) -> list[dict]:
    """Alertas que alguem marcou como resolvidos neste painel. Levanta BancoIndisponivel se o banco esta fora do ar."""
    with conectar() as conn:
        linhas = conn.execute("SELECT chave, titulo, usuario, quando, versao FROM pendencias_resolvidas WHERE painel = ? ORDER BY quando DESC",
                              (painel,)).fetchall()
        return [dict(r) for r in linhas]


def salvar_usuarios(usuarios: list[dict]):
    """Atualiza a tabela de usuarios com base na lista fornecida."""
    with _TRAVA_BANCO:
        with conectar() as conn:
            nomes = [u["usuario"] for u in usuarios]
            # Remove quem nao esta mais na lista
            if nomes:
                conn.execute(f"DELETE FROM usuarios WHERE usuario NOT IN ({','.join('?' for _ in nomes)})", nomes)
            else:
                conn.execute("DELETE FROM usuarios")

            for u in usuarios:
                conn.execute(
                    "INSERT INTO usuarios (usuario, hash, sal, iteracoes, admin, relatorios, criado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(usuario) DO UPDATE SET hash = excluded.hash, sal = excluded.sal, "
                    "iteracoes = excluded.iteracoes, admin = excluded.admin, relatorios = excluded.relatorios",
                    (
                        u["usuario"],
                        u["hash"],
                        u["sal"],
                        int(u.get("iteracoes", 240000)),
                        1 if u.get("admin") else 0,
                        json.dumps(u.get("relatorios", ["*"]), ensure_ascii=False),
                        u.get("criado_em", datetime.now().strftime("%Y-%m-%d"))
                    )
                )
            conn.commit()


def criar_solicitacao(usuario: str, hash_: str, sal: str, iteracoes: int, mensagem: str):
    """Guarda um pedido de cadastro (a senha ja vem em hash). Levanta BancoIndisponivel se o banco esta fora do ar e
    sqlite3.IntegrityError se ja ha um pedido com esse nome."""
    with _TRAVA_BANCO:
        with conectar() as conn:
            conn.execute(
                "INSERT INTO solicitacoes_cadastro (usuario, hash, sal, iteracoes, mensagem, solicitado_em) VALUES (?, ?, ?, ?, ?, ?)",
                (usuario, hash_, sal, int(iteracoes), mensagem, datetime.now().isoformat(timespec="seconds")))


def listar_solicitacoes() -> list[dict]:
    """Pedidos de cadastro esperando o administrador (os mais antigos primeiro). Levanta BancoIndisponivel se o banco esta fora do ar."""
    with conectar() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM solicitacoes_cadastro ORDER BY id ASC").fetchall()]


def remover_solicitacao(usuario: str):
    with _TRAVA_BANCO:
        with conectar() as conn:
            conn.execute("DELETE FROM solicitacoes_cadastro WHERE usuario = ?", (usuario,))


def contar_usuarios() -> int | None:
    """Quantos usuarios o banco tem; None se nao deu para consultar (banco fora do ar)."""
    try:
        with conectar() as conn:
            return conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    except Exception:
        return None


def carregar_usuarios() -> list[dict]:
    """Carrega todos os usuarios cadastrados no banco de dados local."""
    try:
        with conectar() as conn:
            cursor = conn.execute("SELECT * FROM usuarios ORDER BY id ASC")
            resultado = []
            for row in cursor.fetchall():
                r = dict(row)
                relatorios = json.loads(r.get("relatorios") or '["*"]')
                resultado.append({
                    "usuario": r["usuario"],
                    "hash": r["hash"],
                    "sal": r["sal"],
                    "iteracoes": r["iteracoes"],
                    "admin": bool(r["admin"]),
                    "relatorios": relatorios,
                    "criado_em": r["criado_em"]
                })
            return resultado
    except Exception:
        return []


if __name__ == "__main__":
    s = situacao()
    print(f"Banco de dados: {s['caminho']} ({'em outro computador' if s['em_rede'] else 'neste computador'})")
    if not s["ok"]:
        print(f"NAO ACESSIVEL: {s['erro']}")
        raise SystemExit(1)
    inicializar_banco()
    caminho = obter_caminho_banco()
    print(f"Tamanho do arquivo: {caminho.stat().st_size} bytes")
    print(f"Usuarios no banco: {len(carregar_usuarios())}")
