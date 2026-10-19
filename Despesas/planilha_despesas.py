"""Aba "Planilha" do painel de Despesas: a planilha mensal de despesas que a equipe consultava (grupos x itens x meses) e a lista de
fornecedores com a divisão CSI / CSI 2, agora montadas sozinhas a partir do Klingo.

- Matriz (antiga "Planilha2"): cada lançamento do #13505 vai para um ITEM da planilha pelo de-para categoria do Klingo -> item (tabela
  despesa_de_para). Antes do início confiável (`inicio_confiavel`, o começo do uso do Klingo) valem os valores da própria planilha,
  guardados em despesa_historico; do início em diante, só o Klingo. O que o Klingo traz e o de-para não conhece aparece no grupo
  "SEM CLASSIFICAÇÃO" (o total nunca perde dinheiro).
- Fornecedores (antiga "Planilha1"): o que vence no mês, na empresa CSI, somado por fornecedor com o nome da planilha e dividido entre
  CSI e CSI 2. Junta o Financeiro (#798: empresa e vencimento, que não traz fornecedor) com as Despesas Detalhadas (#13509: fornecedor)
  pelo ID do lançamento.

A base (itens, de-para, histórico, nomes de fornecedor) vem do Supabase quando o painel roda no site e de planilha_base.json no programa
local. Qualquer falha aqui vira um aviso na aba: o resto do painel de Despesas continua abrindo.
"""
import json
import unicodedata
from pathlib import Path

import pandas as pd

import painel_comum as pc

PASTA = Path(__file__).parent
BASE_JSON = PASTA / "planilha_base.json"
SEM_DESTINO = "SEM CLASSIFICAÇÃO"
EMPRESA_RATEIO = "CLÍNICA DE SAÚDE E IMAGEM - CSI"   # a planilha de fornecedores só lista o que vence nesta empresa
COLUNAS_LANC = ("Lançamento", "Empresa", "Vencimento", "Categoria", "Valor", "Tipo")
FORN_SEM_ID = "(fornecedor não identificado)"
MESES_A_FRENTE_FORN = 1   # fornecedores: do início confiável até o mês que vem (vencimentos já lançados)


def _norm(s) -> str:
    """Sem acento, maiúscula e sem espaço nas pontas (o mesmo que o norm das Metas), para casar nomes do Klingo."""
    texto = "" if s is None or (isinstance(s, float) and s != s) else str(s)
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper().strip()


# ---------------------------------------------------------------- base
def _base_do_arquivo() -> dict:
    bruto = json.loads(BASE_JSON.read_text(encoding="utf-8"))
    historico: dict[str, dict] = {ym: {} for ym in bruto["meses"]}
    for g in bruto["grupos"]:
        for it in g["itens"]:
            for ym, v in it["valores"].items():
                historico[ym][(g["grupo"], it["item"])] = float(v)
    return {"fonte": "arquivo", "meses": list(bruto["meses"]),
            "grupos": [{"grupo": g["grupo"], "itens": [i["item"] for i in g["itens"]]} for g in bruto["grupos"]], "historico": historico,
            "de_para": {r["categoria"]: {"grupo": r["grupo"], "item": r["item"], "confirmado": bool(r["confirmado"]), "observacao": r.get("observacao")} for r in bruto["de_para"]},
            "fornecedores": [{"ordem": f["ordem"], "nome": f["nome"], "pct_csi": float(f["pct_csi"]), "regras": f["regras"]} for f in bruto["fornecedores"]]}


def _base_do_banco() -> dict:
    import armazenamento as arm
    itens = arm.ler_tabela("despesa_item", "ordem_grupo.asc,ordem_item.asc")
    if not itens:
        raise arm.ErroArmazenamento("a tabela despesa_item está vazia")
    grupos: dict[str, list[str]] = {}
    for r in itens:
        grupos.setdefault(r["grupo"], []).append(r["item"])
    historico: dict[str, dict] = {}
    for r in arm.ler_tabela("despesa_historico", "mes.asc,grupo.asc,item.asc"):
        historico.setdefault(str(r["mes"])[:7], {})[(r["grupo"], r["item"])] = float(r["valor"])
    de_para = {r["categoria_klingo"]: {"grupo": r["grupo"], "item": r["item"], "confirmado": bool(r["confirmado"]), "observacao": r.get("observacao")}
               for r in arm.ler_tabela("despesa_de_para", "categoria_klingo.asc")}
    por_nome: dict[str, dict] = {}
    for r in arm.ler_tabela("despesa_fornecedor", "ordem.asc,id.asc"):
        f = por_nome.setdefault(r["nome_planilha"], {"ordem": r["ordem"], "nome": r["nome_planilha"], "pct_csi": float(r["pct_csi"]), "regras": []})
        if r.get("fornecedor_klingo"):
            f["regras"].append({"fornecedor": r["fornecedor_klingo"], "categoria": r.get("categoria_klingo")})
    return {"fonte": "banco", "meses": sorted(historico), "grupos": [{"grupo": g, "itens": i} for g, i in grupos.items()], "historico": historico,
            "de_para": de_para, "fornecedores": sorted(por_nome.values(), key=lambda f: f["ordem"])}


