"""Servidores de mentira para testar o portal na nuvem sem credenciais: um Supabase (REST + login) e um Klingo.

O Supabase simulado entende so o que armazenamento.py usa (filtros eq/neq, order, Range, upsert, delete, rpc), guardando tudo na memoria.
O Klingo simulado devolve, para qualquer relatorio, as colunas que o relatorios.json do painel declara (mais as que o teste pedir),
com valores que o `validar_resposta` aceita.
"""
import json
import re
import threading
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PADRAO_MES = re.compile(r"^\d{4}-\d\d$")


class BancoSimulado:
    def __init__(self):
        self.dados, self.mes, self.paginas, self.avisos, self.atualizacoes, self.custos = [], {}, {}, [], [], []
        self.avisos_sync = []        # (painel, escopos, versao, alertas) de cada chamada de aviso_sincronizar
        self.falhar_avisos = False   # a sincronizacao responde erro (o painel tem de abrir do mesmo jeito)
        self.relatorios, self.colunas, self.execucoes, self.linhas_dw = [], [], [], []   # a coleta unica do banco (dim_relatorio, dim_relatorio_coluna, sync_relatorio_runs, linhas vigentes)
        self.usuarios = {}   # token -> {"id","email"}
        self.perfis = {}     # id -> {"role","permissions"}
        self.trava = threading.Lock()
        self.pedidos = []    # (metodo, caminho) de cada pedido, para o teste conferir o que foi (ou nao foi) chamado

    def novo_usuario(self, token, email, role="viewer", permissions=None):
        uid = f"uid-{len(self.usuarios) + 1}"
        self.usuarios[token] = {"id": uid, "email": email}
        self.perfis[uid] = {"role": role, "permissions": permissions or {}}
        return uid


def _filtros(params):
    """{coluna: (operador, valor)} dos parametros 'coluna=op.valor' (ignora select/order/limit/on_conflict/or)."""
    out = {}
    for k, v in params.items():
        m = re.match(r"^(eq|neq|gt)\.(.*)$", v)
        if m and k not in ("select", "order", "limit", "on_conflict", "or"):
            out[k] = (m.group(1), m.group(2))
    return out


def _casa(linha, filtros):
    for col, (op, val) in filtros.items():
        atual = str(linha.get(col))
        if op == "eq" and atual != val:
            return False
        if op == "neq" and atual == val:
            return False
        if op == "gt" and not (float(linha.get(col) or 0) > float(val)):
            return False
    return True


def _ou(linha, expr):
    """or=(a.neq.1,b.neq.2): verdadeiro se qualquer uma casa."""
    for parte in expr.strip("()").split(","):
        col, op, val = parte.split(".", 2)
        if _casa(linha, {col: (op, val)}):
            return True
    return False


