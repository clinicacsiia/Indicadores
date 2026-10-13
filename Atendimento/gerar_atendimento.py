"""Atendimento: onde os registros erram, espera, duracao, produtividade por profissional e revisao das metas.

Fonte: relatorio #13402 "Atendimentos - Visao Gerencial de Produtividade, Espera e Receita - Mensal" (uma linha por
procedimento atendido). As metas vem do painel de Metas (metas.json e a planilha da base #13339); este painel so le.

O relatorio nao traz o Id do atendimento nem o paciente. Por isso:
  - "atendimento" = uma linha do relatorio (um procedimento), igual ao que o painel de Metas conta;
  - espera e duracao sao medidas uma vez por "execucao" (mesmo registro, usuario, profissional, inicio e fim),
    para um paciente com 3 exames seguidos nao pesar 3 vezes.
Espera = Inicio - Data do Atendimento (hora do registro). Duracao = Fim - Inicio. A coluna "Duracao" do Klingo nao bate
com nenhuma diferenca entre os horarios (mediana 62 min contra 22 min de Fim - Inicio): o painel mostra as duas.

Uso:  python gerar_atendimento.py             so regenera o dashboard com o que ja esta na planilha
      python gerar_atendimento.py --forcar    consulta o Klingo agora (como o botao) e regenera
"""
import html
import json
import os
import pickle
import sys
import webbrowser
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PASTA = Path(__file__).parent
sys.path.insert(0, str(PASTA.parent))
import klingo_relatorios as k  # noqa: E402
import painel_comum as pc  # noqa: E402
import guia_pendencias as gp  # noqa: E402
import gerar_dashboard as gd  # noqa: E402  (metas, calendario e norm do painel de Metas)

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Atendimento.html"
PARAMETROS = PASTA / "parametros.json"
RESPONSAVEIS = PASTA / "responsaveis.json"
ARQUIVOS_EXTRAS = (PARAMETROS, RESPONSAVEIS)    # o portal refaz a pagina quando um destes muda
ABA = "Atendimentos"
# quem cuida de que (usado se o responsaveis.json nao existir); "setores" sao os nomes dos grupos do metas.json
RESPONSAVEIS_PADRAO = [
    {"id": "juliana", "nome": "Juliana", "area": "Call center e recepção da ressonância", "setores": ["CSI 2"],
     "obs": "Nenhuma coluna dos relatórios identifica o call center: por enquanto esta visão mostra a recepção da ressonância e tomografia (CSI 2)."},
    {"id": "carla", "nome": "Carla", "area": "Pediatria", "setores": ["CSI Pediatria"]},
    {"id": "luzia", "nome": "Luzia", "area": "CSI 1", "setores": ["CSI 1"]},
]

C_DATA, C_SETOR, C_ESP, C_PROF = "Data do Atendimento", "Setor (CSI/RM/RX/TC)", "Especialidade", "Profissional / Equipamento"
C_CONV, C_PROC, C_STATUS, C_USER = "Convênio", "Procedimento", "Status do Atendimento", "Usuário Responsável"
C_VALOR, C_INI, C_FIM, C_DUR = "Valor do Atendimento", "Início do Atendimento", "Fim do Atendimento", "Duração do Atendimento (min)"
OBRIGATORIAS = [C_DATA, C_SETOR, C_ESP, C_PROF, C_CONV, C_PROC, C_STATUS, C_USER, C_VALOR, C_INI, C_FIM]

TOLERANCIA_MIN = 5          # o registro pode ser feito poucos minutos depois de o exame comecar
ATRASO_STATUS_DIAS = 7      # "Aberta" ha mais que isso ja nao e um atendimento em andamento
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
NIVEL = {"critico": 0, "atencao": 1, "info": 2}
PADRAO = {
    "espera_meta_min": 30, "espera_critica_min": 60, "espera_valida_max_min": 480, "exame_valido_max_min": 360,
    "duracao_vs_pares": 1.5, "duracao_minimo_atendimentos": 20,
    "produtividade_baixa_pct": 60, "produtividade_minimo_dias": 3, "produtividade_minimo_pares": 3,
    "problema_atencao_pct": 3, "problema_critico_pct": 10, "valor_zero_atencao_pct": 1, "horario_atencao_pct": 0.5,
    "meta_baixa_pct": 130, "meta_alta_pct": 60, "diferenca_metas_pct": 5,
    "equipamentos": ["RM", "RX", "TC", "DENSITOMETRIA", "MAMOGRAFIA"], "prefixos_equipamento": ["ULTRASSONOGRAFIA ", "ELETRO"],
    "etapa_aberta_max_min": 1440, "permanencia_valida_max_min": 720, "ea_curta_atencao_pct": 30, "sem_finalizado_atencao_pct": 3,
    "setores_fluxo": {"CSI": "CSI 1", "CSI - 2": "CSI 2", "PEDIATRIA": "CSI Pediatria"},
}
ABA_FLUXO = "Fluxo na Recepção"
CHAVE_VISITA = [C_DATA, C_PROF, C_CONV]   # o #13404 nao traz o Id do atendimento: a visita e achada por registro + profissional + convenio
ETAPAS_FLUXO = ["Cadastro", "Procedimentos", "Guia", "Pagamento", "Pré-Atendimento Iniciado", "Chamado Pré-Atendimento", "Finalizado Pré-Atendimento",
                "Chamado", "Em Atendimento", "Finalizado", "Pausado", "Não Compareceu"]   # ordem em que aparecem no fluxo


def arquivo_dados() -> Path:
    return k.planilha_de(PASTA)


def lido_com_cache(arquivo: Path, nome: str, ler):
    """Ler 45 mil linhas de Excel leva ~20 s; guarda o resultado (pickle) ao lado e so le o Excel de novo quando o arquivo muda (data e tamanho)."""
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
    except Exception:    # pasta so de leitura: funciona sem o cache, so mais devagar
        pass
    return dados


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    return k.atualizar(PASTA, forcar=forcar, historico=historico)


# ---------------------------------------------------------------- utilidades
def ler_parametros() -> dict:
    p = dict(PADRAO)
    try:
        p.update({c: v for c, v in json.loads(PARAMETROS.read_text(encoding="utf-8-sig")).items() if not c.startswith("_")})
    except (OSError, ValueError):
        pass
    return p


def ler_responsaveis(cfg: dict) -> list[dict]:
    """Quem cuida de cada parte do atendimento (responsaveis.json). Cada pessoa vira uma visao do painel, so com os setores dela."""
    try:
        lista = json.loads(RESPONSAVEIS.read_text(encoding="utf-8-sig")).get("responsaveis", [])
    except (OSError, ValueError):
        lista = RESPONSAVEIS_PADRAO
    existentes = {g["nome"] for g in cfg.get("grupos", [])}
    out, vistos = [], set()
    for r in lista:
        setores = [s for s in r.get("setores", []) if s in existentes]
        ident = str(r.get("id") or r.get("nome", "")).strip().lower()
        if not ident or ident in vistos or not setores:
            print(f">>> AVISO (responsaveis.json): ignorei {r.get('nome') or ident!r}: sem id, repetido ou sem nenhum setor que exista no metas.json ({sorted(existentes)})", file=sys.stderr, flush=True)
            continue
        vistos.add(ident)
        out.append({"id": ident, "nome": r.get("nome", ident), "area": r.get("area", ""), "setores": setores, "obs": r.get("obs", "")})
    return out


def tem_colunas(df: pd.DataFrame, *colunas: str) -> bool:
    return len(df) > 0 and all(c in df.columns for c in colunas)


def esc(v) -> str:
    return html.escape(str(v))


def pct_de(parte, total) -> float:
    return float(parte) / float(total) * 100 if total else 0.0


