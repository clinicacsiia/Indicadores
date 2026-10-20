"""NPS × Google: a satisfação medida pela clínica (relatório #13697 do Klingo) ao lado da nota pública no Google Maps.

O NPS vem do banco (como os outros painéis: `relatorios.json` + `klingo_relatorios`); a nota e as avaliações do Google vêm da API oficial
(`google_maps.py`), guardadas no mesmo lugar. As contas ficam em `metricas_nps.py` (pandas puro, com testes).

Uso:  python gerar_nps.py             regenera o dashboard com o que já está guardado
      python gerar_nps.py --forcar    atualiza (Klingo e Google) e regenera
"""
import json
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent
RAIZ = PASTA.parent
for pasta in (RAIZ, PASTA):
    if str(pasta) not in sys.path:
        sys.path.insert(0, str(pasta))
import google_maps as gm  # noqa: E402
import klingo_relatorios as k  # noqa: E402
import metricas_nps as mn  # noqa: E402
import painel_comum as pc  # noqa: E402

MODELO = PASTA / "dashboard_modelo.html"
SAIDA = PASTA / "Dashboard NPS.html"
PARAMETROS = PASTA / "parametros.json"
ARQUIVOS_EXTRAS = (PARAMETROS,)    # o portal refaz a pagina quando este muda
ABA = "NPS"
PADRAO = {"meta_nps": 75, "minimo_grupo": 5, "minimo_google_equivalencia": 10, "unidades_no_google": None, "google_cid": None, "google_busca": "Clínica CSI", "temas": {}}
MAX_DETRATORES = 200    # comentários listados por período (os mais recentes); os totais contam todos
MAX_NEUTROS = 80
MAX_AVALIACOES_GOOGLE = 40
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def arquivo_dados():
    return k.planilha_de(PASTA)


def ler_parametros() -> dict:
    p = dict(PADRAO)
    try:
        p.update({c: v for c, v in json.loads(PARAMETROS.read_text(encoding="utf-8-sig")).items() if not c.startswith("_")})
    except (OSError, ValueError):
        pass
    return p


def atualizar(forcar: bool = False, historico: bool = False) -> dict:
    """Atualiza o NPS (do banco) e, se a chave do Google existe, a nota e as avaliações do Maps. Falha do Google vira aviso: o NPS segue."""
    r = k.atualizar(PASTA, forcar=forcar, historico=historico)
    try:
        g = gm.atualizar(ler_parametros(), forcar=forcar)
    except Exception as e:   # o Google nunca derruba a atualizacao do NPS
        g = {"atualizou": False, "avisos": [f"Google Maps: {type(e).__name__}: {e}"], "mensagem": f"Google Maps: {type(e).__name__}: {e}"}
    return {**r, "atualizou": bool(r.get("atualizou") or g.get("atualizou")), "avisos": [*r.get("avisos", []), *g.get("avisos", [])],
            "mensagem": " ".join(m for m in (r.get("mensagem"), g.get("mensagem")) if m)}


# ---------------------------------------------------------------- utilidades
def recorte(d: pd.DataFrame, per: "pc.Periodo") -> pd.DataFrame:
    """As respostas do período: pelo dia da resposta (como o Klingo filtra o relatório); sem data de resposta, pelo mês que a base lhes deu."""
    return d[per.dentro(d["resposta"]) | (d["resposta"].isna() & d["ym"].isin(per.yms))]


def linha_de_comentario(r) -> dict:
    return {"d": r.agendado.strftime("%Y-%m-%d") if pd.notna(r.agendado) else None, "nota": int(r.nota), "unidade": pc.nome_curto_unidade(r.unidade),
            "profissional": str(r.profissional or ""), "procedimento": str(r.procedimento or ""), "texto": r.comentario, "temas": list(r.temas)}


def _curto(itens: list[dict]) -> list[dict]:
    for i in itens:
        i["nome"] = pc.nome_curto_unidade(i["nome"]) if "CLÍNICA DE SAÚDE E IMAGEM" in i["nome"] else i["nome"]
    return itens


