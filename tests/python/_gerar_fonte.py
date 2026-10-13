"""Auxiliar do test_fonte_supabase: gera o painel de um menu na fonte indicada pelo ambiente e imprime o D (sem campos de relógio) em JSON."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "painel_py"))
from painel_runtime import gerar_html  # noqa: E402

html = gerar_html(sys.argv[1])
d = json.loads(re.search(r'<script[^>]*id="dados"[^>]*>(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
for k in ("gerado_em", "versao", "dados_em"):
    d.pop(k, None)
print(json.dumps(d["meses"], sort_keys=True))
