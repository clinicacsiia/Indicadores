"""Gera 'Dashboard Metas.html' a partir da planilha de dados e do metas.json.

Uso isolado (sem acessar o Klingo):  python gerar_dashboard.py
Também é chamado no final do extrair_laudo.py.
"""
import json
import math
import sys
import unicodedata
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent
RAIZ = PASTA.parent   # painel_base.css/js (visual comum dos painéis) ficam na pasta do portal
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
import painel_comum as pc  # noqa: E402
import armazenamento as arm  # noqa: E402  (na Vercel os dados vem do Supabase, nao do Excel)
PLANILHA = arm.PlanilhaVirtual(arm.PAINEL_METAS) if arm.ativo() else PASTA / "Acompanhamento de META.xlsx"
METAS = PASTA / "metas.json"
MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard Metas.html"

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
LIMITE_ATENCAO = 0.75  # abaixo de 75% do esperado até hoje = atrasado


def norm(texto) -> str:
    texto = "" if texto is None or (isinstance(texto, float) and math.isnan(texto)) else str(texto)
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper().strip()


COLUNAS_DADOS = ["Exames Realizados", "Unidade", "Procedimento - Classes", "Especialidade", "Data do Atendimento", "Procedimento", "Mês"]   # mais "Convênio", opcional (SUS x não-SUS)


def carregar_dados() -> pd.DataFrame:
    if arm.ativo():
        df = arm.ler_metas_dados()
        if df is None:
            df = pd.DataFrame(columns=COLUNAS_DADOS)
    elif PLANILHA.exists():
        df = pd.read_excel(PLANILHA, sheet_name="Dados")
    else:   # primeira vez (ou planilha apagada): painel vazio; o botão "Atualizar agora" baixa tudo e cria a planilha
        df = pd.DataFrame(columns=COLUNAS_DADOS)
    df["Data do Atendimento"] = pd.to_datetime(df["Data do Atendimento"])
    df["_uni"] = df["Unidade"].map(norm)
    df["_esp"] = df["Especialidade"].map(norm)
    df["_proc"] = df["Procedimento"].map(norm)
    # So o nome exato "SUS" e SUS: "SUS CURSO" (hoje "CETRUS") e um curso, conta como nao SUS.
    df["_sus"] = df["Convênio"].map(norm) == "SUS" if "Convênio" in df.columns else False
    df["_conv"] = df["Convênio"].map(norm) != "" if "Convênio" in df.columns else False   # False = linha sem convênio informado
    df["_classes"] = df["Procedimento - Classes"].map(
        lambda c: {t.strip().upper() for t in str(c).split(",") if t.strip()} if isinstance(c, str) else set())
    return df


def mascara(df: pd.DataFrame, unidade: str, regra: dict) -> pd.Series:
    if not regra:
        raise ValueError("Meta sem 'regra': ela contaria todos os atendimentos da unidade.")
    m = df["_uni"] == norm(unidade)
    if "classe" in regra:
        alvo = regra["classe"].upper()
        m &= df["_classes"].map(lambda c: alvo in c)
    if "classes_iguais" in regra:
        alvo = {c.upper() for c in regra["classes_iguais"]}
        m &= df["_classes"].map(lambda c: c == alvo)
    if "especialidade" in regra:
        m &= df["_esp"] == norm(regra["especialidade"])
    if "procedimento_igual" in regra:
        m &= df["_proc"] == norm(regra["procedimento_igual"])
    if "procedimento_contem" in regra:
        termos = [norm(t) for t in regra["procedimento_contem"]]
        m &= df["_proc"].map(lambda p: any(t in p for t in termos))
    if "procedimento_nao_contem" in regra:
        termos = [norm(t) for t in regra["procedimento_nao_contem"]]
        m &= ~df["_proc"].map(lambda p: any(t in p for t in termos))
    return m


def dias_uteis(ano: int, mes: int, semana: set, feriados: set) -> list[date]:
    n = monthrange(ano, mes)[1]
    return [date(ano, mes, d) for d in range(1, n + 1)
            if date(ano, mes, d).weekday() in semana and date(ano, mes, d) not in feriados]


def uteis_do_periodo(per: pc.Periodo, semana: set, feriados: set) -> list[date]:
    """Dias uteis dentro dos dias exatos do periodo (num periodo de meses inteiros, sao os dos meses)."""
    return [d for d in per.dias() if d.weekday() in semana and d not in feriados]


def status_de(pct: float, esperado: float) -> str:
    if pct >= 100:
        return "batida"
    if esperado <= 0:
        return "ritmo"
    razao = pct / esperado
    if razao >= 1:
        return "ritmo"
    return "atencao" if razao >= LIMITE_ATENCAO else "atrasado"


def texto_semana(semana: set) -> str:
    idx = sorted(semana)
    nomes = [DIAS[i] for i in idx]
    if len(idx) > 1 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{nomes[0]} a {nomes[-1]}"
    return ", ".join(nomes)


