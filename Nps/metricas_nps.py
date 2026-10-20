"""Contas do NPS (pandas puro, sem Klingo nem Supabase): o que dá para testar à mão.

NPS = % de promotores (nota 9 e 10) menos % de detratores (nota 0 a 6); neutros (7 e 8) não entram na conta mas contam no total.
O resultado vai de -100 a +100. Como é uma conta sobre uma amostra, cada NPS vem com a **margem de erro** (95%): com 30 respostas um NPS
de 60 pode ser, na verdade, 40 ou 80. É ela que separa "mudou de verdade" de "variou por acaso".
"""
import math
import re
from fractions import Fraction
from typing import NamedTuple
import unicodedata

import numpy as np
import pandas as pd

Z95 = 1.96


def classe(nota):
    """Promotor (9-10), Neutro (7-8) ou Detrator (0-6); None se a nota não é um número de 0 a 10."""
    if nota is None or pd.isna(nota) or not 0 <= float(nota) <= 10:
        return None
    return "Promotor" if nota >= 9 else "Neutro" if nota >= 7 else "Detrator"


def nps_de(prom: int, det: int, n: int):
    return None if not n else round((prom - det) / n * 100, 1)


def margem_de(prom: int, det: int, n: int):
    """Meia-largura do intervalo de 95% do NPS, em pontos. Variância da diferença de proporções: (p + d - (p - d)²) / n."""
    if not n:
        return None
    p, d = prom / n, det / n
    return round(Z95 * math.sqrt(max(p + d - (p - d) ** 2, 0) / n) * 100, 1)


def diferenca_confiavel(a: dict, b: dict) -> bool | None:
    """A diferença de NPS entre dois grupos é maior que o acaso explicaria (95%)? None se algum não tem dado."""
    if not a or not b or a.get("nps") is None or b.get("nps") is None or a.get("margem") is None or b.get("margem") is None:
        return None
    erro = math.sqrt((a["margem"] / Z95) ** 2 + (b["margem"] / Z95) ** 2)
    return abs(a["nps"] - b["nps"]) > Z95 * erro


def pct_de(parte, total):
    return round(float(parte) / float(total) * 100, 1) if total else None


def resumo(df: pd.DataFrame) -> dict:
    """Os números de um grupo de respostas (precisa das colunas `nota` e `classe`; `comentario` é opcional)."""
    n = int(len(df))
    prom, neut, det = (int((df["classe"] == c).sum()) for c in ("Promotor", "Neutro", "Detrator"))
    com = int(df["comentario"].fillna("").str.strip().ne("").sum()) if "comentario" in df and n else 0
    return {"n": n, "prom": prom, "neut": neut, "det": det, "nps": nps_de(prom, det, n), "margem": margem_de(prom, det, n),
            "media": round(float(df["nota"].mean()), 2) if n else None, "pct_prom": pct_de(prom, n), "pct_neut": pct_de(neut, n),
            "pct_det": pct_de(det, n), "comentarios": com, "pct_comentarios": pct_de(com, n)}


def distribuicao(df: pd.DataFrame) -> list[int]:
    """Quantas respostas houve em cada nota, de 0 a 10."""
    cont = df["nota"].round().astype(int).value_counts() if len(df) else pd.Series(dtype=int)
    return [int(cont.get(i, 0)) for i in range(11)]


def grupos(df: pd.DataFrame, por: str, minimo: int) -> list[dict]:
    """Um item por valor de `por`, com o resumo do grupo e o quanto ele pesa no NPS geral.

    `contribuicao` = (promotores - detratores) do grupo ÷ respostas do total × 100: a soma de todos os grupos é exatamente o NPS geral, então
    dá para ver quem sustenta e quem puxa o NPS para baixo. `pct_det_total` = que parte de TODOS os detratores está no grupo (comparar com
    `pct_respostas` mostra se ele concentra mais detratores do que o tamanho dele explicaria). `poucos` = menos respostas que o mínimo."""
    total, total_det = len(df), int((df["classe"] == "Detrator").sum())
    nomes = df[por].where(df[por].notna(), "").astype(str).str.strip().replace("", "(sem informação)")   # vazio e nulo sao o mesmo grupo
    out = []
    for nome, g in df.groupby(nomes):
        r = resumo(g)
        r.update(nome=str(nome), poucos=r["n"] < minimo,
                 contribuicao=round((r["prom"] - r["det"]) / total * 100, 1) if total else None,
                 pct_respostas=pct_de(r["n"], total), pct_det_total=pct_de(r["det"], total_det) if total_det else None)
        out.append(r)
    out.sort(key=lambda r: (-r["n"], r["nome"]))
    return out


