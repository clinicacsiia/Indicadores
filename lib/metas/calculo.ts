// Cálculo das metas mensais. Porte do "Acompanhamento de META/gerar_dashboard.py": as
// mesmas regras (metas.json) e as mesmas contas, para o site e o painel local não
// divergirem. Funções puras: recebem a configuração, os atendimentos e "agora".

export type Regra = {
  classe?: string;
  classes_iguais?: string[];
  especialidade?: string;
  procedimento_igual?: string;
  procedimento_contem?: string[];
  procedimento_nao_contem?: string[];
};

export type MetaItem = { id: string; nome: string; meta: number; regra: Regra };
export type MetaGrupo = { id: string; nome: string; unidade: string; itens: MetaItem[] };

export type MetasConfig = {
  primeiro_mes: string;
  dias_semana_atendimento: number[]; // 0 = segunda ... 6 = domingo
  horario_atendimento: [string, string];
  feriados: string[];
  grupos: MetaGrupo[];
  metas_por_mes: Record<string, Record<string, number>>;
};

/** Atendimentos já contados, como a função metas_atendimentos_mes() os devolve. */
export type LinhaAtendimento = {
  unidade: string | null;
  classes: string | null;
  especialidade: string | null;
  procedimento: string | null;
  operadora: string | null;
  qtd: number;
};

export type Situacao = "batida" | "ritmo" | "atencao" | "atrasado";

export type ResultadoItem = {
  id: string;
  nome: string;
  meta: number;
  realizado: number;
  sus: number;
  /** "Convênios e particular": convênio informado que não é SUS nem Cetrus (a conta interna se chama pagante). */
  naoSus: number;
  /** Cetrus (antes "SUS CURSO"): um curso, uma terceira categoria — conta na meta, mas não é SUS nem pagante. */
  cetrus: number;
  semConvenio: number;
  pct: number;
  /** Cumprimento da mesma meta contando só convênios e particular (convênio informado que não é SUS nem Cetrus). */
  pctPagante: number;
  situacaoPagante: Situacao;
  faltam: number;
  porDia: number | null;
  projecao: number | null;
  /** Projeção do pagante até o fim do período, no ritmo médio por dia útil. */
  projecaoPagante: number | null;
  situacao: Situacao;
};

export type ResultadoGrupo = {
  id: string;
  nome: string;
  unidade: string;
  itens: ResultadoItem[];
  pct: number;
  pctPagante: number;
  situacaoPagante: Situacao;
  situacao: Situacao;
  itensOk: number;
};

export type ForaDasMetas = { unidade: string; especialidade: string; procedimento: string; qtd: number };

export type ResultadoMes = {
  mes: string; // mês do começo do período (o próprio mês, no filtro por mês)
  de: string; // primeiro dia, AAAA-MM-DD
  ate: string; // último dia, AAAA-MM-DD
  fechado: boolean;
  diasUteis: number;
  diasDecorridos: number;
  diasRestantes: number;
  esperadoPct: number;
  totalAtendimentos: number;
  totalForaDasMetas: number;
  convenioInformado: boolean;
  /** Atendimentos que contam em alguma meta, separados pelo convênio (cada atendimento uma vez só). */
  convenio: { sus: number; naoSus: number; cetrus: number; semConvenio: number };
  geral: {
    pct: number;
    situacao: Situacao;
    pctPagante: number;
    situacaoPagante: Situacao;
    itensTotal: number;
    itensOk: number;
    itensOkPagante: number;
  };
  grupos: ResultadoGrupo[];
  fora: ForaDasMetas[];
  avisos: string[];
};

// Abaixo de 75% do esperado até hoje = atrasado.
export const LIMITE_ATENCAO = 0.75;

