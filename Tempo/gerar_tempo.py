"""Tempo: ciclo do atendimento (TAT), espera, ociosidade e horário de pico, tudo medido HORA A HORA.

Não tem relatório próprio: lê as abas "Atendimentos" (#13402) e "Fluxo na Recepção" (#13404) que o painel Atendimento já guarda
(no Supabase `painel_dados` do painel `atendimento`, ou no Atendimento.xlsx do programa local), então não duplica dado no banco e
a página se refaz sozinha quando o Atendimento é atualizado (armazenamento.DEPENDENCIAS). "Atualizar agora" aqui atualiza o Atendimento.

As contas ficam em metricas_tempo.py (pandas puro, com testes): Check-In → fim de Finalizado (TAT), Check-In → início de Em Atendimento
(espera), fila (etapa Chamado), pacientes simultâneos por hora, ocupação dos equipamentos e a cerca de outliers. A "hora" é a do Check-In.

Uso:  python gerar_tempo.py             regenera o dashboard com o que já está guardado
      python gerar_tempo.py --forcar    atualiza o Atendimento (consulta o Klingo) e regenera
"""
import json
import os
import pickle
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PASTA = Path(__file__).parent
RAIZ = PASTA.parent
ATENDIMENTO = RAIZ / "Atendimento"
for pasta in (RAIZ, PASTA):
    if str(pasta) not in sys.path:
        sys.path.insert(0, str(pasta))
import klingo_relatorios as k  # noqa: E402
import metricas_tempo as mt  # noqa: E402
import painel_comum as pc  # noqa: E402

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Tempo.html"
PARAMETROS = PASTA / "parametros.json"
METAS = RAIZ / "Acompanhamento de META" / "metas.json"
ARQUIVOS_EXTRAS = (PARAMETROS,)    # o portal refaz a pagina quando este muda
ABA_FLUXO = "Fluxo na Recepção"
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
# Os limites que o painel Atendimento já usa valem aqui também (uma fonte só); parametros.json do Tempo só acrescenta/sobrepõe.
HERDADOS = ("espera_meta_min", "espera_critica_min", "espera_valida_max_min", "permanencia_valida_max_min", "etapa_aberta_max_min", "exame_valido_max_min",
            "equipamentos", "prefixos_equipamento", "setores_fluxo")
PADRAO = {
    "espera_meta_min": 30, "espera_critica_min": 60, "espera_valida_max_min": 480, "permanencia_valida_max_min": 720, "etapa_aberta_max_min": 1440,
    "exame_valido_max_min": 360,
    "equipamentos": ["RM", "RX", "TC", "DENSITOMETRIA", "MAMOGRAFIA"], "prefixos_equipamento": ["ULTRASSONOGRAFIA ", "ELETRO"],
    "setores_fluxo": {"CSI": "CSI 1", "CSI - 2": "CSI 2", "PEDIATRIA": "CSI Pediatria"},
    "metodo_outlier": "iqr", "piso_outlier_min": 5, "minimo_pico": 10, "minimo_celula_mapa": 5, "tolerancia_ocupacao_min": 0,
}


def lido_com_cache(arquivo, nome: str, ler):
    """Como no Atendimento: ler dezenas de milhares de linhas é lento; guarda o resultado (pickle) ao lado e só lê de novo quando os dados mudam."""
    cache = PASTA / f".cache_{nome}.pkl"
    try:
        st = arquivo.stat()
        chave = (st.st_mtime_ns, st.st_size)
    except OSError:
        return ler()
    try:
        with open(cache, "rb") as f:
            guardado = pickle.load(f)
        if guardado.get("chave") == chave:
            return guardado["dados"]
    except Exception:
        pass
    dados = ler()
    try:
        temporario = cache.with_suffix(".tmp")
        with open(temporario, "wb") as f:
            pickle.dump({"chave": chave, "dados": dados}, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporario, cache)
    except Exception:    # pasta so de leitura (Vercel): funciona sem o cache, so mais devagar
        pass
    return dados