def carregar_base() -> dict:
    """No site, as tabelas despesa_* do Supabase (editáveis no Table Editor); no programa local ou se o banco não responder, planilha_base.json."""
    import armazenamento as arm
    if arm.ativo():
        try:
            return _base_do_banco()
        except arm.ErroArmazenamento as e:
            print(f">>> AVISO: não consegui ler a base da aba Planilha no Supabase ({e}); usei o planilha_base.json do repositório.", flush=True)
    return _base_do_arquivo()


# ---------------------------------------------------------------- matriz grupo x item x mês
def montar_matriz(d: pd.DataFrame, base: dict, inicio: str, ym_hoje: str) -> dict:
    """d = débitos do Klingo (Despesa, _ym, Bruto). Meses de `primeiro da planilha` até o mês atual."""
    primeiro = min(base["meses"] + [inicio]) if base["meses"] else inicio
    ordem = pc.meses_entre(primeiro, ym_hoje)
    de_para = base["de_para"]
    com_planilha = {ym for ym in base["meses"] if ym < inicio}

    # Klingo: item de cada categoria, mês a mês (so os meses que NAO vem da planilha)
    kl_meses = [ym for ym in ordem if ym not in com_planilha]
    kl = d[d["_ym"].isin(kl_meses)] if len(d) else d
    por_cat = kl.groupby(["Despesa", "_ym"])["Bruto"].sum() if len(kl) else pd.Series(dtype=float)
    valores: dict[tuple[str, str], dict[str, float]] = {}
    sem_destino: dict[str, float] = {}
    for ym in com_planilha:
        if ym in ordem:
            for chave, v in base["historico"].get(ym, {}).items():
                valores.setdefault(chave, {})[ym] = valores.get(chave, {}).get(ym, 0.0) + v
    for (cat, ym), v in por_cat.items():
        destino = de_para.get(str(cat))
        chave = (destino["grupo"], destino["item"]) if destino else (SEM_DESTINO, str(cat))
        if not destino:
            sem_destino[str(cat)] = sem_destino.get(str(cat), 0.0) + float(v)
        valores.setdefault(chave, {})[ym] = valores.get(chave, {}).get(ym, 0.0) + float(v)

    categorias_do_item: dict[tuple[str, str], list[dict]] = {}
    for cat, dst in de_para.items():
        categorias_do_item.setdefault((dst["grupo"], dst["item"]), []).append({"categoria": cat, "confirmado": dst["confirmado"]})

    grupos_def = [(g["grupo"], g["itens"]) for g in base["grupos"]]
    extra = sorted(i for g, i in valores if g == SEM_DESTINO)
    if extra:
        grupos_def.append((SEM_DESTINO, extra))
    grupos = []
    for grupo, itens in grupos_def:
        linhas = []
        for item in itens:
            v = [round(valores.get((grupo, item), {}).get(ym, 0.0), 2) for ym in ordem]
            cats = categorias_do_item.get((grupo, item), [])
            linhas.append({"item": item, "valores": v, "total": round(sum(v), 2), "categorias": [c["categoria"] for c in cats],
                           "a_confirmar": any(not c["confirmado"] for c in cats), "sem_klingo": not cats and grupo != SEM_DESTINO})
        tot = [round(sum(l["valores"][i] for l in linhas), 2) for i in range(len(ordem))]
        grupos.append({"grupo": grupo, "itens": linhas, "totais": tot, "total": round(sum(tot), 2)})
    geral = [round(sum(g["totais"][i] for g in grupos), 2) for i in range(len(ordem))]
    meses = [{"ym": ym, "rotulo": pc.rotulo_mes(ym), "fonte": "planilha" if ym in com_planilha else "klingo",
              "situacao": "em_curso" if ym == ym_hoje else "fechado"} for ym in ordem]
    sem_klingo = [l["item"] for g in grupos for l in g["itens"] if l["sem_klingo"] and any(v for v in l["valores"])]
    usadas = set(por_cat.index.get_level_values(0)) if len(por_cat) else set()
    a_confirmar = sorted(c for c, dst in de_para.items() if not dst["confirmado"] and c in usadas)
    return {"ok": True, "fonte_base": base["fonte"], "meses": meses, "grupos": grupos, "geral": geral, "total": round(sum(geral), 2), "inicio_klingo": pc.rotulo_mes(inicio),
            "sem_destino": [{"categoria": c, "valor": round(v, 2)} for c, v in sorted(sem_destino.items(), key=lambda x: -x[1])],
            "itens_sem_klingo": sem_klingo, "categorias_a_confirmar": a_confirmar}


