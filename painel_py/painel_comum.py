"""Funcoes comuns dos paineis: periodo De/ate, agrupamentos e montagem da pagina.

ATENCAO: o arquivo original do legado (painel_comum.py) nao veio na copia recebida. Este modulo foi RECONSTRUIDO a partir de como os
gerar_*.py o usam (nomes, argumentos e o que fazem com o resultado) e da descricao do comportamento no prompt do projeto. As decisoes
de interpretacao estao em docs/PREMISSAS.md (secao "Modulos reconstruidos").
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).parent
PADRAO_YM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

# pasta de cada menu -> id do menu (modulos.json)
MENU_DA_PASTA = {
    "Acompanhamento de META": "metas", "Faturamento": "faturamento", "Financeiro": "financeiro", "Despesas": "despesas",
    "Indicadores": "indicadores", "Cesta": "cesta", "Suprimentos": "suprimentos", "Atendimento": "atendimento",
}
TITULO_DO_MENU = {
    "metas": "Metas", "faturamento": "Faturamento", "financeiro": "Financeiro", "despesas": "Despesas",
    "indicadores": "Indicadores", "cesta": "Cesta", "suprimentos": "Suprimentos", "atendimento": "Atendimento",
}


# ---------------------------------------------------------------- meses
def mes_mais(ym: str, n: int) -> str:
    total = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def meses_entre(a: str, b: str) -> list[str]:
    """Todos os meses de a ate b, inclusive ([] se a > b)."""
    out, m = [], a
    while m <= b:
        out.append(m)
        m = mes_mais(m, 1)
    return out


def rotulo_mes(ym: str) -> str:
    return f"{MESES[int(ym[5:7]) - 1]}/{ym[:4]}"


def ultimo_dia(ym: str) -> date:
    prox = mes_mais(ym, 1)
    return date.fromordinal(date(int(prox[:4]), int(prox[5:7]), 1).toordinal() - 1)


# ---------------------------------------------------------------- periodo De/ate
class Periodo:
    """Um ou mais meses seguidos. 'fim' e o ultimo mes: as contas de "um mes" rodam sobre ele (ver reagrupar)."""

    def __init__(self, ini: str, fim: str):
        if ini > fim:
            ini, fim = fim, ini
        self.ini, self.fim = ini, fim
        self.yms = meses_entre(ini, fim)

    @property
    def unico(self) -> bool:
        return self.ini == self.fim

    @property
    def chave(self) -> str:
        return self.fim if self.unico else f"{self.ini}..{self.fim}"

    @property
    def rotulo(self) -> str:
        return rotulo_mes(self.fim) if self.unico else f"{rotulo_mes(self.ini)} a {rotulo_mes(self.fim)}"

    @property
    def anterior(self) -> "Periodo":
        """O periodo imediatamente anterior, do mesmo tamanho."""
        n = len(self.yms)
        return Periodo(mes_mais(self.ini, -n), mes_mais(self.ini, -1))

    def __repr__(self) -> str:
        return f"Periodo({self.ini!r}, {self.fim!r})"


def _ym_valido(v) -> str | None:
    v = str(v).strip() if v is not None else ""
    return v if PADRAO_YM.match(v) else None


def _texto_periodo(per: Periodo, hoje: date) -> str:
    inicio = date(int(per.ini[:4]), int(per.ini[5:7]), 1)
    fim = min(ultimo_dia(per.fim), hoje)
    return f"Período: de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"


def periodo_pedido(de: str | None, ate: str | None, meses: dict) -> tuple[Periodo | None, dict]:
    """Traduz o filtro De/ate ("AAAA-MM") no periodo a calcular e no aviso que o painel mostra.

    Devolve (periodo, info). Sem pedido -> (None, {"pedido": False}) e o painel abre no mes padrao. Pedido sem nenhum dado -> (None, info com
    "aviso"). Pedido com dados so em parte dos meses -> o recorte que existe, e "aviso" diz qual."""
    disp = sorted(m for m in meses if ".." not in m)
    de_v, ate_v = _ym_valido(de), _ym_valido(ate)
    if not de_v and not ate_v:
        return None, {"pedido": False, "aviso": None}
    de_v = de_v or ate_v
    ate_v = ate_v or de_v
    if de_v > ate_v:
        de_v, ate_v = ate_v, de_v
    pedidos = meses_entre(de_v, ate_v)
    if len(pedidos) > 60:
        pedidos = pedidos[-60:]
        de_v = pedidos[0]
    com_dados = [m for m in pedidos if m in disp]
    info = {"pedido": True, "de_pedido": de_v, "ate_pedido": ate_v, "aviso": None}
    if not com_dados:
        info["aviso"] = f"Não há dados no período pedido ({rotulo_mes(de_v)} a {rotulo_mes(ate_v)})." if de_v != ate_v else f"Não há dados em {rotulo_mes(de_v)}."
        return None, info
    per = Periodo(com_dados[0], com_dados[-1])
    faltam = [m for m in pedidos if m not in disp]
    if faltam:
        info["aviso"] = (f"Só há dados de {rotulo_mes(per.ini)} a {rotulo_mes(per.fim)} dentro do período pedido; "
                         f"o painel mostra esse recorte (sem dados: {', '.join(rotulo_mes(m) for m in faltam[:6])}{'…' if len(faltam) > 6 else ''}).")
    info.update(de=per.ini, ate=per.fim, linha=_texto_periodo(per, date.today()))
    return per, info


def acrescentar_periodo(meses: dict, per: Periodo, calcular) -> None:
    """Guarda em meses[per.chave] o resultado de calcular(per) e, se todos os meses dele existem, o do periodo anterior (para comparar)."""
    def marcar(p: Periodo) -> dict:
        r = calcular(p)
        if isinstance(r, dict):   # o JS reconhece o periodo por estes campos (painel_base.js: anteriorDe, ehPeriodo)
            r.update(periodo=True, chave=p.chave, chave_anterior=p.anterior.chave, meses_do_periodo=p.yms, inicio=p.ini, fim=p.fim)
        return r

    meses[per.chave] = marcar(per)
    ant = per.anterior
    if all(m in meses for m in ant.yms):
        meses[ant.chave] = marcar(ant)


def reagrupar(df: pd.DataFrame, col: str, per: Periodo, ref: Periodo | None = None) -> pd.DataFrame:
    """Reescreve a coluna de mes para que as contas de "um mes" valham para o periodo todo: as linhas dos meses do periodo passam a ser do
    mes 'fim' e as do periodo anterior (ou de 'ref', se dado) passam a ser do mes anterior ao 'fim'. As demais saem."""
    if not len(df):
        return df
    anterior = (ref or per.anterior).yms
    mes_ant = mes_mais(per.fim, -1)
    novo = df[col].map(lambda m: per.fim if m in per.yms else (mes_ant if m in anterior else None))
    out = df.assign(**{col: novo})
    return out[out[col].notna()].copy()


# ---------------------------------------------------------------- agrupar e nomes
def agrupar(df: pd.DataFrame, col: str, valor: str, top: int | None = None, outros: str = "Outros") -> list[dict]:
    """Soma 'valor' por 'col', do maior para o menor, com a parte de cada um (%). Com 'top', o resto vira uma linha 'outros'."""
    if not len(df):
        return []
    g = df.assign(**{col: df[col].fillna("(sem informação)")}).groupby(col)[valor].sum().sort_values(ascending=False)
    g = g[g.abs() > 0] if (g.abs() > 0).any() else g
    total = float(g.sum())
    itens = [{"nome": str(n), "valor": float(v)} for n, v in g.items()]
    if top and len(itens) > top + 1:
        resto = sum(i["valor"] for i in itens[top:])
        itens = itens[:top] + [{"nome": outros, "valor": resto}]
    for i in itens:
        i["pct"] = (i["valor"] / total * 100) if total else 0.0
    return itens


def nome_curto_unidade(s) -> str:
    """Nome da unidade/empresa sem espacos sobrando (o legado nao veio: nenhum outro encurtamento e aplicado)."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return "(sem informação)"
    return re.sub(r"\s+", " ", str(s)).strip() or "(sem informação)"