def arquivo_dados():
    return k.planilha_de(ATENDIMENTO)


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    """Os dados são os do Atendimento: atualizar aqui é atualizar lá (a página do Tempo se refaz em seguida)."""
    return k.atualizar(ATENDIMENTO, forcar=forcar, historico=historico)


def ler_json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def ler_parametros() -> dict:
    p = dict(PADRAO)
    p.update({c: v for c, v in ler_json(ATENDIMENTO / "parametros.json").items() if c in HERDADOS})
    p.update({c: v for c, v in ler_json(PARAMETROS).items() if not c.startswith("_")})
    return p


def ler_calendario() -> dict:
    """Expediente, dias de atendimento e feriados: os mesmos do painel de Metas (metas.json)."""
    cfg = ler_json(METAS)
    horario = cfg.get("horario_atendimento", ["07:00", "18:00"])
    return {"expediente": (int(horario[0][:2]), int(horario[1][:2])), "dias_uteis": tuple(cfg.get("dias_semana_atendimento", [0, 1, 2, 3, 4, 5])),
            "feriados": tuple(cfg.get("feriados", []))}


# ---------------------------------------------------------------- utilidades
def num(v):
    """Número JSON: NaN/None viram None; float arredondado a 1 casa (minutos) para a página ficar leve."""
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else round(float(v), 1)


def inteiro(v) -> int:
    return 0 if v is None or pd.isna(v) else int(v)


def mediana(s: pd.Series):
    s = s.dropna()
    return num(s.median()) if len(s) else None


def p90(s: pd.Series):
    s = s.dropna()
    return num(s.quantile(0.9)) if len(s) else None


def pct_de(parte, total):
    return round(float(parte) / float(total) * 100, 1) if total else None


def resumo(s: pd.Series, meta: float | None = None) -> dict:
    s = s.dropna()
    return {"n": int(len(s)), "med": mediana(s), "p90": p90(s), "acima": pct_de((s > meta).sum(), len(s)) if meta is not None and len(s) else None}


def nome_do_dia(i: int) -> str:
    return DIAS_SEMANA[int(i)]


