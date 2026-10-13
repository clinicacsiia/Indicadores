"""Pecas comuns dos geradores de dashboard (Faturamento e Financeiro)."""
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).parent
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def rotulo_mes(ym: str) -> str:
    return f"{MESES[int(ym[5:]) - 1]}/{ym[:4]}"


PADRAO_YM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PADRAO_CHAVE_MES = PADRAO_YM   # chave de um mes simples; a de um periodo tem ".." ("2026-09..2026-10")


def mes_mais(ym: str, n: int) -> str:
    t = int(ym[:4]) * 12 + int(ym[5:]) - 1 + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def meses_entre(ini: str, fim: str) -> list[str]:
    t0, t1 = int(ini[:4]) * 12 + int(ini[5:]) - 1, int(fim[:4]) * 12 + int(fim[5:]) - 1
    return [mes_mais(ini, i) for i in range(t1 - t0 + 1)]


class Periodo:
    """Intervalo de meses ("AAAA-MM" a "AAAA-MM", inclusive) que o usuario escolheu no filtro De/Ate.

    A conta de um periodo e a MESMA de um mes: cada painel junta as linhas de todos os meses do periodo numa so (ver `reagrupar`) e chama
    o calculo mensal de sempre. `anterior` e o periodo de mesmo tamanho logo antes (base das comparacoes)."""

    def __init__(self, ini: str, fim: str):
        self.ini, self.fim = (ini, fim) if ini <= fim else (fim, ini)
        self.yms = meses_entre(self.ini, self.fim)

    @property
    def n(self) -> int:
        return len(self.yms)

    @property
    def unico(self) -> bool:
        return self.n == 1

    @property
    def chave(self) -> str:
        return self.ini if self.unico else f"{self.ini}..{self.fim}"

    @property
    def rotulo(self) -> str:
        return rotulo_mes(self.ini) if self.unico else f"{rotulo_mes(self.ini)} a {rotulo_mes(self.fim)}"

    @property
    def anterior(self) -> "Periodo":
        return Periodo(mes_mais(self.ini, -self.n), mes_mais(self.ini, -1))

    def contem(self, serie: pd.Series) -> pd.Series:
        return serie.isin(self.yms)


def periodo_pedido(de, ate, existentes) -> "tuple[Periodo | None, dict | None]":
    """(periodo, info) do que o usuario pediu (?de=AAAA-MM&ate=AAAA-MM). `existentes` = meses que o painel tem.
    Sem pedido valido: (None, None). O periodo pedido e recortado ao que o painel tem; sem nenhum mes dentro dele, `info["vazio"]` = True.
    `info` e o que vai no payload["periodo"] para a pagina mostrar o filtro e o texto 'de ... a ...'."""
    de, ate = str(de or "").strip(), str(ate or "").strip()
    if not (PADRAO_YM.match(de) and PADRAO_YM.match(ate)):
        return None, None
    if de > ate:
        de, ate = ate, de
    tem = sorted(m for m in existentes if PADRAO_YM.match(str(m)))
    dentro = [m for m in tem if de <= m <= ate]
    info = {"de": de, "ate": ate, "vazio": not dentro, "recortado": False, "chave": None}
    if not dentro:
        return None, info
    per = Periodo(dentro[0], dentro[-1])
    info.update(de=per.ini, ate=per.fim, recortado=(per.ini, per.fim) != (de, ate), chave=per.chave, pedido_de=de, pedido_ate=ate)
    return per, info


def acrescentar_periodo(meses: dict, per: "Periodo", montar) -> None:
    """Poe em `meses` o periodo de varios meses e, se o painel tem dados antes dele, o periodo anterior (base das comparacoes; so entra
    na pagina, fora da lista do filtro). `montar(periodo)` devolve o dict do periodo, como o do mes."""
    ant = per.anterior
    tem_anterior = any(m in meses for m in ant.yms)
    meses[per.chave] = montar(per)
    meses[per.chave].update(periodo=True, n_meses=per.n, meses_do_periodo=per.yms, chave_anterior=ant.chave if tem_anterior else None)
    if tem_anterior:
        meses[ant.chave] = montar(ant)