# ---------------------------------------------------------------- serializacao e pagina
def limpo(o):
    """Deixa o payload pronto para JSON: NaN/inf/NaT -> None, Timestamps -> ISO, tipos numpy -> Python, conjuntos -> listas."""
    if o is None or isinstance(o, (bool, str)):
        return o
    if isinstance(o, dict):
        return {str(k): limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpo(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return [limpo(v) for v in sorted(o, key=str)]
    if isinstance(o, pd.Series):
        return [limpo(v) for v in o.tolist()]
    if isinstance(o, pd.DataFrame):
        return [limpo(r) for r in o.to_dict("records")]
    if o is pd.NaT:
        return None
    if isinstance(o, pd.Timestamp):
        if pd.isna(o):
            return None
        return o.strftime("%Y-%m-%d") if (o.hour, o.minute, o.second, o.microsecond) == (0, 0, 0, 0) else o.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(o, datetime):
        return o.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, Decimal):
        o = float(o)
    if hasattr(o, "item") and not isinstance(o, (int, float)):   # numpy escalar
        try:
            o = o.item()
        except (ValueError, AttributeError):
            return str(o)
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, int):
        return o
    return str(o)


def completar_payload(payload: dict, menu: str | None = None) -> dict:
    """Campos que todo painel precisa e que o gerar_* nao precisa repetir."""
    payload.setdefault("hoje", date.today().isoformat())
    payload.setdefault("periodo", {"pedido": False, "aviso": None})
    if menu:
        payload.setdefault("menu", menu)
        payload.setdefault("titulo", TITULO_DO_MENU.get(menu, menu))
    meses = payload.get("meses") or {}
    payload.setdefault("meses_disponiveis", sorted(m for m in meses if ".." not in m))
    return payload


def _menu_do_modelo(modelo: Path) -> str | None:
    return MENU_DA_PASTA.get(Path(modelo).parent.name)


def montar_html(modelo: Path, payload: dict) -> str:
    """Le o modelo HTML do menu e injeta o visual comum (__CSS__, __JS_BASE__) e os dados (__DADOS__)."""
    modelo = Path(modelo)
    completar_payload(payload, _menu_do_modelo(modelo))
    json_txt = json.dumps(limpo(payload), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    css, js = RAIZ / "painel_base.css", RAIZ / "painel_base.js"
    if not (css.exists() and js.exists()):
        raise FileNotFoundError(f"Faltam {css.name} / {js.name} em {RAIZ}.")
    return (modelo.read_text(encoding="utf-8").replace("__CSS__", css.read_text(encoding="utf-8"))
            .replace("__JS_BASE__", js.read_text(encoding="utf-8").replace("</", "<\\/")).replace("__DADOS__", json_txt))
