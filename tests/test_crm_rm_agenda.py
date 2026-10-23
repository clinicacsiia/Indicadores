"""A agenda do CRM Ressonância vem do Klingo (relatório #13825): confere, rodando o lib/crm-rm.ts de verdade no Node, como cada marcação vira status e confirmação,
o que entra na fila do "Meu dia" e as contas dos indicadores (absenteísmo, cobertura, por convênio e por usuário).
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

ROTEIRO = """
import { calcular, doKlingo, montarFila, resumirAgenda, statusDoKlingo, tamanhoDaFila } from "./crm-rm.ts";
const HOJE = "2026-10-23";
const emDias = (n: number) => new Date(Date.parse(`${HOJE}T12:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);

const base = (o: any) => ({
  codigo_marcacao: "1", id_atendimento: null, prontuario: "10", agendado_em: "2026-10-01T09:00:00", data_exame: HOJE, horario: "09:00",
  exame: "RM DE CRÂNIO", convenio: "AMIL", forma_pagamento: "Convênio", responsavel: "ana", valor: 100, confirm_status: "A Confirmar",
  cancelada: false, atendido: false, motivo_cancelamento: null, observacao: null, paciente: "Fulano", celular: null, telefone: null,
  unidade: "RM", atualizado_em: "2026-10-23T12:00:00+00:00", ...o,
});

const status = (o: any) => statusDoKlingo(base(o), HOJE);
const regras = {
  atendido: status({ atendido: true, id_atendimento: "5", data_exame: emDias(-3) }),
  atendido_e_cancelada: status({ atendido: true, cancelada: true, data_exame: emDias(-3) }),
  remarcado: status({ cancelada: true, motivo_cancelamento: "Remarcado." }),
  cancelada_erro: status({ cancelada: true, motivo_cancelamento: "ERRO" }),
  cancelada_sem_motivo: status({ cancelada: true }),
  aberta_passada: status({ data_exame: emDias(-1) }),
  aberta_hoje: status({ data_exame: HOJE }),
  aberta_futura: status({ data_exame: emDias(3) }),
};

const conf = (c: string | null) => doKlingo(base({ confirm_status: c }), HOJE).confirmacao;
const confirmacoes = { c: conf("Confirmado"), sr: conf("Sem Resposta"), ac: conf("A Confirmar"), nulo: conf(null), outro: conf("Qualquer") };
const tel = (o: any) => doKlingo(base(o), HOJE).telefone;
const telefones = { celular: tel({ celular: "7199", telefone: "7133" }), fixo: tel({ telefone: "7133" }), nenhum: tel({}) };

// Fila: 14 marcações com o que importa para cada lista.
const linhas = [
  base({ codigo_marcacao: "a", data_exame: HOJE, confirm_status: "A Confirmar" }),                    // confirmar
  base({ codigo_marcacao: "b", data_exame: emDias(2), confirm_status: "Sem Resposta" }),              // confirmar
  base({ codigo_marcacao: "c", data_exame: emDias(1), confirm_status: "Confirmado" }),                // já confirmou
  base({ codigo_marcacao: "d", data_exame: emDias(3), confirm_status: "A Confirmar" }),               // longe demais
  base({ codigo_marcacao: "e", data_exame: emDias(-2) }),                                             // faltou
  base({ codigo_marcacao: "f", data_exame: emDias(-8) }),                                             // faltou há muito tempo
  base({ codigo_marcacao: "g", data_exame: emDias(4), cancelada: true, motivo_cancelamento: "ERRO" }),         // vaga
  base({ codigo_marcacao: "h", data_exame: emDias(1), cancelada: true, motivo_cancelamento: "Remarcado." }),   // vaga
  base({ codigo_marcacao: "i", data_exame: emDias(9), cancelada: true }),                                      // vaga longe demais
  base({ codigo_marcacao: "j", data_exame: emDias(-1), cancelada: true }),                                     // vaga que já passou
  base({ codigo_marcacao: "k", data_exame: emDias(-1), atendido: true, id_atendimento: "9" }),       // feito
].map((a) => doKlingo(a, HOJE));
const fila = montarFila([], linhas, HOJE, emDias);
const filas = {
  confirmar: fila.confirmar.map((h) => h.codigo_marcacao),
  faltaram: fila.faltaram.map((h) => h.codigo_marcacao),
  vagas: fila.vagasAbertas.map((h) => h.codigo_marcacao),
  tamanho: tamanhoDaFila(fila),
};

// Indicadores: 6 feitos (2 com confirmação), 2 faltas, 1 cancelada, 1 remarcada e 1 futura aberta.
const f = (o: any) => doKlingo(base(o), HOJE);
const ontem = emDias(-1);
const hs = [
  ...[1, 2, 3, 4].map((n) => f({ codigo_marcacao: `r${n}`, atendido: true, id_atendimento: `${n}`, data_exame: ontem, confirm_status: "Confirmado", valor: 200 })),
  ...[5, 6].map((n) => f({ codigo_marcacao: `r${n}`, atendido: true, id_atendimento: `${n}`, data_exame: ontem, confirm_status: "A Confirmar", valor: 100, convenio: "SUS", forma_pagamento: "SUS" })),
  f({ codigo_marcacao: "f1", data_exame: ontem, confirm_status: "A Confirmar", valor: 300 }),
  f({ codigo_marcacao: "f2", data_exame: ontem, confirm_status: "Confirmado", valor: 300 }),
  f({ codigo_marcacao: "c1", cancelada: true, data_exame: ontem, responsavel: "bia" }),
  f({ codigo_marcacao: "m1", cancelada: true, motivo_cancelamento: "Remarcado.", data_exame: ontem, responsavel: "bia" }),
  f({ codigo_marcacao: "x1", data_exame: emDias(5) }),
];
const contatos: any[] = [1, 2].map((id) => ({ id, situacao: "Agendado", data_contato: "2026-10-10", valor_informado: null, forma_pagamento: "Convênio", canal: "WhatsApp", exame: "RM DE CRÂNIO", motivo_perda: null }));
const ind = calcular(contatos, hs.filter((h) => h.data_exame <= HOJE), 1, 20);
const resumo = resumirAgenda(hs, () => "Crânio");

console.log(JSON.stringify({
  regras, confirmacoes, telefones, filas,
  ind: {
    realizados: ind.realizados, faltas: ind.faltas, cancelamentos: ind.cancelamentos, reagendados: ind.reagendados, aRealizar: ind.aRealizar,
    absenteismo: ind.absenteismo, cobertura: ind.cobertura, valorRealizado: ind.valorRealizado, valorFaltas: ind.valorPrevistoFaltas,
    porConfirmacao: ind.faltasPorConfirmacao.map((c) => [c.confirmacao, c.agendados, c.faltas, c.taxa]),
    porForma: ind.porForma.map((p) => [p.forma, p.realizados, p.faltas]),
    funil: ind.funil.map((e) => e.n),
  },
  convenios: resumo.porConvenio.map((l) => [l.nome, l.marcacoes, l.feitos, l.faltas, l.cancelados]),
  usuarios: resumo.porResponsavel.map((r) => [r.nome, r.marcacoes, r.cancelados, r.pctCancelado]),
}));
"""


@unittest.skipUnless(shutil.which("node"), "sem Node")
class AgendaDoKlingoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pasta = Path(tempfile.mkdtemp())
        try:
            (pasta / "crm-rm.ts").write_text((RAIZ / "lib" / "crm-rm.ts").read_text(encoding="utf-8"), encoding="utf-8")
            (pasta / "roteiro.mts").write_text(ROTEIRO, encoding="utf-8")
            r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "roteiro.mts"], cwd=pasta, capture_output=True, text=True, timeout=120)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
        assert r.returncode == 0, r.stderr[-800:]
        cls.saida = json.loads(r.stdout)

    def test_status_a_partir_do_que_o_klingo_registra(self):
        self.assertEqual(self.saida["regras"], {
            "atendido": "Realizado",
            "atendido_e_cancelada": "Realizado",       # o atendimento aberto vale mais que a marcação cancelada depois
            "remarcado": "Reagendado",
            "cancelada_erro": "Cancelado",
            "cancelada_sem_motivo": "Cancelado",
            "aberta_passada": "Faltou",
            "aberta_hoje": "Agendado",                 # ainda pode chegar: só vira falta depois do dia
            "aberta_futura": "Agendado",
        })

    def test_confirmacao_e_telefone(self):
        self.assertEqual(self.saida["confirmacoes"], {"c": "Confirmou", "sr": "Não respondeu", "ac": "Não contatado", "nulo": "Não contatado", "outro": "Não contatado"})
        self.assertEqual(self.saida["telefones"], {"celular": "7199", "fixo": "7133", "nenhum": None})

    def test_fila_do_meu_dia(self):
        f = self.saida["filas"]
        self.assertEqual(f["confirmar"], ["a", "b"])        # hoje e daqui a 2 dias; quem já confirmou e quem está longe ficam de fora
        self.assertEqual(f["faltaram"], ["e"])              # só os últimos 7 dias
        self.assertEqual(f["vagas"], ["h", "g"])            # canceladas e remarcadas dos próximos 7 dias, a mais próxima primeiro
        self.assertEqual(f["tamanho"], 3)                   # as vagas são oportunidade, não pendência

    def test_indicadores(self):
        i = self.saida["ind"]
        self.assertEqual((i["realizados"], i["faltas"], i["cancelamentos"], i["reagendados"], i["aRealizar"]), (6, 2, 1, 1, 1))
        self.assertAlmostEqual(i["absenteismo"], 25.0)       # 2 faltas em 8 horários com resultado
        self.assertAlmostEqual(i["cobertura"], 10.0)         # 2 contatos agendados em 20 marcações novas do Klingo
        self.assertEqual((i["valorRealizado"], i["valorFaltas"]), (1000, 600))
        self.assertEqual(i["funil"], [2, 2, 2])
        por = {c[0]: c[1:] for c in i["porConfirmacao"]}
        self.assertEqual(por["Confirmou"], [5, 1, 20.0])     # 4 feitos + 1 falta de quem confirmou
        self.assertEqual(por["Não contatado"][:2], [3, 1])
        self.assertAlmostEqual(por["Não contatado"][2], 100 / 3)
        self.assertEqual({p[0]: p[1:] for p in i["porForma"]}, {"Convênio": [4, 2], "SUS": [2, 0]})

    def test_resumo_da_agenda(self):
        self.assertEqual(self.saida["convenios"], [["AMIL", 9, 4, 2, 2], ["SUS", 2, 2, 0, 0]])
        usuarios = {u[0]: u[1:] for u in self.saida["usuarios"]}
        self.assertEqual(usuarios["bia"], [2, 2, 100.0])
        self.assertEqual(usuarios["ana"], [9, 0, 0.0])


if __name__ == "__main__":
    unittest.main()