def criar_supabase(banco: BancoSimulado):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _enviar(self, status, corpo=None):
            dados = b"" if corpo is None else json.dumps(corpo).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def _enviar_faixa(self, itens):
            """Como o PostgREST: respeita Range e limita a 1000 linhas por resposta; Range alem do fim = 416."""
            ini, fim = 0, len(itens)
            if "Range" in self.headers:
                a, b = self.headers["Range"].split("-")
                ini, fim = int(a), int(b) + 1
                if ini >= len(itens) and ini > 0:
                    return self._enviar(416, {"message": "Requested range not satisfiable"})
            return self._enviar(200, itens[ini:min(fim, ini + 1000)])

        def _corpo(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n)) if n else None

        def _tratar(self):
            u = urllib.parse.urlsplit(self.path)
            params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            banco.pedidos.append((self.command, u.path))
            with banco.trava:
                if u.path == "/auth/v1/user":
                    tok = self.headers.get("Authorization", "")[7:]
                    return self._enviar(200, banco.usuarios[tok]) if tok in banco.usuarios else self._enviar(401, {"msg": "invalid"})
                if not self.headers.get("apikey") or not self.headers.get("Authorization", "").startswith("Bearer "):
                    return self._enviar(401, {"message": "sem chave"})
                tabela = u.path.rsplit("/", 1)[-1]
                if u.path == "/rest/v1/profiles":
                    f = _filtros(params)["id"][1]
                    return self._enviar(200, [banco.perfis[f]] if f in banco.perfis else [])
                if tabela == "painel_dados_ativos":
                    f = _filtros(params)
                    ativos = [(m["mes"], d) for d in banco.dados for m in [banco.mes.get((d["painel"], d["aba"], d["mes"]))]
                              if m and m["versao"] == d["versao"] and _casa(d, f)]
                    ativos.sort(key=lambda t: (t[0], t[1]["lote"]))
                    saida = [{"mes": m, "lote": d["lote"], "linhas": d["linhas"]} for m, d in ativos]
                    return self._enviar_faixa(saida)
                if tabela == "painel_dados" and self.command == "POST":
                    banco.dados.extend(self._corpo())
                    return self._enviar(201)
                if tabela == "painel_publicar_mes":
                    c = self._corpo()
                    chave = (c["p_painel"], c["p_aba"], c["p_mes"])
                    if c["p_n_linhas"] > 0 and not any((d["painel"], d["aba"], d["mes"], d["versao"]) == (*chave, c["p_versao"]) for d in banco.dados):
                        return self._enviar(400, {"message": "Nenhum lote gravado"})
                    banco.mes[chave] = {"painel": chave[0], "aba": chave[1], "mes": chave[2], "versao": c["p_versao"], "n_linhas": c["p_n_linhas"],
                                        "atualizado_em": datetime.now(timezone.utc).isoformat()}
                    banco.dados[:] = [d for d in banco.dados if not ((d["painel"], d["aba"], d["mes"]) == chave and d["versao"] != c["p_versao"])]
                    if c.get("p_exclusivo"):
                        banco.dados[:] = [d for d in banco.dados if not (d["painel"] == chave[0] and d["aba"] == chave[1] and d["mes"] != chave[2])]
                        for k in [k for k in banco.mes if k[0] == chave[0] and k[1] == chave[1] and k[2] != chave[2]]:
                            del banco.mes[k]
                    return self._enviar(204)
                if tabela == "painel_mes":
                    f = _filtros(params)
                    lin = [m for m in banco.mes.values() if _casa(m, f)]
                    if params.get("order") == "atualizado_em.desc":
                        lin.sort(key=lambda m: m["atualizado_em"], reverse=True)
                    if "limit" in params:
                        lin = lin[:int(params["limit"])]
                    return self._enviar_faixa(lin)
                if tabela == "painel_pagina":
                    if self.command == "GET":
                        f = _filtros(params)
                        return self._enviar(200, [p for p in banco.paginas.values() if _casa(p, f)])
                    if self.command == "POST":
                        for p in self._corpo():
                            banco.paginas[(p["painel"], p["chave"])] = p
                        return self._enviar(201)
                    if self.command == "DELETE":
                        f = _filtros(params)
                        for k in [k for k, p in banco.paginas.items() if _casa(p, f) and ("or" not in params or _ou(p, params["or"]))]:
                            del banco.paginas[k]
                        return self._enviar(204)
                if tabela == "aviso" and self.command == "GET":
                    return self._enviar(200, [a for a in banco.avisos if _casa(a, _filtros(params))])
                if tabela == "aviso_sincronizar":
                    if banco.falhar_avisos:
                        return self._enviar(400, {"message": "aviso_sincronizar falhou de mentira"})
                    c = self._corpo()
                    banco.avisos_sync.append((c["p_painel"], c["p_escopos"], c["p_versao"], c["p_alertas"]))
                    return self._enviar(200, {"novos": len(c["p_alertas"]), "total": len(c["p_alertas"])})
                if tabela == "dim_relatorio":
                    return self._enviar(200, [r for r in banco.relatorios if _casa(r, _filtros(params))])
                if tabela == "dim_relatorio_coluna":
                    return self._enviar_faixa([c for c in banco.colunas if _casa(c, _filtros(params))])
                if tabela == "sync_relatorio_runs":
                    return self._enviar_faixa([r for r in banco.execucoes if _casa(r, _filtros(params))])
                if tabela == "v_relatorio_linha_vigente":
                    lin = [l for l in banco.linhas_dw if _casa(l, _filtros(params))]
                    faixa = re.match(r"^\(periodo\.gte\.(.+),periodo\.lte\.(.+)\)$", params.get("and", ""))
                    if faixa:
                        lin = [l for l in lin if faixa.group(1) <= l["periodo"] <= faixa.group(2)]
                    lin.sort(key=lambda l: (l["periodo"], l["id"]))
                    return self._enviar_faixa([{"linha": l["linha"], "repeticoes": l["repeticoes"]} for l in lin])
                if tabela == "painel_atualizacao" and self.command == "POST":
                    banco.atualizacoes.extend({**a, "criado_em": datetime.now(timezone.utc).isoformat()} for a in self._corpo())
                    return self._enviar(201)
                if tabela == "painel_atualizacao" and self.command == "GET":
                    lin = sorted((a for a in banco.atualizacoes if _casa(a, _filtros(params))), key=lambda a: a["criado_em"], reverse=True)
                    return self._enviar(200, lin[:int(params.get("limit", len(lin)))])
                if tabela == "painel_custo_item":
                    return self._enviar_faixa([c for c in banco.custos if (c.get("custo") or 0) > 0])
            self._enviar(404, {"message": f"rota nao simulada: {self.command} {self.path}"})

        do_GET = do_POST = do_DELETE = _tratar

    return H


