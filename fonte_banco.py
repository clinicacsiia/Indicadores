"""Os paineis leem os dados do BANCO (coletados pela Edge Function sync-relatorios-dw), nao do Klingo.

Antes, cada painel tinha a sua propria coleta: ao clicar em "Atualizar" o Python consultava o Klingo mes a mes e
gravava em `painel_dados`. Agora existe uma coleta so (supabase/functions/sync-relatorios-dw, a cada 5 min no pg_cron)
que guarda tudo em `fact_relatorio_linha`; este modulo copia dali para o formato que os paineis ja leem. Os geradores
(gerar_*.py), as telas (*.html) e o `painel_dados` continuam os mesmos.

Regras (as mesmas que valiam no Klingo, mais as do banco):
- So entra o que o banco coletou COMPLETO: mes do relatorio com coleta bem-sucedida (granularidade 'mes') ou todos os
  dias do mes coletados (granularidade 'dia'). O que ainda nao foi coletado fica como estava e vira aviso.
- So entra relatorio cujo filtro de periodo o Klingo ja comprovou (`dim_relatorio.periodo_validado_em`); sem isso o
  Klingo pode ter devolvido o dia de hoje no lugar do periodo pedido.
- Linhas vem de `v_relatorio_linha_vigente` (so o que a ultima coleta de cada periodo viu), repetidas `repeticoes` vezes
  como o Klingo as devolveu; os titulos das colunas vem de `dim_relatorio_coluna`.
- Nao ha chamada ao Klingo: a atualizacao e rapida e nao depende do token nem do tempo limite da Vercel.
- `PAINEL_FONTE=klingo` volta ao caminho antigo (consulta direta ao Klingo) em caso de emergencia.
"""
import os
from datetime import date, datetime

import armazenamento as arm

PAGINA = 1000


class DadosIncompletos(RuntimeError):
    """O banco ainda nao tem este relatorio/periodo em condicoes de virar painel (nao coletado, sem titulos, filtro nao comprovado)."""


def ativa() -> bool:
    """Verdadeiro na nuvem, a menos que PAINEL_FONTE=klingo."""
    return arm.ativo() and os.environ.get("PAINEL_FONTE", "banco").strip().lower() != "klingo"


def _mes(iso: str) -> str:
    return iso[:7]


def hora_local(d: datetime | None) -> datetime | None:
    """O horario da coleta como o painel o guardava (datetime.now() do servidor, que roda em horario de Brasilia)."""
    return d.astimezone().replace(tzinfo=None) if d and d.tzinfo else d


# ---------------------------------------------------------------- consultas
def relatorio(klingo_id) -> dict | None:
    """Cadastro do relatorio em dim_relatorio (None se nao existir)."""
    _, _, res = arm._pedir("GET", "/rest/v1/dim_relatorio", {
        "klingo_id": f"eq.{klingo_id}",
        "select": "id,klingo_id,nome,ativo,supersedido_por,granularidade,filtro_periodo,periodo_validado_em",
    })
    return res[0] if res else None


def titulos(relatorio_id: str) -> dict[str, str]:
    """{chave da coluna (col0...): titulo do Klingo}. Coluna sem titulo fica de fora."""
    res = arm._paginado("/rest/v1/dim_relatorio_coluna", {"relatorio_id": f"eq.{relatorio_id}", "select": "coluna_key,titulo_klingo",
                                                          "order": "coluna_key.asc"}, PAGINA)
    return {r["coluna_key"]: r["titulo_klingo"] for r in res if r.get("titulo_klingo")}


def execucoes(relatorio_id: str) -> dict[str, datetime]:
    """{periodo AAAA-MM-DD: quando terminou a ultima coleta bem-sucedida dele}."""
    res = arm._paginado("/rest/v1/sync_relatorio_runs", {"relatorio_id": f"eq.{relatorio_id}", "status": "eq.success",
                                                         "select": "periodo,finished_at", "order": "periodo.asc,finished_at.asc"}, PAGINA)
    out: dict[str, datetime] = {}
    for r in res:
        quando = arm._dt(r.get("finished_at"))
        if quando and (r["periodo"] not in out or quando > out[r["periodo"]]):
            out[r["periodo"]] = quando
    return out