/** Sem acento, maiúsculas e sem espaços nas pontas: "Densitometria " == "DENSITOMETRIA". */
export function norm(texto: string | null | undefined): string {
  return (texto ?? "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toUpperCase()
    .trim();
}

/** "RM, TC" ou '["RM","TC"]' (o Klingo manda as duas formas) -> {"RM","TC"}. */
export function lerClasses(bruto: string | null | undefined): Set<string> {
  const texto = (bruto ?? "").trim();
  if (!texto) return new Set();
  let itens: string[];
  if (texto.startsWith("[")) {
    try {
      const lista: unknown = JSON.parse(texto);
      itens = Array.isArray(lista) ? lista.map(String) : [texto];
    } catch {
      itens = texto.split(",");
    }
  } else {
    itens = texto.split(",");
  }
  return new Set(itens.map((c) => c.trim().toUpperCase()).filter(Boolean));
}

type Preparada = {
  unidade: string;
  especialidade: string;
  procedimento: string;
  classes: Set<string>;
  sus: boolean;
  cetrus: boolean;
  semConvenio: boolean;
  original: LinhaAtendimento;
};

/** O Cetrus (curso) era trazido pelo Klingo como "SUS CURSO"; o histórico ainda tem esse nome, o novo é "CETRUS". */
const NOMES_CETRUS = new Set(["CETRUS", "SUS CURSO"]);

function preparar(l: LinhaAtendimento): Preparada {
  const convenio = norm(l.operadora);
  return {
    unidade: norm(l.unidade),
    especialidade: norm(l.especialidade),
    procedimento: norm(l.procedimento),
    classes: lerClasses(l.classes),
    // Só o nome exato "SUS" é SUS. O Cetrus ("SUS CURSO" no histórico) é um curso: terceira categoria, nem SUS nem pagante.
    sus: convenio === "SUS",
    cetrus: NOMES_CETRUS.has(convenio),
    semConvenio: convenio === "",
    original: l,
  };
}

function criarFiltro(unidade: string, regra: Regra): (l: Preparada) => boolean {
  if (!regra || Object.keys(regra).length === 0) {
    throw new Error("Meta sem 'regra': ela contaria todos os atendimentos da unidade.");
  }
  const uni = norm(unidade);
  const classe = regra.classe?.toUpperCase();
  const iguais = regra.classes_iguais ? new Set(regra.classes_iguais.map((c) => c.toUpperCase())) : null;
  const esp = regra.especialidade !== undefined ? norm(regra.especialidade) : null;
  const procIgual = regra.procedimento_igual !== undefined ? norm(regra.procedimento_igual) : null;
  const contem = regra.procedimento_contem?.map(norm);
  const naoContem = regra.procedimento_nao_contem?.map(norm);

  return (l) => {
    if (l.unidade !== uni) return false;
    if (classe !== undefined && !l.classes.has(classe)) return false;
    if (iguais && !(l.classes.size === iguais.size && [...l.classes].every((c) => iguais.has(c)))) return false;
    if (esp !== null && l.especialidade !== esp) return false;
    if (procIgual !== null && l.procedimento !== procIgual) return false;
    if (contem && !contem.some((t) => l.procedimento.includes(t))) return false;
    if (naoContem && naoContem.some((t) => l.procedimento.includes(t))) return false;
    return true;
  };
}

// ───────── calendário ─────────

function diasDoMes(ano: number, mes: number): number {
  return new Date(Date.UTC(ano, mes, 0)).getUTCDate();
}

function iso(ano: number, mes: number, dia: number): string {
  return `${ano}-${String(mes).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
}

/** Dias do mês em que a clínica atende (dias da semana configurados, fora feriados), em ISO. */
export function diasUteisDoMes(ano: number, mes: number, semana: Set<number>, feriados: Set<string>): string[] {
  const dias: string[] = [];
  for (let d = 1; d <= diasDoMes(ano, mes); d++) {
    const data = iso(ano, mes, d);
    const diaDaSemana = (new Date(`${data}T12:00:00Z`).getUTCDay() + 6) % 7; // 0 = segunda
    if (semana.has(diaDaSemana) && !feriados.has(data)) dias.push(data);
  }
  return dias;
}

/** Quanto do expediente de hoje já passou (0 a 1), para não contar o dia inteiro às 13h. */
export function fracaoDoDia(minutosAgora: number, horario: [string, string]): number {
  const minutos = (hhmm: string) => {
    const [h, m] = hhmm.split(":").map(Number);
    return h * 60 + m;
  };
  const abre = minutos(horario[0]);
  const fecha = minutos(horario[1]);
  if (fecha <= abre) return 0;
  return Math.min(Math.max((minutosAgora - abre) / (fecha - abre), 0), 1);
}

export function situacaoDe(pct: number, esperado: number): Situacao {
  if (pct >= 100) return "batida";
  if (esperado <= 0) return "ritmo";
  const razao = pct / esperado;
  if (razao >= 1) return "ritmo";
  return razao >= LIMITE_ATENCAO ? "atencao" : "atrasado";
}

export type Agora = { hoje: string; minutos: number }; // hoje em AAAA-MM-DD e minutos desde 00:00, horário de São Paulo

export function agoraSaoPaulo(data = new Date()): Agora {
  const partes = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(data);
  const v = (tipo: string) => partes.find((p) => p.type === tipo)?.value ?? "0";
  return { hoje: `${v("year")}-${v("month")}-${v("day")}`, minutos: Number(v("hour")) * 60 + Number(v("minute")) };
}

/** Meses AAAA-MM de `primeiro` até `ultimo`, do mais recente ao mais antigo. */
export function mesesDisponiveis(primeiro: string, ultimo: string): string[] {
  const meses: string[] = [];
  let [a, m] = ultimo.split("-").map(Number);
  const [pa, pm] = primeiro.split("-").map(Number);
  while (a > pa || (a === pa && m >= pm)) {
    meses.push(`${a}-${String(m).padStart(2, "0")}`);
    m -= 1;
    if (m === 0) {
      m = 12;
      a -= 1;
    }
  }
  return meses;
}

export function fimDoMes(mes: string): string {
  const [a, m] = mes.split("-").map(Number);
  return iso(a, m, diasDoMes(a, m));
}

/** Soma `n` dias a uma data AAAA-MM-DD. */
export function somarDias(data: string, n: number): string {
  const d = new Date(`${data}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Todos os dias de `de` a `ate`, inclusive, em ISO. */
function diasEntre(de: string, ate: string): string[] {
  const dias: string[] = [];
  for (let d = de; d <= ate; d = somarDias(d, 1)) dias.push(d);
  return dias;
}

/** O período cobre meses inteiros (do dia 1 ao último dia do mês)? Devolve os meses das pontas, ou null se corta algum mês. */
export function mesesInteiros(de: string, ate: string): { de: string; ate: string } | null {
  if (!de.endsWith("-01") || fimDoMes(ate.slice(0, 7)) !== ate) return null;
  return { de: de.slice(0, 7), ate: ate.slice(0, 7) };
}

// ───────── conta principal ─────────

export function calcularMes(cfg: MetasConfig, mes: string, linhas: LinhaAtendimento[], agora: Agora): ResultadoMes {
  return calcularPeriodo(cfg, `${mes}-01`, fimDoMes(mes), linhas, agora);
}

type ContextoPeriodo = { uteis: string[]; mesesDoPeriodo: string[]; fracaoDoMes: Map<string, number> };

/** Dias úteis do período e, para cada mês que ele toca, a parte dos dias úteis do mês que cai dentro dele. */
function contextoDoPeriodo(cfg: MetasConfig, de: string, ate: string): ContextoPeriodo {
  const semana = new Set(cfg.dias_semana_atendimento);
  const feriados = new Set(cfg.feriados);
  const uteis = diasEntre(de, ate).filter((d) => {
    const diaDaSemana = (new Date(`${d}T12:00:00Z`).getUTCDay() + 6) % 7; // 0 = segunda
    return semana.has(diaDaSemana) && !feriados.has(d);
  });
  const mesesDoPeriodo = mesesDisponiveis(de.slice(0, 7), ate.slice(0, 7));
  const fracaoDoMes = new Map<string, number>();
  for (const m of mesesDoPeriodo) {
    const [a, n] = m.split("-").map(Number);
    const doMes = diasUteisDoMes(a, n, semana, feriados).length;
    fracaoDoMes.set(m, doMes ? uteis.filter((d) => d.startsWith(m)).length / doMes : 0);
  }
  return { uteis, mesesDoPeriodo, fracaoDoMes };
}

/** Meta de um serviço no período: a de cada mês (metas_por_mes ou a padrão) pela parte do mês que o período cobre. */
function metaDoPeriodo(cfg: MetasConfig, g: MetaGrupo, it: MetaItem, ctx: ContextoPeriodo): number {
  return Math.round(
    ctx.mesesDoPeriodo.reduce(
      (soma, m) => soma + Number(cfg.metas_por_mes?.[m]?.[`${g.id}/${it.id}`] ?? it.meta) * (ctx.fracaoDoMes.get(m) ?? 0),
      0
    )
  );
}

/**
 * Mesma conta do mês, para quaisquer dias de `de` a `ate` (AAAA-MM-DD). Os dias úteis são os do período; a meta de cada mês que o
 * período toca vale pela parte dos dias úteis do mês que cai dentro do período (mês inteiro = meta inteira), e as metas somam.
 */
export function calcularPeriodo(cfg: MetasConfig, de: string, ate: string, linhas: LinhaAtendimento[], agora: Agora): ResultadoMes {
  const mes = de.slice(0, 7);
  const ctx = contextoDoPeriodo(cfg, de, ate);
  const uteis = ctx.uteis;
  const totalUteis = uteis.length;

  const fechado = ate < agora.hoje;
  let decorridos: number;
  if (fechado) {
    decorridos = totalUteis;
  } else {
    decorridos = uteis.filter((d) => d < agora.hoje).length;
    if (uteis.includes(agora.hoje)) decorridos += fracaoDoDia(agora.minutos, cfg.horario_atendimento);
  }
  const restantes = totalUteis - decorridos;
  const esperado = totalUteis ? (decorridos / totalUteis) * 100 : 0;

  const preparadas = linhas.map(preparar);
  const contagem = new Array<number>(preparadas.length).fill(0);
  const avisos: string[] = [];

  const grupos: ResultadoGrupo[] = [];
  let somaMeta = 0;
  let somaCap = 0;
  let somaCapPagante = 0;
  let itensTotal = 0;
  let itensOk = 0;
  let itensOkPagante = 0;

  for (const g of cfg.grupos) {
    const itens: ResultadoItem[] = [];
    let gMeta = 0;
    let gCap = 0;
    let gCapPagante = 0;
    let gOk = 0;
    let gOkPagante = 0;
    for (const it of g.itens) {
      const filtro = criarFiltro(g.unidade, it.regra);
      let realizado = 0;
      let sus = 0;
      let cetrus = 0;
      let semConvenio = 0;
      preparadas.forEach((l, i) => {
        if (!filtro(l)) return;
        contagem[i] += 1;
        realizado += l.original.qtd;
        if (l.sus) sus += l.original.qtd;
        if (l.cetrus) cetrus += l.original.qtd;
        if (l.semConvenio) semConvenio += l.original.qtd;
      });
      const meta = metaDoPeriodo(cfg, g, it, ctx);
      const pct = meta ? (realizado / meta) * 100 : 0;
      const situacao = situacaoDe(pct, esperado);
      const pagante = realizado - sus - cetrus - semConvenio;
      const pctPagante = meta ? (pagante / meta) * 100 : 0;
      const situacaoPagante = situacaoDe(pctPagante, esperado);
      const faltam = Math.max(meta - realizado, 0);
      itens.push({
        id: it.id,
        nome: it.nome,
        meta,
        realizado,
        sus,
        naoSus: pagante,
        cetrus,
        semConvenio,
        pct,
        pctPagante,
        situacaoPagante,
        faltam,
        porDia: faltam && restantes >= 0.5 ? Math.ceil(faltam / restantes) : null,
        projecao: decorridos >= 0.5 && !fechado ? Math.round((realizado / decorridos) * totalUteis) : null,
        projecaoPagante: decorridos >= 0.5 && !fechado ? Math.round((pagante / decorridos) * totalUteis) : null,
        situacao,
      });
      gMeta += meta;
      gCap += Math.min(realizado, meta);
      gCapPagante += Math.min(pagante, meta);
      if (situacao === "batida" || situacao === "ritmo") gOk += 1;
      if (situacaoPagante === "batida" || situacaoPagante === "ritmo") gOkPagante += 1;
    }
    const gPct = gMeta ? (gCap / gMeta) * 100 : 0;
    const gPctPagante = gMeta ? (gCapPagante / gMeta) * 100 : 0;
    grupos.push({
      id: g.id,
      nome: g.nome,
      unidade: g.unidade,
      itens,
      pct: gPct,
      pctPagante: gPctPagante,
      situacaoPagante: situacaoDe(gPctPagante, esperado),
      situacao: situacaoDe(gPct, esperado),
      itensOk: gOk,
    });
    somaMeta += gMeta;
    somaCap += gCap;
    somaCapPagante += gCapPagante;
    itensTotal += itens.length;
    itensOk += gOk;
    itensOkPagante += gOkPagante;
  }

  const total = preparadas.reduce((s, l) => s + l.original.qtd, 0);
  const emMaisDeUma = preparadas.filter((_, i) => contagem[i] > 1);
  if (emMaisDeUma.length) {
    const qtd = emMaisDeUma.reduce((s, l) => s + l.original.qtd, 0);
    avisos.push(
      `${qtd} atendimento${qtd === 1 ? "" : "s"} conta${qtd === 1 ? "" : "m"} em mais de uma meta (ex.: ${emMaisDeUma[0].original.procedimento ?? "—"}). Ajuste as regras no metas.json.`
    );
  }

  const foraMapa = new Map<string, ForaDasMetas>();
  let totalFora = 0;
  preparadas.forEach((l, i) => {
    if (contagem[i] > 0) return;
    totalFora += l.original.qtd;
    const o = l.original;
    const chave = `${o.unidade}\u0000${o.especialidade}\u0000${o.procedimento}`;
    const atual = foraMapa.get(chave);
    if (atual) atual.qtd += o.qtd;
    else
      foraMapa.set(chave, {
        unidade: o.unidade ?? "—",
        especialidade: o.especialidade ?? "—",
        procedimento: o.procedimento ?? "—",
        qtd: o.qtd,
      });
  });
  const fora = [...foraMapa.values()].sort((a, b) => b.qtd - a.qtd);

  const convenio = { sus: 0, naoSus: 0, cetrus: 0, semConvenio: 0 };
  preparadas.forEach((l, i) => {
    if (contagem[i] === 0) return;
    if (l.sus) convenio.sus += l.original.qtd;
    else if (l.cetrus) convenio.cetrus += l.original.qtd;
    else if (l.semConvenio) convenio.semConvenio += l.original.qtd;
    else convenio.naoSus += l.original.qtd;
  });

  const geralPct = somaMeta ? (somaCap / somaMeta) * 100 : 0;
  const geralPctPagante = somaMeta ? (somaCapPagante / somaMeta) * 100 : 0;
  return {
    mes,
    de,
    ate,
    fechado,
    diasUteis: totalUteis,
    diasDecorridos: decorridos,
    diasRestantes: restantes,
    esperadoPct: esperado,
    totalAtendimentos: total,
    totalForaDasMetas: totalFora,
    convenioInformado: preparadas.some((l) => !l.semConvenio),
    convenio,
    geral: {
      pct: geralPct,
      situacao: situacaoDe(geralPct, esperado),
      pctPagante: geralPctPagante,
      situacaoPagante: situacaoDe(geralPctPagante, esperado),
      itensTotal,
      itensOk,
      itensOkPagante,
    },
    grupos,
    fora,
    avisos,
  };
}

// ───────── comparação com e sem SUS ─────────
// "Pagante" = atendimento com convênio informado que não é SUS nem Cetrus (outros convênios e particular); o Cetrus conta na meta mas fica fora das duas leituras. A meta é a mesma: a comparação mostra
// quanto dela estaria cumprida se só o pagante contasse. Tudo em quantidade e porcentagem (as Metas não trazem valores em R$).

export type LinhaAtendimentoDia = LinhaAtendimento & { dia: string };

export type PontoDia = {
  dia: string;
  /** % acumulado esperado ao fim do dia, pelos dias úteis (hoje conta só a parte do expediente que passou). */
  esperado: number;
  /** % acumulado das metas contando todos os atendimentos / só o pagante. Nulo nos dias depois da última sincronização. */
  total: number | null;
  pagante: number | null;
  /** Atendimentos do dia que contam em alguma meta. */
  sus: number;
  naoSus: number;
  /** % de pagante entre SUS + pagante, média dos 7 dias até este (calendário). Nulo com menos de 20 atendimentos na janela. */
  participacao: number | null;
};

export type SerieDiaria = { pontos: PontoDia[]; ultimoDia: string | null; participacaoPeriodo: number | null };

const JANELA_PARTICIPACAO = 7;
const MIN_ATENDIMENTOS_JANELA = 20;

/** Evolução dia a dia (acumulada) do cumprimento geral com todos os atendimentos e só com o pagante, contra o esperado. */
export function serieDiaria(cfg: MetasConfig, de: string, ate: string, linhas: LinhaAtendimentoDia[], agora: Agora): SerieDiaria {
  const ctx = contextoDoPeriodo(cfg, de, ate);
  const fim = ate < agora.hoje ? ate : agora.hoje;
  if (fim < de) return { pontos: [], ultimoDia: null, participacaoPeriodo: null };
  const dias = diasEntre(de, fim);
  const indice = new Map(dias.map((d, i) => [d, i]));

  const itens: { meta: number; filtro: (l: Preparada) => boolean; total: number[]; pagante: number[] }[] = [];
  for (const g of cfg.grupos)
    for (const it of g.itens)
      itens.push({
        meta: metaDoPeriodo(cfg, g, it, ctx),
        filtro: criarFiltro(g.unidade, it.regra),
        total: new Array<number>(dias.length).fill(0),
        pagante: new Array<number>(dias.length).fill(0),
      });
  const susDia = new Array<number>(dias.length).fill(0);
  const paganteDia = new Array<number>(dias.length).fill(0);
  let ultimoDia: string | null = null;

  for (const linha of linhas) {
    const i = indice.get(linha.dia);
    if (i === undefined) continue;
    if (ultimoDia === null || linha.dia > ultimoDia) ultimoDia = linha.dia;
    const l = preparar(linha);
    let contou = false;
    for (const item of itens) {
      if (!item.filtro(l)) continue;
      contou = true;
      item.total[i] += linha.qtd;
      if (!l.sus && !l.cetrus && !l.semConvenio) item.pagante[i] += linha.qtd;
    }
    if (contou) {
      if (l.sus) susDia[i] += linha.qtd;
      else if (!l.cetrus && !l.semConvenio) paganteDia[i] += linha.qtd;
    }
  }

  const somaMeta = itens.reduce((s, it) => s + it.meta, 0);
  const cumTotal = new Array<number>(itens.length).fill(0);
  const cumPagante = new Array<number>(itens.length).fill(0);
  const totalUteis = ctx.uteis.length;
  const uteis = new Set(ctx.uteis);
  let uteisAteOntem = 0;
  let somaSus = 0;
  let somaPagante = 0;

  const pontos: PontoDia[] = dias.map((dia, i) => {
    let esperado: number;
    if (!totalUteis) esperado = 0;
    else {
      const util = uteis.has(dia);
      const hojeAberto = dia === agora.hoje && ate >= agora.hoje;
      const decorridos = uteisAteOntem + (util ? (hojeAberto ? fracaoDoDia(agora.minutos, cfg.horario_atendimento) : 1) : 0);
      esperado = (decorridos / totalUteis) * 100;
    }
    if (uteis.has(dia)) uteisAteOntem += 1;

    let capTotal = 0;
    let capPagante = 0;
    itens.forEach((it, k) => {
      cumTotal[k] += it.total[i];
      cumPagante[k] += it.pagante[i];
      capTotal += Math.min(cumTotal[k], it.meta);
      capPagante += Math.min(cumPagante[k], it.meta);
    });
    somaSus += susDia[i];
    somaPagante += paganteDia[i];

    let janelaSus = 0;
    let janelaPagante = 0;
    for (let j = Math.max(0, i - JANELA_PARTICIPACAO + 1); j <= i; j++) {
      janelaSus += susDia[j];
      janelaPagante += paganteDia[j];
    }
    const comDado = ultimoDia !== null && dia <= ultimoDia;
    return {
      dia,
      esperado,
      total: comDado && somaMeta ? (capTotal / somaMeta) * 100 : null,
      pagante: comDado && somaMeta ? (capPagante / somaMeta) * 100 : null,
      sus: susDia[i],
      naoSus: paganteDia[i],
      participacao:
        comDado && janelaSus + janelaPagante >= MIN_ATENDIMENTOS_JANELA ? (janelaPagante / (janelaSus + janelaPagante)) * 100 : null,
    };
  });

  return {
    pontos,
    ultimoDia,
    participacaoPeriodo: somaSus + somaPagante > 0 ? (somaPagante / (somaSus + somaPagante)) * 100 : null,
  };
}

export type Achado = { tom: "ok" | "atencao" | "info"; texto: string };

const fmt1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const fmt0 = new Intl.NumberFormat("pt-BR");
const pctT = (v: number) => `${fmt1.format(v)}%`;
const ppT = (v: number) => `${fmt1.format(Math.abs(v))} p.p.`;
const ROTULO: Record<Situacao, string> = { batida: "meta batida", ritmo: "no ritmo", atencao: "em atenção", atrasado: "atrasado" };
const ordem: Record<Situacao, number> = { batida: 3, ritmo: 2, atencao: 1, atrasado: 0 };
const lista = (nomes: string[]) => (nomes.length <= 1 ? nomes.join("") : `${nomes.slice(0, -1).join(", ")} e ${nomes[nomes.length - 1]}`);

/** Leitura automática da comparação: o que mudaria sem o SUS, quem depende dele e para onde as linhas estão indo. */
export function analisarPagante(res: ResultadoMes, serie: SerieDiaria | null): Achado[] {
  const achados: Achado[] = [];
  const itens = res.grupos.flatMap((g) => g.itens);
  const contados = res.convenio.sus + res.convenio.naoSus + res.convenio.cetrus + res.convenio.semConvenio;
  if (!itens.length || contados === 0) return achados;
  const nomePeriodo = res.fechado ? "O período fechou" : "Até agora";

  // 1. O quadro geral.
  const dif = res.geral.pct - res.geral.pctPagante;
  const naoPagante = ["SUS", ...(res.convenio.cetrus > 0 ? ["Cetrus"] : [])].join(" e ");
  const piorou = ordem[res.geral.situacaoPagante] < ordem[res.geral.situacao];
  achados.push({
    tom: piorou ? "atencao" : "info",
    texto:
      `${nomePeriodo} com ${pctT(res.geral.pct)} das metas cumpridas. Contando só convênios e particular, são ${pctT(res.geral.pctPagante)}: ` +
      `${naoPagante === "SUS" ? "o SUS responde" : `${naoPagante} respondem`} por ${ppT(dif)} do cumprimento` +
      (piorou
        ? `, e sem ${naoPagante === "SUS" ? "ele" : "eles"} o geral passaria de "${ROTULO[res.geral.situacao]}" para "${ROTULO[res.geral.situacaoPagante]}".`
        : "."),
  });

  // 2. Contra o ritmo esperado.
  if (!res.fechado && res.esperadoPct > 0) {
    const d = res.geral.pctPagante - res.esperadoPct;
    achados.push({
      tom: d >= 0 ? "ok" : "atencao",
      texto:
        d >= 0
          ? `Convênios e particular estão ${ppT(d)} acima do esperado até hoje (${pctT(res.esperadoPct)}): sozinhos já acompanham o ritmo das metas.`
          : `Convênios e particular estão ${ppT(d)} abaixo do esperado até hoje (${pctT(res.esperadoPct)}); contando todos os atendimentos a diferença é de ${ppT(res.geral.pct - res.esperadoPct)}${res.geral.pct >= res.esperadoPct ? " a favor" : " abaixo"}.`,
    });
  }

  // 3. Projeção até o fim do período.
  if (!res.fechado && itens.every((i) => i.projecao !== null && i.projecaoPagante !== null)) {
    const somaMeta = itens.reduce((s, i) => s + i.meta, 0);
    if (somaMeta > 0) {
      const proj = (campo: "projecao" | "projecaoPagante") =>
        (itens.reduce((s, i) => s + Math.min(i[campo] ?? 0, i.meta), 0) / somaMeta) * 100;
      const pTotal = proj("projecao");
      const pPagante = proj("projecaoPagante");
      achados.push({
        tom: pPagante >= 100 ? "ok" : "info",
        texto: `No ritmo médio atual, convênios e particular devem chegar a cerca de ${pctT(pPagante)} das metas no fim do período (com todos os atendimentos: ${pctT(pTotal)}).`,
      });
    }
  }

  // 4. Serviços que só fecham com o SUS e serviços que fecham sozinhos com o pagante.
  const soComSus = itens.filter((i) => i.meta > 0 && i.pct >= 100 && i.pctPagante < 100);
  if (soComSus.length)
    achados.push({
      tom: "atencao",
      texto: `${soComSus.length === 1 ? "A meta bate" : "As metas batem"} só por causa do SUS: ${lista(soComSus.map((i) => i.nome))}.`,
    });
  const soPagante = itens.filter((i) => i.meta > 0 && i.pctPagante >= 100);
  if (soPagante.length)
    achados.push({
      tom: "ok",
      texto: `${soPagante.length === 1 ? "Meta batida" : "Metas batidas"} só com convênios e particular: ${lista(soPagante.map((i) => i.nome))}.`,
    });

  // 5. Quem mais depende do SUS.
  const dependentes = itens
    .map((i) => ({ i, partSus: i.sus + i.naoSus > 0 ? i.sus / (i.sus + i.naoSus) : 0, queda: i.pct - i.pctPagante }))
    .filter((d) => d.partSus >= 0.35 && d.queda >= 5)
    .sort((a, b) => b.queda - a.queda)
    .slice(0, 3);
  for (const d of dependentes)
    achados.push({
      tom: ordem[d.i.situacaoPagante] < ordem[d.i.situacao] ? "atencao" : "info",
      texto:
        `${d.i.nome} depende do SUS: ${pctT(d.partSus * 100)} do que foi feito. ` +
        `Só com convênios e particular, o cumprimento cai de ${pctT(d.i.pct)} para ${pctT(d.i.pctPagante)}.`,
    });

  // 6. Como as linhas estão se comportando.
  if (serie) {
    const comDado = serie.pontos.filter((p) => p.total !== null && p.pagante !== null);
    if (comDado.length > JANELA_PARTICIPACAO) {
      const fimP = comDado[comDado.length - 1];
      const iniP = comDado[comDado.length - 1 - JANELA_PARTICIPACAO];
      const ganhoPagante = (fimP.pagante ?? 0) - (iniP.pagante ?? 0);
      const ganhoEsperado = fimP.esperado - iniP.esperado;
      if (!res.fechado && ganhoEsperado > 0) {
        const ganhando = ganhoPagante >= ganhoEsperado;
        achados.push({
          tom: ganhando ? "ok" : "atencao",
          texto:
            `Nos últimos ${JANELA_PARTICIPACAO} dias a linha de convênios e particular avançou ${ppT(ganhoPagante)} e a do esperado ${ppT(ganhoEsperado)}: ` +
            (ganhando ? "convênios e particular estão recuperando terreno." : "convênios e particular estão perdendo terreno para o ritmo esperado."),
        });
      }
      // participação: últimos 7 dias contra os 7 anteriores
      const soma = (de: number, ate: number) => {
        let sus = 0;
        let pag = 0;
        for (const p of serie.pontos.slice(de, ate)) {
          sus += p.sus;
          pag += p.naoSus;
        }
        return { sus, pag };
      };
      const n = serie.pontos.length;
      const recente = soma(Math.max(0, n - JANELA_PARTICIPACAO), n);
      const anterior = soma(Math.max(0, n - 2 * JANELA_PARTICIPACAO), Math.max(0, n - JANELA_PARTICIPACAO));
      if (recente.sus + recente.pag >= MIN_ATENDIMENTOS_JANELA && anterior.sus + anterior.pag >= MIN_ATENDIMENTOS_JANELA) {
        const a = (recente.pag / (recente.sus + recente.pag)) * 100;
        const b = (anterior.pag / (anterior.sus + anterior.pag)) * 100;
        const d = a - b;
        const forma = Math.abs(d) < 2 ? "estável" : d > 0 ? "subindo" : "caindo";
        achados.push({
          tom: forma === "caindo" ? "atencao" : forma === "subindo" ? "ok" : "info",
          texto: `A participação de convênios e particular está ${forma}: ${pctT(a)} nos últimos ${JANELA_PARTICIPACAO} dias contra ${pctT(b)} nos ${JANELA_PARTICIPACAO} anteriores.`,
        });
      }
    }
  }

  // 6b. O Cetrus é uma terceira categoria: conta na meta, mas não é SUS nem pagante.
  if (res.convenio.cetrus > 0)
    achados.push({
      tom: "info",
      texto: `${fmt0.format(res.convenio.cetrus)} atendimentos (${pctT((res.convenio.cetrus / contados) * 100)}) são do Cetrus, um curso: contam nas metas, mas não entram como SUS nem como convênios e particular.`,
    });

  // 7. Atendimentos sem convênio informado ficam de fora das duas leituras.
  if (res.convenio.semConvenio > 0 && res.convenio.semConvenio / contados >= 0.01) {
    const somaMeta = itens.reduce((s, i) => s + i.meta, 0);
    const teto =
      somaMeta > 0 ? (itens.reduce((s, i) => s + Math.min(i.naoSus + i.semConvenio, i.meta), 0) / somaMeta) * 100 - res.geral.pctPagante : 0;
    achados.push({
      tom: "info",
      texto:
        `${fmt0.format(res.convenio.semConvenio)} atendimentos (${pctT((res.convenio.semConvenio / contados) * 100)}) estão sem convênio informado e não entram como convênios e particular nem como SUS` +
        (teto >= 0.1 ? `; se todos fossem de convênios ou particular, essa leitura subiria até ${ppT(teto)}.` : "."),
    });
  }

  return achados;
}