def fracao_do_dia(agora: datetime, cfg: dict) -> float:
    """Quanto do expediente de hoje já passou (0 a 1), para não contar o dia inteiro as 13h."""
    abre, fecha = (datetime.combine(agora.date(), datetime.strptime(h, "%H:%M").time())
                   for h in cfg.get("horario_atendimento", ["07:00", "18:00"]))
    return min(max((agora - abre) / (fecha - abre), 0.0), 1.0)


def montar_mes(df_mes: pd.DataFrame, ym: str, cfg: dict, agora: datetime, avisos: list, per: pc.Periodo | None = None) -> dict:
    """Um mes, ou (per) um periodo de varios meses: "ym" e o ultimo mes dele, "df_mes" tem as linhas de todos os meses; a meta do periodo e a
    soma das metas dos meses, os dias uteis somam os dos meses e o grafico dia a dia (que so existe dentro de um mes) nao e montado."""
    hoje = agora.date()
    ano, mes = int(ym[:4]), int(ym[5:])
    yms = per.yms if per else [ym]
    semana = set(cfg.get("dias_semana_atendimento", [0, 1, 2, 3, 4, 5]))
    feriados = {date.fromisoformat(f) for f in cfg.get("feriados", [])}
    uteis = uteis_do_periodo(per, semana, feriados) if per else dias_uteis(ano, mes, semana, feriados)
    total_uteis = len(uteis)
    fechado = per.fechado(hoje) if per else date(ano, mes, monthrange(ano, mes)[1]) < hoje
    # meta de cada mes do periodo: o mes inteiro, ou (recorte de dias) a parte proporcional aos dias uteis do recorte dentro dele
    fracao_mes = {y: 1.0 for y in yms}
    if per and per.exato:
        for y in yms:
            do_mes = len(dias_uteis(int(y[:4]), int(y[5:]), semana, feriados))
            fracao_mes[y] = sum(1 for u in uteis if u.strftime("%Y-%m") == y) / do_mes if do_mes else 0.0
    if fechado:
        decorridos = float(total_uteis)
    else:
        decorridos = float(sum(1 for d in uteis if d < hoje))
        if hoje in uteis:  # hoje conta só a parte do expediente que já passou
            decorridos += fracao_do_dia(agora, cfg)
    restantes = total_uteis - decorridos
    esperado = decorridos / total_uteis * 100 if total_uteis else 0.0
    ajustes_mes = cfg.get("metas_por_mes", {})

    contagem = pd.Series(0, index=df_mes.index)
    grupos, soma_meta, soma_cap, itens_total, itens_ok = [], 0, 0, 0, 0
    dia_do_mes = df_mes["Data do Atendimento"].dt.day
    por_item_dia = []   # (meta, atendimentos acumulados por dia) de cada meta: só para o gráfico do ritmo
    for g in cfg["grupos"]:
        itens, g_meta, g_cap, g_ok = [], 0, 0, 0
        for it in g["itens"]:
            m = mascara(df_mes, g["unidade"], it["regra"])
            contagem += m.astype(int)
            realizado = int(m.sum())
            sus = int((m & df_mes["_sus"]).sum())
            sem_conv = int((m & ~df_mes["_conv"]).sum())
            meta = round(sum(int(ajustes_mes.get(y, {}).get(f"{g['id']}/{it['id']}", it["meta"])) * fracao_mes[y] for y in yms))
            if not per:
                por_item_dia.append((meta, m.groupby(dia_do_mes[m]).size().reindex(range(1, monthrange(ano, mes)[1] + 1), fill_value=0).cumsum()))
            pct = realizado / meta * 100 if meta else 0.0
            st = status_de(pct, esperado)
            faltam = max(meta - realizado, 0)
            itens.append({
                "id": it["id"], "nome": it["nome"], "meta": meta, "realizado": realizado, "sus": sus, "nao_sus": realizado - sus - sem_conv, "sem_conv": sem_conv,
                "pct": pct, "faltam": faltam, "status": st,
                "por_dia": math.ceil(faltam / restantes) if faltam and restantes >= 0.5 else None,
                "projecao": round(realizado / decorridos * total_uteis) if decorridos >= 0.5 and not fechado else None,
            })
            g_meta += meta
            g_cap += min(realizado, meta)
            g_ok += st in ("batida", "ritmo")
        g_pct = g_cap / g_meta * 100 if g_meta else 0.0
        grupos.append({"id": g["id"], "nome": g["nome"], "unidade": g["unidade"], "itens": itens,
                       "pct": g_pct, "status": status_de(g_pct, esperado), "ok": g_ok})
        soma_meta += g_meta
        soma_cap += g_cap
        itens_total += len(itens)
        itens_ok += g_ok

    conflitos = df_mes[contagem > 1]
    if len(conflitos):
        avisos.append(f"{ym}: {len(conflitos)} atendimento(s) contam em mais de uma meta "
                      f"(ex.: {conflitos['Procedimento'].iloc[0]}). Ajuste as regras no metas.json.")
    fora = (df_mes[contagem == 0].groupby(["Unidade", "Especialidade", "Procedimento"]).size()
            .reset_index(name="qtd").sort_values("qtd", ascending=False))

    geral_pct = soma_cap / soma_meta * 100 if soma_meta else 0.0

    # série diária para o gráfico: % das metas já cumprido ao fim de cada dia (cada meta limitada a 100%, como no geral)
    # e o esperado pelos dias úteis. Não entra em nenhum cálculo.
    ndias = monthrange(ano, mes)[1]
    ate = ndias if fechado else min(hoje.day, ndias)
    atend_dia = df_mes.groupby(dia_do_mes).size().reindex(range(1, ndias + 1), fill_value=0)
    serie = []
    for d in range(1, 1 if per else ndias + 1):   # num periodo de varios meses nao ha "dia do mes" que se compare
        esp_d = sum(1 for u in uteis if u.day <= d) / total_uteis * 100 if total_uteis else 0.0
        ponto = {"d": d, "esp": round(esp_d, 2)}
        if d <= ate:
            ponto["n"] = int(atend_dia[d])
            ponto["pct"] = round(sum(min(int(c[d]), meta) for meta, c in por_item_dia) / soma_meta * 100, 2) if soma_meta else 0.0
            if d == ate and not fechado:
                ponto["esp"] = round(esperado, 2)   # hoje conta só a parte do expediente que já passou
        serie.append(ponto)
    return {
        "dias": serie,
        "rotulo": per.rotulo if per else f"{MESES[mes - 1]}/{ano}",
        "fechado": fechado,
        "uteis_total": total_uteis, "uteis_decorridos": round(decorridos, 1), "uteis_restantes": round(restantes, 1),
        "esperado_pct": esperado,
        "ultimo_atendimento": df_mes["Data do Atendimento"].max().strftime("%d/%m/%Y %H:%M") if len(df_mes) else None,
        "convenio_ok": bool(df_mes["_conv"].any()),
        "total_atendimentos": int(len(df_mes)), "total_fora": int((contagem == 0).sum()),
        "geral": {"pct": geral_pct, "status": status_de(geral_pct, esperado),
                  "itens_total": itens_total, "itens_ok": itens_ok},
        "grupos": grupos,
        "fora": fora.to_dict("records"),
    }


