"""Métricas de tempo (TAT, ociosidade, gargalo por horário) a partir de logs em segundos, tudo vetorizado.

Só depende de pandas/numpy (>=2.2, testado também no 3.0): nada daqui conhece o Klingo, o Supabase ou o site. O adaptador
`adaptar_fluxo_klingo` liga o #13404 deste repositório ao formato genérico abaixo.

Formatos de entrada (uma linha por evento, timestamps em segundos):
  etapas      atendimento_id | etapa | inicio | fim | setor              (uma linha por etapa do atendimento)
  usos        recurso | inicio | fim | setor                              (uma linha por uso do equipamento)
  transicoes  recurso | ts | status | setor                              (uma linha por mudança de status do equipamento)

Fluxo:  etapas ──► ciclo_por_atendimento ──► sinalizar_outliers ──► resumo_por_janela ──► pico_de_gargalo
        usos/transicoes ──► intervalos_* ──► ratear_por_janela ──► ocupacao_por_janela
        tudo ──► preparar_saida ──► exportar          (DataFrames planos, prontos para BI ou front-end)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.frequencies import to_offset

MIN = pd.Timedelta(minutes=1)


# ---------------------------------------------------------------- 0. durações
def para_timedelta(s: pd.Series, unidade: str = "s") -> pd.Series:
    """Número (segundos por padrão), 'HH:MM:SS' ou '1 days 02:00:00' viram timedelta64. Lixo vira NaT, não erro.
    Guarde SEMPRE em timedelta enquanto calcula e só converta para minutos (float) na saída: somar/comparar Timedelta é exato."""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_timedelta(s, unit=unidade)
    return pd.to_timedelta(s, errors="coerce")


def minutos(td: pd.Series) -> pd.Series:
    return td.dt.total_seconds() / 60


# ---------------------------------------------------------------- 1. TAT e esperas (shift por atendimento)
def ciclo_por_atendimento(etapas: pd.DataFrame, etapa_final: str = "Finalizado", etapa_espera: str = "Chamado",
                          col_id: str = "atendimento_id") -> tuple[pd.DataFrame, pd.DataFrame]:
    """(etapas enriquecidas, uma linha por atendimento).

    TAT = fim da etapa final - início da primeira etapa (chegada). Para cada etapa também sai:
      - `dur`          = fim - início da própria etapa;
      - `repasse`      = início - fim da etapa ANTERIOR do mesmo atendimento (tempo entre etapas que nenhuma etapa registra).
    O "fim anterior" usa cummax e não o fim da linha de cima: se duas etapas se sobrepõem, a anterior que importa é a que terminou por último.
    """
    e = etapas.sort_values([col_id, "inicio", "fim"], kind="stable").copy()
    e["dur"] = e["fim"] - e["inicio"]
    fim_acumulado = e.groupby(col_id, sort=False)["fim"].cummax()
    e["fim_anterior"] = fim_acumulado.groupby(e[col_id], sort=False).shift()          # shift DENTRO de cada atendimento
    e["repasse"] = (e["inicio"] - e["fim_anterior"]).clip(lower=pd.Timedelta(0))      # sobreposição vira 0, não negativo
    e["_fim_final"] = e["fim"].where(e["etapa"] == etapa_final)
    e["_aberto"] = e["fim"].isna()

    g = e.groupby(col_id, sort=False)
    v = g.agg(chegada=("inicio", "min"), saida=("_fim_final", "max"), n_etapas=("etapa", "size"), setor=("setor", "first"),
              repasse=("repasse", "sum"), aberto=("_aberto", "any"))
    v["espera"] = e[e["etapa"] == etapa_espera].groupby(col_id, sort=False)["dur"].sum()   # NaT se o atendimento não passou pela fila
    v["tat"] = v["saida"] - v["chegada"]                      # NaT enquanto não existe etapa final: não é zero
    v["tat_min"], v["espera_min"], v["repasse_min"] = minutos(v["tat"]), minutos(v["espera"]), minutos(v["repasse"])
    return e.drop(columns=["_fim_final", "_aberto"]), v.reset_index()


# ---------------------------------------------------------------- 3. outliers (esquecimento de encerramento)
def sinalizar_outliers(df: pd.DataFrame, col: str, por: list[str] | None = None, metodo: str = "iqr", k: float = 1.5,
                       z_max: float = 3.5, n_min: int = 30, log: bool = True, teto: float | pd.Series | None = None,
                       piso_limite: float = 0.0, piso_log: float = 1 / 60) -> pd.DataFrame:
    """Devolve `outlier` (bool) e `limite` (na unidade original) alinhados a df.index. Nada é apagado: quem usa decide o que fazer.

    metodo:
      "iqr"   cerca de Tukey, Q3 + k*IQR. Não depende da média: poucos casos absurdos não a movem.
      "mad"   z-score ROBUSTO: 0,6745*(x - mediana)/MAD > z_max (mediana e MAD em vez de média e desvio).
      "zscore" z-score clássico (x - média)/desvio. Mantido para comparar: é o pior aqui, porque os esquecimentos inflam
               a média e o desvio e escondem os próprios outliers (efeito "masking").
    log=True calcula tudo em log(max(x, piso_log)) (piso de 1 segundo, se x está em minutos; log1p achataria os tempos curtos): tempos de fila são assimétricos (cauda direita longa), e na escala crua a cerca de um
    grupo de mediana 2 min cairia onde a de um grupo de mediana 40 min não pegaria nada.
    por: o cálculo é feito dentro de cada grupo (etapa, setor...); grupo com menos de n_min linhas usa a estatística global.
    piso_limite: a cerca nunca fica abaixo disto (unidade original). Etapas de poucos segundos (mediana 0,1 min) têm cerca
        perto de zero e a regra estatística sinalizaria pacientes normais; 5 min, por exemplo, só olha o que já é demorado.
    teto: limite duro (ex.: 1440 min; aceita Series, um teto por linha/etapa). Etapas bimodais (metade em segundos, metade em
        dezenas de minutos) têm IQR enorme e a regra estatística não pega nada: nelas o teto é o que funciona.
    Regra final: limite = min(max(cerca estatística, piso_limite), teto); outlier = x > limite.
    Só a cauda superior é sinalizada: tempo curto não é esquecimento (é outro problema: horário idêntico, ver o painel Atendimento)."""
    x = pd.to_numeric(df[col], errors="coerce").astype("float64")
    t = np.log(x.clip(lower=piso_log)) if log else x
    chaves = [df[c] for c in por] if por else [pd.Series(0, index=df.index)]
    g = t.groupby(chaves, sort=False, dropna=False)
    pequeno = g.transform("count") < n_min

    def lim(serie_ou_grupo, glob):
        return pd.Series(np.where(pequeno, glob, serie_ou_grupo), index=df.index)

    if metodo == "iqr":
        q1, q3 = g.transform("quantile", 0.25), g.transform("quantile", 0.75)
        corte = lim(q3 + k * (q3 - q1), t.quantile(0.75) + k * (t.quantile(0.75) - t.quantile(0.25)))
    elif metodo == "mad":
        med = g.transform("median")
        mad = (t - med).abs().groupby(chaves, sort=False, dropna=False).transform("median")
        mad_g = (t - t.median()).abs().median()
        piso = 0.05 if log else 1e-9                      # MAD = 0 (valores repetidos) faria a cerca colapsar na mediana
        mad = np.maximum(mad.where(mad > 0, mad_g), piso)
        mad_g = max(mad_g, piso)
        corte = lim(med + z_max * mad / 0.6745, t.median() + z_max * mad_g / 0.6745)
    elif metodo == "zscore":
        corte = lim(g.transform("mean") + z_max * g.transform("std"), t.mean() + z_max * t.std())
    else:
        raise ValueError(f"metodo desconhecido: {metodo!r}")
    limite = pd.Series(np.maximum(np.exp(corte) if log else corte, piso_limite), index=df.index)
    if teto is not None:
        limite = np.minimum(limite, teto)
    outlier = (x > limite).fillna(False)                    # NaN nunca é outlier
    return pd.DataFrame({"outlier": outlier.to_numpy(), "limite": limite.to_numpy()}, index=df.index)


# ---------------------------------------------------------------- 2. ociosidade (intervalos → janelas)
def intervalos_de_status(transicoes: pd.DataFrame, fim_periodo: pd.Timestamp, col_rec: str = "recurso") -> pd.DataFrame:
    """Log de transições (recurso, ts, status) → intervalos (recurso, inicio, fim, estado).
    O estado vale até a PRÓXIMA transição do mesmo recurso: shift(-1) dentro do grupo. O último estado vai até fim_periodo."""
    t = transicoes.sort_values([col_rec, "ts"], kind="stable").copy()
    t["inicio"] = t["ts"]
    t["fim"] = t.groupby(col_rec, sort=False)["ts"].shift(-1).fillna(fim_periodo)
    t = t.rename(columns={"status": "estado"})
    return t.loc[t["fim"] > t["inicio"], [col_rec, "inicio", "fim", "estado"] + (["setor"] if "setor" in t else [])]


def unir_sobrepostos(iv: pd.DataFrame, col_rec: str = "recurso") -> pd.DataFrame:
    """Funde intervalos que se sobrepõem ou se tocam, por recurso, sem laço: dois exames "ao mesmo tempo" na mesma máquina
    contariam 120 min ocupados numa hora de 60. Ordena por início; o bloco só recomeça quando o início passa do maior
    fim visto até ali (cummax + shift); cumsum dá o número do bloco; um agg fecha cada bloco."""
    u = iv.sort_values([col_rec, "inicio", "fim"], kind="stable")
    fim_ant = u.groupby(col_rec, sort=False)["fim"].cummax().groupby(u[col_rec], sort=False).shift()
    bloco = (fim_ant.isna() | (u["inicio"] > fim_ant)).cumsum()
    extras = {"setor": ("setor", "first")} if "setor" in u else {}
    return u.groupby(bloco, sort=False).agg(**{col_rec: (col_rec, "first")}, inicio=("inicio", "min"), fim=("fim", "max"), **extras).reset_index(drop=True)


def intervalos_de_uso(usos: pd.DataFrame, periodo: tuple[pd.Timestamp, pd.Timestamp], col_rec: str = "recurso",
                      tolerancia: pd.Timedelta = pd.Timedelta(0)) -> pd.DataFrame:
    """Só há usos (início/fim de cada exame) e não há log de status: a ociosidade é o buraco entre um uso e o seguinte.

    1) recorta ao período e funde sobreposições (ocupado nunca passa de 60 min por hora);
    2) sentinelas: duas linhas de comprimento zero por recurso (início e fim do período) fazem o buraco antes do primeiro
       uso e depois do último também contar;
    3) ordena por recurso/início; buraco = início - fim da linha anterior (shift dentro do recurso); só conta se > tolerancia.
    Devolve usos (estado 'ocupado') e buracos (estado 'ocioso') no mesmo formato de intervalos_de_status."""
    cols = [col_rec, "inicio", "fim"] + (["setor"] if "setor" in usos else [])
    u = usos[cols].dropna(subset=["inicio", "fim"]).assign(inicio=lambda d: d["inicio"].clip(lower=periodo[0]), fim=lambda d: d["fim"].clip(upper=periodo[1]))
    ocupado = unir_sobrepostos(u[u["fim"] > u["inicio"]], col_rec)
    base = ocupado.groupby(col_rec, sort=False).first().reset_index()
    sent = pd.concat([base.assign(inicio=periodo[0], fim=periodo[0]), base.assign(inicio=periodo[1], fim=periodo[1])])
    g = pd.concat([ocupado, sent], ignore_index=True).sort_values([col_rec, "inicio", "fim"], kind="stable")
    fim_ant = g.groupby(col_rec, sort=False)["fim"].shift()
    achou = (g["inicio"] - fim_ant) > tolerancia
    ocioso = g.loc[achou, cols].assign(inicio=fim_ant[achou], fim=g.loc[achou, "inicio"], estado="ocioso")
    return pd.concat([ocupado[cols].assign(estado="ocupado"), ocioso], ignore_index=True)


def ratear_por_janela(iv: pd.DataFrame, freq: str = "h") -> pd.DataFrame:
    """Reparte cada intervalo [inicio, fim) pelas janelas que ele toca, com os segundos exatos de cada uma.

    `resample` sozinho não faz isto: ele joga o intervalo INTEIRO na janela do `inicio` (um exame de 10:50 às 11:20 contaria
    30 min às 10h). Aqui o intervalo vira uma linha por janela (np.repeat), sem laço em Python.
    Só frequências fixas e alinhadas à época ('h', '30min', '15min'...)."""
    iv = iv[iv["fim"] > iv["inicio"]]
    passo = to_offset(freq).nanos
    ini = iv["inicio"].astype("datetime64[ns]").to_numpy().astype("int64")
    fim = iv["fim"].astype("datetime64[ns]").to_numpy().astype("int64")
    piso_ini = ini - ini % passo
    n_janelas = (fim - 1) // passo - piso_ini // passo + 1                       # janelas tocadas por linha
    pos = np.repeat(np.arange(len(iv)), n_janelas)
    deslocamento = np.arange(n_janelas.sum()) - np.repeat(np.cumsum(n_janelas) - n_janelas, n_janelas)
    janela = piso_ini[pos] + deslocamento * passo
    dentro = np.minimum(fim[pos], janela + passo) - np.maximum(ini[pos], janela)
    out = iv.iloc[pos].reset_index(drop=True)
    out["janela"] = pd.to_datetime(janela).astype("datetime64[ns]")
    out["minutos"] = dentro / 60e9
    return out.drop(columns=["inicio", "fim"])


def ocupacao_por_janela(iv: pd.DataFrame, expediente: tuple[int, int] = (7, 18), dias_uteis: tuple[int, ...] = (0, 1, 2, 3, 4, 5),
                        feriados: tuple[str, ...] = (), freq: str = "h", col_rec: str = "recurso") -> pd.DataFrame:
    """Minutos ocupado / ocioso / outros por recurso e janela, só dentro do expediente.

    O corte do expediente é feito DEPOIS de ratear, janela a janela: um buraco de 17:30 de segunda a 08:10 de terça
    entrega 30 min às 17h, 0 min entre 18h e 07h e 60 min às 7h. `expediente` em horas cheias (a janela é de 1 h)."""
    r = ratear_por_janela(iv, freq)
    hora, dow, dia = r["janela"].dt.hour, r["janela"].dt.weekday, r["janela"].dt.normalize()
    r = r[hora.between(expediente[0], expediente[1] - 1) & dow.isin(dias_uteis) & ~dia.isin(pd.to_datetime(list(feriados)))]
    chaves = [col_rec] + (["setor"] if "setor" in r else [])
    w = r.groupby(["janela", *chaves, "estado"], observed=True)["minutos"].sum().unstack("estado", fill_value=0.0)
    w = w.rename(columns=lambda c: f"min_{c}").reset_index()
    w.columns.name = None
    for c in ("min_ocupado", "min_ocioso"):
        if c not in w:
            w[c] = 0.0
    outros = [c for c in w.columns if c.startswith("min_") and c not in ("min_ocupado", "min_ocioso")]
    w["min_outros"] = w[outros].sum(axis=1) if outros else 0.0
    w["min_disponivel"] = w[["min_ocupado", "min_ocioso", "min_outros"]].sum(axis=1)
    w["pct_ociosidade"] = 100 * w["min_ocioso"] / w["min_disponivel"].where(w["min_disponivel"] > 0)
    return w.drop(columns=[c for c in outros])


# ---------------------------------------------------------------- 2b. janelas: resample / pd.Grouper
def resumo_por_janela(visitas: pd.DataFrame, metricas: dict[str, str], freq: str = "h", por: tuple[str, ...] = ("setor",),
                      col_tempo: str = "chegada") -> pd.DataFrame:
    """Downsampling dos atendimentos (segundos) para janelas de análise, formato LONGO (uma linha por janela × grupo × métrica).

    O atendimento pertence à janela em que CHEGOU (é a "coorte de chegada": a espera das 10h é a de quem chegou às 10h).
    `metricas` = {coluna_de_minutos: coluna_de_flag_outlier}. Estatísticas sobre o que NÃO é outlier; `n_outliers` mostra quanto foi descartado.
    pd.Grouper(freq=...) dentro do groupby é o mesmo que resample, mas permite agrupar por mais chaves ao mesmo tempo."""
    partes = []
    for col, flag in metricas.items():
        d = visitas.assign(_v=visitas[col].where(~visitas[flag]), _o=visitas[flag] & visitas[col].notna())
        g = d.groupby([pd.Grouper(key=col_tempo, freq=freq), *por], observed=True)
        r = g.agg(n=("_v", "count"), media_min=("_v", "mean"), mediana_min=("_v", "median"), n_outliers=("_o", "sum"))
        r["p90_min"] = g["_v"].quantile(0.90)
        partes.append(r.reset_index().assign(metrica=col).rename(columns={col_tempo: "janela"}))
    return pd.concat(partes, ignore_index=True)


def ocupacao_diaria(horas: pd.DataFrame, por: tuple[str, ...] = ("recurso",)) -> pd.DataFrame:
    """Horas → dias com pd.Grouper(freq='D'). Minutos SOMAM, então somar é válido; o percentual é refeito da soma (média de
    percentuais por hora estaria errada). Mediana e p90 NÃO se somam: para tempo de espera por dia use
    `resumo_por_janela(..., freq='D')` direto dos atendimentos, nunca "agregue o agregado"."""
    somas = [c for c in horas.columns if c.startswith("min_")]
    d = horas.groupby([pd.Grouper(key="janela", freq="D"), *por], observed=True)[somas].sum().reset_index()
    d["pct_ociosidade"] = 100 * d["min_ocioso"] / d["min_disponivel"].where(d["min_disponivel"] > 0)
    return d[d["min_disponivel"] > 0].reset_index(drop=True)


def pico_de_gargalo(janelas: pd.DataFrame, metrica: str = "espera_min", col_valor: str = "p90_min", n_min: int = 10,
                    por: tuple[str, ...] = ("setor",)) -> pd.DataFrame:
    """Para cada dia (e setor), a hora com a maior espera: groupby(dia, setor).idxmax() sobre a tabela por hora.
    Janelas com menos de n_min atendimentos não disputam: 2 pacientes esperando muito não são um pico."""
    t = janelas[(janelas["metrica"] == metrica) & (janelas["n"] >= n_min)].copy()
    t["dia"] = t["janela"].dt.normalize()
    escolhida = t.groupby(["dia", *por], observed=True)[col_valor].idxmax().dropna()
    return t.loc[escolhida, ["dia", *por, "janela", "n", "mediana_min", col_valor]].rename(
        columns={"janela": "hora_pico", col_valor: "valor_pico_min"}).reset_index(drop=True)


# ---------------------------------------------------------------- 4. saída para BI / front-end
def preparar_saida(df: pd.DataFrame, col_janela: str = "janela", janela_ate: pd.Timestamp | None = None, freq: str = "h") -> pd.DataFrame:
    """Tabela plana: um DataFrame por assunto, grão explícito, tipos baratos e nada que o BI tenha de interpretar.

    - sem MultiIndex nem índice com significado (reset_index): BI lê colunas, não índices;
    - sem Timedelta (nenhuma ferramenta de BI entende): tempos em minutos, float32, 2 casas; contagens em int32;
    - datas sem fuso (datetime64[ns]) + colunas prontas `dia`, `hora`, `dia_semana` (0=seg): o filtro/heatmap não recalcula nada;
    - texto repetitivo como `category` (cai o tamanho do Parquet/JSON); chaves nunca nulas;
    - `janela_fechada` = a janela já terminou nos dados (a de agora é parcial e o front pode esmaecê-la);
    - ordenado pelas chaves: compacta melhor e a saída é determinística (diff e testes)."""
    s = df.copy()
    j = pd.to_datetime(s[col_janela])
    s[col_janela] = (j.dt.tz_localize(None) if j.dt.tz is not None else j).astype("datetime64[ns]")
    s["dia"] = s[col_janela].dt.normalize()
    if to_offset(freq).nanos < 86_400 * 10**9:               # janela diária não tem "hora"
        s["hora"] = s[col_janela].dt.hour.astype("int8")
    s["dia_semana"] = s[col_janela].dt.weekday.astype("int8")
    if janela_ate is not None:
        s["janela_fechada"] = s[col_janela] + pd.Timedelta(to_offset(freq).nanos, "ns") <= janela_ate
    for c in s.columns:
        if pd.api.types.is_timedelta64_dtype(s[c]):
            s[c] = minutos(s[c])
        if c.endswith("_min") or c.startswith("min_") or c.startswith("pct_") or c == "limite":
            s[c] = s[c].astype("float32").round(2)
        elif pd.api.types.is_integer_dtype(s[c]) and c not in ("hora", "dia_semana"):
            s[c] = s[c].astype("int32")
        elif s[c].dtype == object or pd.api.types.is_string_dtype(s[c]):
            s[c] = s[c].where(s[c].notna(), "(sem informação)").astype("category")
    chaves = [c for c in ("dia", col_janela, "setor", "recurso", "metrica") if c in s]
    return s.sort_values(chaves, kind="stable").reset_index(drop=True).rename(columns={col_janela: "janela_inicio"})


def exportar(tabelas: dict[str, pd.DataFrame], pasta: Path, meta: dict | None = None) -> dict[str, Path]:
    """Um arquivo por tabela: CSV (BI de planilha), JSON colunar (site) e Parquet quando houver pyarrow.
    O JSON usa orient='split' (colunas uma vez, linhas como listas): 3 a 5x menor que lista de objetos e o front monta o gráfico direto."""
    pasta.mkdir(parents=True, exist_ok=True)
    saidas = {}
    for nome, df in tabelas.items():
        csv = pasta / f"{nome}.csv"
        df.to_csv(csv, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S", float_format="%.2f")
        saidas[f"{nome}.csv"] = csv
        js = pasta / f"{nome}.json"
        f32 = [c for c in df.columns if df[c].dtype == "float32"]       # float32 -> 58.869998931884766 no JSON; arredonda antes
        limpo = df.astype({c: "float64" for c in f32}).assign(**{c: lambda d, c=c: d[c].round(2) for c in f32})
        corpo = json.loads(limpo.to_json(orient="split", index=False, date_format="iso", date_unit="s"))
        js.write_text(json.dumps({"meta": meta or {}, **corpo}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        saidas[f"{nome}.json"] = js
        try:
            pq = pasta / f"{nome}.parquet"
            df.to_parquet(pq, index=False)
            saidas[f"{nome}.parquet"] = pq
        except ImportError:
            pass
    return saidas


# ---------------------------------------------------------------- pipeline completo
def construir_tabelas(etapas: pd.DataFrame, usos: pd.DataFrame, periodo: tuple[str, str], expediente: tuple[int, int] = (7, 18),
                      dias_uteis: tuple[int, ...] = (0, 1, 2, 3, 4, 5), feriados: tuple[str, ...] = (), metodo: str = "iqr",
                      teto_min: float = 1440, piso_min: float = 5.0, tetos_por_etapa: dict[str, float] | None = None,
                      n_min_pico: int = 10) -> dict[str, pd.DataFrame]:
    """etapas + usos de equipamento → tabelas finais (planas, grão explícito). Quem consome escolhe o que usar:

      atendimentos   grão: atendimento           (detalhe/drill-down; NÃO mande ao navegador sem necessidade: volume e granularidade)
      janelas_hora   grão: hora × setor × métrica (tat_min / espera_min)
      janelas_dia    grão: dia  × setor × métrica (calculado dos atendimentos, não das horas)
      gargalo_dia    grão: dia  × setor           (hora de maior espera do dia)
      ocupacao_hora  grão: hora × recurso         (min ocupado / ocioso / disponível)
      ocupacao_dia   grão: dia  × recurso
      limites        grão: etapa × setor          (cerca de outlier usada: o que a tela mostra em "como tratamos os casos esquecidos")
    """
    ini, fim = pd.Timestamp(periodo[0]), pd.Timestamp(periodo[1]) + pd.Timedelta(days=1)
    e, v = ciclo_por_atendimento(etapas)

    # outliers: por etapa (para o perfil das etapas) e por atendimento (para TAT e espera), sempre dentro do setor
    e["dur_min"] = minutos(e["dur"])
    teto_etapa = e["etapa"].map(tetos_por_etapa or {}).fillna(teto_min).astype("float64")
    e[["dur_outlier", "dur_limite"]] = sinalizar_outliers(e, "dur_min", ["etapa", "setor"], metodo, teto=teto_etapa, piso_limite=piso_min).to_numpy()
    for col, flag in (("tat_min", "tat_outlier"), ("espera_min", "espera_outlier")):
        r = sinalizar_outliers(v, col, ["setor"], metodo, teto=teto_min, piso_limite=piso_min)
        v[flag], v[col + "_limite"] = r["outlier"], r["limite"]

    # equipamentos: um uso "esquecido aberto" não pode manter a máquina ocupada por dias; o fim é limitado à cerca do próprio recurso
    u = usos.dropna(subset=["inicio", "fim"]).copy()
    u["dur_min"] = minutos(u["fim"] - u["inicio"])
    r = sinalizar_outliers(u, "dur_min", ["recurso"], metodo, teto=teto_min, piso_limite=piso_min)
    u["fim"] = u["fim"].where(~r["outlier"], u["inicio"] + pd.to_timedelta(r["limite"], unit="m"))

    metricas = {"tat_min": "tat_outlier", "espera_min": "espera_outlier"}
    ate = v["chegada"].max()
    horas = ocupacao_por_janela(intervalos_de_uso(u, (ini, fim)), expediente, dias_uteis, feriados)
    jan_h = resumo_por_janela(v, metricas, "h")
    limites = (e.groupby(["etapa", "setor"], observed=True).agg(n=("dur_min", "count"), n_outliers=("dur_outlier", "sum"), limite_min=("dur_limite", "first"),
                                                                mediana_min=("dur_min", "median")).reset_index())
    detalhe = preparar_saida(v.drop(columns=["tat", "espera", "repasse", "saida"]), "chegada").rename(columns={"janela_inicio": "chegada"})
    return {"atendimentos": detalhe,
            "janelas_hora": preparar_saida(jan_h, janela_ate=ate),
            "janelas_dia": preparar_saida(resumo_por_janela(v, metricas, "D"), freq="D", janela_ate=ate),
            "gargalo_dia": preparar_saida(pico_de_gargalo(jan_h, "espera_min", n_min=n_min_pico).rename(columns={"hora_pico": "janela"}).drop(columns=["dia"])).rename(columns={"janela_inicio": "hora_pico"}),
            "ocupacao_hora": preparar_saida(horas),
            "ocupacao_dia": preparar_saida(ocupacao_diaria(horas), freq="D"),
            "limites": preparar_saida(limites.assign(janela=ini), freq="D").drop(columns=["janela_inicio", "dia", "dia_semana"])}


# ---------------------------------------------------------------- adaptador do repositório (#13404 do Klingo)
def eh_equipamento(nome: pd.Series, equipamentos: list[str], prefixos: list[str]) -> pd.Series:
    n = nome.fillna("").astype(str).str.strip().str.upper()
    return n.isin([e.upper() for e in equipamentos]) | n.str.startswith(tuple(p.upper() for p in prefixos))


def adaptar_fluxo_klingo(f: pd.DataFrame, equipamentos: list[str], prefixos: list[str], mapa_setor: dict[str, str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DataFrame do relatório #13404 (colunas com os títulos do Klingo) → (etapas, usos de equipamento).

    O relatório não traz o Id do atendimento: a visita é achada por Data do Atendimento + Profissional + Convênio, igual ao painel
    Atendimento (`CHAVE_VISITA`). O Id aqui é só um número da execução (factorize): não guarde nem exiba."""
    prof, conv = f["Profissional / Equipamento"].fillna("").astype(str), f["Convênio"].fillna("").astype(str)
    chave = f["Data do Atendimento"].astype(str) + "|" + prof + "|" + conv
    setor = f["Setor (CSI/RM/RX/TC)"].astype(str).str.strip()
    etapas = pd.DataFrame({"atendimento_id": pd.factorize(chave)[0], "etapa": f["Etapa"].astype(str).str.strip(),
                           "inicio": pd.to_datetime(f["Início da Etapa"], errors="coerce"), "fim": pd.to_datetime(f["Fim da Etapa"], errors="coerce"),
                           "setor": setor.map(mapa_setor or {}).fillna(setor), "recurso": prof.str.strip()})
    em_uso = etapas[(etapas["etapa"] == "Em Atendimento") & eh_equipamento(etapas["recurso"], equipamentos, prefixos)]
    return etapas, em_uso[["recurso", "inicio", "fim", "setor"]]