def txt_pct(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + "%"


def txt_min(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:.0f} min".replace(".", ",") if v < 100 else f"{v / 60:.1f} h".replace(".", ",")


def nz(v):
    return None if v is None or pd.isna(v) else float(v)


def mediana(s: pd.Series):
    s = s.dropna()
    return float(s.median()) if len(s) else None


def p90(s: pd.Series):
    s = s.dropna()
    return float(np.percentile(s, 90)) if len(s) else None


def top_texto(serie: pd.Series, n: int = 3) -> str:
    return ", ".join(f"{esc(nome)} ({qtd})" for nome, qtd in serie.value_counts().head(n).items())


def pessoa(login) -> str:
    return str(login).replace(".", " ").title() if login is not None else ""


def eh_equipamento(nome, p: dict) -> bool:
    n = gd.norm(nome)
    return n in {gd.norm(e) for e in p["equipamentos"]} or any(n.startswith(gd.norm(pf)) for pf in p["prefixos_equipamento"])


def calendario(ym: str, cfg: dict, agora: datetime, yms: list[str] | None = None) -> tuple[int, float, bool]:
    """(dias uteis do mes, dias uteis ja decorridos, mes fechado) com a mesma regra do painel de Metas. Com `yms` (periodo de varios meses),
    "ym" e o ultimo mes e os dias uteis somam os de todos."""
    ano, mes = int(ym[:4]), int(ym[5:])
    semana = set(cfg.get("dias_semana_atendimento", [0, 1, 2, 3, 4, 5]))
    feriados = {date.fromisoformat(f) for f in cfg.get("feriados", [])}
    uteis = [d for y in (yms or [ym]) for d in gd.dias_uteis(int(y[:4]), int(y[5:]), semana, feriados)]
    hoje = agora.date()
    fechado = date(ano, mes, monthrange(ano, mes)[1]) < hoje
    if fechado:
        return len(uteis), float(len(uteis)), True
    dec = float(sum(1 for d in uteis if d < hoje))
    if hoje in uteis:
        dec += gd.fracao_do_dia(agora, cfg)
    return len(uteis), dec, False


# ---------------------------------------------------------------- preparo dos dados
def preparar_fluxo(f: pd.DataFrame, p: dict, hoje: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(etapas, visitas) do #13404. Uma visita = registro + profissional + convenio, com os horarios de cada etapa.
    O tempo de cada etapa e recalculado de Fim - Inicio (as colunas calculadas do Klingo vem erradas)."""
    obrig = [C_DATA, C_PROF, C_CONV, "Etapa", "Check-In", "Início da Etapa", "Fim da Etapa", C_SETOR]
    if not tem_colunas(f, *obrig):
        return f.iloc[0:0], f.iloc[0:0]
    e = f.copy()
    e["_dt"] = pd.to_datetime(e[C_DATA], errors="coerce")
    e = e[e["_dt"].notna()].copy()
    if not len(e):
        return e, e
    for col in (C_PROF, C_CONV, "Etapa"):
        e[col] = e[col].fillna("(sem informação)").astype(str).str.strip()
    e["_fila"] = e["Fila"].fillna("").astype(str).str.strip() if "Fila" in e else ""
    e["_setor"] = e[C_SETOR].map(lambda s: p["setores_fluxo"].get(str(s).strip(), str(s)))
    e["_ym"] = e["_dt"].dt.strftime("%Y-%m")
    e["_tempo"] = (e["Fim da Etapa"] - e["Início da Etapa"]).dt.total_seconds() / 60
    e["_aberta"] = e["_tempo"] > p["etapa_aberta_max_min"]           # etapa que ninguem encerrou (ex.: pagamento esquecido por dias)
    e["_t"] = e["_tempo"].where((e["_tempo"] >= 0) & ~e["_aberta"])
    g = e.groupby(CHAVE_VISITA, dropna=False)
    v = g.agg(checkin=("Check-In", "min"), setor=("_setor", "first"), ym=("_ym", "first"), n_etapas=("Etapa", "size"), aberta=("_aberta", "any")).reset_index()
    for etapa, rotulo in [("Cadastro", "cad"), ("Chamado", "cha"), ("Em Atendimento", "ea"), ("Finalizado", "fin")]:
        s = e[e["Etapa"] == etapa].groupby(CHAVE_VISITA, dropna=False)
        v = v.merge(s["Início da Etapa"].min().rename("ini_" + rotulo).reset_index(), on=CHAVE_VISITA, how="left")
        v = v.merge(s["_t"].sum(min_count=1).rename("t_" + rotulo).reset_index(), on=CHAVE_VISITA, how="left")
    v = v.merge(e[e["Etapa"] == "Finalizado"].groupby(CHAVE_VISITA, dropna=False)["Fim da Etapa"].max().rename("fim_fin").reset_index(), on=CHAVE_VISITA, how="left")
    fila = e[(e["Etapa"] == "Chamado") & (e["_fila"] != "")].groupby(CHAVE_VISITA, dropna=False)["_fila"].first().rename("fila").reset_index()
    v = v.merge(fila, on=CHAVE_VISITA, how="left")

    def minutos(a, b, maximo):                 # b - a em minutos; negativo dentro da tolerancia vira 0, fora dela e acima do maximo vira vazio
        d = (v[b] - v[a]).dt.total_seconds() / 60
        return d.where((d >= -TOLERANCIA_MIN) & (d <= maximo)).clip(lower=0)
    v["esp_recep"] = minutos("checkin", "ini_cad", p["espera_valida_max_min"])        # Check-In ate comecar o cadastro
    v["esp_total"] = minutos("checkin", "ini_ea", p["espera_valida_max_min"])         # Check-In ate comecar o atendimento
    v["esp_chamado"] = v["t_cha"].where(v["t_cha"] <= p["espera_valida_max_min"])     # tempo na fila para ser chamado
    v["permanencia"] = minutos("checkin", "fim_fin", p["permanencia_valida_max_min"])
    v["_dia"] = v[C_DATA].dt.normalize()
    antigo = v["_dia"] < pd.Timestamp(hoje)
    v["sem_checkin"] = v["checkin"].isna() & antigo
    v["sem_final"] = v["ini_fin"].isna() & antigo & v["ini_ea"].notna()   # chegou a ser atendido e nao foi finalizado
    v["ea_curta"] = v["t_ea"].notna() & (v["t_ea"] < 1)
    return e, v


def preparar(df: pd.DataFrame, p: dict, cfg: dict, hoje: date, visitas: pd.DataFrame | None = None) -> pd.DataFrame:
    if not tem_colunas(df, *OBRIGATORIAS):
        return df.iloc[0:0]
    x = df.copy()
    x["_dt"] = pd.to_datetime(x[C_DATA], errors="coerce")
    x = x[x["_dt"].notna()].copy()
    if not len(x):
        return x
    nomes_setor = {gd.norm(g["unidade"]): g["nome"] for g in cfg.get("grupos", [])}
    x["_setor"] = x[C_SETOR].map(lambda s: nomes_setor.get(gd.norm(s), pc.nome_curto_unidade(s)))
    for col in (C_ESP, C_PROF, C_CONV, C_PROC, C_USER, C_STATUS):
        x[col] = x[col].fillna("(sem informação)").astype(str).str.strip()
    x["_ym"] = x["_dt"].dt.strftime("%Y-%m")
    x["_dia"] = x["_dt"].dt.normalize()
    x["_valor"] = pd.to_numeric(x[C_VALOR], errors="coerce")
    x["_equip"] = x[C_PROF].map(lambda n: eh_equipamento(n, p))
    esp = (x[C_INI] - x["_dt"]).dt.total_seconds() / 60
    exa = (x[C_FIM] - x[C_INI]).dt.total_seconds() / 60
    x["_esp"], x["_exa"] = esp, exa
    antigo = x["_dia"] < pd.Timestamp(hoje)           # o que e de hoje pode ainda nao ter comecado ou terminado
    x["_sem_ini"] = x[C_INI].isna() & antigo
    x["_sem_fim"] = x[C_FIM].isna() & antigo
    x["_valor0"] = x["_valor"] == 0
    x["_esp_neg"] = esp < -TOLERANCIA_MIN
    x["_esp_alta"] = esp > p["espera_valida_max_min"]
    x["_exa_inc"] = (exa < 0) | (exa > p["exame_valido_max_min"])
    x["_incoerente"] = x["_esp_neg"] | x["_esp_alta"] | x["_exa_inc"]
    x["_fim_junto"] = (exa >= 0) & (exa < 1)         # inicio e fim marcados no mesmo minuto: nenhum atendimento dura menos que isso
    x["_problema"] = x["_sem_ini"] | x["_sem_fim"] | x["_valor0"] | x["_incoerente"] | x["_fim_junto"]
    x["_esp_v"] = esp.where((esp >= -TOLERANCIA_MIN) & (esp <= p["espera_valida_max_min"])).clip(lower=0)
    x["_exa_v"] = exa.where((exa >= 1) & (exa <= p["exame_valido_max_min"]))
    x["_exec"] = ~x.duplicated([C_DATA, C_USER, C_PROF, C_INI, C_FIM])   # 1 por execucao, para espera e duracao
    abre = int(cfg.get("horario_atendimento", ["07:00", "18:00"])[0][:2])
    fecha = int(cfg.get("horario_atendimento", ["07:00", "18:00"])[1][:2])
    semana = set(cfg.get("dias_semana_atendimento", [0, 1, 2, 3, 4, 5]))
    feriados = {pd.Timestamp(f) for f in cfg.get("feriados", [])}
    x["_hora"] = x["_dt"].dt.hour
    x["_sem"] = x["_dt"].dt.weekday
    x["_fora_exp"] = (x["_hora"] < abre) | (x["_hora"] >= fecha)
    x["_sem_exp"] = ~x["_sem"].isin(semana) | x["_dia"].isin(feriados)
    x["_teste"] = x[[C_PROF, C_USER, C_CONV]].apply(lambda c: c.map(gd.norm).str.contains("TESTE", regex=False)).any(axis=1)
    x["_ci"], x["_fluxo"] = pd.NaT, False
    if visitas is not None and len(visitas):     # com o fluxo (#13404), a espera passa a ser a real: do Check-In ao inicio do atendimento
        x = x.merge(visitas[CHAVE_VISITA + ["checkin", "esp_total", "esp_recep", "esp_chamado", "permanencia"]], on=CHAVE_VISITA, how="left")
        x["_ci"], x["_fluxo"], x["_esp_v"] = x["checkin"], x["esp_total"].notna() | x["checkin"].notna(), x["esp_total"]
    return x


# ---------------------------------------------------------------- tabelas do mes
def stats_tempo(m: pd.DataFrame, meta_min: float) -> dict:
    e = m[m["_exec"]]
    ev, xv = e["_esp_v"].dropna(), e["_exa_v"].dropna()
    return {"esp_n": int(len(ev)), "esp_med": mediana(ev), "esp_p90": p90(ev),
            "esp_acima": pct_de((ev > meta_min).sum(), len(ev)) if len(ev) else None,
            "exa_n": int(len(xv)), "exa_med": mediana(xv), "exa_p90": p90(xv)}


def tabela_tempo(m: pd.DataFrame, por, p: dict, minimo: int = 1) -> list[dict]:
    """Espera e duracao por grupo, do pior (maior espera mediana) para o melhor."""
    linhas = []
    for nome, g in m.groupby(por, dropna=False):
        if len(g) < minimo:
            continue
        linhas.append({"nome": str(nome), "n": int(len(g)), **stats_tempo(g, p["espera_meta_min"])})
    linhas.sort(key=lambda r: (-(r["esp_med"] if r["esp_med"] is not None else -1), -r["n"]))
    return linhas


def por_usuario(m: pd.DataFrame) -> list[dict]:
    out = []
    for nome, g in m.groupby(C_USER):
        sem_h = g["_sem_ini"] | g["_sem_fim"]
        out.append({"nome": str(nome), "n": int(len(g)), "sem_horario": int(sem_h.sum()), "valor_zero": int(g["_valor0"].sum()),
                    "incoerente": int(g["_incoerente"].sum()), "fim_junto": int(g["_fim_junto"].sum()), "problemas": int(g["_problema"].sum()),
                    "pct": pct_de(g["_problema"].sum(), len(g)), "setor": g["_setor"].value_counts().index[0]})
    out.sort(key=lambda r: (-r["problemas"], -r["n"]))
    return out


def por_setor(m: pd.DataFrame, ant: dict | None, dec: float, p: dict) -> list[dict]:
    out = []
    for nome, g in m.groupby("_setor"):
        ritmo = len(g) / dec if dec >= 0.5 else None
        ritmo_ant = ant["setores"].get(nome) if ant else None
        out.append({"nome": str(nome), "n": int(len(g)), "receita": float(g["_valor"].fillna(0).sum()), "ritmo": ritmo, "ritmo_ant": ritmo_ant,
                    "delta": (ritmo / ritmo_ant - 1) * 100 if ritmo is not None and ritmo_ant else None,
                    "problemas": int(g["_problema"].sum()), "pct": pct_de(g["_problema"].sum(), len(g)), **stats_tempo(g, p["espera_meta_min"])})
    out.sort(key=lambda r: -r["n"])
    return out


def por_pessoa(m: pd.DataFrame, p: dict) -> tuple[list[dict], list[dict]]:
    """Profissionais e equipamentos, com a produtividade (atendimentos por dia) e a comparacao com os colegas da especialidade."""
    linhas = []
    for nome, g in m.groupby(C_PROF):
        dias = int(g["_dia"].nunique())
        stt = stats_tempo(g, p["espera_meta_min"])
        linhas.append({"nome": str(nome), "equip": bool(g["_equip"].iloc[0]), "esp": g[C_ESP].value_counts().index[0], "setor": g["_setor"].value_counts().index[0],
                       "n": int(len(g)), "dias": dias, "por_dia": len(g) / dias if dias else 0.0, "receita": float(g["_valor"].fillna(0).sum()),
                       "ticket": float(g["_valor"].fillna(0).sum() / len(g)), "problemas": int(g["_problema"].sum()), "pct": pct_de(g["_problema"].sum(), len(g)), **stt})
    # colegas = profissionais (nao aparelhos) da mesma especialidade, com dias suficientes
    elegiveis = pd.DataFrame([l for l in linhas if not l["equip"] and l["dias"] >= p["produtividade_minimo_dias"]])
    pares = {}
    if len(elegiveis):
        for esp, grupo in elegiveis.groupby("esp"):
            if len(grupo) >= p["produtividade_minimo_pares"]:
                pares[esp] = float(grupo["por_dia"].median())
    for l in linhas:
        ref = pares.get(l["esp"]) if not l["equip"] and l["dias"] >= p["produtividade_minimo_dias"] else None
        l["ref_pares"] = ref
        l["vs_pares"] = l["por_dia"] / ref * 100 if ref else None
        sit, pontos = [], 0
        if l["esp_med"] is not None and l["esp_n"] >= 10:
            if l["esp_med"] > p["espera_critica_min"]:
                sit.append("espera"); pontos += 2
            elif l["esp_med"] > p["espera_meta_min"]:
                sit.append("espera"); pontos += 1
        if l["n"] >= 10 and l["pct"] >= p["problema_critico_pct"]:     # com menos de 10 atendimentos o percentual diz pouco
            sit.append("registro"); pontos += 2
        elif l["n"] >= 10 and l["pct"] >= p["problema_atencao_pct"]:
            sit.append("registro"); pontos += 1
        l["situacoes"], l["prioridade"] = sit, pontos
    linhas.sort(key=lambda r: (-r["receita"], -r["n"]))
    return [l for l in linhas if not l["equip"]], [l for l in linhas if l["equip"]]


def contagem_mes(m: pd.DataFrame, chave: str, dec: float, ant: dict | None, campo: str, top: int | None = None) -> list[dict]:
    tot = len(m)
    out = []
    for nome, g in m.groupby(chave):
        ritmo = len(g) / dec if dec >= 0.5 else None
        ref = ant[campo].get(nome) if ant else None
        out.append({"nome": str(nome), "n": int(len(g)), "pct": pct_de(len(g), tot), "receita": float(g["_valor"].fillna(0).sum()),
                    "ticket": float(g["_valor"].fillna(0).sum() / len(g)), "delta": (ritmo / ref - 1) * 100 if ritmo is not None and ref else None})
    out.sort(key=lambda r: -r["n"])
    return out[:top]


def por_dia(m: pd.DataFrame, p: dict) -> list[dict]:
    out = []
    for dia, g in m.groupby("_dia"):
        ev = g[g["_exec"]]["_esp_v"].dropna()
        out.append({"d": dia.strftime("%Y-%m-%d"), "n": int(len(g)), "receita": float(g["_valor"].fillna(0).sum()),
                    "esp_med": mediana(ev), "problemas": int(g["_problema"].sum()), "dom": bool(g["_sem_exp"].iloc[0])})
    return out


def resumo_tempo(s: pd.Series, meta: float | None = None) -> dict:
    s = s.dropna()
    return {"n": int(len(s)), "med": mediana(s), "p90": p90(s), "acima": pct_de((s > meta).sum(), len(s)) if meta is not None and len(s) else None}


def tabela_visitas(mv: pd.DataFrame, por, p: dict, minimo: int = 10) -> list[dict]:
    """Espera real (Check-In ate o inicio) por grupo de visitas, da maior para a menor. Mesmos campos da tabela_tempo, para o painel usar igual."""
    out = []
    for nome, g in mv.groupby(por):
        s = g["esp_total"].dropna()
        if len(s) < minimo:
            continue
        out.append({"nome": str(nome), "n": int(len(g)), "esp_n": int(len(s)), "esp_med": mediana(s), "esp_p90": p90(s),
                    "esp_acima": pct_de((s > p["espera_meta_min"]).sum(), len(s)), "exa_med": None, "exa_p90": None})
    out.sort(key=lambda r: -r["esp_med"])
    return out


def montar_fluxo(mv: pd.DataFrame, me: pd.DataFrame, p: dict) -> dict:
    """Fluxo do paciente no mes (#13404): quanto espera em cada trecho, quanto tempo cada etapa leva e onde o registro foge do padrao."""
    meta = p["espera_meta_min"]
    ea = mv[mv["t_ea"].notna()]
    kp = {"visitas": int(len(mv)), "esp_total": resumo_tempo(mv["esp_total"], meta), "esp_recep": resumo_tempo(mv["esp_recep"], 15),
          "esp_chamado": resumo_tempo(mv["esp_chamado"], meta), "permanencia": resumo_tempo(mv["permanencia"]),
          "sem_checkin": int(mv["sem_checkin"].sum()), "ea_n": int(len(ea)), "ea_curta": int(ea["ea_curta"].sum()),
          "sem_final": int(mv["sem_final"].sum()), "aberta": int(mv["aberta"].sum())}
    total = float(me["_t"].sum())
    etapas = []
    for ordem, etapa in enumerate(ETAPAS_FLUXO + sorted(set(me["Etapa"]) - set(ETAPAS_FLUXO))):
        s = me[me["Etapa"] == etapa]
        if not len(s):
            continue
        t = s["_t"].dropna()
        etapas.append({"nome": etapa, "ordem": ordem, "n": int(len(s)), "med": mediana(t), "p90": p90(t), "horas": float(t.sum() / 60),
                       "pct_tempo": pct_de(t.sum(), total), "abertas": int(s["_aberta"].sum())})
    etapas.sort(key=lambda r: -r["horas"])
    setores = []
    for nome, g in mv.groupby("setor"):
        e_ = g[g["t_ea"].notna()]
        setores.append({"nome": str(nome), "n": int(len(g)), "recep": mediana(g["esp_recep"]), "recep_p90": p90(g["esp_recep"]), "chamado": mediana(g["esp_chamado"]),
                        "chamado_p90": p90(g["esp_chamado"]), "total": mediana(g["esp_total"]), "total_p90": p90(g["esp_total"]), "perm": mediana(g["permanencia"]),
                        "ea_curta": pct_de(e_["ea_curta"].sum(), len(e_)) if len(e_) else None})
    setores.sort(key=lambda r: -(r["total"] if r["total"] is not None else -1))
    filas = []
    for nome, g in mv[mv["fila"].notna()].groupby("fila"):
        if len(g) >= 10:
            filas.append({"nome": str(nome), "n": int(len(g)), "chamado": mediana(g["esp_chamado"]), "chamado_p90": p90(g["esp_chamado"]), "total": mediana(g["esp_total"]),
                          "acima": pct_de((g["esp_chamado"].dropna() > meta).sum(), g["esp_chamado"].notna().sum())})
    filas.sort(key=lambda r: -(r["chamado"] if r["chamado"] is not None else -1))
    return {"kpis": kp, "etapas": etapas, "setores": setores, "filas": filas}


def resumo_anterior(m: pd.DataFrame, ym_ant: str, cfg: dict, agora: datetime, yms_ant: list[str] | None = None) -> dict | None:
    """Ritmo por dia util do mes anterior (por setor, convenio e procedimento), para dizer se subiu ou caiu. Num periodo de varios
    meses, `ym_ant` e o ultimo mes do periodo anterior e `yms_ant` sao os meses dele."""
    a = m[m["_ym"].isin(yms_ant or [ym_ant])]
    if not len(a):
        return None
    uteis, dec, _ = calendario(ym_ant, cfg, agora, yms_ant)
    if dec < 1:
        return None
    return {"ritmo": len(a) / dec, "uteis": uteis,
            "setores": (a.groupby("_setor").size() / dec).to_dict(),
            "convenios": (a.groupby(C_CONV).size() / dec).to_dict(),
            "procedimentos": (a.groupby(C_PROC).size() / dec).to_dict()}


# ---------------------------------------------------------------- metas (lidas do painel de Metas)
def metas_do_mes(df_metas: pd.DataFrame, ym: str, cfg: dict, agora: datetime, dec: float, setores_13402: pd.Series, p: dict, per: pc.Periodo | None = None) -> dict | None:
    dm = df_metas[df_metas["Data do Atendimento"].dt.strftime("%Y-%m").isin(per.yms if per else [ym])] if len(df_metas) else df_metas
    if not len(dm):
        return None
    r = gd.montar_mes(dm, ym, cfg, agora, [], per=per)
    itens = []
    for g in r["grupos"]:
        for it in g["itens"]:
            ref = it["realizado"] if r["fechado"] else it.get("projecao")
            ratio = pct_de(ref, it["meta"]) if ref is not None and it["meta"] else None
            leitura = None
            if ratio is not None and (r["fechado"] or dec >= 5):   # a projecao dos primeiros dias do mes oscila demais para julgar a meta
                leitura = "baixa" if ratio >= p["meta_baixa_pct"] else "alta" if ratio <= p["meta_alta_pct"] else None
            media = it["realizado"] / dec if dec >= 0.5 else None
            itens.append({**it, "grupo": g["nome"], "ref": ref, "ratio": ratio, "leitura": leitura, "media_dia": media,
                          "acelerar": (it["por_dia"] / media - 1) * 100 if it.get("por_dia") and media else None})
    ordem = {"atrasado": 0, "atencao": 1, "ritmo": 2, "batida": 3}
    por_unid = dm.groupby("Unidade").size()
    conf = []
    for g in r["grupos"]:
        n_metas = int(por_unid.get(g["unidade"], 0))
        n_atend = int(setores_13402.get(g["nome"], 0))
        conf.append({"nome": g["nome"], "unidade": g["unidade"], "n_atend": n_atend, "n_metas": n_metas,
                     "dif": pct_de(n_atend - n_metas, n_metas) if n_metas else None})
    r["itens"] = sorted(itens, key=lambda i: (ordem[i["status"]], -i["faltam"]))
    r["conferencia"] = conf
    r["fora"] = r["fora"][:12]
    r["fora_pct"] = pct_de(r["total_fora"], r["total_atendimentos"])
    return r


# ---------------------------------------------------------------- alertas
def tabela_registros(df: pd.DataFrame, detalhe: str, fn) -> dict:
    d = df.sort_values("_dt", ascending=False)
    linhas = [[r["_dt"].strftime("%d/%m/%Y %H:%M"), r["_setor"], r[C_PROF], r[C_PROC], r[C_CONV], pessoa(r[C_USER]), fn(r)] for _, r in d.head(gp.MAX_ITENS).iterrows()]
    return gp.tabela(["Data e hora do registro", "Setor", "Profissional / equipamento", "Procedimento", "Convênio", "Usuário responsável", detalhe], linhas, total=len(d))


def nivel_por_pct(pc_: float, p: dict, atencao_key: str = "problema_atencao_pct") -> str:
    return "critico" if pc_ >= p["problema_critico_pct"] else "atencao" if pc_ >= p[atencao_key] else "info"


def alertas_do_mes(m: pd.DataFrame, rot: str, p: dict, hoje: date, ctx: dict) -> list[dict]:
    n = len(m)
    out = []

    def novo(nivel, titulo, texto, impacto, itens=None):
        a = {"nivel": nivel, "titulo": titulo, "texto": texto, "_impacto": float(impacto)}
        if itens is not None:
            a["itens"] = itens
        out.append(a)

    # 1) status que nunca muda
    abertas = m[m[C_STATUS].map(gd.norm) == "ABERTA"]
    velhas = abertas[abertas["_dia"] < pd.Timestamp(hoje) - pd.Timedelta(days=ATRASO_STATUS_DIAS)]
    if len(velhas) and pct_de(len(velhas), n) >= 20:
        status = ", ".join(f"{esc(s)} ({q})" for s, q in m[C_STATUS].value_counts().items())
        novo("atencao", "Atendimentos que nunca foram encerrados",
             f"<b>{len(velhas)}</b> atendimentos de {rot} ({txt_pct(pct_de(len(velhas), n))}) estão há mais de {ATRASO_STATUS_DIAS} dias com status <b>Aberta</b>. Status no mês: {status}. "
             f"Se o Klingo só muda esse status em outra etapa (fechamento da conta, por exemplo), confirme com o suporte e marque como resolvido.", len(velhas))

    # 2) sem horario de inicio ou fim
    sem_h = m[m["_sem_ini"] | m["_sem_fim"]]
    if len(sem_h):
        pc_ = pct_de(len(sem_h), n)
        novo(nivel_por_pct(pc_, p), "Atendimentos sem horário de início ou de fim",
             f"<b>{len(sem_h)}</b> atendimentos ({txt_pct(pc_)}) sem horário de início (<b>{int(m['_sem_ini'].sum())}</b>) ou de fim (<b>{int(m['_sem_fim'].sum())}</b>); "
             f"sem eles não dá para medir espera nem duração. Usuários com mais casos: {top_texto(sem_h[C_USER].map(pessoa))}. Por setor: {top_texto(sem_h['_setor'])}.",
             len(sem_h), tabela_registros(sem_h, "O que falta", lambda r: "início e fim" if r["_sem_ini"] and r["_sem_fim"] else "início" if r["_sem_ini"] else "fim"))

    # 3) valor zero
    v0 = m[m["_valor0"]]
    if len(v0):
        pc_ = pct_de(len(v0), n)
        novo("critico" if pc_ >= p["problema_critico_pct"] else "atencao" if pc_ >= p["valor_zero_atencao_pct"] else "info", "Atendimentos com valor R$ 0,00",
             f"<b>{len(v0)}</b> atendimentos ({txt_pct(pc_)}) com valor zero. Convênios: {top_texto(v0[C_CONV])}. Procedimentos: {top_texto(v0[C_PROC], 2)}. "
             f"Pode ser cortesia ou retorno; se for preço que falta na tabela do convênio, o faturamento deixa de receber.",
             len(v0), tabela_registros(v0, "Valor", lambda r: "R$ 0,00"))

    # 4) horarios incoerentes
    inc = m[m["_incoerente"]]
    if len(inc):
        pc_ = pct_de(len(inc), n)

        def porque(r):
            t = []
            if r["_esp_neg"]:
                t.append(f"início {abs(r['_esp']):.0f} min antes do registro")
            if r["_esp_alta"]:
                t.append(f"início {r['_esp'] / 60:.1f} h depois do registro")
            if r["_exa_inc"]:
                t.append("fim antes do início" if r["_exa"] < 0 else f"duração de {r['_exa'] / 60:.1f} h")
            return "; ".join(t)
        novo("critico" if pc_ >= p["problema_critico_pct"] else "atencao" if pc_ >= p["horario_atencao_pct"] else "info", "Horários incoerentes nos atendimentos",
             f"<b>{len(inc)}</b> atendimentos ({txt_pct(pc_)}) com horário que não faz sentido. Início antes do registro: <b>{int(inc['_esp_neg'].sum())}</b>. "
             f"Início mais de {p['espera_valida_max_min'] / 60:.0f} h depois do registro: <b>{int(inc['_esp_alta'].sum())}</b>. "
             f"Fim antes do início ou duração acima de {p['exame_valido_max_min'] / 60:.0f} h: <b>{int(inc['_exa_inc'].sum())}</b>. "
             f"Ficam fora das médias de espera e duração. Usuários com mais casos: {top_texto(inc[C_USER].map(pessoa))}.",
             len(inc), tabela_registros(inc, "Por quê", porque))

    # 4b) inicio e fim marcados juntos
    junto = m[m["_fim_junto"]]
    if len(junto):
        pc_ = pct_de(len(junto), n)
        piores = junto.groupby(C_ESP).size().div(m.groupby(C_ESP).size()).mul(100).sort_values(ascending=False)
        piores = piores[m.groupby(C_ESP).size().reindex(piores.index) >= 10].head(3)
        novo(nivel_por_pct(pc_, p), "Início e fim marcados no mesmo minuto",
             f"<b>{len(junto)}</b> atendimentos ({txt_pct(pc_)}) têm menos de 1 minuto entre o início e o fim: o início e o fim foram marcados juntos, então a duração real não existe. "
             + (f"Especialidades com mais casos: {', '.join(f'{esc(e)} ({v:.0f}%)' for e, v in piores.items())}. " if len(piores) else "")
             + f"Usuários com mais casos: {top_texto(junto[C_USER].map(pessoa))}. Ficam fora das médias de duração.",
             len(junto), tabela_registros(junto, "Duração", lambda r: f"{r['_exa'] * 60:.0f} s"))

    # 4c) fluxo (#13404)
    fx, mv, me = ctx["fluxo"], ctx["mv"], ctx["me"]
    if fx:
        nv = len(mv)

        def tab_visitas(df, detalhe, fn):
            d = df.sort_values(C_DATA, ascending=False)
            linhas = [[r[C_DATA].strftime("%d/%m/%Y %H:%M"), r["setor"], r[C_PROF], r[C_CONV], fn(r)] for _, r in d.head(gp.MAX_ITENS).iterrows()]
            return gp.tabela(["Data e hora do registro", "Setor", "Profissional / equipamento", "Convênio", detalhe], linhas, total=len(d))
        sc = mv[mv["sem_checkin"]]
        if len(sc):
            pc_ = pct_de(len(sc), nv)
            novo(nivel_por_pct(pc_, p), "Atendimentos sem Check-In",
                 f"<b>{len(sc)}</b> atendimentos ({txt_pct(pc_)}) não têm Check-In: sem ele não dá para medir a espera real do paciente. Por setor: {top_texto(sc['setor'])}. "
                 f"Profissionais com mais casos: {top_texto(sc[C_PROF].map(lambda n: n if eh_equipamento(n, p) else n.title()))}.",
                 len(sc), tab_visitas(sc, "Etapas", lambda r: f"{int(r['n_etapas'])} etapa(s)"))
        ab = me[me["_aberta"]]
        if len(ab):
            v_ab = mv[mv["aberta"]]
            pc_ = pct_de(len(v_ab), nv)
            novo("atencao" if pc_ >= 1 else "info", "Etapas deixadas em aberto no fluxo",
                 f"<b>{len(ab)}</b> etapas de <b>{len(v_ab)}</b> atendimentos ({txt_pct(pc_)}) ficaram mais de {p['etapa_aberta_max_min'] / 60:.0f} h sem serem encerradas: "
                 + ", ".join(f"{esc(e)} ({q})" for e, q in ab["Etapa"].value_counts().head(4).items())
                 + ". Elas ficam fora das médias de tempo; o paciente já foi embora, mas o fluxo não fechou.", len(v_ab),
                 gp.tabela(["Data e hora do registro", "Setor", "Profissional / equipamento", "Convênio", "Etapa", "Tempo aberta"],
                           [[r[C_DATA].strftime("%d/%m/%Y %H:%M"), r["_setor"], r[C_PROF], r[C_CONV], r["Etapa"], f"{r['_tempo'] / 1440:.1f} dias"] for _, r in ab.sort_values("_tempo", ascending=False).iterrows()],
                           total=len(ab), numericas=(5,)))
        ea = mv[mv["t_ea"].notna()]
        if len(ea):
            curta = ea[ea["ea_curta"]]
            pc_ = pct_de(len(curta), len(ea))
            if pc_ >= p["ea_curta_atencao_pct"]:
                prof = curta.groupby(C_PROF).size().div(ea.groupby(C_PROF).size()).mul(100)
                prof = prof[ea.groupby(C_PROF).size().reindex(prof.index) >= 20].sort_values(ascending=False).head(4)
                novo("atencao", "Etapa Em Atendimento dura só segundos",
                     f"Em <b>{len(curta)}</b> de {len(ea)} atendimentos ({txt_pct(pc_)}) a etapa <b>Em Atendimento</b> dura menos de 1 minuto: ela é aberta e fechada quase no mesmo instante, então não mede o exame. "
                     + (f"Mais frequente em: {', '.join(f'{esc(n.title())} ({v:.0f}%)' for n, v in prof.items())}. " if len(prof) else "")
                     + "Para a duração, o painel usa o início de Em Atendimento até o fim de Finalizado (o mesmo intervalo do relatório de Atendimentos).", len(curta),
                     tab_visitas(curta, "Em Atendimento", lambda r: f"{r['t_ea'] * 60:.0f} s"))
        sf = mv[mv["sem_final"]]
        if len(sf):
            base_ = int(mv["ini_ea"].notna().sum())
            pc_ = pct_de(len(sf), base_)
            novo(nivel_por_pct(pc_, p, "sem_finalizado_atencao_pct"), "Atendimentos sem a etapa Finalizado",
                 f"<b>{len(sf)}</b> atendimentos ({txt_pct(pc_)} dos que chegaram a ser atendidos) começaram, têm mais de 1 dia e nunca chegaram a <b>Finalizado</b>. Por setor: {top_texto(sf['setor'])}.",
                 len(sf), tab_visitas(sf, "Etapas registradas", lambda r: f"{int(r['n_etapas'])} etapa(s)"))
        sem_par = m[~m["_fluxo"] & (m["_dia"] < pd.Timestamp(hoje))]
        chaves_m = set(map(tuple, m[CHAVE_VISITA].itertuples(index=False, name=None)))
        so_fluxo = mv[[tuple(k_) not in chaves_m for k_ in mv[CHAVE_VISITA].itertuples(index=False, name=None)]]
        pa, pb = pct_de(len(sem_par), n), pct_de(len(so_fluxo), nv)
        if max(pa, pb) > p["diferenca_metas_pct"]:
            novo("atencao", "Fluxo e atendimento não batem",
                 f"<b>{len(sem_par)}</b> atendimentos do relatório de Atendimentos ({txt_pct(pa)}) não têm fluxo no relatório de Fluxo do Paciente e <b>{len(so_fluxo)}</b> atendimentos do fluxo ({txt_pct(pb)}) não aparecem no relatório de Atendimentos. "
                 f"A ligação é por data do registro, profissional e convênio. Sem fluxo, o atendimento fica sem espera real.", len(sem_par) + len(so_fluxo),
                 tab_visitas(so_fluxo, "Só no fluxo", lambda r: "não está no relatório de Atendimentos"))

    # 5) espera acima do aceitavel
    esp_setor = ctx["espera_setor"]
    lista = [r for r in esp_setor if r["esp_med"] is not None and r["esp_med"] > p["espera_meta_min"]]
    lista += [r for r in ctx["espera_esp"] if r["esp_med"] is not None and r["esp_med"] > p["espera_meta_min"] and r["n"] >= 30]
    if lista:
        critico = any(r["esp_med"] > p["espera_critica_min"] for r in esp_setor if r["esp_med"] is not None)
        geral = ctx["kpis"]
        piores = sorted(lista, key=lambda r: -r["esp_med"])[:3]
        hora = max((h for h in ctx["espera_hora"] if h["esp_med"] is not None and h["esp_n"] >= 30), key=lambda h: h["esp_med"], default=None)
        novo("critico" if critico else "atencao", "Espera acima do aceitável",
             f"Mediana de espera do mês{' (do Check-In ao início do atendimento)' if fx else ''}: <b>{txt_min(geral['esp_med'])}</b> (90% esperam até {txt_min(geral['esp_p90'])}); o aceitável é {p['espera_meta_min']} min. "
             f"Pior: " + ", ".join(f"{esc(r['nome'])} <b>{txt_min(r['esp_med'])}</b>" for r in piores) +
             (f". Horário de {'check-in' if fx else 'registro'} mais lento: <b>{hora['nome']}</b> ({txt_min(hora['esp_med'])})" if hora else "") +
             (f". Onde o tempo se perde: recepção <b>{txt_min(fx['kpis']['esp_recep']['med'])}</b> até começar o cadastro e <b>{txt_min(fx['kpis']['esp_chamado']['med'])}</b> na fila para ser chamado (mediana)." if fx else "."),
             sum(r["n"] for r in esp_setor if r["esp_med"] is not None and r["esp_med"] > p["espera_meta_min"]) or len(m),
             gp.tabela(["Onde", "Atendimentos", "Espera mediana", "90% esperam até", "Acima de " + str(p["espera_meta_min"]) + " min"],
                       [[r["nome"], r["n"], txt_min(r["esp_med"]), txt_min(r["esp_p90"]), txt_pct(r["esp_acima"]) if r["esp_acima"] is not None else ""]
                        for r in sorted(lista, key=lambda r: -r["esp_med"])], numericas=(1, 2, 3, 4)))

    # 6) duracao muito maior que a dos pares
    longos = ctx["duracao_longa"]
    if longos:
        novo("info", "Duração muito maior que a dos colegas",
             f"<b>{len(longos)}</b> profissional(is) ou equipamento(s) levam mais de {str(p['duracao_vs_pares']).replace('.', ',')}x a duração mediana da própria especialidade: "
             + ", ".join(f"{esc(l['nome'])} (<b>{txt_min(l['exa_med'])}</b> contra {txt_min(l['ref'])})" for l in longos[:4]) + ".",
             sum(l["n"] for l in longos),
             gp.tabela(["Profissional / equipamento", "Especialidade", "Atendimentos", "Duração mediana", "Mediana da especialidade", "Vezes"],
                       [[l["nome"], l["esp"], l["n"], txt_min(l["exa_med"]), txt_min(l["ref"]), f"{l['exa_med'] / l['ref']:.1f}".replace(".", ",") + "x"] for l in longos], numericas=(2, 3, 4, 5)))

    # 8) queda em relacao ao mes anterior
    k_ = ctx["kpis"]
    if k_["delta_ritmo"] is not None and ctx["dec"] >= 3 and k_["delta_ritmo"] < -10:
        piores = sorted([s for s in ctx["setores"] if s["delta"] is not None and s["delta"] < -10], key=lambda s: s["delta"])
        novo("critico" if k_["delta_ritmo"] < -25 else "atencao", "Atendimentos abaixo do mês anterior",
             f"O ritmo é de <b>{num_br(k_['ritmo'], 0)}</b> atendimentos por dia útil, contra {num_br(k_['ritmo_ant'], 0)} no mês anterior (<b>{k_['delta_ritmo']:+.0f}%</b>)"
             + (". Mais afetados: " + ", ".join(f"{esc(s['nome'])} ({s['delta']:+.0f}%)" for s in piores[:3]) if piores else "") + ".",
             abs(k_["delta_ritmo"]) / 100 * n,
             gp.tabela(["Setor", "Por dia útil agora", "Por dia útil no mês anterior", "Variação"],
                       [[s["nome"], num_br(s["ritmo"], 0), num_br(s["ritmo_ant"], 0), f"{s['delta']:+.0f}%"] for s in ctx["setores"] if s["delta"] is not None], numericas=(1, 2, 3)))

    # 9, 10, 11, 12) metas
    mt = ctx["metas"]
    if mt:
        abaixo = [i for i in mt["itens"] if i["status"] in ("atrasado", "atencao")]
        if abaixo:
            grupo_atrasado = any(g["status"] == "atrasado" for g in mt["grupos"])
            novo("critico" if grupo_atrasado else "atencao", "Metas de atendimento abaixo do ritmo",
                 (f"<b>{len(abaixo)}</b> de {len(mt['itens'])} metas ficaram abaixo do que se esperava em {rot}: " if mt["fechado"] else
                  f"<b>{len(abaixo)}</b> de {len(mt['itens'])} metas abaixo do ritmo esperado ({txt_pct(mt['esperado_pct'])} do mês já passou): ")
                 + ", ".join(f"{esc(i['nome'])} <b>{i['pct']:.0f}%</b>" for i in abaixo[:4]) + f". {'Faltaram' if mt['fechado'] else 'Faltam'} <b>{sum(i['faltam'] for i in abaixo)}</b> atendimentos no total.",
                 sum(i["faltam"] for i in abaixo),
                 gp.tabela(["Setor", "Meta", "Meta (qtd)", "Realizado", "% da meta", "Faltam", "Por dia útil para bater"],
                           [[i["grupo"], i["nome"], i["meta"], i["realizado"], f"{i['pct']:.0f}%", i["faltam"], i["por_dia"] if i["por_dia"] else "—"] for i in abaixo], numericas=(2, 3, 4, 5, 6)))
        rev = [i for i in mt["itens"] if i["leitura"]]
        if rev:
            ref_txt = "pelo realizado do mês" if mt["fechado"] else "pela projeção do mês"
            novo("info", "Metas que parecem desalinhadas com o volume",
                 f"<b>{len(rev)}</b> meta(s) merecem revisão {ref_txt}: "
                 + ", ".join(f"{esc(i['nome'])} ({i['ratio']:.0f}% da meta, {'meta baixa' if i['leitura'] == 'baixa' else 'meta alta ou pouca demanda'})" for i in rev[:4])
                 + ". Não alterei o metas.json: a decisão é sua.", len(rev),
                 gp.tabela(["Setor", "Meta", "Meta (qtd)", "Referência", "% da meta", "Leitura"],
                           [[i["grupo"], i["nome"], i["meta"], round(i["ref"]), f"{i['ratio']:.0f}%", "Meta baixa" if i["leitura"] == "baixa" else "Meta alta ou pouca demanda"] for i in rev], numericas=(2, 3, 4)))
        if mt["fora_pct"] >= 10:
            novo("info", "Atendimentos sem nenhuma meta",
                 f"<b>{mt['total_fora']}</b> atendimentos ({txt_pct(mt['fora_pct'])}) de {rot} não entram em nenhuma meta. Os maiores: "
                 + ", ".join(f"{esc(f['Procedimento'])} ({f['qtd']})" for f in mt["fora"][:3]) + ". Se algum deles deve ter meta, inclua no metas.json.", mt["total_fora"],
                 gp.tabela(["Unidade", "Especialidade", "Procedimento", "Atendimentos"], [[f["Unidade"], f["Especialidade"], f["Procedimento"], f["qtd"]] for f in mt["fora"]], numericas=(3,)))
        difs = [c for c in mt["conferencia"] if c["dif"] is not None and abs(c["dif"]) > p["diferenca_metas_pct"]]
        if difs:
            novo("atencao", "Atendimento e Metas não batem",
                 "O número de atendimentos deste relatório difere da base das Metas em " + ", ".join(f"{esc(c['nome'])} ({c['dif']:+.1f}%)" for c in difs)
                 + ". As duas bases são atualizadas em horários diferentes; se a diferença persistir depois de atualizar as duas, confira o filtro dos relatórios.",
                 sum(abs(c["n_atend"] - c["n_metas"]) for c in difs),
                 gp.tabela(["Setor", "Atendimentos", "Base das Metas", "Diferença"], [[c["nome"], c["n_atend"], c["n_metas"], f"{c['dif']:+.1f}%"] for c in mt["conferencia"] if c["dif"] is not None], numericas=(1, 2, 3)))

    # 13) fora do expediente
    fora = m[m["_fora_exp"] | m["_sem_exp"]]
    if len(fora) and pct_de(len(fora), n) >= 1:
        dom = m[m["_sem_exp"]]
        novo("info", "Atendimentos fora do expediente",
             f"<b>{len(fora)}</b> atendimentos ({txt_pct(pct_de(len(fora), n))}) foram registrados fora do horário de atendimento: <b>{int((m['_fora_exp'] & ~m['_sem_exp']).sum())}</b> antes ou depois do expediente e "
             f"<b>{len(dom)}</b> em dia sem expediente (domingo ou feriado). Mais registros: {top_texto(fora['_setor'])}. O expediente e os dias de atendimento são os do painel de Metas.", len(fora),
             tabela_registros(fora, "Motivo", lambda r: "dia sem expediente" if r["_sem_exp"] else "fora do horário"))

    # 14) registros de teste
    te = m[m["_teste"]]
    if len(te):
        novo("info", "Registros de teste nos atendimentos", f"<b>{len(te)}</b> registro(s) com “teste” no profissional, usuário ou convênio. Contam nos totais e nas metas.", len(te),
             tabela_registros(te, "Valor", lambda r: gp.reais(r["_valor"])))

    out.sort(key=lambda a: (NIVEL[a["nivel"]], -a["_impacto"]))
    for i, a in enumerate(out, 1):
        a["texto"] = f'<span class="prio">Prioridade {i}</span> {a["texto"]}'
        a.pop("_impacto")
    return out


def num_br(v, d=0) -> str:
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- montagem
def montar_mes(ym: str, x: pd.DataFrame, df_metas: pd.DataFrame, cfg: dict, p: dict, agora: datetime, visitas: pd.DataFrame, etapas: pd.DataFrame,
              per: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses: "ym" e o ultimo mes dele, as linhas de todos entram juntas, os dias uteis somam e a
    comparacao e com o periodo anterior de mesmo tamanho. O dia a dia (que so existe dentro de um mes) nao e montado."""
    hoje = agora.date()
    yms = per.yms if per else [ym]
    m = x[x["_ym"].isin(yms)]
    mv = visitas[visitas["ym"].isin(yms)] if len(visitas) else None
    me = etapas[etapas["_ym"].isin(yms)] if len(etapas) else None
    fluxo = montar_fluxo(mv, me, p) if mv is not None and len(mv) else None
    n = len(m)
    rot = per.rotulo if per else pc.rotulo_mes(ym)
    uteis, dec, fechado = calendario(ym, cfg, agora, yms)
    ant = resumo_anterior(x, k.mes_mais(ym, -1), cfg, agora) if not per else resumo_anterior(x, per.anterior.fim, cfg, agora, per.anterior.yms)
    tempo = stats_tempo(m, p["espera_meta_min"])
    ritmo = n / dec if dec >= 0.5 else None
    receita = float(m["_valor"].fillna(0).sum())
    tipos = [("Sem horário de início", int(m["_sem_ini"].sum()), "var(--serious)"), ("Sem horário de fim", int(m["_sem_fim"].sum()), "var(--serious)"),
             ("Início e fim no mesmo minuto", int(m["_fim_junto"].sum()), "var(--serious)"),
             ("Valor R$ 0,00", int(m["_valor0"].sum()), "var(--warn)"), ("Horário incoerente", int(m["_incoerente"].sum()), "var(--crit)")]
    tipos.sort(key=lambda t: -t[1])
    problemas = int(m["_problema"].sum())
    setores = por_setor(m, ant, dec, p)
    espera_setor = [r for r in tabela_tempo(m, "_setor", p)]
    espera_esp = tabela_tempo(m, C_ESP, p, minimo=10)
    profissionais, equipamentos = por_pessoa(m, p)
    # duracao: pessoa ou aparelho muito acima da mediana da propria especialidade
    ref_dur = {r["nome"]: r["exa_med"] for r in tabela_tempo(m, C_ESP, p, minimo=10)}
    todos = profissionais + equipamentos
    longos = []
    for l in todos:
        ref = ref_dur.get(l["esp"])
        if ref and l["exa_med"] is not None and l["exa_n"] >= p["duracao_minimo_atendimentos"] and l["exa_med"] >= ref * p["duracao_vs_pares"] and l["exa_med"] - ref >= 10:
            longos.append({"nome": l["nome"].title() if not l["equip"] else l["nome"], "esp": l["esp"], "n": l["n"], "exa_med": l["exa_med"], "ref": ref})
    longos.sort(key=lambda l: -(l["exa_med"] / l["ref"]))
    if fluxo:      # espera real, pela hora e pelo dia do Check-In
        com_ci = mv[mv["checkin"].notna()]
        horas = tabela_visitas(com_ci.assign(_h=com_ci["checkin"].dt.hour.map(lambda h: f"{int(h):02d}h")), "_h", p)
        semana = tabela_visitas(com_ci.assign(_ds=com_ci["checkin"].dt.weekday.map(lambda d: DIAS_SEMANA[d])), "_ds", p)
    else:
        horas = tabela_tempo(m.assign(_h=m["_hora"].map(lambda h: f"{h:02d}h")), "_h", p, minimo=10)
        semana = tabela_tempo(m.assign(_ds=m["_sem"].map(lambda d: DIAS_SEMANA[d])), "_ds", p, minimo=10)
    horas.sort(key=lambda r: r["nome"])
    metas = metas_do_mes(df_metas, ym, cfg, agora, dec, m.groupby("_setor").size(), p, per=per)
    k_ = {"n": n, "receita": receita, "ticket": receita / n if n else None, "ritmo": ritmo, "ritmo_ant": ant["ritmo"] if ant else None,
          "delta_ritmo": (ritmo / ant["ritmo"] - 1) * 100 if ritmo is not None and ant else None,
          "esp_med": tempo["esp_med"], "esp_p90": tempo["esp_p90"], "esp_n": tempo["esp_n"], "exa_med": tempo["exa_med"], "exa_p90": tempo["exa_p90"],
          "klingo_dur_med": mediana(m[m["_exec"]][C_DUR]), "problemas": problemas, "problemas_pct": pct_de(problemas, n),
          "usuarios": int(m[C_USER].nunique()), "profissionais": len(profissionais), "equipamentos": len(equipamentos),
          "metas_pct": metas["geral"]["pct"] if metas else None, "metas_ok": metas["geral"]["itens_ok"] if metas else None, "metas_total": metas["geral"]["itens_total"] if metas else None}
    ctx = {"kpis": k_, "dec": dec, "setores": setores, "espera_setor": espera_setor, "espera_esp": espera_esp, "espera_hora": horas,
           "profissionais": profissionais, "duracao_longa": longos, "metas": metas, "fluxo": fluxo, "mv": mv, "me": me}
    alertas = alertas_do_mes(m, rot, p, hoje, ctx)
    gp.anotar("atendimento", alertas, per.chave if per else ym)
    metas_out = None
    if metas:
        metas_out = {c: metas[c] for c in ("fechado", "esperado_pct", "uteis_total", "uteis_decorridos", "geral", "grupos", "itens", "conferencia", "fora", "fora_pct", "total_fora", "total_atendimentos")}
        for g in metas_out["grupos"]:
            g["itens"] = [i["id"] for i in g["itens"]]
    return {"rotulo": rot, "fechado": fechado, "uteis_total": uteis, "uteis_decorridos": round(dec, 1), "kpis": k_, "alertas": alertas,
            "tipos": [{"nome": t, "qtd": q, "pct": pct_de(q, n), "cor": c} for t, q, c in tipos],
            "usuarios": por_usuario(m), "setores": setores, "metas": metas_out,
            "profissionais": profissionais, "equipamentos": equipamentos,
            "espera": {"setor": espera_setor, "esp": espera_esp, "hora": horas, "semana": semana, "real": bool(fluxo)}, "fluxo": fluxo,
            "dias": [] if per else por_dia(m, p),
            "convenios": contagem_mes(m, C_CONV, dec, ant, "convenios"), "procedimentos": contagem_mes(m, C_PROC, dec, ant, "procedimentos")}


def montar_visao(resp: dict, meses_geral, x, df_metas, cfg, p, agora, visitas, etapas, per: pc.Periodo | None = None) -> dict:
    """Os mesmos numeros do painel, recalculados so com os setores desta pessoa (atendimentos, fluxo, metas e alertas)."""
    nomes = set(resp["setores"])
    cfg_v = {**cfg, "grupos": [g for g in cfg["grupos"] if g["nome"] in nomes]}
    unidades = {gd.norm(g["unidade"]) for g in cfg_v["grupos"]}
    xv = x[x["_setor"].isin(nomes)]
    mt = df_metas[df_metas["Unidade"].map(gd.norm).isin(unidades)] if len(df_metas) else df_metas
    vv = visitas[visitas["setor"].isin(nomes)] if len(visitas) else visitas
    ev = etapas[etapas["_setor"].isin(nomes)] if len(etapas) else etapas
    res = {ym: montar_mes(ym, xv, mt, cfg_v, p, agora, vv, ev) for ym in meses_geral if (xv["_ym"] == ym).any()}
    if per and not per.unico and any(y in res for y in per.yms):   # o periodo so entra na visao que tem atendimentos nele
        pc.acrescentar_periodo(res, per, lambda q: montar_mes(q.fim, xv, mt, cfg_v, p, agora, vv, ev, per=q))
    return res


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    agora = datetime.now()
    hoje = agora.date()
    p = ler_parametros()
    cfg = json.loads(gd.METAS.read_text(encoding="utf-8-sig"))
    defn = k.ler_definicao(PASTA)
    abas = lido_com_cache(arquivo_dados(), "atendimento", lambda: k.carregar(PASTA))
    bruto = abas.get(ABA, pd.DataFrame())
    etapas, visitas = preparar_fluxo(abas.get(ABA_FLUXO, pd.DataFrame()), p, hoje)
    x = preparar(bruto, p, cfg, hoje, visitas)
    try:
        df_metas = lido_com_cache(gd.PLANILHA, "metas", gd.carregar_dados)
    except Exception:   # a planilha de Metas ainda nao existe: o painel abre sem a parte das metas
        df_metas = pd.DataFrame()
    meses = {}
    if len(x):
        for ym in k.meses_entre(defn["primeiro_mes"], hoje.strftime("%Y-%m")):
            if (x["_ym"] == ym).any():
                meses[ym] = montar_mes(ym, x, df_metas, cfg, p, agora, visitas, etapas)
    per, info = pc.periodo_pedido(de, ate, meses)
    visoes = ler_responsaveis(cfg) if meses else []
    por_visao = {v["id"]: montar_visao(v, meses, x, df_metas, cfg, p, agora, visitas, etapas, per=per) for v in visoes}
    if per and not per.unico:
        pc.acrescentar_periodo(meses, per, lambda q: montar_mes(q.fim, x, df_metas, cfg, p, agora, visitas, etapas, per=q))
    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else agora
    payload = {"gerado_em": agora.strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"), "versao": int(dados_em.timestamp()),
               "hoje": hoje.isoformat(), "mes_padrao": per.chave if per else (max(m for m in meses if ".." not in m) if meses else None), "periodo": info, "meses": meses, "tem_dados": bool(meses),
               "visoes": visoes, "por_visao": por_visao,
               "limites": {c: p[c] for c in ("espera_meta_min", "espera_critica_min", "espera_valida_max_min", "exame_valido_max_min", "produtividade_baixa_pct",
                                              "problema_atencao_pct", "problema_critico_pct", "meta_baixa_pct", "meta_alta_pct")},
               "horario": cfg.get("horario_atendimento", ["07:00", "18:00"])}
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
