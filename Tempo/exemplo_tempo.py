"""Roda o pipeline de metricas_tempo com um log SINTETICO (nenhum dado real) e grava as tabelas em Tempo/saida_exemplo/.

    python Tempo/exemplo_tempo.py

O gerador de dados imita o que os relatorios mostram (medianas e caudas parecidas com o #13404) para os numeros fazerem sentido:
chegadas com picos as 9h e 14h, etapas com duracao lognormal e alguns encerramentos esquecidos (2 a 30 dias abertos)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import metricas_tempo as mt  # noqa: E402

ETAPAS = [("Cadastro", 1.1, 0.8), ("Chamado", 31, 0.9), ("Em Atendimento", 18, 0.7), ("Finalizado", 3, 0.9)]   # (etapa, mediana em min, sigma do log)
EQUIPAMENTOS = {"RM": "CSI 2", "TC": "CSI 2", "DENSITOMETRIA": "CSI 1", "MAMOGRAFIA": "CSI 1"}


def gerar_log_sintetico(dias: int = 14, inicio: str = "2026-09-07", por_dia: int = 120, esquecidos: float = 0.01, seed: int = 7):
    """(etapas, usos): etapas no formato 'uma linha por etapa'; usos = as etapas 'Em Atendimento' que caem num equipamento."""
    rng = np.random.default_rng(seed)
    dia0 = pd.Timestamp(inicio)
    linhas, usos = [], []
    atend = 0
    for d in range(dias):
        dia = dia0 + pd.Timedelta(days=d)
        if dia.weekday() == 6:
            continue
        horas = rng.choice([7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], size=por_dia, p=np.array([2, 6, 12, 10, 7, 4, 5, 11, 8, 5, 2]) / 72)
        chegadas = dia + pd.to_timedelta(horas * 3600 + rng.integers(0, 3600, por_dia), unit="s")
        for ch in chegadas:
            atend += 1
            setor = rng.choice(["CSI 1", "CSI 2", "CSI Pediatria"], p=[.5, .35, .15])
            t = ch
            equip = rng.choice(list(EQUIPAMENTOS)) if rng.random() < .3 else "PROFISSIONAL"
            for etapa, med, sig in ETAPAS:
                dur = rng.lognormal(np.log(med * 60), sig)
                if rng.random() < esquecidos:
                    dur = rng.uniform(2, 30) * 86400                       # ninguem encerrou
                fim = t + pd.Timedelta(seconds=float(dur))
                linhas.append((atend, etapa, t, fim, setor, equip))
                if etapa == "Em Atendimento" and equip in EQUIPAMENTOS:
                    usos.append((equip, t, fim, EQUIPAMENTOS[equip]))
                t = fim + pd.Timedelta(seconds=float(rng.integers(0, 90)))
    etapas = pd.DataFrame(linhas, columns=["atendimento_id", "etapa", "inicio", "fim", "setor", "recurso"])
    return etapas, pd.DataFrame(usos, columns=["recurso", "inicio", "fim", "setor"])


def main():
    etapas, usos = gerar_log_sintetico()
    periodo = (str(etapas["inicio"].min().date()), str(etapas["inicio"].max().date()))
    t = mt.construir_tabelas(etapas, usos, periodo)
    for nome, df in t.items():
        print(f"\n== {nome}: {len(df)} linhas | {df.memory_usage(deep=True).sum() / 1024:.0f} KB\n{df.head(4).to_string(index=False)}")
    print("\nPior hora de cada dia (espera p90):\n", t["gargalo_dia"].head(6).to_string(index=False))
    pasta = Path(__file__).parent / "saida_exemplo"
    arquivos = mt.exportar({k: v for k, v in t.items() if k != "atendimentos"}, pasta, meta={"periodo": periodo, "origem": "sintetico"})
    print("\nGravado em", pasta, "->", ", ".join(sorted(arquivos)))


if __name__ == "__main__":
    main()
