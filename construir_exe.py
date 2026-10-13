"""Gera os DOIS programas do Indicadores CSI:

  1. "Indicadores CSI - Servidor.exe"  (fica ao lado de "Codigo-fonte"; SO no computador de quem cuida dos dados)
     AUTONOMO: Python, pandas, openpyxl, numpy, playwright e o proprio portal dentro de um unico .exe. Guarda banco, planilhas, log e
     token do Klingo, consulta o Klingo e atende os colegas pela rede (HTTPS, so redes internas, com login).
  2. "Compartilhar\\Indicadores CSI.exe"  (pequeno, so biblioteca padrao: cliente_portal.py) + servidor.json + LEIA-ME.txt
     E o que se copia para a pasta corporativa ou se manda aos colegas. Nao guarda nada: abre o portal do servidor num tunel seguro.
     O endereco e a impressao digital do certificado do servidor vao embutidos nele (e o servidor.json ao lado, se existir, vale
     mais por ser mais novo).

Como o servidor e montado
  - O portal (programas, modelos HTML, configuracoes iniciais) vai dentro do .exe como "app_embutido.zip", com um manifesto
    que diz o que e 'codigo' (atualizado a cada abertura) e o que e 'semente' (criado so se nao existir: metas.json etc.).
  - O PyInstaller leva o interpretador e as bibliotecas. Como os programas do portal sao lidos da pasta de dados (e nao
    compilados dentro do .exe), o script percorre o codigo deles e passa cada biblioteca usada como --hidden-import.
  - O icone vem de gerar_icone.py.

Uso:  python construir_exe.py            gera os dois (ou de dois cliques em "Gerar EXE.bat")   Demora alguns minutos.
      python construir_exe.py servidor   so o servidor
      python construir_exe.py cliente    so o cliente (1 minuto)
"""
import ast
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ.parent   # o .exe pronto fica na pasta principal, ao lado de "Codigo-fonte"
CODIGO, SEMENTE = "codigo", "semente"
METAS, FAT, FIN, CESTA, IND, SUP, ATE, DESP = "Acompanhamento de META", "Faturamento", "Financeiro", "Cesta", "Indicadores", "Suprimentos", "Atendimento", "Despesas"
ARQUIVOS = {   # caminho relativo -> categoria
    "servidor_portal.py": CODIGO, "klingo_relatorios.py": CODIGO, "painel_comum.py": CODIGO,
    "painel_base.css": CODIGO, "painel_base.js": CODIGO, "portal.html": CODIGO, "modulos.json": CODIGO,
    "autenticacao.py": CODIGO, "guia_pendencias.py": CODIGO, "login.html": CODIGO, "exportar_pdf.py": CODIGO, "portal_csi.ico": CODIGO,
    "banco_dados.py": CODIGO, "config.json": SEMENTE,   # o banco (portal_csi.db) NAO vai dentro: fica so no servidor (os colegas usam o cliente, nunca o arquivo)
    "seguranca_rede.py": CODIGO, "rede.json": SEMENTE,  # acesso pela rede: porta, redes liberadas, intervalo entre atualizacoes manuais (ajustavel)
    f"{METAS}/servidor_painel.py": CODIGO, f"{METAS}/extrair_laudo.py": CODIGO, f"{METAS}/gerar_dashboard.py": CODIGO,
    f"{METAS}/dashboard_modelo.html": CODIGO,
    f"{METAS}/metas.json": SEMENTE, f"{METAS}/config.json": SEMENTE, f"{METAS}/Link dos dados das meta relatorio.txt": SEMENTE,
    f"{FAT}/gerar_faturamento.py": CODIGO, f"{FAT}/dashboard_modelo.html": CODIGO, f"{FAT}/relatorios.json": CODIGO,
    f"{FIN}/gerar_financeiro.py": CODIGO, f"{FIN}/dashboard_modelo.html": CODIGO, f"{FIN}/relatorios.json": CODIGO,
    f"{DESP}/gerar_despesas.py": CODIGO, f"{DESP}/dashboard_modelo.html": CODIGO, f"{DESP}/relatorios.json": CODIGO,
    f"{IND}/gerar_indicadores.py": CODIGO, f"{IND}/dashboard_modelo.html": CODIGO, f"{IND}/relatorios.json": CODIGO,
    f"{CESTA}/gerar_cesta.py": CODIGO, f"{CESTA}/dashboard_modelo.html": CODIGO, f"{CESTA}/relatorios.json": CODIGO,
    f"{CESTA}/equivalencias.py": SEMENTE,
    f"{SUP}/gerar_suprimentos.py": CODIGO, f"{SUP}/dashboard_modelo.html": CODIGO, f"{SUP}/relatorios.json": CODIGO,
    f"{ATE}/gerar_atendimento.py": CODIGO, f"{ATE}/dashboard_modelo.html": CODIGO, f"{ATE}/relatorios.json": CODIGO,
    f"{ATE}/responsaveis.json": SEMENTE,   # quem cuida de que: ajustavel, so e copiado se ainda nao existir
    f"{ATE}/parametros.json": SEMENTE,   # os limites podem ser ajustados pelo usuario: so e copiado se ainda nao existir
}
# nao tem como o PyInstaller descobrir sozinho (carregados por nome ou por plugin): garante que entram
# (o playwright e so da exportacao de PDF, exportar_pdf.py; a captura dos relatorios usa a API externa do Klingo, sem navegador)
EXTRAS = ["pandas.io.excel._openpyxl", "openpyxl.cell._writer", "mimetypes", "socketserver", "http.server", "html", "unicodedata",
          "playwright.sync_api", "email.mime.text", "pypdf", "sqlite3"]