# ---------------------------------------------------------------- Google
def google_global(G: dict, p: dict) -> dict:
    """O que vale para a página inteira: se está configurado, o resumo mais recente e a série de resumos diários."""
    r = G["resumos"]
    ultimo = r[-1] if r else None
    return {"disponivel": gm.disponivel(), "configurado": gm.configurado(), "tem_dados": bool(r),
            "primeiro_dia": r[0]["dia"] if r else None,
            "atual": {"dia": ultimo["dia"], "nota": ultimo["nota"], "total": ultimo["total"], "nome": ultimo.get("nome", ""), "url": ultimo.get("url", "")} if ultimo else None,
            "serie": [{"d": x["dia"], "nota": x["nota"], "total": x["total"]} for x in r], "avaliacoes_guardadas": len(G["avaliacoes"])}


def google_do_periodo(G: dict, dia_ini: date, dia_fim: date, p: dict, temas: dict) -> dict:
    """Nota e avaliações do Google dentro do período. Nota e total vêm do último resumo até o fim do período; as novas avaliações são a diferença
    do total contra o resumo anterior ao período (ou o primeiro da coleta, que é de quando o histórico começa)."""
    ini, fim = dia_ini.isoformat(), dia_fim.isoformat()
    resumos = G["resumos"]
    ate_fim = [r for r in resumos if r["dia"] <= fim]
    no_fim = ate_fim[-1] if ate_fim else None
    antes = [r for r in resumos if r["dia"] < ini]
    base = antes[-1] if antes else (next((r for r in resumos if ini <= r["dia"] <= fim), None))
    out = {"nota": no_fim["nota"] if no_fim else None, "total": no_fim["total"] if no_fim else None, "dia": no_fim["dia"] if no_fim else None,
           "novas": (no_fim["total"] - base["total"]) if no_fim and base and base["dia"] < no_fim["dia"] else None,
           "base_dia": base["dia"] if base else None, "avaliacoes": [], "equivalente": None, "temas_baixas": [], "n_avaliacoes": 0}
    avs = [a for a in G["avaliacoes"] if ini <= (a.get("dia") or "") <= fim]
    out["n_avaliacoes"] = len(avs)
    if avs:
        out["equivalente"] = mn.nps_equivalente([int(a["nota"]) for a in avs]) if len(avs) >= p["minimo_google_equivalencia"] else None
        out["distribuicao"] = [sum(1 for a in avs if int(a["nota"]) == e) for e in range(1, 6)]
        out["avaliacoes"] = [{"d": a["dia"], "nota": int(a["nota"]), "texto": a.get("texto") or "", "temas": mn.temas_do_texto(a.get("texto"), temas)}
                             for a in avs[:MAX_AVALIACOES_GOOGLE]]
        baixas = pd.DataFrame([{"comentario": a.get("texto") or "", "classe": "Detrator" if int(a["nota"]) <= 3 else "Promotor" if int(a["nota"]) == 5 else "Neutro",
                                "temas": mn.temas_do_texto(a.get("texto"), temas)} for a in avs])
        out["temas_baixas"] = [t for t in mn.analisar_temas(baixas, temas) if t["det"]]
    return out


# ---------------------------------------------------------------- leituras automáticas
def faixa_do_nps(v: float, meta: float) -> tuple[str, str]:
    if v >= meta:
        return "ok", "dentro da meta"
    if v >= 50:
        return "info", "zona de qualidade (acima de 50)"
    if v >= 0:
        return "atencao", "zona de aperfeiçoamento (entre 0 e 50)"
    return "critico", "zona crítica (abaixo de 0)"