# ---------------------------------------------------------------- fornecedores a vencer no mês, com a divisão CSI / CSI 2
def _indice_regras(base: dict) -> dict[tuple[str, str | None], dict]:
    idx: dict[tuple[str, str | None], dict] = {}
    for f in base["fornecedores"]:
        for r in f["regras"]:
            idx[(_norm(r["fornecedor"]), _norm(r["categoria"]) if r.get("categoria") else None)] = f
    return idx


def montar_fornecedores(d: pd.DataFrame, lanc: pd.DataFrame | None, base: dict, inicio: str, ym_hoje: str) -> dict:
    if lanc is None or not len(lanc) or not set(COLUNAS_LANC) <= set(lanc.columns):
        return {"ok": False, "motivo": "Ainda não há lançamentos do Financeiro (#798) guardados. Abra o painel Financeiro ou use Atualizar agora."}
    x = lanc[lanc["Tipo"].map(_norm) == "DESPESAS"].copy()
    x = x[x["Empresa"].fillna("").astype(str).str.strip() == EMPRESA_RATEIO]
    x = x[x["Vencimento"].notna()].drop_duplicates(subset=["Lançamento"], keep="last")
    x["_ym"] = x["Vencimento"].dt.strftime("%Y-%m")
    forn_de = {}
    if len(d) and "ID" in d.columns:
        com_id = d[d["ID"].notna()]
        forn_de = {int(i): (str(f).strip() if isinstance(f, str) and f.strip() else FORN_SEM_ID) for i, f in zip(com_id["ID"], com_id["Fornecedor"])}
    idx = _indice_regras(base)
    ordem = {f["nome"]: f for f in base["fornecedores"]}
    saida: dict[str, dict] = {}
    for ym in pc.meses_entre(inicio, pc.mes_mais(ym_hoje, MESES_A_FRENTE_FORN)):
        mes = x[x["_ym"] == ym]
        soma_lista: dict[str, dict] = {n: {"total": 0.0, "qtd": 0} for n in ordem}
        outros: dict[str, dict] = {}
        sem_id = 0
        for _, r in mes.iterrows():
            valor = float(r["Valor"]) if pd.notna(r["Valor"]) else 0.0
            lid = int(r["Lançamento"]) if pd.notna(r["Lançamento"]) else None
            forn = forn_de.get(lid) if lid is not None else None
            if forn is None:
                sem_id += 1
                forn = FORN_SEM_ID
            cat = _norm(r["Categoria"])
            alvo = idx.get((_norm(forn), cat)) or idx.get((_norm(forn), None))
            if alvo:
                soma_lista[alvo["nome"]]["total"] += valor
                soma_lista[alvo["nome"]]["qtd"] += 1
            else:
                o = outros.setdefault(forn, {"nome": forn, "total": 0.0, "qtd": 0})
                o["total"] += valor
                o["qtd"] += 1
        lista = []
        for nome, f in ordem.items():
            t = round(soma_lista[nome]["total"], 2)
            csi = round(t * f["pct_csi"] / 100, 2)
            lista.append({"nome": nome, "total": t, "qtd": soma_lista[nome]["qtd"], "pct_csi": f["pct_csi"], "csi": csi, "csi2": round(t - csi, 2), "ligado": bool(f["regras"])})
        total = round(sum(l["total"] for l in lista), 2)
        outros_l = sorted(({"nome": o["nome"], "total": round(o["total"], 2), "qtd": o["qtd"]} for o in outros.values()), key=lambda o: -o["total"])
        saida[ym] = {"rotulo": pc.rotulo_mes(ym), "lista": lista, "total": total, "csi": round(sum(l["csi"] for l in lista), 2), "csi2": round(sum(l["csi2"] for l in lista), 2),
                     "outros": outros_l, "total_outros": round(sum(o["total"] for o in outros_l), 2), "qtd_lancamentos": int(len(mes)), "sem_fornecedor": sem_id}
    return {"ok": True, "meses": saida, "empresa": EMPRESA_RATEIO}


def montar(d: pd.DataFrame, lanc: pd.DataFrame | None, inicio: str, ym_hoje: str) -> dict:
    """{"matriz": ..., "fornecedores": ...}; nunca levanta: falha vira {"ok": False, "motivo": ...} na parte que falhou."""
    try:
        base = carregar_base()
    except Exception as e:   # noqa: BLE001 (a aba nao pode derrubar o painel)
        motivo = f"Não consegui ler a base da planilha ({type(e).__name__}: {e})."
        return {"matriz": {"ok": False, "motivo": motivo}, "fornecedores": {"ok": False, "motivo": motivo}}
    saida = {}
    for nome, fn in (("matriz", lambda: montar_matriz(d, base, inicio, ym_hoje)), ("fornecedores", lambda: montar_fornecedores(d, lanc, base, inicio, ym_hoje))):
        try:
            saida[nome] = fn()
        except Exception as e:   # noqa: BLE001
            print(f">>> AVISO: aba Planilha ({nome}): {type(e).__name__}: {e}", flush=True)
            saida[nome] = {"ok": False, "motivo": f"Erro ao montar esta parte ({type(e).__name__}: {e})."}
    return saida