def linhas_do_periodo(relatorio_id: str, de: str, ate: str) -> list[tuple[dict, int]]:
    """[(linha com as chaves col0..., repeticoes)] vigentes dos periodos de..ate (inclusive)."""
    res = arm._paginado("/rest/v1/v_relatorio_linha_vigente", {
        "relatorio_id": f"eq.{relatorio_id}", "and": f"(periodo.gte.{de},periodo.lte.{ate})",
        "select": "linha,repeticoes", "order": "periodo.asc,id.asc"}, PAGINA)
    return [(r["linha"], int(r.get("repeticoes") or 1)) for r in res]


# ---------------------------------------------------------------- cobertura
def ultimo_dia(ym: str) -> str:
    from calendar import monthrange
    return f"{ym}-{monthrange(int(ym[:4]), int(ym[5:]))[1]:02d}"


def dias_do_mes(ym: str, hoje: date) -> list[str]:
    """Dias do mes ate hoje (mes futuro = nenhum; mes passado = todos)."""
    from datetime import timedelta
    ini, fim = date.fromisoformat(f"{ym}-01"), min(date.fromisoformat(ultimo_dia(ym)), hoje)
    return [(ini + timedelta(days=i)).isoformat() for i in range((fim - ini).days + 1)] if fim >= ini else []


def cobertura_mes(info: dict, ym: str, exec_: dict[str, datetime], hoje: date) -> datetime | None:
    """Quando terminou a coleta que cobre o mes `ym` por inteiro (None = o banco ainda nao cobre).

    granularidade 'mes': a coleta do periodo AAAA-MM-01. 'dia': uma coleta bem-sucedida por dia do mes ate hoje (e, nos dias
    passados, feita depois da meia-noite deles, senao o dia pode estar incompleto); vale a mais antiga delas."""
    if info.get("granularidade") == "mes":
        return exec_.get(f"{ym}-01")
    dias = dias_do_mes(ym, hoje)
    if not dias:
        return None
    quando = []
    for d in dias:
        q = exec_.get(d)
        if q is None or (d < hoje.isoformat() and q.date().isoformat() <= d):
            return None
        quando.append(q)
    return min(quando)


# ---------------------------------------------------------------- linhas no formato do Klingo
def brutas(relatorio_id: str, tit: dict[str, str], de: str, ate: str) -> list[dict]:
    """Linhas {titulo: valor} dos periodos de..ate, como `klingo_relatorios.baixar_faixa` as devolvia (numeros como texto)."""
    saida = []
    for linha, rep in linhas_do_periodo(relatorio_id, de, ate):
        sem_titulo = [k for k in linha if k not in tit]
        if sem_titulo:
            raise DadosIncompletos(f"coluna(s) {', '.join(sem_titulo)} sem título no dicionário do banco")
        bruta = {tit[k]: (str(v) if type(v) in (int, float) else v) for k, v in linha.items()}
        saida.extend(dict(bruta) for _ in range(max(rep, 1)))
    return saida


def conferir_pronto(info: dict | None, klingo_id) -> None:
    """Levanta DadosIncompletos se o relatorio nao pode alimentar um painel agora."""
    if not info:
        raise DadosIncompletos(f"o relatório {klingo_id} não está cadastrado no banco")
    if not info.get("ativo") or info.get("supersedido_por"):
        raise DadosIncompletos(f"o relatório {klingo_id} está desativado no banco (dim_relatorio.ativo)")
    if info.get("filtro_periodo") and not info.get("periodo_validado_em"):
        raise DadosIncompletos(f"o relatório {klingo_id} ainda não teve o filtro de período comprovado pelo Klingo")
