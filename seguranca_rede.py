"""Acesso pela rede ao Indicadores CSI: certificado, quem pode entrar e como os colegas encontram o servidor.

O servidor (servidor_portal.py) escuta em dois lugares ao mesmo tempo:
  - 127.0.0.1:8765  HTTP simples, so deste computador (o dono, o lancador e a exportacao de PDF);
  - 0.0.0.0:8766    HTTPS, para os computadores da rede. So aceita enderecos das redes internas (rede.json), so fala TLS com o
                    certificado deste servidor e so entra quem tem login. O cliente "Indicadores CSI.exe" confere o certificado
                    pela impressao digital que vem no servidor.json, entao o navegador nunca mostra aviso de seguranca.

O banco, as planilhas, o log e o token do Klingo ficam SO no computador do servidor: os outros computadores nao guardam nada.
Aqui so ha biblioteca padrao, menos a criacao do certificado (cryptography, que vai dentro do .exe do servidor).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOWS = os.name == "nt"
NOME_REGRA = "Indicadores CSI"             # nome da regra de entrada no Firewall do Windows
ARQUIVO_CONFIG = "rede.json"
ARQUIVO_PUBLICACAO = "servidor.json"       # endereco + impressao digital do servidor, lido pelo cliente
PASTA_SEGURANCA = "seguranca"              # servidor.crt / servidor.key / servidor.json (dentro da pasta de dados)
VALIDADE_ANOS = 10
REDES_PRIVADAS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
SEM_JANELA = 0x08000000 if WINDOWS else 0

PADRAO = {
    "ativar_rede": True,
    "porta_rede": 8766,
    "redes_permitidas": REDES_PRIVADAS,
    "nomes_aceitos": [],
    "pasta_compartilhada": "",
    "intervalo_minimo_atualizar_agora_minutos": 5,
}


# ---------------------------------------------------------------- configuracao (rede.json)
def ler_config(pasta: Path) -> dict:
    """rede.json da pasta de dados, com os valores padrao no que faltar e as redes ja convertidas ('_redes').
    Erro de digitacao no arquivo nunca derruba o servidor: usa o padrao e devolve o aviso em '_avisos'."""
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in PADRAO.items()}
    cfg["_avisos"] = []
    arquivo = Path(pasta) / ARQUIVO_CONFIG
    if arquivo.exists():
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8-sig"))
            if not isinstance(dados, dict):
                raise ValueError("o conteúdo precisa ser um objeto { ... }")
            cfg.update({k: v for k, v in dados.items() if not str(k).startswith("_")})
        except (OSError, ValueError) as e:
            cfg["_avisos"].append(f"{ARQUIVO_CONFIG} está com erro ({e}): usei os valores padrão.")
    try:
        porta = int(cfg["porta_rede"])
        if not 1024 <= porta <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        cfg["_avisos"].append(f'"porta_rede" inválida em {ARQUIVO_CONFIG}: usei {PADRAO["porta_rede"]}.')
        porta = PADRAO["porta_rede"]
    cfg["porta_rede"] = porta
    cfg["ativar_rede"] = bool(cfg["ativar_rede"])
    redes = []
    for texto in (cfg["redes_permitidas"] if isinstance(cfg["redes_permitidas"], list) else []):
        try:
            redes.append(ipaddress.ip_network(str(texto).strip(), strict=False))
        except ValueError:
            cfg["_avisos"].append(f'Rede inválida em {ARQUIVO_CONFIG}: "{texto}" (ignorei).')
    if not redes:
        redes = [ipaddress.ip_network(t) for t in REDES_PRIVADAS]
        cfg["_avisos"].append("Nenhuma rede válida em redes_permitidas: usei as redes internas (10.x, 172.16-31.x, 192.168.x).")
    cfg["_redes"] = redes
    cfg["nomes_aceitos"] = [str(n).strip().lower() for n in (cfg["nomes_aceitos"] or []) if str(n).strip()]
    try:
        cfg["intervalo_minimo_atualizar_agora_minutos"] = max(0.0, float(cfg["intervalo_minimo_atualizar_agora_minutos"]))
    except (TypeError, ValueError):
        cfg["intervalo_minimo_atualizar_agora_minutos"] = float(PADRAO["intervalo_minimo_atualizar_agora_minutos"])
    cfg["pasta_compartilhada"] = str(cfg.get("pasta_compartilhada") or "").strip().strip('"')
    return cfg


# ---------------------------------------------------------------- quem sou eu na rede
def ips_locais() -> list[str]:
    """Enderecos IPv4 deste computador (o da rede principal primeiro; sem loopback nem 169.254.x.x)."""
    achados: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:   # nao envia nada: so descobre qual interface sairia para a rede
            s.connect(("10.255.255.255", 1))
            achados.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        achados += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    saida: list[str] = []
    for ip in achados:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_loopback or a.is_link_local or a.is_unspecified or ip in saida:
            continue
        saida.append(ip)
    return saida


def nomes_do_computador() -> list[str]:
    """Nome do computador e, se houver, o nome completo no dominio (ex.: PC01 e PC01.empresa.local)."""
    nome = socket.gethostname()
    nomes = [nome]
    try:
        completo = socket.getfqdn()
        if completo and "." in completo and completo.lower() != nome.lower() and not completo.lower().startswith("localhost"):
            nomes.append(completo)
    except OSError:
        pass
    return nomes


class Anfitrioes:
    """Nomes e enderecos pelos quais ESTE servidor pode ser chamado (cabecalho Host). Barra pagina de outro site que, por
    'DNS rebinding', tente falar com o portal usando o navegador de alguem da rede. O IP pode mudar (DHCP): recalcula de tempos em tempos."""

    def __init__(self, extras: list[str] | None = None):
        self.extras = {e.lower() for e in (extras or [])}
        self._trava = threading.Lock()
        self._quando = 0.0
        self._valores: set[str] = set()
        self._atualizando = False

    def _recalcular(self):
        try:
            novos = {n.lower() for n in nomes_do_computador()} | set(ips_locais()) | {"localhost", "127.0.0.1", "::1"} | self.extras
        except Exception:
            novos = None
        with self._trava:
            if novos:
                self._valores, self._quando = novos, time.time()
            self._atualizando = False

    def valores(self) -> set[str]:
        """A lista fica pronta na primeira chamada; depois e renovada em segundo plano (resolver o nome completo pode demorar
        segundos na rede da empresa, e isso nunca pode segurar o pedido de um colega)."""
        if not self._valores:
            self._recalcular()
        elif time.time() - self._quando > 60:
            with self._trava:
                iniciar = not self._atualizando
                self._atualizando = True
            if iniciar:
                threading.Thread(target=self._recalcular, daemon=True).start()
        return self._valores

    def aceita(self, cabecalho_host: str) -> bool:
        host = host_sem_porta(cabecalho_host)
        return bool(host) and host in self.valores()


def host_sem_porta(cabecalho_host: str) -> str:
    h = (cabecalho_host or "").strip().lower()
    if h.startswith("["):                       # [::1]:8766
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def ip_permitido(ip: str, redes: list) -> bool:
    """O endereco do computador que conectou esta numa das redes liberadas? (loopback sempre pode: so o proprio servidor chega ali.)"""
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    if a.is_loopback:
        return True
    return any(a.version == r.version and a in r for r in redes)


# ---------------------------------------------------------------- certificado (TLS)
def _restringir_ao_usuario(arquivo: Path):
    """A chave privada so pode ser lida por quem roda o servidor (o resto do ACL herdado sai)."""
    if not WINDOWS:
        try:
            os.chmod(arquivo, 0o600)
        except OSError:
            pass
        return
    usuario = os.environ.get("USERNAME")
    if usuario:
        try:
            subprocess.run(["icacls", str(arquivo), "/inheritance:r", "/grant:r", f"{usuario}:F"], capture_output=True, timeout=20,
                           creationflags=SEM_JANELA)
        except (OSError, subprocess.SubprocessError):
            pass


def _gerar_certificado(cert: Path, chave: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    nomes = nomes_do_computador()
    ips = ["127.0.0.1"] + ips_locais()
    privada = ec.generate_private_key(ec.SECP256R1())
    dono = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Indicadores CSI"),
                      x509.NameAttribute(NameOID.COMMON_NAME, nomes[0])])
    agora = datetime.now(timezone.utc)
    san = [x509.DNSName(n) for n in dict.fromkeys(nomes + ["localhost"])] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    certificado = (x509.CertificateBuilder().subject_name(dono).issuer_name(dono).public_key(privada.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=365 * VALIDADE_ANOS))
                   .add_extension(x509.SubjectAlternativeName(san), critical=False)
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                                                key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                   .sign(privada, hashes.SHA256()))
    cert.parent.mkdir(parents=True, exist_ok=True)
    novo_cert, nova_chave = cert.with_name(cert.name + ".novo"), chave.with_name(chave.name + ".novo")
    nova_chave.write_bytes(privada.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    _restringir_ao_usuario(nova_chave)
    novo_cert.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    os.replace(nova_chave, chave)
    os.replace(novo_cert, cert)


def garantir_certificado(pasta_dados: Path) -> tuple[Path, Path, str, bool]:
    """(certificado, chave, impressao digital, criou_agora). Cria o certificado so se ainda nao existir: trocar o certificado
    obriga todos os clientes a receberem o servidor.json novo, entao ele dura 10 anos e fica guardado (e no backup diario)."""
    pasta = Path(pasta_dados) / PASTA_SEGURANCA
    cert, chave = pasta / "servidor.crt", pasta / "servidor.key"
    criou = False
    if not (cert.exists() and chave.exists()):
        _gerar_certificado(cert, chave)
        criou = True
    return cert, chave, impressao_digital(cert), criou


def impressao_digital(cert: Path) -> str:
    """SHA-256 do certificado (em hexadecimal): o que o cliente confere para ter certeza de que fala com o servidor certo."""
    der = ssl.PEM_cert_to_DER_cert(Path(cert).read_text(encoding="ascii"))
    return hashlib.sha256(der).hexdigest()


def formatar_impressao(hexa: str) -> str:
    return ":".join(hexa[i:i + 2] for i in range(0, len(hexa), 2)).upper()


def contexto_tls(cert: Path, chave: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert), str(chave))
    return ctx


# ---------------------------------------------------------------- publicacao do endereco para os clientes
def montar_publicacao(cfg: dict, impressao: str, titulo: str = "") -> dict:
    return {"versao": 1, "titulo": titulo, "nomes": nomes_do_computador(), "ips": ips_locais(), "porta": cfg["porta_rede"],
            "impressao_digital": impressao, "atualizado_em": datetime.now().isoformat(timespec="seconds")}


def _sem_data(pub: dict) -> dict:
    return {k: v for k, v in pub.items() if k != "atualizado_em"}


def publicar(pub: dict, pastas: list[Path]) -> list[tuple[Path, str | None]]:
    """Grava o servidor.json em cada pasta (a do cliente, a compartilhada...). Devolve (pasta, erro ou None).
    So reescreve se algo mudou, para o 'atualizado_em' significar 'o endereco mudou'."""
    resultado = []
    for pasta in pastas:
        pasta = Path(pasta)
        destino = pasta / ARQUIVO_PUBLICACAO
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            try:
                atual = json.loads(destino.read_text(encoding="utf-8-sig"))
                if _sem_data(atual) == _sem_data(pub):
                    resultado.append((pasta, None))
                    continue
            except (OSError, ValueError):
                pass
            tmp = destino.with_name(destino.name + ".novo")
            tmp.write_text(json.dumps(pub, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, destino)
            resultado.append((pasta, None))
        except OSError as e:
            resultado.append((pasta, f"{type(e).__name__}: {e}"))
    return resultado


# ---------------------------------------------------------------- Firewall do Windows
def _netsh(*args: str, timeout: float = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def regra_firewall(porta: int) -> str:
    """'ativa' (existe regra de entrada liberando esta porta), 'ausente' ou 'desconhecida' (nao e Windows / netsh nao respondeu)."""
    if not WINDOWS:
        return "desconhecida"
    codigo, texto = _netsh("show", "rule", f"name={NOME_REGRA}")
    if codigo == -1:
        return "desconhecida"
    return "ativa" if codigo == 0 and str(porta) in texto else "ausente"


def comando_liberar_firewall(porta: int) -> list[str]:
    """Argumentos do netsh que liberam a porta so para as redes internas (o mesmo vale para o pessoal de TI fazer na mao).
    Perfis 'domain,private': numa rede publica (cafe, hotel) o Windows continua bloqueando a porta, mesmo que o IP la seja 192.168.x."""
    return ["advfirewall", "firewall", "add", "rule", f"name={NOME_REGRA}", "dir=in", "action=allow", "protocol=TCP",
            f"localport={porta}", "profile=domain,private", "remoteip=" + ",".join(REDES_PRIVADAS), "enable=yes"]


def e_administrador() -> bool:
    if not WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _linha_netsh(partes: list[str]) -> str:
    """Os argumentos viram uma linha de comando; o nome da regra tem espaco, entao vai entre aspas (name="Indicadores CSI")."""
    return " ".join(f'name="{p[5:]}"' if p.startswith("name=") else p for p in partes)


def liberar_firewall(porta: int) -> tuple[bool, str]:
    """Cria (ou refaz) a regra de entrada. Sem ser administrador, o Windows pergunta uma vez (UAC) e roda so este .bat temporario
    como administrador (ele so contem os dois comandos netsh abaixo)."""
    if not WINDOWS:
        return False, "Só no Windows."
    apagar = _linha_netsh(["advfirewall", "firewall", "delete", "rule", f"name={NOME_REGRA}"])
    criar = _linha_netsh(comando_liberar_firewall(porta))
    if e_administrador():
        _netsh("delete", "rule", f"name={NOME_REGRA}")
        codigo, saida = _netsh(*comando_liberar_firewall(porta)[2:])
        return codigo == 0, saida.strip()
    import tempfile
    bat = Path(tempfile.gettempdir()) / f"liberar_rede_csi_{os.getpid()}.bat"
    try:
        bat.write_text(f"@echo off\r\nnetsh {apagar} >nul 2>&1\r\nnetsh {criar}\r\nexit /b %errorlevel%\r\n", encoding="ascii")
        script = (f"$p = Start-Process -FilePath '{bat}' -Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, stdin=subprocess.DEVNULL, creationflags=SEM_JANELA)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        bat.unlink(missing_ok=True)
    return r.returncode == 0 and regra_firewall(porta) == "ativa", (r.stdout + r.stderr).strip()


def texto_para_ti(porta: int) -> str:
    """Instrucao pronta para entregar a quem cuida da rede, caso o Windows nao deixe criar a regra por aqui."""
    return (f'No Firewall do Windows deste computador, crie uma regra de ENTRADA que permita TCP na porta {porta} para os endereços '
            f'{", ".join(REDES_PRIVADAS)} (nome "{NOME_REGRA}"). Num Prompt de Comando como administrador:  '
            f'netsh {_linha_netsh(comando_liberar_firewall(porta))}')