EXCLUIR = ["tkinter", "matplotlib", "scipy", "IPython", "jupyter", "notebook", "pytest", "PIL", "sphinx", "numba", "sqlalchemy", "lxml"]


def modulos_usados() -> set[str]:
    """Bibliotecas importadas pelos programas do portal (menos os proprios programas dele)."""
    proprios = {Path(rel).stem for rel in ARQUIVOS if rel.endswith(".py")}
    achados: set[str] = set()
    for rel in ARQUIVOS:
        if not rel.endswith(".py"):
            continue
        for no in ast.walk(ast.parse((RAIZ / rel).read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                achados |= {a.name for a in no.names}
            elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
                achados.add(no.module)
    return {m for m in achados if m.split(".")[0] not in proprios}


def montar_zip(destino: Path) -> str:
    faltam = [rel for rel in ARQUIVOS if not (RAIZ / rel).exists()]
    if faltam:
        sys.exit("Faltam arquivos para empacotar: " + ", ".join(faltam))
    sha = hashlib.sha256()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, categoria in ARQUIVOS.items():
            dados = (RAIZ / rel).read_bytes()
            sha.update(rel.encode() + dados)
            z.writestr(rel, dados)
        versao = sha.hexdigest()[:12]
        z.writestr("manifesto.json", json.dumps({"versao": versao, "arquivos": ARQUIVOS}, ensure_ascii=False, indent=1))
    return versao


NOME_SERVIDOR, NOME_CLIENTE = "Indicadores CSI - Servidor", "Indicadores CSI"
PASTA_DADOS = SAIDA / "Dados do Indicadores CSI"   # onde o servidor guarda tudo (o mesmo lugar em que ele se instala ao lado do .exe)
PASTA_COMPARTILHAR = SAIDA / "Compartilhar"
LEIA_ME_CLIENTE = """Indicadores CSI - como abrir

1. Dê dois cliques em "Indicadores CSI.exe" (nesta pasta). Uma janela preta abre e, em seguida, o navegador.
2. Entre com o seu usuário e senha do portal. Se ainda não tem, use "Solicitar cadastro" na tela de entrada e avise o administrador.
3. Pode minimizar a janela preta, mas NÃO a feche: fechar a janela encerra o acesso. Para sair do portal, feche a janela.

Importante
- Os dados ficam no computador do servidor, não no seu. Se aparecer "O servidor do portal não respondeu", o computador dele está
  desligado ou o programa do servidor não está aberto: avise quem cuida do portal. A página tenta de novo sozinha.
- Não mexa em "servidor.json": ele diz onde está o servidor e qual é o certificado dele. Se o servidor for trocado ou reinstalado,
  quem cuida do portal atualiza esta pasta.
- "Indicadores CSI.exe --testar" mostra, passo a passo, se o seu computador consegue falar com o servidor.
"""


def preparar_publicacao() -> dict:
    """Endereco + impressao digital do servidor (cria o certificado na pasta de dados se ainda nao existir). Vai embutido no cliente."""
    sys.path.insert(0, str(RAIZ))
    import seguranca_rede as rede
    cfg = rede.ler_config(PASTA_DADOS if (PASTA_DADOS / rede.ARQUIVO_CONFIG).exists() else RAIZ)
    _cert, _chave, impressao, criou = rede.garantir_certificado(PASTA_DADOS)
    if criou:
        print(f"Criei o certificado de segurança do servidor em {PASTA_DADOS / rede.PASTA_SEGURANCA}.", flush=True)
    try:
        titulo = json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig")).get("titulo", "")
    except (OSError, ValueError):
        titulo = ""
    return rede.montar_publicacao(cfg, impressao, titulo)


def pyinstaller(nome: str, entrada: Path, destino: Path, tmp: Path, extra: list[str]):
    icone = RAIZ / "portal_csi.ico"
    if not icone.exists():
        subprocess.run([sys.executable, str(RAIZ / "gerar_icone.py")], check=False)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console", "--name", nome,
           "--distpath", str(destino), "--workpath", str(tmp / f"work_{nome}"), "--specpath", str(tmp / f"spec_{nome}")]
    if icone.exists():
        cmd += ["--icon", str(icone)]
    cmd += extra + [str(entrada)]
    if subprocess.call(cmd) != 0:
        sys.exit(f"O PyInstaller falhou ao gerar {nome}. Veja as mensagens acima.")


def construir_servidor(tmp: Path):
    zip_embutido = tmp / "app_embutido.zip"
    versao = montar_zip(zip_embutido)
    usados = sorted(modulos_usados() | set(EXTRAS))
    print(f"Portal embutido (versão {versao}): {len(ARQUIVOS)} arquivos; {len(usados)} bibliotecas a incluir.", flush=True)
    extra = ["--add-data", f"{zip_embutido};.", "--collect-all", "playwright", "--collect-submodules", "cryptography"]   # cryptography: cria o certificado do servidor
    for m in usados:
        extra += ["--hidden-import", m]
    for m in EXCLUIR:
        extra += ["--exclude-module", m]
    print("Gerando o servidor (pode demorar alguns minutos)...", flush=True)
    pyinstaller(NOME_SERVIDOR, RAIZ / "iniciar_portal.py", SAIDA, tmp, extra)
    exe = SAIDA / f"{NOME_SERVIDOR}.exe"
    print(f"\nPronto: {exe.name} ({exe.stat().st_size / 1_000_000:.0f} MB). Fica SÓ no computador de quem cuida dos dados.")


def construir_cliente(tmp: Path):
    publicacao = preparar_publicacao()
    padrao = tmp / "servidor_padrao.json"
    padrao.write_text(json.dumps(publicacao, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Cliente apontando para {publicacao['nomes'][0]} (porta {publicacao['porta']}, IP {', '.join(publicacao['ips']) or '?'}).", flush=True)
    PASTA_COMPARTILHAR.mkdir(parents=True, exist_ok=True)
    print("Gerando o cliente...", flush=True)
    pyinstaller(NOME_CLIENTE, RAIZ / "cliente_portal.py", PASTA_COMPARTILHAR, tmp, ["--add-data", f"{padrao};."])
    (PASTA_COMPARTILHAR / "servidor.json").write_text(json.dumps(publicacao, ensure_ascii=False, indent=2), encoding="utf-8")
    (PASTA_COMPARTILHAR / "LEIA-ME.txt").write_text(LEIA_ME_CLIENTE, encoding="utf-8")
    exe = PASTA_COMPARTILHAR / f"{NOME_CLIENTE}.exe"
    print(f"\nPronto: {exe.name} ({exe.stat().st_size / 1_000_000:.0f} MB) na pasta “Compartilhar”. Copie a pasta inteira para a pasta corporativa "
          f"(só com permissão de LEITURA para os colegas) ou mande o .exe a quem precisar.")


def main():
    alvo = (sys.argv[1] if len(sys.argv) > 1 else "tudo").lower()
    if alvo not in ("tudo", "servidor", "cliente"):
        sys.exit("Use:  python construir_exe.py [tudo|servidor|cliente]")
    with tempfile.TemporaryDirectory(prefix="portal_csi_build_") as tmp:
        tmp = Path(tmp)
        if alvo in ("tudo", "cliente"):
            construir_cliente(tmp)
        if alvo in ("tudo", "servidor"):
            construir_servidor(tmp)


if __name__ == "__main__":
    main()