def criar_klingo(colunas_extras: dict[int, list[str]] | None = None, linhas_por_mes: int = 3, falhar_ids: set[int] | None = None):
    """Klingo de mentira. `colunas_extras[id]` = titulos de colunas a mais; `falhar_ids` = relatorios que respondem erro."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    declarados = {}
    for pasta in ("Faturamento", "Financeiro", "Despesas", "Indicadores", "Cesta", "Suprimentos", "Atendimento"):
        for rel in json.loads((raiz / pasta / "relatorios.json").read_text(encoding="utf-8"))["relatorios"]:
            titulos = list(dict.fromkeys([*rel.get("chave", []), *rel.get("numeros", []), *rel.get("datas", {})]))
            declarados[rel["id"]] = (titulos, set(rel.get("numeros", [])), set(rel.get("datas", {})), rel)

    class K(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
            rid = int(q["id"])
            if self.headers.get("X-APP-TOKEN") != "token-de-teste":
                self.send_response(401); self.end_headers(); return
            if falhar_ids and rid in falhar_ids:
                corpo = {"status_code": 400, "msg": "Relatório não encontrado"}
            elif rid == 13339:   # base das Metas
                dia = q[":periodo0-from"] if ":periodo0-from" in q else date.today().isoformat()
                cols = ["Exames Realizados", "Unidade", "Procedimento - Classes", "Especialidade", "Data do Atendimento", "Procedimento", "Operadora"]
                hoje = date.today()
                dados = [{f"c{i}": v for i, v in enumerate([str(1000 + n), "CLÍNICA DE SAÚDE E IMAGEM - CSI 1", '["RESSONANCIA"]', "RESSONÂNCIA",
                                                           f"{hoje.strftime('%Y-%m')}-{n % 28 + 1:02d}T10:00:00", "RM CRANIO", "SUS" if n % 2 else "UNIMED"])} for n in range(linhas_por_mes)]
                corpo = {"id": 13339, "inputs": [{"id": "periodo0", "value": q.get(":periodo0", "m")}],
                         "result": {"columns": [{"name": f"c{i}", "title": t} for i, t in enumerate(cols)], "rows": len(dados), "data": dados}}
            else:
                titulos, numeros, datas, rel = declarados[rid]
                titulos = titulos + [t for t in (colunas_extras or {}).get(rid, []) if t not in titulos]
                pid = rel.get("periodo")
                de = q.get(f":{pid}-from") if pid else None
                base = date.fromisoformat(de) if de else date.today()
                dados = []
                for n in range(linhas_por_mes):
                    linha = {}
                    for i, t in enumerate(titulos):
                        if t in numeros or re.search(r"(Valor|Qtd|Quant|Saldo|Taxa|Custo|Tempo|Minuto|Idade|Total|Preço)", t):
                            linha[f"c{i}"] = str(100 + n + (i * 7))
                        elif t in datas or re.search(r"\b(Data|Emiss|Vencimento|Compet|Validade)", t):
                            linha[f"c{i}"] = (base + timedelta(days=n % 28)).strftime("%Y-%m-%d 09:58:25")   # as datas ficam dentro do mes baixado
                        elif "Faixa" in t:
                            linha[f"c{i}"] = ("0-9", "10-19", "20-29")[n % 3]
                        else:
                            linha[f"c{i}"] = f"{t[:12]} {n % 2}"
                    dados.append(linha)
                corpo = {"id": rid, "inputs": [{"id": pid, "value": q.get(f":{pid}", "l")}] if pid else [],
                         "result": {"columns": [{"name": f"c{i}", "title": t} for i, t in enumerate(titulos)], "rows": len(dados), "data": dados} if dados else ""}
            dados_resp = json.dumps(corpo).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados_resp)))
            self.end_headers()
            self.wfile.write(dados_resp)

    return K


def subir(handler_cls) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