# ---------------------------------------------------------------- preparo
def preparar(abas: dict, p: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(etapas, atendimentos, usos de equipamento, todos os Em Atendimento) do #13404, já com as cercas de outlier.
    Atendimentos sem nenhum horário utilizável são descartados (não há como medir a hora)."""
    fluxo = abas.get(ABA_FLUXO, pd.DataFrame())
    vazio = pd.DataFrame()
    obrig = ["Data do Atendimento", "Profissional / Equipamento", "Convênio", "Etapa", "Início da Etapa", "Fim da Etapa", "Setor (CSI/RM/RX/TC)"]
    if not len(fluxo) or any(c not in fluxo for c in obrig):
        return vazio, vazio, vazio, vazio
    etapas, usos = mt.adaptar_fluxo_klingo(fluxo, p["equipamentos"], p["prefixos_equipamento"], p["setores_fluxo"])
    etapas = etapas[etapas["inicio"].notna()]
    if not len(etapas):
        return vazio, vazio, vazio, vazio
    atend_todos = etapas[etapas["etapa"] == "Em Atendimento"]
    usos = usos[usos["inicio"].notna()]
    e, v, u = mt.preparar_base(etapas, usos, p["metodo_outlier"], p["piso_outlier_min"], p["etapa_aberta_max_min"],
                               {"Em Atendimento": p["exame_valido_max_min"]},
                               {"tat_min": p["permanencia_valida_max_min"], "espera_min": p["espera_valida_max_min"], "fila_min": p["espera_valida_max_min"]})
    v["dia"] = v["chegada"].dt.normalize()
    v["ym"] = v["chegada"].dt.strftime("%Y-%m")
    e["ym"] = e["inicio"].dt.strftime("%Y-%m")
    return e, v, u, atend_todos


# ---------------------------------------------------------------- uma fatia (mês ou período)
def horas_do_dia(v: pd.DataFrame, n_dias: int, cargas: dict[str, pd.Series], meta: float) -> list[dict]:
    """Uma linha por hora do dia: chegadas, esperas, TAT e quantos pacientes (em média) há na clínica, na fila e em atendimento."""
    pf = mt.perfil_por_hora(v)
    out = []
    for r in pf.itertuples():
        h = int(r.hora)
        valido = v[(v["chegada"].dt.hour == h) & ~v["espera_outlier"]]["espera_min"].dropna()
        out.append({"h": h, "n": int(r.n), "por_dia": round(r.n / n_dias, 1) if n_dias else None, "outliers": int(r.n_outliers),
                    "esp_n": int(r.espera_min_n), "esp_med": num(r.espera_min_mediana), "esp_p90": num(r.espera_min_p90),
                    "esp_acima": pct_de((valido > meta).sum(), len(valido)) if len(valido) else None,
                    "fila_med": num(r.fila_min_mediana), "fila_p90": num(r.fila_min_p90),
                    "tat_med": num(r.tat_min_mediana), "tat_p90": num(r.tat_min_p90),
                    "horas_espera": round(r.espera_min_soma / 60, 1),
                    "na_clinica": num(cargas["clinica"].get(h)), "na_fila": num(cargas["fila"].get(h)), "em_atendimento": num(cargas["atendimento"].get(h))})
    return out


def mapa_semana(v: pd.DataFrame, minimo: int) -> list[dict]:
    pf = mt.perfil_por_hora(v, por=("dia_semana", "hora"))
    return [{"d": int(r.dia_semana), "h": int(r.hora), "n": int(r.n), "esp_med": num(r.espera_min_mediana) if r.espera_min_n >= minimo else None,
             "esp_p90": num(r.espera_min_p90) if r.espera_min_n >= minimo else None} for r in pf.itertuples()]


def por_dia(v: pd.DataFrame, p: dict) -> list[dict]:
    """Um ponto por dia: chegadas, espera, TAT e a hora de maior espera do dia (a hora de pico do gargalo)."""
    if not len(v):
        return []
    jan = mt.resumo_por_janela(v, mt.METRICAS, "h", por=())
    pico = mt.pico_de_gargalo(jan, "espera_min", n_min=p["minimo_pico"], por=())
    pico = {r.dia: r for r in pico.itertuples()}
    out = []
    for dia, g in v.groupby("dia"):
        r = pico.get(dia)
        out.append({"d": dia.strftime("%Y-%m-%d"), "n": int(len(g)), "esp_med": mediana(g["espera_min"].where(~g["espera_outlier"])),
                    "esp_p90": p90(g["espera_min"].where(~g["espera_outlier"])), "tat_med": mediana(g["tat_min"].where(~g["tat_outlier"])),
                    "outliers": int(g[["tat_outlier", "espera_outlier", "fila_outlier"]].any(axis=1).sum()),
                    "pico_h": int(r.hora_pico.hour) if r is not None else None, "pico_p90": num(r.valor_pico_min) if r is not None else None,
                    "pico_n": int(r.n) if r is not None else None, "dom": bool(dia.weekday() == 6)})
    return out


def por_setor(v: pd.DataFrame, p: dict) -> list[dict]:
    out = []
    for nome, g in v.groupby("setor"):
        horas = mt.perfil_por_hora(g)
        horas = horas[horas["espera_min_n"] >= p["minimo_pico"]]
        pior = horas.loc[horas["espera_min_p90"].idxmax()] if len(horas) else None
        esp = g["espera_min"].where(~g["espera_outlier"])
        out.append({"nome": str(nome), "n": int(len(g)), "esp_med": mediana(esp), "esp_p90": p90(esp), "fila_med": mediana(g["fila_min"].where(~g["fila_outlier"])),
                    "tat_med": mediana(g["tat_min"].where(~g["tat_outlier"])), "tat_p90": p90(g["tat_min"].where(~g["tat_outlier"])),
                    "pior_h": int(pior["hora"]) if pior is not None else None, "pior_p90": num(pior["espera_min_p90"]) if pior is not None else None,
                    "outliers": int(g[["tat_outlier", "espera_outlier", "fila_outlier"]].any(axis=1).sum())})
    out.sort(key=lambda r: -(r["esp_med"] if r["esp_med"] is not None else -1))
    return out


def limites_da_fatia(e: pd.DataFrame) -> list[dict]:
    """A cerca de cada etapa e quantos casos ela descartou: é o "como tratamos os encerramentos esquecidos" da tela."""
    out = []
    for (etapa, setor), g in e.groupby(["etapa", "setor"]):
        out.append({"etapa": str(etapa), "setor": str(setor), "n": int(g["dur_min"].notna().sum()), "outliers": int(g["dur_outlier"].sum()),
                    "med": mediana(g["dur_min"].where(~g["dur_outlier"])), "limite": num(g["dur_limite"].iloc[0]),
                    "maior": num(g["dur_min"].max())})
    out.sort(key=lambda r: (-r["outliers"], r["etapa"]))
    return out


def equipamentos_da_fatia(u: pd.DataFrame, atend: pd.DataFrame, periodo: tuple[date, date], cal: dict, p: dict) -> dict:
    """Ocupação dos equipamentos que o relatório identifica. ATENÇÃO: só parte dos exames traz o equipamento (nos demais a coluna traz o
    nome do profissional), então os percentuais valem para os exames identificados e a `cobertura` diz quanto isso representa."""
    total_por_setor = atend.groupby("setor").size()
    ident = u.groupby("setor").size()
    cobertura = [{"setor": str(s), "identificados": int(ident.get(s, 0)), "total": int(t), "pct": pct_de(ident.get(s, 0), t)} for s, t in total_por_setor.items()]
    cobertura.sort(key=lambda c: c["setor"])
    if not len(u):
        return {"recursos": [], "horas": [], "cobertura": cobertura}
    ini, fim = pd.Timestamp(periodo[0]), pd.Timestamp(periodo[1]) + pd.Timedelta(days=1)
    horas = mt.ocupacao_por_janela(mt.intervalos_de_uso(u, (ini, fim), tolerancia=pd.Timedelta(minutes=p["tolerancia_ocupacao_min"])),
                                   cal["expediente"], cal["dias_uteis"], cal["feriados"])
    if not len(horas):
        return {"recursos": [], "horas": [], "cobertura": cobertura}
    horas["hora"] = horas["janela"].dt.hour
    recursos = []
    for nome, g in horas.groupby("recurso"):
        recursos.append({"nome": str(nome), "setor": str(g["setor"].iloc[0]) if "setor" in g else "", "usos": int((u["recurso"] == nome).sum()),
                         "min_ocupado": num(g["min_ocupado"].sum()), "min_ocioso": num(g["min_ocioso"].sum()), "min_disponivel": num(g["min_disponivel"].sum()),
                         "pct_ocioso": num(100 * g["min_ocioso"].sum() / g["min_disponivel"].sum()) if g["min_disponivel"].sum() else None})
    recursos.sort(key=lambda r: -(r["pct_ocioso"] or 0))
    celulas = horas.groupby(["recurso", "hora"]).agg(oc=("min_ocupado", "sum"), disp=("min_disponivel", "sum")).reset_index()
    return {"recursos": recursos, "cobertura": cobertura,
            "horas": [{"r": str(c.recurso), "h": int(c.hora), "pct_ocupado": num(100 * c.oc / c.disp) if c.disp else None} for c in celulas.itertuples()]}


def leituras(k_: dict, horas: list[dict], dias: list[dict], p: dict) -> list[dict]:
    """Frases prontas sobre o que os números dizem (a leitura automática da tela). Só afirma o que os dados mostram."""
    out = []
    com_esp = [h for h in horas if h["esp_p90"] is not None and h["esp_n"] >= p["minimo_pico"]]
    if com_esp:
        pior = max(com_esp, key=lambda h: h["esp_p90"])
        nivel = "critico" if pior["esp_p90"] > 2 * p["espera_critica_min"] else "atencao" if pior["esp_p90"] > p["espera_critica_min"] else "info"
        out.append({"nivel": nivel, "texto": f"A pior hora para chegar é <b>{pior['h']:02d}h</b>: 90% dos pacientes que chegam nela esperam até <b>{pior['esp_p90']:.0f} min</b> "
                                             f"(mediana {pior['esp_med']:.0f} min, {pior['n']} chegadas)."})
    if horas:
        cheia = max(horas, key=lambda h: h["n"])
        out.append({"nivel": "info", "texto": f"A hora mais cheia é <b>{cheia['h']:02d}h</b>, com <b>{cheia['por_dia']:.0f}</b> chegadas por dia em média "
                                              f"({pct_de(cheia['n'], sum(h['n'] for h in horas)):.0f}% de todas as chegadas)."})
    com_pico = [d for d in dias if d["pico_h"] is not None]
    if len(com_pico) >= 3:
        contagem = pd.Series([d["pico_h"] for d in com_pico]).value_counts()
        h, n = int(contagem.index[0]), int(contagem.iloc[0])
        out.append({"nivel": "info", "texto": f"O gargalo do dia cai às <b>{h:02d}h</b> em <b>{n}</b> de {len(com_pico)} dias com movimento suficiente."})
    if k_["outliers"]:
        out.append({"nivel": "info", "texto": f"<b>{k_['outliers']}</b> atendimentos ({k_['outliers_pct']:.1f}%) tinham um tempo muito acima do normal da etapa (encerramento esquecido, "
                                              f"por exemplo) e ficaram de fora das medianas. Veja a cerca de cada etapa em Detalhes."})
    return out


def montar_fatia(rotulo: str, v: pd.DataFrame, e: pd.DataFrame, u: pd.DataFrame, atend: pd.DataFrame, periodo: tuple[date, date], p: dict, cal: dict,
                 hoje: date, mensal: bool) -> dict:
    """Tudo o que a tela mostra para um mês (ou período): `v` = atendimentos que chegaram nele; `e`, `u` e `atend` = etapas e usos do mesmo recorte."""
    meta = p["espera_meta_min"]
    n_dias = int(v["dia"].nunique())
    ok = v[~v["tat_outlier"]]
    # pacientes simultâneos por hora: na clinica (chegada até o fim de Finalizado), na fila (Chamado) e em atendimento (Em Atendimento)
    clinica = ok[ok["saida"].notna()][["chegada", "saida"]].rename(columns={"chegada": "inicio", "saida": "fim"})
    fila = e[(e["etapa"] == "Chamado") & ~e["dur_outlier"]][["inicio", "fim"]].dropna()
    em_atend = e[(e["etapa"] == "Em Atendimento") & ~e["dur_outlier"]][["inicio", "fim"]].dropna()
    cargas = {"clinica": mt.carga_por_hora(clinica, n_dias), "fila": mt.carga_por_hora(fila, n_dias), "atendimento": mt.carga_por_hora(em_atend, n_dias)}
    horas = horas_do_dia(v, n_dias, cargas, meta)
    dias = por_dia(v, p)
    esp, tat, fila_s = v["espera_min"].where(~v["espera_outlier"]), v["tat_min"].where(~v["tat_outlier"]), v["fila_min"].where(~v["fila_outlier"])
    teve_outlier = v[["tat_outlier", "espera_outlier", "fila_outlier"]].any(axis=1)
    com_p90 = [h for h in horas if h["esp_p90"] is not None and h["esp_n"] >= p["minimo_pico"]]
    pior = max(com_p90, key=lambda h: h["esp_p90"]) if com_p90 else None
    cheia = max(horas, key=lambda h: h["n"]) if horas else None
    kp = {"n": int(len(v)), "dias": n_dias, "por_dia": round(len(v) / n_dias, 1) if n_dias else None,
          "tat": resumo(tat), "espera": resumo(esp, meta), "fila": resumo(fila_s, meta),
          "horas_espera": round(float(esp.dropna().sum()) / 60, 1), "outliers": int(teve_outlier.sum()), "outliers_pct": pct_de(teve_outlier.sum(), len(v)),
          "pior_hora": pior["h"] if pior else None, "pior_hora_p90": pior["esp_p90"] if pior else None, "pior_hora_med": pior["esp_med"] if pior else None,
          "hora_cheia": cheia["h"] if cheia else None, "hora_cheia_dia": cheia["por_dia"] if cheia else None,
          "sem_saida": int((v["saida"].isna() & (v["dia"] < pd.Timestamp(hoje))).sum()), "abertos": int(v["aberto"].sum())}
    return {"rotulo": rotulo, "kpis": kp, "horas": horas, "semana": mapa_semana(v, p["minimo_celula_mapa"]), "setores": por_setor(v, p),
            "dias": dias if mensal else [], "limites": limites_da_fatia(e), "equipamentos": equipamentos_da_fatia(u, atend, periodo, cal, p),
            "leituras": leituras(kp, horas, dias, p)}


# ---------------------------------------------------------------- montagem
def fatia_de(ym_ou_periodo, e, v, u, atend, p, cal, hoje, rotulo, periodo_dias, mensal=True):
    if isinstance(ym_ou_periodo, str):
        vv, ee, uu, aa = v[v["ym"] == ym_ou_periodo], e[e["ym"] == ym_ou_periodo], u[u["inicio"].dt.strftime("%Y-%m") == ym_ou_periodo], atend[atend["inicio"].dt.strftime("%Y-%m") == ym_ou_periodo]
    else:   # Periodo (vários meses ou dias exatos): a data de cada linha decide
        per = ym_ou_periodo
        vv, ee, uu, aa = v[per.dentro(v["chegada"])], e[per.dentro(e["inicio"])], u[per.dentro(u["inicio"])], atend[per.dentro(atend["inicio"])]
    if not len(vv):
        return None
    return montar_fatia(rotulo, vv, ee, uu, aa, periodo_dias, p, cal, hoje, mensal)


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` = período pedido no filtro; com `devolver_html` devolve a página (texto) em vez de gravar."""
    agora = datetime.now()
    hoje = agora.date()
    p, cal = ler_parametros(), ler_calendario()
    abas = lido_com_cache(arquivo_dados(), "tempo", lambda: k.carregar(ATENDIMENTO))
    e, v, u, atend = preparar(abas, p)
    meses = {}
    if len(v):
        for ym in sorted(v["ym"].unique()):
            ini = date(int(ym[:4]), int(ym[5:]), 1)
            fim = pc.Periodo(ym, ym).dia_fim
            f = fatia_de(ym, e, v, u, atend, p, cal, hoje, pc.rotulo_mes(ym), (ini, min(fim, hoje)))
            if f:
                f["fechado"] = fim < hoje
                meses[ym] = f
    per, info = pc.periodo_pedido(de, ate, meses)
    if per and not per.unico:
        def montar(q):
            f = fatia_de(q, e, v, u, atend, p, cal, hoje, q.rotulo, (q.dia_ini, min(q.dia_fim, hoje)), mensal=False)
            return {**(f or {"rotulo": q.rotulo, "kpis": None, "horas": [], "semana": [], "setores": [], "dias": [], "limites": [], "equipamentos": {}, "leituras": []}),
                    "fechado": q.fechado(hoje)}
        pc.acrescentar_periodo(meses, per, montar)
    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else agora
    payload = {"gerado_em": agora.strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"), "versao": int(dados_em.timestamp()),
               "hoje": hoje.isoformat(), "mes_padrao": per.chave if per else (max(m for m in meses if ".." not in m) if meses else None), "periodo": info,
               "meses": meses, "tem_dados": bool(meses),
               "limites": {c: p[c] for c in ("espera_meta_min", "espera_critica_min", "espera_valida_max_min", "permanencia_valida_max_min", "etapa_aberta_max_min",
                                              "exame_valido_max_min", "piso_outlier_min", "minimo_pico", "minimo_celula_mapa")},
               "expediente": list(cal["expediente"]), "dias_uteis": list(cal["dias_uteis"]), "metodo": p["metodo_outlier"]}
    pagina = pc.montar_html(MODELO, payload)
    if devolver_html:
        return pagina
    SAIDA.write_text(pagina, encoding="utf-8")
    return SAIDA


def main():
    args = set(sys.argv[1:])
    if args & {"--forcar", "--historico"}:
        print(">>>", atualizar(forcar=True, historico="--historico" in args)["mensagem"])
    saida = gerar()
    print(">>> Dashboard gerado:", saida)
    if "--sem-abrir" not in args:
        webbrowser.open(saida.as_uri())


if __name__ == "__main__":
    main()
