/** Tudo que pode dar errado ao buscar um relatório na API do Klingo (porte de extrair_laudo.py). */
export class ErroApiKlingo extends Error {
  constructor(mensagem: string) {
    super(mensagem);
    this.name = new.target.name;
  }
}
/** Token ausente ou recusado: só o administrador resolve (repetir não adianta). Aborta a atualização inteira. */
export class TokenInvalido extends ErroApiKlingo {}
/** Sem conexão, tempo esgotado ou servidor do Klingo fora do ar, mesmo depois de repetir. Aborta a atualização inteira. */
export class FalhaDeRede extends ErroApiKlingo {}
/** O Klingo respondeu com erro para este relatório ou período (só este relatório/mês vira aviso). */
export class RelatorioComErro extends ErroApiKlingo {}
/** A resposta não passou na conferência: estrutura, colunas, tipos ou campos obrigatórios fora do esperado. */
export class RespostaInvalida extends RelatorioComErro {}
/** Resposta cortada (limit: true) que não dá para dividir mais: erro, nunca truncar calado. */
export class LimiteAtingido extends RelatorioComErro {}
