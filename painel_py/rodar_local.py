"""Gera o HTML de um painel com os dados de DADOS_DIR (teste local, sem Supabase).  python rodar_local.py <menu> [de] [ate] > saida.html"""
import sys

from painel_runtime import gerar_html

if __name__ == "__main__":
    menu = sys.argv[1]
    sys.stdout.write(gerar_html(menu, sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3] if len(sys.argv) > 3 else None))