# ---------------------------------------------------------------- tempo: dia da semana e hora do agendamento
def por_dia_da_semana(df: pd.DataFrame, minimo: int) -> list[dict]:
    d = df[df["agendado"].notna()]
    out = []
    for dia, g in d.groupby(d["agendado"].dt.weekday):
        r = resumo(g)
        r.update(d=int(dia), poucos=r["n"] < minimo)
        out.append(r)
    return sorted(out, key=lambda r: r["d"])


def por_hora(df: pd.DataFrame, minimo: int) -> list[dict]:
    d = df[df["agendado"].notna()]
    out = []
    for h, g in d.groupby(d["agendado"].dt.hour):
        r = resumo(g)
        r.update(h=int(h), poucos=r["n"] < minimo)
        out.append(r)
    return sorted(out, key=lambda r: r["h"])


def por_dia(df: pd.DataFrame) -> list[dict]:
    d = df[df["agendado"].notna()].assign(dia=lambda x: x["agendado"].dt.normalize())
    return [{"d": dia.strftime("%Y-%m-%d"), **{c: v for c, v in resumo(g).items() if c in ("n", "prom", "det", "nps", "media")}}
            for dia, g in d.groupby("dia")]


# ---------------------------------------------------------------- comentários e temas
def normalizar(texto) -> str:
    """Minúsculas e sem acento: 'Demorou' e 'DEMORÓU' viram a mesma coisa para achar palavras."""
    s = unicodedata.normalize("NFD", str(texto or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


class Tema(NamedTuple):
    rotulo: str
    rx: "re.Pattern"
    nega: bool      # "negacao": true no parametros.json: um "não" até duas palavras antes anula a palavra ("não recomendo" não é elogio)


NEGACAO = re.compile(r"\b(?:nao|nunca|jamais|nem)\b(?:\s+\w+){0,2}")


def compilar_temas(cfg: dict) -> dict[str, Tema]:
    """{id: Tema}. Cada palavra do parametros.json é o começo de uma palavra (\\b na frente): 'demor' pega demora, demorou, demorado."""
    out = {}
    for tid, t in (cfg or {}).items():
        palavras = [p for p in t.get("palavras", []) if p]
        if palavras:
            out[tid] = Tema(t.get("rotulo", tid), re.compile(r"\b(?:" + "|".join(palavras) + ")"), bool(t.get("negacao")))
    return out


def temas_do_texto(texto, temas: dict) -> list[str]:
    s = normalizar(texto)
    if not s:
        return []
    sem_negacao = NEGACAO.sub(" ", s)
    return [tid for tid, t in temas.items() if t.rx.search(sem_negacao if t.nega else s)]


def analisar_temas(df: pd.DataFrame, temas: dict) -> list[dict]:
    """Para cada tema: quantas respostas o citam, em cada grupo (promotor, neutro, detrator), e quantos pontos de NPS ele custa.

    `pontos` = detratores que citam o tema ÷ total de respostas × 100: é quanto o NPS subiria se esses detratores tivessem dado 9 ou 10
    (o tema não é necessariamente a causa; é o que o cliente escolheu dizer). Só vale para quem comentou: sem comentário não há tema."""
    com = df[df["comentario"].fillna("").str.strip().ne("")]
    total, n_det = len(df), int((df["classe"] == "Detrator").sum())
    n_det_com = int(((df["classe"] == "Detrator") & df.index.isin(com.index)).sum())
    out = []
    for tid, tema in temas.items():
        tem = com[com["temas"].apply(lambda t: tid in t)]
        prom, neut, det = (int((tem["classe"] == c).sum()) for c in ("Promotor", "Neutro", "Detrator"))
        if not (prom or neut or det):
            continue
        out.append({"id": tid, "rotulo": tema.rotulo, "n": int(len(tem)), "prom": prom, "neut": neut, "det": det,
                    "pct_det_com_comentario": pct_de(det, n_det_com), "pontos": round(det / total * 100, 1) if total else None,
                    "pontos_neutros": round(neut / total * 100, 1) if total else None, "det_total": n_det})
    out.sort(key=lambda r: (-r["det"], -r["n"], r["rotulo"]))
    return out


# ---------------------------------------------------------------- meta
def caminho_para_a_meta(prom: int, neut: int, det: int, meta: float) -> dict | None:
    """Quanto falta para o NPS chegar na meta, de duas maneiras:
    - `converter`: quantos detratores teriam de virar promotores (cada conversão soma 2 ÷ n × 100 pontos);
    - `novas`: quantas respostas novas, todas de promotores, seriam necessárias além das de agora.
    None se não há respostas; {'ja': True} se a meta já foi batida."""
    n = prom + neut + det
    if not n:
        return None
    meta_f = Fraction(str(meta))   # conta exata: com float, "50 respostas" pode virar 51 so por arredondamento
    falta = meta_f * n - 100 * (prom - det)      # em "pontos x respostas": quanto o saldo (promotores - detratores) precisa crescer, vezes 100
    if falta <= 0:
        return {"ja": True, "meta": meta}
    converter = math.ceil(falta / 200)           # cada conversao de detrator em promotor soma 2 ao saldo
    novas = math.ceil(falta / (100 - meta_f)) if meta_f < 100 else None   # cada resposta nova de promotor soma 1 ao saldo e 1 ao total
    return {"ja": False, "meta": meta, "converter": min(converter, det) if det else converter, "converter_cabe": converter <= det,
            "novas": novas, "faltam_pontos": round(float(meta_f - Fraction(100 * (prom - det), n)), 1)}


# ---------------------------------------------------------------- Google: estrelas × NPS
def nps_equivalente(estrelas: list[int]) -> dict | None:
    """O NPS que as avaliações do Google dariam se 5 estrelas fossem promotores, 4 neutros e 1 a 3 detratores.
    É uma APROXIMAÇÃO (o Google pergunta outra coisa, de outro jeito, e quem avalia lá não é uma amostra de quem foi atendido), boa para
    acompanhar a tendência, não para dizer que os dois números têm de ser iguais."""
    n = len(estrelas)
    if not n:
        return None
    prom, neut = sum(e == 5 for e in estrelas), sum(e == 4 for e in estrelas)
    det = n - prom - neut
    return {"n": n, "prom": prom, "neut": neut, "det": det, "nps": nps_de(prom, det, n), "margem": margem_de(prom, det, n),
            "media": round(sum(estrelas) / n, 2), "pct_5": pct_de(prom, n), "pct_baixas": pct_de(det, n)}


def estrelas_do_nps(media_nps) -> float | None:
    """A nota média do NPS (0 a 10) na escala de 5 estrelas do Google (÷ 2). Comparação de escala, não de método."""
    return None if media_nps is None or pd.isna(media_nps) else round(float(media_nps) / 2, 2)


# ---------------------------------------------------------------- preparo da base
def preparar(df: pd.DataFrame, temas: dict) -> pd.DataFrame:
    """A aba do Klingo com os nomes curtos que as contas usam. Linha sem nota válida (0 a 10) é descartada: não dá para classificar."""
    if not len(df):
        return pd.DataFrame(columns=["id", "agendado", "nota", "classe", "resposta", "comentario", "profissional", "procedimento", "unidade", "ym", "temas"])
    col = lambda nome: df[nome] if nome in df else pd.Series([None] * len(df), index=df.index)   # coluna que o Klingo deixou de mandar: vazia, nao erro
    d = pd.DataFrame({
        "id": col("Id da Marcação"), "agendado": pd.to_datetime(col("Data Agendado Para"), errors="coerce"),
        "nota": pd.to_numeric(col("NPS - Nota"), errors="coerce"), "resposta": pd.to_datetime(col("NPS - Data de Resposta"), errors="coerce"),
        "comentario": col("NPS - Comentário"), "profissional": col("Profissional"), "procedimento": col("Procedimento"),
        "unidade": col("Unidade"), "mes_filtro": col("Mês (filtro)")})
    d = d[d["nota"].between(0, 10)].copy()
    d["classe"] = d["nota"].apply(classe)
    # o mês é o do agendamento (o que o Klingo filtrou); sem data de agendamento, vale o mês em que o dado foi baixado
    d["ym"] = d["agendado"].dt.strftime("%Y-%m").where(d["agendado"].notna(), d["mes_filtro"])
    d["comentario"] = d["comentario"].where(d["comentario"].notna(), "").astype(str).str.replace(r"\s*\r?\n\s*", " ", regex=True).str.strip()
    d["comentario"] = d["comentario"].where(~d["comentario"].str.fullmatch(r"\W*\d{1,2}\W*"), "")   # "10", "8": a pessoa só repetiu a nota
    d["temas"] = d["comentario"].apply(lambda t: temas_do_texto(t, temas))
    return d.reset_index(drop=True)
