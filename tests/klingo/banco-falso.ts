/** Supabase falso, em memória, só com o que o motor usa (tabelas + as funções SQL de supabase/migrations/…_funcoes_sincronizacao.sql). */
type Linha = Record<string, any>;

export function bancoFalso() {
  const t: Record<string, Linha[]> = { fila_sincronizacao: [], dados_blocos: [], historico_atualizacoes: [], dados_versao: [] };
  const log: string[] = [];
  let seq = 1, lease = false, trava = true;

  const consulta = (nome: string) => {
    const filtros: ((l: Linha) => boolean)[] = [];
    let modo: "select" | "update" | "insert" = "select", valores: any, head = false, contar = false;
    const aplica = () => (t[nome] ??= []).filter((l) => filtros.every((f) => f(l)));
    const q: any = {
      select: (_c?: string, o?: { count?: string; head?: boolean }) => { head = !!o?.head; contar = !!o?.count; return q; },
      insert: (v: Linha | Linha[]) => { modo = "insert"; valores = v; return q; },
      update: (v: Linha) => { modo = "update"; valores = v; return q; },
      eq: (c: string, v: any) => { filtros.push((l) => l[c] === v); return q; },
      in: (c: string, vs: any[]) => { filtros.push((l) => vs.includes(l[c])); return q; },
      maybeSingle: async () => ({ data: aplica()[0] ?? null, error: null }),
      then: (ok: any, ko: any) => Promise.resolve().then(() => {
        if (modo === "insert") { for (const v of [].concat(valores)) (t[nome] ??= []).push({ id: seq++, estado: "pendente", tentativas: 0, criado_em: new Date().toISOString(), ...(v as Linha) }); return { data: null, error: null }; }
        if (modo === "update") { aplica().forEach((l) => Object.assign(l, valores)); return { data: null, error: null }; }
        const linhas = aplica();
        return { data: head ? null : linhas, count: contar ? linhas.length : null, error: null };
      }).then(ok, ko),
    };
    return q;
  };

  const rpc = async (nome: string, a: Linha = {}) => {
    log.push(nome);
    switch (nome) {
      case "pegar_lease": if (lease) return { data: false, error: null }; lease = true; return { data: true, error: null };
      case "soltar_lease": lease = false; return { data: null, error: null };
      case "reservar_item_fila": {
        const it = t.fila_sincronizacao.find((l) => l.estado === "pendente");
        if (!it) return { data: null, error: null };
        Object.assign(it, { estado: "executando", iniciado_em: new Date().toISOString() });
        return { data: { ...it }, error: null };
      }
      case "estender_trava": return { data: null, error: null };
      case "liberar_trava": trava = false; return { data: null, error: null };
      case "subir_versao": { const v = t.dados_versao.find((l) => l.menu === a.p_menu); v ? v.versao++ : t.dados_versao.push({ menu: a.p_menu, versao: 1 }); return { data: null, error: null }; }
      case "podar_historico": return { data: null, error: null };
      case "gravar_bloco": {
        const i = t.dados_blocos.findIndex((l) => l.menu === a.p_menu && l.aba === a.p_aba && l.mes === a.p_mes);
        const novo = { menu: a.p_menu, aba: a.p_aba, mes: a.p_mes, colunas: a.p_colunas, linhas: a.p_linhas, conteudo: a.p_conteudo };
        i >= 0 ? (t.dados_blocos[i] = novo) : t.dados_blocos.push(novo);
        if (a.p_apagar_outros) t.dados_blocos = t.dados_blocos.filter((l) => !(l.menu === a.p_menu && l.aba === a.p_aba && l.mes !== a.p_mes));
        return { data: null, error: null };
      }
    }
    return { data: null, error: { message: `rpc desconhecida: ${nome}` } };
  };
  return { sb: { from: consulta, rpc } as any, t, log, travaLiberada: () => !trava };
}