def leituras(kp: dict, f: dict, prev: dict | None, p: dict) -> list[dict]:
    """Frases prontas sobre o que os números dizem. Só afirma o que os dados mostram e diz quando a amostra é pequena demais."""
    out = []
    meta, minimo = p["meta_nps"], p["minimo_grupo"]
    if kp["n"] and kp["nps"] is not None:
        nivel, faixa = faixa_do_nps(kp["nps"], meta)
        out.append({"nivel": nivel, "texto": f"NPS de <b>{kp['nps']:.0f}</b> (margem de erro de ±{kp['margem']:.0f}), {faixa}: <b>{kp['pct_prom']:.0f}%</b> promotores, "
                                             f"{kp['pct_neut']:.0f}% neutros e <b>{kp['pct_det']:.0f}%</b> detratores em {kp['n']} respostas."})
    if prev and prev.get("kpis") and prev["kpis"].get("nps") is not None and kp["nps"] is not None:
        dif = kp["nps"] - prev["kpis"]["nps"]
        real = mn.diferenca_confiavel(kp, prev["kpis"])
        if abs(dif) >= 0.5:
            out.append({"nivel": "info" if real is not True else ("ok" if dif > 0 else "atencao"),
                        "texto": f"O NPS {'subiu' if dif > 0 else 'caiu'} <b>{abs(dif):.0f} pontos</b> contra o período anterior (de {prev['kpis']['nps']:.0f} para {kp['nps']:.0f}). "
                                 + ("A diferença é maior que a margem de erro: provavelmente é uma mudança real." if real else "Mas está <b>dentro da margem de erro</b>: com tão poucas respostas, pode ser só acaso.")})
    top = next((t for t in f["temas"] if t["det"] and t["id"] != "elogio"), None)
    if top and kp["det"]:
        out.append({"nivel": "atencao" if top["pontos"] and top["pontos"] >= 3 else "info",
                    "texto": f"<b>{top['rotulo']}</b> é o assunto mais citado pelos detratores: <b>{top['det']}</b> de {kp['det']} ({mn.pct_de(top['det'], kp['det']):.0f}%). "
                             f"Se esses detratores tivessem dado 9 ou 10, o NPS subiria <b>{br(top['pontos'], 1)} pontos</b>."})
    lista = f["detratores_lista"]
    com = sum(1 for x in lista if x["texto"])
    if kp["det"] and len(lista) == kp["det"] and com < kp["det"] * 0.7:   # a lista traz todos os detratores (nao foi cortada): da para contar quantos nao comentaram
        out.append({"nivel": "info", "texto": f"Só <b>{com}</b> dos {kp['det']} detratores deixaram comentário: sem ele não se sabe o motivo da nota. "
                                              "Perguntar “o que podemos melhorar?” logo depois de uma nota baixa aumenta esse número."})
    un = [u for u in f["unidades"] if not u["poucos"]]
    if len(un) >= 2:
        melhor, pior = max(un, key=lambda u: u["nps"]), min(un, key=lambda u: u["nps"])
        if melhor["nome"] != pior["nome"] and melhor["nps"] - pior["nps"] >= 5:
            real = mn.diferenca_confiavel(melhor, pior)
            out.append({"nivel": "atencao" if real else "info", "texto": f"<b>{pior['nome']}</b> tem NPS {pior['nps']:.0f} contra {melhor['nps']:.0f} de <b>{melhor['nome']}</b> "
                        f"({melhor['nps'] - pior['nps']:.0f} pontos de diferença"
                        + ("; é maior que a margem de erro" if real else "; ainda dentro da margem de erro, com as respostas de agora") + ")."})
    horas = [h for h in f["horas"] if not h["poucos"] and h["pct_det"] is not None]
    if horas and kp["pct_det"]:
        pior_h = max(horas, key=lambda h: h["pct_det"])
        if pior_h["pct_det"] >= 1.5 * kp["pct_det"] and pior_h["pct_det"] - kp["pct_det"] >= 5:
            out.append({"nivel": "info", "texto": f"Quem foi agendado às <b>{pior_h['h']:02d}h</b> deu mais nota baixa: <b>{pior_h['pct_det']:.0f}%</b> de detratores (a média é {kp['pct_det']:.0f}%), "
                                                  f"em {pior_h['n']} respostas. Compare com a hora de pico da espera na aba Tempo."})
    cam = f.get("meta")
    if cam and not cam["ja"]:
        txt = f"Para chegar a <b>{cam['meta']:.0f}</b> faltam <b>{cam['faltam_pontos']:.0f} pontos</b>: "
        txt += f"seria preciso virar <b>{cam['converter']}</b> detrator(es) em promotor" if cam["converter_cabe"] else f"nem converter todos os {kp['det']} detratores bastaria"
        txt += f", ou juntar mais <b>{cam['novas']}</b> respostas de promotores às {kp['n']} de agora." if cam["novas"] is not None else "."
        out.append({"nivel": "info", "texto": txt})
    neutros_com = [x for x in f["neutros_lista"] if x["texto"]]
    if kp["neut"] and kp["n"]:
        out.append({"nivel": "info", "texto": f"Há <b>{kp['neut']}</b> neutros ({kp['pct_neut']:.0f}%) a um ou dois pontos de virar promotores; <b>{len(neutros_com)}</b> disseram o que faltou. "
                                              "São o caminho mais curto para subir o NPS."})
    g = f["google"]
    if g and g.get("nota") is not None and kp["media"] is not None:
        est = mn.estrelas_do_nps(kp["media"])
        out.append({"nivel": "info", "texto": f"No Google a clínica tem <b>{br(g['nota'], 1)} estrelas</b> ({num_br(g['total'])} avaliações); a nota média do NPS equivale a <b>{br(est, 1)}</b> na mesma escala. "
                    + ("O Google está acima do que quem foi atendido diz à clínica: quem vai ao Google costuma ser quem já ficou satisfeito, ou o convidado pela recepção." if g["nota"] - est >= 0.3
                       else "O Google está abaixo do que quem foi atendido diz à clínica: quem avalia lá tende a ser quem teve um problema, e isso é público." if est - g["nota"] >= 0.3
                       else "Os dois contam a mesma história.")})
    return out


