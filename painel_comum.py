"""Pecas comuns dos geradores de dashboard (Faturamento e Financeiro)."""
import hashlib
import json
import math
import re
import threading
from calendar import monthrange
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).parent
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def rotulo_mes(ym: str) -> str:
    return f"{MESES[int(ym[5:]) - 1]}/{ym[:4]}"


def _inicio_klingo() -> str:
    """Mes (AAAA-MM) em que o Klingo passou a ser usado (`inicio_klingo` do modulos.json). O que vem de antes e de teste ou do sistema
    anterior (Clinical): nenhum historico, media, comparacao ou previsao pode se apoiar nisso."""
    try:
        return str(json.loads((RAIZ / "modulos.json").read_text(encoding="utf-8-sig")).get("inicio_klingo") or "")[:7] or "2026-09"
    except (OSError, ValueError):
        return "2026-09"


INICIO_KLINGO = _inicio_klingo()
INICIO_KLINGO_DIA = f"{INICIO_KLINGO}-01"
AVISO_KLINGO = (f"O Klingo só passou a ser usado em {MESES[int(INICIO_KLINGO[5:]) - 1].lower()}/{INICIO_KLINGO[:4]}: o que vem de antes é de teste ou do "
                "sistema anterior (Clinical) e não entra em históricos, médias, comparações nem previsões.")


def antes_do_klingo(ym) -> bool:
    """O mes (AAAA-MM, ou AAAA-MM-DD) e anterior ao inicio do Klingo?"""
    return str(ym)[:7] < INICIO_KLINGO


def a_partir_do_klingo(meses, *, permitir_antes: bool = False) -> list[str]:
    """Os meses (AAAA-MM) que valem para historico e comparacao: so os do Klingo em diante."""
    return sorted(m for m in meses if permitir_antes or not antes_do_klingo(m))


PADRAO_YM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PADRAO_CHAVE_MES = PADRAO_YM   # chave de um mes simples; a de um periodo tem ".." ("2026-09..2026-10")


def mes_mais(ym: str, n: int) -> str:
    t = int(ym[:4]) * 12 + int(ym[5:]) - 1 + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def meses_entre(ini: str, fim: str) -> list[str]:
    t0, t1 = int(ini[:4]) * 12 + int(ini[5:]) - 1, int(fim[:4]) * 12 + int(fim[5:]) - 1
    return [mes_mais(ini, i) for i in range(t1 - t0 + 1)]


PADRAO_DIA = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def _dia(texto: str, inicio: bool) -> date:
    """'AAAA-MM' vira o primeiro (inicio) ou o ultimo dia do mes; 'AAAA-MM-DD' e o proprio dia."""
    if len(texto) == 7:
        a, m = int(texto[:4]), int(texto[5:])
        return date(a, m, 1) if inicio else date(a, m, monthrange(a, m)[1])
    return date.fromisoformat(texto)


def _valido(texto) -> bool:
    texto = str(texto or "").strip()
    if PADRAO_YM.match(texto):
        return True
    if not PADRAO_DIA.match(texto):
        return False
    try:
        date.fromisoformat(texto)
    except ValueError:
        return False
    return True