def reagrupar(df: pd.DataFrame, col: str, per: "Periodo", incluir_anterior: bool = True, ref: "Periodo | None" = None) -> pd.DataFrame:
    """Copia de `df` so com as linhas dos meses do periodo (e do anterior), com a coluna de mes `col` trocada: tudo do periodo vira o
    ultimo mes dele (per.fim) e tudo do periodo anterior vira o mes antes dele. Assim o calculo mensal de sempre, chamado com
    `per.fim`, enxerga o periodo inteiro como 'o mes' e o periodo anterior como 'o mes anterior'.
    `ref` = outro conjunto de meses para fazer o papel do 'mes anterior' (ex.: so os meses ja fechados do proprio periodo, quando o
    ultimo mes ainda esta aberto); pode se sobrepor ao periodo."""
    alvo_ant = mes_mais(per.fim, -1)
    ant = ref or per.anterior
    atual = df[df[col].isin(per.yms)].copy()
    atual[col] = per.fim
    if not incluir_anterior:
        return atual
    antes = df[df[col].isin(ant.yms)].copy()
    antes[col] = alvo_ant
    return pd.concat([atual, antes], ignore_index=True)


def limpo(obj):
    """Converte para tipos que o JSON aceita (NaN e NaT viram null; numpy vira numero comum)."""
    if isinstance(obj, dict):
        return {str(k): limpo(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [limpo(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if (math.isnan(obj) or math.isinf(obj)) else float(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return None if pd.isna(obj) else obj.strftime("%Y-%m-%d")
    if isinstance(obj, date):
        return obj.isoformat()
    if obj is pd.NaT or (not isinstance(obj, (str, bool, int)) and obj is not None and pd.isna(obj)):
        return None
    return obj


def completar_payload(payload: dict) -> dict:
    """Campos que o filtro de periodo (painel_base.js) espera em todo painel: 'hoje' e a lista de meses que o filtro oferece."""
    payload.setdefault("hoje", date.today().isoformat())
    payload["todos_meses"] = sorted(m for m in payload.get("meses", {}) if PADRAO_YM.match(str(m)))
    return payload


def montar_html(modelo: Path, payload: dict) -> str:
    completar_payload(payload)
    css = (RAIZ / "painel_base.css").read_text(encoding="utf-8")
    js = (RAIZ / "painel_base.js").read_text(encoding="utf-8")
    dados = json.dumps(limpo(payload), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return (modelo.read_text(encoding="utf-8")
            .replace("__CSS__", css).replace("__JS_BASE__", js.replace("</", "<\\/")).replace("__DADOS__", dados))


def nome_curto_unidade(nome) -> str:
    s = str(nome or "(sem unidade)")
    return s.split(" - ")[-1] if "CLÍNICA DE SAÚDE E IMAGEM" in s else s


def agrupar(df: pd.DataFrame, por: str, valor: str, top: int | None = None, outros: str = "Outros", extra: dict | None = None) -> list[dict]:
    """Soma 'valor' por categoria, do maior para o menor; o que passa de 'top' vira 'Outros'."""
    if df.empty:
        return []
    g = df.groupby(por, dropna=False)[valor].sum().sort_values(ascending=False)
    total = g.sum()
    itens = [{"nome": ("(vazio)" if pd.isna(n) else str(n)), "valor": float(v), "pct": float(v / total * 100) if total else 0.0}
             for n, v in g.items()]
    if top and len(itens) > top:
        resto = itens[top:]
        itens = itens[:top] + [{"nome": f"{outros} ({len(resto)})", "valor": sum(i["valor"] for i in resto),
                                "pct": sum(i["pct"] for i in resto)}]
    return itens
