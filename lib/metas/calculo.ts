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
  naoSus: number;
  semConvenio: number;
  pct: number;
  faltam: number;
  porDia: number | null;
  projecao: number | null;
  situacao: Situacao;
};

export type ResultadoGrupo = {
  id: string;
  nome: string;
  unidade: string;
  itens: ResultadoItem[];
  pct: number;
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
  convenio: { sus: number; naoSus: number; semConvenio: number };
  geral: { pct: number; situacao: Situacao; itensTotal: number; itensOk: number };
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
  semConvenio: boolean;
  original: LinhaAtendimento;
};

function preparar(l: LinhaAtendimento): Preparada {
  const convenio = norm(l.operadora);
  return {
    unidade: norm(l.unidade),
    especialidade: norm(l.especialidade),
    procedimento: norm(l.procedimento),
    classes: lerClasses(l.classes),
    sus: convenio === "SUS",
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

/**
 * Mesma conta do mês, para quaisquer dias de `de` a `ate` (AAAA-MM-DD). Os dias úteis são os do período; a meta de cada mês que o
 * período toca vale pela parte dos dias úteis do mês que cai dentro do período (mês inteiro = meta inteira), e as metas somam.
 */
export function calcularPeriodo(cfg: MetasConfig, de: string, ate: string, linhas: LinhaAtendimento[], agora: Agora): ResultadoMes {
  const mes = de.slice(0, 7);
  const semana = new Set(cfg.dias_semana_atendimento);
  const feriados = new Set(cfg.feriados);
  const uteis = diasEntre(de, ate).filter((d) => {
    const diaDaSemana = (new Date(`${d}T12:00:00Z`).getUTCDay() + 6) % 7; // 0 = segunda
    return semana.has(diaDaSemana) && !feriados.has(d);
  });
  const totalUteis = uteis.length;
  const mesesDoPeriodo = mesesDisponiveis(de.slice(0, 7), ate.slice(0, 7));
  const fracaoDoMes = new Map<string, number>();
  for (const m of mesesDoPeriodo) {
    const [a, n] = m.split("-").map(Number);
    const doMes = diasUteisDoMes(a, n, semana, feriados).length;
    fracaoDoMes.set(m, doMes ? uteis.filter((d) => d.startsWith(m)).length / doMes : 0);
  }

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
  let itensTotal = 0;
  let itensOk = 0;

  for (const g of cfg.grupos) {
    const itens: ResultadoItem[] = [];
    let gMeta = 0;
    let gCap = 0;
    let gOk = 0;
    for (const it of g.itens) {
      const filtro = criarFiltro(g.unidade, it.regra);
      let realizado = 0;
      let sus = 0;
      let semConvenio = 0;
      preparadas.forEach((l, i) => {
        if (!filtro(l)) return;
        contagem[i] += 1;
        realizado += l.original.qtd;
        if (l.sus) sus += l.original.qtd;
        if (l.semConvenio) semConvenio += l.original.qtd;
      });
      const meta = Math.round(
        mesesDoPeriodo.reduce(
          (soma, m) => soma + Number(cfg.metas_por_mes?.[m]?.[`${g.id}/${it.id}`] ?? it.meta) * (fracaoDoMes.get(m) ?? 0),
          0
        )
      );
      const pct = meta ? (realizado / meta) * 100 : 0;
      const situacao = situacaoDe(pct, esperado);
      const faltam = Math.max(meta - realizado, 0);
      itens.push({
        id: it.id,
        nome: it.nome,
        meta,
        realizado,
        sus,
        naoSus: realizado - sus - semConvenio,
        semConvenio,
        pct,
        faltam,
        porDia: faltam && restantes >= 0.5 ? Math.ceil(faltam / restantes) : null,
        projecao: decorridos >= 0.5 && !fechado ? Math.round((realizado / decorridos) * totalUteis) : null,
        situacao,
      });
      gMeta += meta;
      gCap += Math.min(realizado, meta);
      if (situacao === "batida" || situacao === "ritmo") gOk += 1;
    }
    const gPct = gMeta ? (gCap / gMeta) * 100 : 0;
    grupos.push({ id: g.id, nome: g.nome, unidade: g.unidade, itens, pct: gPct, situacao: situacaoDe(gPct, esperado), itensOk: gOk });
    somaMeta += gMeta;
    somaCap += gCap;
    itensTotal += itens.length;
    itensOk += gOk;
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

  const convenio = { sus: 0, naoSus: 0, semConvenio: 0 };
  preparadas.forEach((l, i) => {
    if (contagem[i] === 0) return;
    if (l.sus) convenio.sus += l.original.qtd;
    else if (l.semConvenio) convenio.semConvenio += l.original.qtd;
    else convenio.naoSus += l.original.qtd;
  });

  const geralPct = somaMeta ? (somaCap / somaMeta) * 100 : 0;
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
    geral: { pct: geralPct, situacao: situacaoDe(geralPct, esperado), itensTotal, itensOk },
    grupos,
    fora,
    avisos,
  };
}