class Periodo:
    """Intervalo que o usuario escolheu no filtro De/Ate: de um mes inteiro a varios meses, ou dias exatos ("2026-09-10" a "2026-10-25").

    As pontas aceitam "AAAA-MM" (o mes inteiro) ou "AAAA-MM-DD". `ini`/`fim` sao sempre os MESES das pontas e `yms` os meses que o periodo
    toca; `dia_ini`/`dia_fim` sao os dias exatos e `exato` diz se o periodo corta algum mes no meio.

    A conta de um periodo e a MESMA de um mes: cada painel junta as linhas do periodo numa so (ver `reagrupar`) e chama o calculo mensal de
    sempre. `anterior` e o periodo de mesmo tamanho logo antes (base das comparacoes)."""

    def __init__(self, ini: str, fim: str):
        a, b = _dia(ini, True), _dia(fim, False)
        if a > b:
            a, b = _dia(fim, True), _dia(ini, False)
        self.dia_ini, self.dia_fim = a, b
        self.exato = not (a.day == 1 and b.day == monthrange(b.year, b.month)[1])
        self.ini, self.fim = a.strftime("%Y-%m"), b.strftime("%Y-%m")
        self.yms = meses_entre(self.ini, self.fim)

    @property
    def n(self) -> int:
        return len(self.yms)

    @property
    def n_dias(self) -> int:
        return (self.dia_fim - self.dia_ini).days + 1

    @property
    def unico(self) -> bool:
        """Um mes inteiro so (a pagina de sempre). Um recorte de dias dentro de um mes NAO e unico: precisa ser calculado."""
        return self.n == 1 and not self.exato

    @property
    def chave(self) -> str:
        if self.exato:
            return f"{self.dia_ini.isoformat()}..{self.dia_fim.isoformat()}"
        return self.ini if self.unico else f"{self.ini}..{self.fim}"

    @property
    def rotulo(self) -> str:
        if self.exato:
            if self.dia_ini == self.dia_fim:
                return self.dia_ini.strftime("%d/%m/%Y")
            return f"{self.dia_ini.strftime('%d/%m/%Y')} a {self.dia_fim.strftime('%d/%m/%Y')}"
        return rotulo_mes(self.ini) if self.unico else f"{rotulo_mes(self.ini)} a {rotulo_mes(self.fim)}"

    @property
    def anterior(self) -> "Periodo":
        if self.exato:   # mesma quantidade de dias, terminando na vespera
            fim = self.dia_ini - timedelta(days=1)
            return Periodo((fim - timedelta(days=self.n_dias - 1)).isoformat(), fim.isoformat())
        return Periodo(mes_mais(self.ini, -self.n), mes_mais(self.ini, -1))

    @property
    def meses_inteiros(self) -> "Periodo":
        """Os meses inteiros que o periodo toca (o proprio periodo, se ele ja e de meses inteiros): para dados que so existem por mes."""
        return Periodo(self.ini, self.fim) if self.exato else self

    def contem(self, serie: pd.Series) -> pd.Series:
        """Serie de meses 'AAAA-MM' -> True nos meses que o periodo toca (para dados que so existem por mes)."""
        return serie.isin(self.yms)

    def dentro(self, datas: pd.Series) -> pd.Series:
        """Serie de datas -> True nos dias do periodo (a hora e ignorada)."""
        d = pd.to_datetime(datas, errors="coerce")
        return (d >= pd.Timestamp(self.dia_ini)) & (d < pd.Timestamp(self.dia_fim) + pd.Timedelta(days=1))

    def dias(self) -> list[date]:
        return [self.dia_ini + timedelta(days=i) for i in range(self.n_dias)]

    def fechado(self, hoje: date) -> bool:
        """O ultimo dia do periodo ja passou (hoje, que ainda esta em curso, nao conta)."""
        return self.dia_fim < hoje


def periodo_da_consulta(de, ate) -> "tuple[str, str] | None":
    """(de, ate) no formato do pedido que o servidor repassa ao painel: meses inteiros ('AAAA-MM') ou dias exatos ('AAAA-MM-DD').
    None quando nao ha pedido valido ou quando e um mes inteiro so (essa e a pagina de sempre, em que o proprio painel escolhe o mes)."""
    de, ate = str(de or "").strip(), str(ate or "").strip()
    if not (_valido(de) and _valido(ate)):
        return None
    per = Periodo(de, ate)
    if per.unico:
        return None
    return (per.dia_ini.isoformat(), per.dia_fim.isoformat()) if per.exato else (per.ini, per.fim)