def montar_periodo(per: pc.Periodo, df: pd.DataFrame, ym_de_cada: pd.Series, cfg: dict, agora: datetime, avisos: list) -> dict:
    """Varios meses (ou dias exatos) juntos: as linhas do periodo, com a conta de um mes (ver montar_mes)."""
    linhas = df[per.dentro(df["Data do Atendimento"])] if per.exato else df[ym_de_cada.isin(per.yms)]
    return montar_mes(linhas, per.fim, cfg, agora, avisos, per=per)


def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` ("AAAA-MM") = periodo pedido no filtro; com `devolver_html` devolve a pagina (texto) em vez de gravar."""
    cfg = json.loads(METAS.read_text(encoding="utf-8-sig"))   # -sig: Bloco de Notas/PowerShell gravam UTF-8 com BOM
    df = carregar_dados()
    agora = datetime.now()
    avisos: list[str] = []
    meses = {}
    ym_linha = df["Data do Atendimento"].dt.strftime("%Y-%m")
    primeiro = max(cfg.get("primeiro_mes", "0000-00"), pc.INICIO_KLINGO)   # nunca antes do uso do Klingo, mesmo que o metas.json peca
    for ym, df_mes in df.groupby(ym_linha):
        if ym >= primeiro:
            meses[ym] = montar_mes(df_mes, ym, cfg, agora, avisos)
    per, info = pc.periodo_pedido(de, ate, meses)
    if per and not per.unico:
        pc.acrescentar_periodo(meses, per, lambda p: montar_periodo(p, df, ym_linha, cfg, agora, [] if p is not per else avisos))

    dados_em = datetime.fromtimestamp(PLANILHA.stat().st_mtime) if PLANILHA.exists() else agora  # quando o Klingo foi consultado pela última vez
    payload = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"),
        "versao": int(dados_em.timestamp()),
        "semana_txt": texto_semana(set(cfg.get("dias_semana_atendimento", [0, 1, 2, 3, 4, 5]))),
        "limite_atencao": LIMITE_ATENCAO,
        "mes_padrao": per.chave if per else (max(m for m in meses if ".." not in m) if meses else None), "periodo": info,
        "meses": meses,
    }
    pc.completar_payload(payload)
    json_txt = json.dumps(pc.limpo(payload), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    css, js = RAIZ / "painel_base.css", RAIZ / "painel_base.js"
    if not (css.exists() and js.exists()):
        raise FileNotFoundError(f"O painel de Metas usa o visual comum do portal e não achou {css.name} / {js.name} em {RAIZ}. "
                                "Mantenha a pasta 'Acompanhamento de META' dentro da pasta do portal.")
    html = (MODELO.read_text(encoding="utf-8").replace("__CSS__", css.read_text(encoding="utf-8"))
            .replace("__JS_BASE__", js.read_text(encoding="utf-8").replace("</", "<\\/")).replace("__DADOS__", json_txt))
    for a in avisos:
        print(">>> AVISO:", a)
    if devolver_html:
        return html
    SAIDA.write_text(html, encoding="utf-8")
    return SAIDA


if __name__ == "__main__":
    print(">>> Dashboard gerado:", gerar())