def num_br(v) -> str:
    return f"{int(v):,}".replace(",", ".")


def br(v, casas: int = 0) -> str:
    """Numero no formato da tela: virgula nos decimais (os textos das leituras sao escritos aqui, nao no navegador)."""
    return f"{v:.{casas}f}".replace(".", ",")


# ---------------------------------------------------------------- uma fatia (mês ou período)
def montar_fatia(rotulo: str, d: pd.DataFrame, p: dict, temas: dict, G: dict, dia_ini: date, dia_fim: date, mensal: bool, prev: dict | None = None) -> dict:
    minimo = p["minimo_grupo"]
    kp = mn.resumo(d)
    kp["dias"] = int(d["resposta"].dt.normalize().nunique())      # dias com resposta: um mes em andamento nao pode ser comparado com um mes inteiro pelo total
    kp["por_dia"] = round(kp["n"] / kp["dias"], 1) if kp["dias"] else None
    no_google = d[d["unidade"].isin(p["unidades_no_google"])] if p.get("unidades_no_google") else d
    detratores = d[(d["classe"] == "Detrator")].sort_values("agendado", ascending=False)
    neutros = d[(d["classe"] == "Neutro") & d["comentario"].ne("")].sort_values("agendado", ascending=False)
    f = {"rotulo": rotulo, "kpis": kp, "distribuicao": mn.distribuicao(d),
         "unidades": _curto(mn.grupos(d, "unidade", minimo)), "profissionais": mn.grupos(d, "profissional", minimo), "procedimentos": mn.grupos(d, "procedimento", minimo),
         "semana": mn.por_dia_da_semana(d, minimo), "horas": mn.por_hora(d, minimo), "dias": mn.por_dia(d) if mensal else [],
         "temas": mn.analisar_temas(d, temas), "meta": mn.caminho_para_a_meta(kp["prom"], kp["neut"], kp["det"], p["meta_nps"]),
         "detratores_lista": [linha_de_comentario(r) for r in detratores.head(MAX_DETRATORES).itertuples()],
         "neutros_lista": [linha_de_comentario(r) for r in neutros.head(MAX_NEUTROS).itertuples()],
         "google": google_do_periodo(G, dia_ini, dia_fim, p, temas)}
    comparavel = mn.resumo(no_google)
    f["comparavel"] = {**comparavel, "estrelas": mn.estrelas_do_nps(comparavel["media"])}
    f["leituras"] = leituras(kp, f, prev, p)
    return f