def periodo_pedido(de, ate, existentes, permitir_antes: bool = False) -> "tuple[Periodo | None, dict | None]":
    """(periodo, info) do que o usuario pediu (?de=AAAA-MM&ate=AAAA-MM, ou com dias: AAAA-MM-DD). `existentes` = meses que o painel tem.
    Sem pedido valido: (None, None). O periodo pedido e recortado ao que o painel tem; sem nenhum mes dentro dele, `info["vazio"]` = True.
    Meses de antes do inicio do Klingo (teste ou sistema anterior) nunca entram no periodo, a menos que o painel diga `permitir_antes`;
    quando o pedido os inclui, `info["antes_klingo"]` e True e a pagina explica o recorte.
    `info` e o que vai no payload["periodo"] para a pagina mostrar o filtro e o texto 'de ... a ...'."""
    de, ate = str(de or "").strip(), str(ate or "").strip()
    if not (_valido(de) and _valido(ate)):
        return None, None
    pedido = Periodo(de, ate)
    tem = a_partir_do_klingo((m for m in existentes if PADRAO_YM.match(str(m))), permitir_antes=permitir_antes)
    dentro = [m for m in tem if pedido.ini <= m <= pedido.fim]
    info = {"de": pedido.ini, "ate": pedido.fim, "dia_de": pedido.dia_ini.isoformat(), "dia_ate": pedido.dia_fim.isoformat(),
            "exato": pedido.exato, "vazio": not dentro, "recortado": False, "chave": None,
            "antes_klingo": (not permitir_antes) and pedido.dia_ini < date.fromisoformat(INICIO_KLINGO_DIA)}
    if not dentro:
        return None, info
    # recorta ao que o painel tem: o primeiro e o ultimo mes com dados dentro do pedido (e, num recorte de dias, nao passa das pontas do pedido)
    ini = max(pedido.dia_ini, _dia(dentro[0], True))
    fim = min(pedido.dia_fim, _dia(dentro[-1], False))
    per = Periodo(ini.isoformat(), fim.isoformat())
    info.update(de=per.ini, ate=per.fim, dia_de=per.dia_ini.isoformat(), dia_ate=per.dia_fim.isoformat(), exato=per.exato,
                recortado=(per.dia_ini, per.dia_fim) != (pedido.dia_ini, pedido.dia_fim), chave=per.chave,
                pedido_de=pedido.ini, pedido_ate=pedido.fim, pedido_dia_de=pedido.dia_ini.isoformat(), pedido_dia_ate=pedido.dia_fim.isoformat())
    return per, info


def acrescentar_periodo(meses: dict, per: "Periodo", montar, permitir_antes: bool = False) -> None:
    """Poe em `meses` o periodo (varios meses ou um recorte de dias) e, se o painel tem dados antes dele, o periodo anterior (base das
    comparacoes; so entra na pagina, fora da lista do filtro). `montar(periodo)` devolve o dict do periodo, como o do mes.
    O periodo anterior so vale se comeca no Klingo ou depois: comparar com teste ou com o sistema anterior (Clinical) engana."""
    ant = per.anterior
    tem_anterior = any(m in meses for m in ant.yms) and (permitir_antes or ant.dia_ini >= date.fromisoformat(INICIO_KLINGO_DIA))
    meses[per.chave] = montar(per)
    meses[per.chave].update(periodo=True, n_meses=per.n, n_dias=per.n_dias, exato=per.exato, meses_do_periodo=per.yms,
                            chave_anterior=ant.chave if tem_anterior else None)
    if tem_anterior:
        meses[ant.chave] = montar(ant)


def reagrupar(df: pd.DataFrame, col: str, per: "Periodo", incluir_anterior: bool = True, ref: "Periodo | None" = None,
              datacol: str | None = None) -> pd.DataFrame:
    """Copia de `df` so com as linhas do periodo (e do anterior), com a coluna de mes `col` trocada: tudo do periodo vira o ultimo mes
    dele (per.fim) e tudo do periodo anterior vira o mes antes dele. Assim o calculo mensal de sempre, chamado com `per.fim`, enxerga o
    periodo inteiro como 'o mes' e o periodo anterior como 'o mes anterior'.
    `datacol` = coluna de data da linha: num periodo de DIAS EXATOS e ela quem recorta (sem ela, dados que so existem por mes entram
    pelos meses inteiros que o periodo toca). Num periodo de meses inteiros, o mes em `col` basta.
    `ref` = outro conjunto de meses para fazer o papel do 'mes anterior' (ex.: so os meses ja fechados do proprio periodo, quando o
    ultimo mes ainda esta aberto); pode se sobrepor ao periodo."""
    if per.exato and datacol is None:   # dado que so existe por mes: os meses inteiros que o periodo toca, e os meses antes deles
        return reagrupar(df, col, per.meses_inteiros, incluir_anterior, ref)
    alvo_ant = mes_mais(per.fim, -1)
    ant = ref or per.anterior

    def recorte(p: "Periodo") -> pd.DataFrame:
        if datacol is not None and (p.exato or per.exato) and datacol in df.columns:
            return df[p.dentro(df[datacol])].copy()
        return df[df[col].isin(p.yms)].copy()

    atual = recorte(per)
    atual[col] = per.fim
    if not incluir_anterior:
        return atual
    antes = recorte(ant)
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
    """Campos que o filtro de periodo (painel_base.js) espera em todo painel: 'hoje' e a lista de meses que o filtro oferece.
    Tambem diz a pagina quando o Klingo comecou (`inicio_klingo`): meses de antes ficam de fora do painel e do filtro, a menos que o painel
    declare `historico_antes_klingo` (so a Despesas: ela traz a planilha antiga, mostrada como historico que pode estar incompleto)."""
    payload.setdefault("hoje", date.today().isoformat())
    payload["inicio_klingo"] = INICIO_KLINGO
    payload["aviso_klingo"] = AVISO_KLINGO
    meses = payload.get("meses", {})
    if not payload.get("historico_antes_klingo"):
        for m in [m for m in meses if PADRAO_YM.match(str(m)) and antes_do_klingo(m)]:
            del meses[m]
    payload["todos_meses"] = sorted(m for m in meses if PADRAO_YM.match(str(m)))
    return payload


@lru_cache(maxsize=1)
def versao_layout() -> str:
    """Impressao digital do que desenha as paginas (CSS e JS base, modelos HTML e geradores). Vai escrita em cada pagina pronta: mudou o
    layout, a pagina guardada deixa de valer e e refeita, mesmo com os dados e o dia iguais."""
    arquivos = [RAIZ / "painel_base.css", RAIZ / "painel_base.js", Path(__file__)]
    arquivos += sorted(RAIZ.glob("*/dashboard_modelo.html")) + sorted(RAIZ.glob("*/gerar_*.py"))
    h = hashlib.sha1()
    for a in arquivos:
        h.update(a.relative_to(RAIZ).as_posix().encode())
        h.update(a.read_bytes())
    return h.hexdigest()[:12]


def marca_layout() -> str:
    return f"<!-- layout:{versao_layout()} -->"


_ULTIMA = threading.local()


def payload_montado() -> dict | None:
    """O payload da ultima pagina montada nesta linha de execucao (e esquece): e dele que sai a aba Avisos, sem calcular o painel duas vezes."""
    payload, _ULTIMA.payload = getattr(_ULTIMA, "payload", None), None
    return payload


def montar_html(modelo: Path, payload: dict) -> str:
    completar_payload(payload)
    _ULTIMA.payload = payload
    css = (RAIZ / "painel_base.css").read_text(encoding="utf-8")
    js = (RAIZ / "painel_base.js").read_text(encoding="utf-8")
    dados = json.dumps(limpo(payload), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return (modelo.read_text(encoding="utf-8")
            .replace("__CSS__", css).replace("__JS_BASE__", js.replace("</", "<\\/")).replace("__DADOS__", dados)) + marca_layout()


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