def serie_mensal(meses: dict, G: dict) -> list[dict]:
    """Um ponto por mês (do mais antigo ao mais novo) com o NPS e a nota do Google no fim do mês: a base do gráfico de comparação."""
    out = []
    for ym in sorted(m for m in meses if ".." not in m):
        m = meses[ym]
        no_mes = [r for r in G["resumos"] if r["dia"][:7] == ym]   # a nota do Google do mes e a do ultimo resumo guardado nele
        c = m["comparavel"]
        out.append({"ym": ym, "n": m["kpis"]["n"], "nps": m["kpis"]["nps"], "margem": m["kpis"]["margem"], "media": m["kpis"]["media"], "estrelas_nps": mn.estrelas_do_nps(m["kpis"]["media"]),
                    "nps_comparavel": c["nps"], "estrelas_comparavel": c["estrelas"], "google_nota": no_mes[-1]["nota"] if no_mes else None,
                    "google_total": no_mes[-1]["total"] if no_mes else None, "google_dia": no_mes[-1]["dia"] if no_mes else None})
    return out


# ---------------------------------------------------------------- montagem
def gerar(de: str | None = None, ate: str | None = None, devolver_html: bool = False):
    """Escreve o painel. `de`/`ate` = período pedido no filtro; com `devolver_html` devolve a página (texto) em vez de gravar."""
    agora = datetime.now()
    hoje = agora.date()
    p = ler_parametros()
    temas = mn.compilar_temas(p["temas"])
    abas = k.carregar(PASTA)
    d = mn.preparar(abas.get(ABA, pd.DataFrame()), temas)
    d = d[d["ym"].map(lambda m: isinstance(m, str) and not pc.antes_do_klingo(m)).astype(bool)]   # (astype: com a base vazia o mapa vem sem tipo e o pandas o leria como lista de colunas)
    G = gm.ler()
    meses, anterior = {}, None
    for ym in sorted(d["ym"].dropna().unique()):
        ini, fim = pc.Periodo(ym, ym).dia_ini, pc.Periodo(ym, ym).dia_fim
        meses[ym] = anterior = montar_fatia(pc.rotulo_mes(ym), d[d["ym"] == ym], p, temas, G, ini, min(fim, hoje), True, anterior)   # compara com o mes anterior com dado
        meses[ym]["fechado"] = fim < hoje
    per, info = pc.periodo_pedido(de, ate, meses)
    if per and not per.unico:
        def montar(q):
            dq = recorte(d, q)
            if not len(dq):
                return {"rotulo": q.rotulo, "kpis": None, "fechado": q.fechado(hoje)}
            return {**montar_fatia(q.rotulo, dq, p, temas, G, q.dia_ini, min(q.dia_fim, hoje), False), "fechado": q.fechado(hoje)}
        pc.acrescentar_periodo(meses, per, montar)
        atual = meses[per.chave]
        if atual.get("kpis"):   # as leituras de "subiu/caiu" comparam com o periodo anterior, que so existe depois de montado
            atual["leituras"] = leituras(atual["kpis"], atual, meses.get(atual.get("chave_anterior") or ""), p)
    arq = arquivo_dados()
    dados_em = datetime.fromtimestamp(arq.stat().st_mtime) if arq.exists() else agora
    com_dados = {m: v for m, v in meses.items() if v.get("kpis")}
    payload = {"gerado_em": agora.strftime("%d/%m/%Y %H:%M"), "dados_em": dados_em.strftime("%d/%m/%Y %H:%M"), "versao": int(dados_em.timestamp()),
               "hoje": hoje.isoformat(), "mes_padrao": per.chave if per else (max(m for m in meses if ".." not in m) if meses else None), "periodo": info,
               "meses": meses, "tem_dados": bool(com_dados), "serie": serie_mensal(meses, G), "google": google_global(G, p),
               "params": {"meta_nps": p["meta_nps"], "minimo_grupo": p["minimo_grupo"], "minimo_google_equivalencia": p["minimo_google_equivalencia"],
                          "unidades_no_google": p.get("unidades_no_google"), "temas": {tid: t.rotulo for tid, t in temas.items()}},
               "dias_semana": DIAS_SEMANA}
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
