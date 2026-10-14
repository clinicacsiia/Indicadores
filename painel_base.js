// ---- utilitarios comuns aos paineis (Faturamento e Financeiro)
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (n, d = 0) => Number(n).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const brl = n => Number(n).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const brlc = n => {            // formato curto para os numeros grandes dos cartoes
  const a = Math.abs(n);
  if (a >= 1e6) return 'R$ ' + num(n / 1e6, 2) + ' mi';
  if (a >= 1e4) return 'R$ ' + num(n / 1e3, 1) + ' mil';
  return brl(n);
};
const rotEixo = n => {          // rotulo curto para o eixo dos graficos: "500 mil", "1,5 mi"
  const a = Math.abs(n);
  if (a >= 1e6) return num(n / 1e6, 1) + ' mi';
  if (a >= 1e3) return num(n / 1e3, 0) + ' mil';
  return num(n, 0);
};
const pct = (n, d = 1) => (n == null || isNaN(n)) ? '—' : num(n, d) + '%';
const dataBR = iso => iso ? iso.split('-').reverse().join('/') : '';
const soma = (v, f) => v.reduce((s, x) => s + (f ? f(x) : x), 0);

const ICONES = {   // formas vazadas (evenodd): o simbolo aparece como "furo" no preenchimento
  critico: 'M8.6 2h6.8L22 8.6v6.8L15.4 22H8.6L2 15.4V8.6ZM11 6.5h2v7h-2ZM11 15.5h2v2h-2Z',
  atencao: 'M12 2 22.5 21h-21ZM11 9h2v6h-2ZM11 16.5h2v2.2h-2Z',
  info: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM11 6.5h2v2h-2ZM11 10.5h2v7h-2Z',
  ok: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM10.8 16.4 6.8 12.4 8.2 11 10.8 13.6 15.8 8.6 17.2 10Z',
};
const ROTULO_NIVEL = { critico: 'Crítico', atencao: 'Atenção', info: 'Informação', ok: 'Tudo certo' };
const chip = nivel => `<span class="chip"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="${ICONES[nivel]}"/></svg>${ROTULO_NIVEL[nivel]}</span>`;

// ---- alertas: cada um pode trazer "guia" (onde achar no Klingo, passos) e "itens" (tabela dos registros afetados)
// ym = mes que a tela mostra (alertas de "hoje" tem escopo vazio; os do mes, o proprio mes). Ver guia_pendencias.py.
const chaveAlerta = a => (a.escopo || '') + '|' + a.id;
const linkAviso = a => `/avisos?painel=${encodeURIComponent(painelAtual())}&aviso=${encodeURIComponent(chaveAlerta(a))}`;

function guiaHtml(a) {
  const g = a.guia, it = a.itens;
  const links = g.relatorios.map(r => `<a class="btn-mini link" href="${esc(r.url)}" target="_blank" rel="noopener">Abrir no Klingo: ${esc(r.nome)} ↗</a>`).join('');
  const passos = g.passos.map(p => `<li>${esc(p)}</li>`).join('');
  let tab = '';
  if (it && it.linhas.length) {
    const n = new Set(it.numericas || []);
    const cab = it.colunas.map((c, i) => `<th class="${n.has(i) ? 'n' : ''}">${esc(c)}</th>`).join('');
    const corpo = it.linhas.map(l => '<tr>' + l.map((v, i) => `<td class="${n.has(i) ? 'n' : ''}">${esc(v)}</td>`).join('') + '</tr>').join('');
    const mostra = it.linhas.length < it.total ? `Mostrando ${num(it.linhas.length)} de ${num(it.total)}; o resto está no relatório.` : `${num(it.total)} no total.`;
    tab = `<h4>Quais são <span class="al-conta">${mostra}</span></h4><div class="tab-wrap"><table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody></table></div>` +
      `<button type="button" class="btn-mini" data-al="copiar">Copiar a lista</button>`;
  }
  return `<div class="al-guia" hidden><h4>Onde olhar</h4><div class="al-links">${links}</div>` +
    `<h4>Passo a passo</h4><ol>${passos}</ol>${tab}` +
    `<p class="al-resolve"><b>Quando o painel considera resolvido:</b> ${esc(g.resolve)} Depois de corrigir no Klingo, use <b>Atualizar agora</b> para conferir.</p></div>`;
}

function alertasHtml(lista, ym) {
  if (!lista.length) return `<ul class="alertas" data-escopo="${esc(ym || '')}"><li class="alerta n-ok">${chip('ok')}<div><span class="tit">Nada fora do normal</span><p>Nenhum ponto de atenção encontrado nos dados atuais.</p></div></li></ul>`;
  return `<ul class="alertas" data-escopo="${esc(ym || '')}">` + lista.map((a, n) => {
    const guia = a.guia && a.id;
    return `<li class="alerta n-${a.nivel}" data-ordem="${n}"${guia ? ` data-chave="${esc(chaveAlerta(a))}" data-titulo="${esc(a.titulo)}"` : ''}>${chip(a.nivel)}<div><span class="tit">${esc(a.titulo)}</span><p>${a.texto}</p>` +
      (guia ? `<div class="al-acoes"><button type="button" class="btn-mini" data-al="guia" aria-expanded="false">Como achar o problema</button>` +
        (window.PAINEL_NUVEM
          ? `<a class="btn-mini ok" data-al="justificar" href="${esc(linkAviso(a))}" target="_top">Justificar e fechar</a>`   // na nuvem quem fecha e a aba Avisos, e exige justificativa
          : `<button type="button" class="btn-mini ok" data-al="resolver">Marcar como resolvido</button>`) +
        `</div><div class="al-nota" hidden></div>${guiaHtml(a)}` : '') +
      `</div></li>`;
  }).join('') + '</ul>';
}

// mostra so os primeiros alertas (os mais urgentes) e recolhe o resto: a Analise nao fica uma tela abaixo
function alertasTopo(lista, ym, max = 3) {
  if (lista.length <= max + 1) return alertasHtml(lista, ym);
  const resto = lista.slice(max), cont = {};
  resto.forEach(a => { cont[a.nivel] = (cont[a.nivel] || 0) + 1; });
  const txt = ['critico', 'atencao', 'info', 'ok'].filter(n => cont[n]).map(n => `${cont[n]} ${ROTULO_NIVEL[n].toLowerCase()}`).join(' · ');
  return alertasHtml(lista.slice(0, max), ym) +
    `<details class="acord" style="margin-top:14px"><summary>Ver os outros ${resto.length} alertas<small>${txt}</small></summary><div class="acord-corpo">${alertasHtml(resto, ym)}</div></details>`;
}

// marcacoes "resolvido" (guardadas no banco do portal, valem para todos os usuarios)
const ALERTAS = { marcas: null, aviso: null };
// Programa local: o painel e o 1o trecho do endereco (/faturamento/). Na Vercel (window.PAINEL_NUVEM, posto pelo servidor) o painel vem em window.PAINEL_ID
// e as chamadas ao servidor sao funcoes em /api/*.
const painelAtual = () => window.PAINEL_ID || location.pathname.split('/')[1] || '';
const apiPainel = (nome, extra = '') => window.PAINEL_NUVEM ? `/api/${nome}?id=${encodeURIComponent(painelAtual())}${extra}` : nome;
const apiPendencias = acao => window.PAINEL_NUVEM ? `/api/pendencias?id=${encodeURIComponent(painelAtual())}&acao=${acao}` : (acao ? `/pendencias/${acao}` : `/pendencias?painel=${encodeURIComponent(painelAtual())}`);
const versaoDados = () => (typeof D !== 'undefined' && D.versao) || 0;
const dataHora = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const marcasPorChave = lista => Object.fromEntries((lista || []).map(m => [m.chave, m]));

// Painel recortado (ex.: Atendimento filtrado por responsavel) liga window.PAINEL_FILTRADO: o alerta passa a mostrar so uma parte dos dados,
// entao "Marcar como resolvido" fica desligado (a marcacao e da clinica inteira) e "resolvido, nao aparece mais" nao vale (o alerta pode so ter saido do recorte).
const servidoEditavel = () => location.protocol.startsWith('http') && !window.PAINEL_FILTRADO;
function desfazerResolvidos(ul) {
  const velho = ul.nextElementSibling && ul.nextElementSibling.matches('details.resolvidas') ? ul.nextElementSibling : null;
  if (velho) {   // devolve os alertas que estavam guardados em "Resolvidos" a lista principal, na ordem de antes
    velho.querySelectorAll('li[data-ordem]').forEach(li => ul.appendChild(li));
    [...ul.children].sort((a, b) => (a.dataset.ordem ?? 1e9) - (b.dataset.ordem ?? 1e9)).forEach(li => ul.appendChild(li));
    velho.remove();
  }
}

// Painel na nuvem: o que a aba Avisos sabe de cada alerta. m = {chave, titulo, status: aberto|justificado|resolvido, recorrencias, reaberturas,
// justificativa, justificado_por, justificado_em, resolvido_em}. Quem decide se voltou, continua ou foi corrigido e o banco (ver avisos.py); aqui so se mostra.
const historicoAviso = m => [m.recorrencias ? `voltou a acontecer ${m.recorrencias} ${m.recorrencias === 1 ? 'vez' : 'vezes'}` : '',
  m.reaberturas ? `reaberto ${m.reaberturas} ${m.reaberturas === 1 ? 'vez' : 'vezes'} por continuar nos dados depois de fechado` : ''].filter(Boolean).join(' · ');
const nomeUsuario = email => String(email || 'alguém').replace(/@csi\.local$/, '');   // "ana@csi.local" aparece como "ana", igual ao menu do site
const citacao = m => m.justificativa ? ` Justificativa: “${esc(m.justificativa)}”` : '';
function aplicarAvisos(ul) {
  const filtrado = !!window.PAINEL_FILTRADO;
  desfazerResolvidos(ul);
  const lis = [...ul.querySelectorAll('li[data-chave]')];
  const todas = alertasPrincipais();
  const presentes = new Set([...document.querySelectorAll('li[data-chave]')].map(li => li.dataset.chave));
  const guardadas = [];
  lis.forEach(li => {
    const nota = li.querySelector('.al-nota'), link = li.querySelector('[data-al="justificar"]');
    li.classList.remove('resolvida', 'reaparece'); nota.hidden = true; nota.innerHTML = '';
    if (link) link.hidden = filtrado;
    const m = !filtrado && ALERTAS.marcas && ALERTAS.marcas[li.dataset.chave];
    if (!m) return;
    if (m.status === 'justificado') {
      li.classList.add('resolvida');
      nota.innerHTML = `✔ Fechado por ${esc(nomeUsuario(m.justificado_por))} em ${dataHora(m.justificado_em)}.${citacao(m)} O painel confere na próxima atualização dos dados e reabre se o problema continuar.`;
      nota.hidden = false; if (link) link.hidden = true;
      guardadas.push(li);
    } else if (m.status === 'aberto') {
      li.classList.add('reaparece');
      nota.innerHTML = `⚠ ${esc(historicoAviso(m))}.${citacao(m)}`;
      nota.hidden = false;
    }
  });
  const escopos = new Set(['', ...todas.map(u => u.dataset.escopo || '')]);
  const limite = Date.now() - 30 * 86400000;
  const confirmadas = todas[0] !== ul || filtrado ? [] : Object.values(ALERTAS.marcas || {})
    .filter(m => m.status === 'resolvido' && escopos.has(m.chave.split('|')[0]) && !presentes.has(m.chave) && new Date(m.resolvido_em) > limite);
  if (!guardadas.length && !confirmadas.length) return;
  const det = document.createElement('details'); det.className = 'resolvidas';
  det.innerHTML = `<summary>Resolvidos (${guardadas.length + confirmadas.length})</summary><ul class="alertas"></ul>`;
  const alvo = det.querySelector('ul');
  guardadas.forEach(li => alvo.appendChild(li));
  confirmadas.forEach(m => {
    const li = document.createElement('li'); li.className = 'alerta n-ok'; li.dataset.chave = m.chave;
    const volta = historicoAviso(m);
    li.innerHTML = `${chip('ok')}<div><span class="tit">${esc(m.titulo || m.chave)}</span><p>✔ Resolvido: não aparece mais nos dados desde ${dataHora(m.resolvido_em)}.${volta ? ` (${esc(volta)})` : ''}${citacao(m)}</p></div>`;
    alvo.appendChild(li);
  });
  ul.after(det);
}

function aplicarMarcas(ul) {
  if (window.PAINEL_NUVEM) return aplicarAvisos(ul);
  const servido = servidoEditavel(), filtrado = !!window.PAINEL_FILTRADO;
  desfazerResolvidos(ul);
  const lis = [...ul.querySelectorAll('li[data-chave]')];
  const todas = alertasPrincipais();   // a pagina pode ter mais de uma lista (ex.: atencao e conferencia): o que sumiu so e conferido na primeira
  const presentes = new Set([...document.querySelectorAll('li[data-chave]')].map(li => li.dataset.chave));
  const guardadas = [];
  lis.forEach(li => {
    const nota = li.querySelector('.al-nota'), btn = li.querySelector('[data-al="resolver"]');
    li.classList.remove('resolvida', 'reaparece'); nota.hidden = true; nota.innerHTML = '';
    btn.hidden = !servido; btn.textContent = 'Marcar como resolvido';
    const m = !filtrado && ALERTAS.marcas && ALERTAS.marcas[li.dataset.chave];
    if (!m) return;
    const quem = `${esc(m.usuario)} em ${dataHora(m.quando)}`;
    if (m.versao === versaoDados()) {            // marcou olhando estes mesmos dados: espera a proxima atualizacao para conferir
      li.classList.add('resolvida');
      nota.innerHTML = `✔ Marcada como resolvida por ${quem}. O painel confere na próxima atualização dos dados. <button type="button" class="btn-mini" data-al="reabrir">Ainda não resolvi</button>`;
      nota.hidden = false; btn.hidden = true;
      guardadas.push(li);
    } else {                                      // os dados mudaram desde a marcacao e o alerta continua
      li.classList.add('reaparece');
      nota.innerHTML = `⚠ ${quem} marcou como resolvida, mas ela <b>ainda aparece</b> nos dados de ${esc(typeof D !== 'undefined' ? D.dados_em || '' : '')}. Confira se a correção foi salva no Klingo.`;
      nota.hidden = false; btn.textContent = 'Marcar de novo';
    }
  });
  const escopos = new Set(['', ...todas.map(u => u.dataset.escopo || '')]);
  const limite = Date.now() - 30 * 86400000;
  const confirmadas = todas[0] !== ul || filtrado ? [] : Object.values(ALERTAS.marcas || {}).filter(m => escopos.has(m.chave.split('|')[0]) && !presentes.has(m.chave) && new Date(m.quando) > limite);
  if (!guardadas.length && !confirmadas.length) return;
  const det = document.createElement('details'); det.className = 'resolvidas';
  det.innerHTML = `<summary>Resolvidos (${guardadas.length + confirmadas.length})</summary><ul class="alertas"></ul>`;
  const alvo = det.querySelector('ul');
  guardadas.forEach(li => alvo.appendChild(li));
  confirmadas.forEach(m => {
    const li = document.createElement('li'); li.className = 'alerta n-ok'; li.dataset.chave = m.chave;
    li.innerHTML = `${chip('ok')}<div><span class="tit">${esc(m.titulo || m.chave)}</span><p>✔ Resolvido: não aparece mais nos dados. Marcado por ${esc(m.usuario)} em ${dataHora(m.quando)}. ` +
      `<button type="button" class="btn-mini" data-al="reabrir">Limpar da lista</button></p></div>`;
    alvo.appendChild(li);
  });
  ul.after(det);
}

const alertasPrincipais = () => [...document.querySelectorAll('ul.alertas')].filter(ul => !ul.closest('details.resolvidas'));
function reaplicarMarcas() { alertasPrincipais().forEach(ul => { if (ul.querySelector('li[data-chave]') || ALERTAS.marcas) aplicarMarcas(ul); }); }

async function chamarPendencias(rota, corpo) {
  try {
    const r = await fetch(rota, { method: 'POST', headers: { 'X-Painel': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ painel: painelAtual(), ...corpo }) });
    const j = await r.json();
    if (j.ok) ALERTAS.marcas = marcasPorChave(j.resolvidas);
    return j;
  } catch (e) { return { ok: false, mensagem: 'Não consegui falar com o portal.' }; }
}

function avisoAlertas(msg) { const a = $('aviso'); if (a) { a.innerHTML = esc(msg); a.dataset.tipo = 'erro'; a.hidden = false; scrollTo({ top: 0, behavior: 'smooth' }); } }

document.addEventListener('click', async e => {
  const b = e.target.closest && e.target.closest('[data-al]');
  if (!b) return;
  const li = b.closest('li[data-chave]');
  if (b.dataset.al === 'guia') {
    const g = li.querySelector('.al-guia'); g.hidden = !g.hidden;
    b.setAttribute('aria-expanded', String(!g.hidden)); b.textContent = g.hidden ? 'Como achar o problema' : 'Esconder o passo a passo';
  } else if (b.dataset.al === 'copiar') {
    const t = li.querySelector('.al-guia table');
    const txt = [...t.rows].map(r => [...r.cells].map(c => c.textContent).join('\t')).join('\n');
    try { await navigator.clipboard.writeText(txt); b.textContent = 'Copiado ✔'; } catch (err) { b.textContent = 'Não consegui copiar'; }
    setTimeout(() => { b.textContent = 'Copiar a lista'; }, 2000);
  } else if (b.dataset.al === 'resolver' || b.dataset.al === 'reabrir') {
    b.disabled = true;
    const j = await chamarPendencias(apiPendencias(b.dataset.al === 'resolver' ? 'resolver' : 'reabrir'),
      { chave: li.dataset.chave, titulo: li.dataset.titulo || li.querySelector('.tit').textContent, versao: versaoDados() });
    b.disabled = false;
    if (j.ok) reaplicarMarcas(); else avisoAlertas(j.mensagem || 'Não consegui gravar a marcação.');
  }
});

if (location.protocol.startsWith('http')) {   // busca as marcacoes e acompanha cada vez que o painel redesenha os alertas (troca de mes)
  fetch(apiPendencias(''), { cache: 'no-store' }).then(r => r.json())
    .then(j => { ALERTAS.marcas = marcasPorChave(j.avisos || j.resolvidas); reaplicarMarcas(); }).catch(() => { ALERTAS.marcas = {}; reaplicarMarcas(); });
}
new MutationObserver(ms => {
  const novos = alertasPrincipais().filter(ul => !ul.dataset.pronto);
  if (!novos.length) return;
  novos.forEach(ul => { ul.dataset.pronto = '1'; if (ALERTAS.marcas) aplicarMarcas(ul); else ul.querySelectorAll('[data-al="resolver"]').forEach(b => { b.hidden = !servidoEditavel(); }); });
}).observe(document.documentElement, { childList: true, subtree: true });

// barras horizontais (ranking): itens = [{rotulo, valor, texto, extra, tip, cor, marca}]
// O numero fica colado na ponta da barra. Cor neutra por padrao: so passe "cor" quando a cor tiver significado (alerta).
// opts: {max} escala fixa (ex.: 100 para percentuais); {destaque} indice da barra em azul; i.marca = valor de referencia (ex.: esperado ate hoje).
// Paginacao: passou de opts.porPagina (padrao 10) itens, aparecem botoes Anterior/Proxima; a escala e a reserva do texto valem para todas as paginas.
const COR_DECORATIVA = new Set(['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--accent)']);   // cor so enfeita: vira cinza neutro
function barras(itens, vazio = 'Sem dados neste mês.', larguraRotulo = '34%', opts = {}) {
  if (!itens.length) return `<p class="vazio">${vazio}</p>`;
  const max = opts.max || Math.max(...itens.map(i => Math.max(i.valor, i.marca || 0)), 1);
  // a maior barra deixa de fora so o espaco do maior texto (estimado em px), para o numero nunca estourar a borda
  const maiorTexto = Math.max(...itens.map(i => String(i.texto).length + (i.extra ? String(i.extra).length * .85 + 1 : 0)));
  const reserva = Math.round(maiorTexto * 7.8 + 30);   // texto + espaco entre a barra e o numero + folga
  const pos = v => `calc((100% - ${reserva}px) * ${(Math.min(Math.max(v, 0) / max, 1)).toFixed(4)})`;
  const pp = opts.porPagina || 10, paginas = Math.ceil(itens.length / pp);
  const corpo = `<div class="barras" style="--rot:${larguraRotulo}">` + itens.map((i, n) =>
    `<div class="barra${opts.destaque === n ? ' destaque' : ''}" data-p="${Math.floor(n / pp)}"${n >= pp ? ' hidden' : ''} tabindex="0" data-tip="${esc(i.tip || i.rotulo + '\n' + i.texto)}"${i.cor && !COR_DECORATIVA.has(i.cor) ? ` style="--cor:${i.cor}"` : ''}>` +
    `<div class="barra-rot" title="${esc(i.rotulo)}">${esc(i.rotulo)}</div>` +
    `<div class="barra-area"><div class="barra-fill" style="width:max(${pos(i.valor)}, 2px)"></div>` +
    `<span class="barra-val"${i.marca != null && i.marca > i.valor ? ` style="margin-left:calc(${pos(i.marca)} - ${pos(i.valor)} + 2px)"` : ''}>${esc(i.texto)}${i.extra ? `<small>${esc(i.extra)}</small>` : ''}</span>` +
    (i.marca != null ? `<i class="barra-marca" style="left:${pos(i.marca)}"></i>` : '') + `</div></div>`).join('') + '</div>';
  if (paginas < 2) return corpo;
  return `<div class="barras-pag" data-pag="0" data-paginas="${paginas}">${corpo}<nav class="pag" aria-label="Paginação do gráfico"><button type="button" class="btn-mini" data-pag-ir="-1" disabled>‹ Anterior</button><span class="pag-info" aria-live="polite"></span><button type="button" class="btn-mini" data-pag-ir="1">Próxima ›</button></nav></div>`;
}

// botoes de paginacao dos graficos de barras (delegado: vale para o que for redesenhado)
function atualizarPag(w, p) {
  const n = +w.dataset.paginas, tot = w.querySelectorAll('.barra').length;
  p = Math.max(0, Math.min(n - 1, p)); w.dataset.pag = p;
  w.querySelectorAll('.barra').forEach(b => { b.hidden = +b.dataset.p !== p; });
  const a = w.querySelectorAll('.barra[data-p="' + p + '"]').length, ini = [...w.querySelectorAll('.barra')].findIndex(b => +b.dataset.p === p) + 1;
  w.querySelector('.pag-info').textContent = `${ini}–${ini + a - 1} de ${tot} · página ${p + 1}/${n}`;
  const [ant, prox] = w.querySelectorAll('[data-pag-ir]'); ant.disabled = p === 0; prox.disabled = p === n - 1;
}
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('[data-pag-ir]'); if (!b) return;
  const w = b.closest('.barras-pag'); if (w) atualizarPag(w, +w.dataset.pag + +b.dataset.pagIr);
});
new MutationObserver(() => { document.querySelectorAll('.barras-pag:not([data-ok])').forEach(w => { w.dataset.ok = '1'; atualizarPag(w, 0); }); }).observe(document.documentElement, { childList: true, subtree: true });

// ---- cartao de numero-chave: rotulo, numero grande e a comparacao logo abaixo (vs mes anterior, vs meta...)
// o: {comp, sub, destaque, titulo, classe}
function kpi(rot, valor, o = {}) {
  return `<div class="kpi${o.destaque ? ' destaque' : ''}"><div class="kpi-rot">${rot}</div>` +
    `<div class="kpi-num ${o.classe || ''}"${o.titulo ? ` title="${esc(o.titulo)}"` : ''}>${valor}</div>` +
    (o.comp ? `<div class="kpi-comp">${o.comp}</div>` : '') + (o.sub ? `<div class="kpi-sub">${o.sub}</div>` : '') + '</div>';
}

// variacao percentual de atual sobre ref (null se nao der para comparar)
const varPct = (atual, ref) => (atual == null || ref == null || !ref) ? null : (atual - ref) / Math.abs(ref) * 100;

// comparacao com sentido: inverso = true quando MENOS e melhor (espera, problemas, glosa...)
// unidade '%' (variacao relativa) ou 'pp' (pontos percentuais) ou qualquer texto (diferenca absoluta ja formatada por fmt)
function comp(v, sufixo, o = {}) {
  if (v == null || isNaN(v)) return o.vazio || '';
  const bom = o.inverso ? v <= 0 : v >= 0, igual = Math.abs(v) < 0.05;
  const cls = igual ? 'igual' : bom ? 'sobe' : 'desce';
  const un = o.unidade || '%', d = o.d ?? 1;
  const corpo = o.fmt ? o.fmt(Math.abs(v)) : num(Math.abs(v), d) + (un === 'pp' ? ' pp' : '%');
  return `<span class="delta ${cls}">${igual ? '● ' : v >= 0 ? '▲ +' : '▼ −'}${corpo}</span> ${sufixo || ''}`;
}

// ---- niveis da pagina: Resumo -> Analise -> Detalhes
const tier = (n, titulo, html) => `<div class="tier"><div class="tier-h"><b>${n}</b><span>${titulo}</span></div>${html}</div>`;
// sanfona dos detalhes: tudo que e tabela ou lista longa fica aqui, fechado
function acordeao(titulo, corpo, o = {}) {
  return `<details class="acord"${o.aberto ? ' open' : ''}><summary>${titulo}${o.dica ? `<small>${o.dica}</small>` : ''}</summary><div class="acord-corpo">${corpo}</div></details>`;
}

// ---- barra unica empilhada: segs = [{rotulo, valor, cor, tip}] (poucas partes; cor so quando tiver significado)
function empilhada(segs, fmt = v => num(v)) {
  const tot = soma(segs, s => s.valor), vis = segs.filter(s => s.valor > 0);
  if (!tot) return '';
  return `<div class="empilhada" role="img" aria-label="${esc(segs.map(s => `${s.rotulo}: ${fmt(s.valor)}`).join('; '))}">` +
    vis.map(s => `<div style="width:${s.valor / tot * 100}%;background:${s.cor || 'var(--neutro)'}" tabindex="0" data-tip="${esc(s.tip || `${s.rotulo}\n${fmt(s.valor)} (${pct(s.valor / tot * 100, 1)})`)}"></div>`).join('') + '</div>' +
    `<div class="empilhada-leg">${segs.map(s => `<span style="--c:${s.cor || 'var(--neutro)'}"><i></i>${esc(s.rotulo)} <b>${fmt(s.valor)}</b> (${pct(s.valor / tot * 100, 0)})</span>`).join('')}</div>`;
}

// ---- donut: no maximo 4 fatias (o resto vira "Outros"). fatias = [{rotulo, valor, cor, tip}]; o: {centro: {num, rot}, fmt, max, outros}
const TONS_DONUT = ['var(--accent)', 'var(--s1)', 'var(--neutro-2)', 'var(--neutro-3)'];
function donut(fatias, o = {}) {
  let f = fatias.filter(x => x.valor > 0).sort((a, b) => b.valor - a.valor);
  const max = o.max || 4, fmt = o.fmt || (v => num(v));
  if (f.length > max) { const resto = f.slice(max - 1); f = [...f.slice(0, max - 1), { rotulo: `${o.outros || 'Outros'} (${resto.length})`, valor: soma(resto, x => x.valor) }]; }
  const tot = soma(f, x => x.valor);
  if (!tot) return `<p class="vazio">${o.vazio || 'Sem dados neste mês.'}</p>`;
  const r = 52, C = 2 * Math.PI * r;
  let acum = 0;
  const arcos = f.map((x, i) => {
    const len = x.valor / tot * C, cor = x.cor || TONS_DONUT[i];
    const arco = `<circle class="fatia" cx="74" cy="74" r="${r}" fill="none" stroke="${cor}" stroke-width="24" stroke-dasharray="${Math.max(len - (f.length > 1 ? 1.5 : 0), 0.5)} ${C}" stroke-dashoffset="${-acum}" transform="rotate(-90 74 74)" tabindex="0" data-tip="${esc(x.tip || `${x.rotulo}\n${fmt(x.valor)} (${pct(x.valor / tot * 100, 1)})`)}"/>`;
    acum += len;
    return arco;
  }).join('');
  const tamanho = o.centro ? Math.max(Math.min(21, 70 / (String(o.centro.num).length * 0.58)), 11) : 0;   // o numero precisa caber dentro do furo
  const centro = o.centro ? `<text class="c-num" style="font-size:${tamanho.toFixed(1)}px" x="74" y="${o.centro.rot ? 76 : 80}">${esc(o.centro.num)}</text>${o.centro.rot ? `<text class="c-rot" x="74" y="91">${esc(o.centro.rot)}</text>` : ''}` : '';
  const leg = f.map((x, i) => `<li style="--c:${x.cor || TONS_DONUT[i]}"><i></i><span>${esc(x.rotulo)}</span><span class="v">${fmt(x.valor)}<small>${pct(x.valor / tot * 100, 0)}</small></span></li>`).join('');
  return `<div class="donut"><svg viewBox="0 0 148 148" role="img" aria-label="${esc(f.map(x => `${x.rotulo}: ${pct(x.valor / tot * 100, 0)}`).join('; '))}">${arcos}${centro}</svg><ul class="donut-leg">${leg}</ul></div>`;
}

// ---- grafico de linhas (serie temporal): rotulo escrito na ponta da linha, sem eixo de valores e sem grade
// o.series = [{nome, cor, traco, larg, pontos: [{x, y}], principal, marcaPico}]; o.xRot = [{x, t}]; o.tipX = x => texto
// o.fmt formata os numeros; o.teto limita a escala (pontos acima viram "▲ valor"); o.rotulosEm = 'todos' escreve o valor em cada ponto
function linhas(o) {
  const W = o.W || 760, H = o.H || 250, ml = o.ml ?? 38, mr = o.mr ?? 112, mt = o.mt ?? 26, mb = o.mb ?? 26;
  const fmt = o.fmt || (v => num(v));
  const series = o.series.map(s => ({ ...s, pontos: s.pontos.filter(p => p.y != null) })).filter(s => s.pontos.length);
  if (!series.length) return '';
  const todos = series.flatMap(s => s.pontos);
  const x0 = Math.min(...todos.map(p => p.x)), x1 = Math.max(...todos.map(p => p.x));
  const topo = o.teto || Math.max(...todos.map(p => p.y), 1) * 1.08;
  const X = x => ml + (x1 === x0 ? 0.5 : (x - x0) / (x1 - x0)) * (W - ml - mr);
  const Y = v => mt + (1 - Math.min(Math.max(v, 0), topo) / topo) * (H - mt - mb);
  let g = `<line class="base" x1="${ml}" x2="${W - mr}" y1="${Y(0)}" y2="${Y(0)}"/>`;
  (o.xRot || []).forEach(t => { g += `<text x="${X(t.x)}" y="${H - 7}" text-anchor="middle">${esc(t.t)}</text>`; });
  const rotulosFim = [];
  series.forEach(s => {
    const cor = s.cor || 'var(--neutro-2)', pts = s.pontos.map(p => `${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');
    g += `<polyline fill="none" stroke="${cor}" stroke-width="${s.larg || (s.principal ? 2.6 : 1.8)}" ${s.traco ? 'stroke-dasharray="6 4"' : ''} stroke-linejoin="round" stroke-linecap="round" points="${pts}"/>`;
    const u = s.pontos[s.pontos.length - 1];
    if (s.principal || s.rotuloFim) { g += `<circle cx="${X(u.x)}" cy="${Y(u.y)}" r="4.5" fill="${cor}" stroke="var(--page)" stroke-width="2"/>`; }
    if (s.rotuloFim !== false) rotulosFim.push({ s, u, y: Y(u.y) });
    if (o.rotulosEm === 'todos') s.pontos.forEach(p => { g += `<text class="rot-pt" x="${X(p.x)}" y="${Y(p.y) + (s.rotuloEmbaixo ? 17 : -9)}" text-anchor="middle">${fmt(p.y)}</text>`; });
    if (s.marcaPico) { const pk = s.pontos.reduce((a, b) => b.y > a.y ? b : a); g += `<circle cx="${X(pk.x)}" cy="${Y(pk.y)}" r="3.5" fill="${cor}"/><text class="rot-pt" x="${X(pk.x)}" y="${Y(pk.y) - 9}" text-anchor="middle">${fmt(pk.y)}</text>`; }
    s.pontos.filter(p => p.y > topo).forEach(p => { g += `<text class="rot-fim" x="${X(p.x)}" y="${mt - 8}" text-anchor="middle">▲ ${fmt(p.y)}</text>`; });
  });
  rotulosFim.sort((a, b) => a.y - b.y);   // afasta rotulos que cairiam um em cima do outro
  const celular = window.matchMedia && matchMedia('(max-width: 640px)').matches;   // no celular a letra do grafico cresce (ver painel_base.css)
  const dyNome = celular ? 25 : 17, duasLinhas = rotulosFim.some(r => r.s.nome) && o.rotulosEm !== 'todos';
  const passoFim = duasLinhas ? dyNome + (celular ? 24 : 13) : celular ? 26 : 15;   // valor + nome ocupam duas linhas
  for (let i = 1; i < rotulosFim.length; i++) if (rotulosFim[i].y - rotulosFim[i - 1].y < passoFim) rotulosFim[i].y = rotulosFim[i - 1].y + passoFim;
  const baixo = duasLinhas ? H - dyNome - 4 : H - mb + 4;   // se a pilha de rotulos passou da base, sobe de volta sem deixar sobrepor
  for (let i = rotulosFim.length - 1; i >= 0; i--) {
    const lim = i === rotulosFim.length - 1 ? baixo : rotulosFim[i + 1].y - passoFim;
    if (rotulosFim[i].y > lim) rotulosFim[i].y = lim;
  }
  if (rotulosFim.length && rotulosFim[0].y < mt - 4) rotulosFim[0].y = mt - 4;
  rotulosFim.forEach(({ s, u, y }) => {
    if (o.rotulosEm === 'todos') {   // o valor ja esta escrito em cada ponto: na ponta fica so o nome da serie
      g += s.nome ? `<text class="${s.principal ? 'rot-fim' : ''}" x="${X(u.x) + 10}" y="${y + 4}">${esc(s.nome)}</text>` : '';
      return;
    }
    g += `<text class="${s.principal ? 'rot-fim' : ''}" x="${X(u.x) + 10}" y="${y + 4}">${fmt(u.y)}</text>` +
      (s.nome ? `<text class="rot-nome" x="${X(u.x) + 10}" y="${y + dyNome}">${esc(s.nome)}</text>` : '');
  });
  const xs = [...new Set(todos.map(p => p.x))].sort((a, b) => a - b), larg = xs.length > 1 ? (W - ml - mr) / (x1 - x0) * Math.min(...xs.slice(1).map((v, i) => v - xs[i])) : W - ml - mr;
  g += xs.map(x => `<rect class="alvo" x="${X(x) - larg / 2}" y="${mt - 6}" width="${larg}" height="${H - mt - mb + 6}" fill="transparent" data-tip="${esc(o.tipX ? o.tipX(x) : '')}"/>`).join('');
  return `<svg class="grafico" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || '')}">${g}</svg>`;
}

// uma serie diaria simples (variavel por dia do mes) para blocos de varios graficos pequenos
// dias = [{d: 'AAAA-MM-DD' ou numero do dia, ...campos}]; o: {cor, fmt, marcaDia: d => bool (ex.: domingo), teto: 'auto'}
function miniLinha(titulo, dias, campo, o = {}) {
  const dia = d => typeof d.d === 'string' ? Number(d.d.slice(8)) : d.d;
  const vals = dias.map(d => d[campo] || 0), ord = [...vals].sort((a, b) => b - a);
  const cortar = ord.length > 1 && ord[0] > 3 * Math.max(ord[1], 1);     // um dia muito fora da curva (baixa em lote) nao esconde os demais
  const teto = cortar ? Math.max(ord[1] * 1.25, 1) : null;
  const n = dias.length, passo = n > 16 ? 5 : 1;
  const xRot = dias.filter((d, i) => i === 0 || i === n - 1 || dia(d) % passo === 0).map(d => ({ x: dia(d), t: String(dia(d)) }));
  const tipX = x => { const d = dias.find(z => dia(z) === x); return `${d.d.length === 10 ? dataBR(d.d) : 'Dia ' + x}${d.dom ? ' (sem expediente)' : ''}\n${titulo}: ${(o.fmt || num)(d[campo] || 0)}`; };
  return `<p class="graf-tit">${esc(titulo)}</p>` + linhas({ W: o.W || 520, H: 120, ml: 24, mt: 22, mb: 24, mr: 56, fmt: o.fmt || (v => num(v)), teto, xRot, tipX, aria: titulo,
    series: [{ cor: o.cor || 'var(--accent)', principal: true, rotuloFim: true, marcaPico: !cortar, pontos: dias.map((d, i) => ({ x: dia(d), y: vals[i] })) }] });
}

// tabela: cols = [{t, n?, txt?}]; linhas = arrays de strings ja formatadas; rodape opcional
function tabela(cols, linhas, rodape) {
  const cab = cols.map(c => `<th class="${c.n ? 'n' : ''}">${esc(c.t)}</th>`).join('');
  const cel = (c, v) => `<td class="${c.n ? 'n' : ''}${c.txt ? ' txt' : ''}">${v}</td>`;
  const corpo = linhas.map(l => '<tr>' + l.map((v, i) => cel(cols[i], v)).join('') + '</tr>').join('');
  const pe = rodape ? '<tfoot><tr>' + rodape.map((v, i) => cel(cols[i], v)).join('') + '</tr></tfoot>' : '';
  return `<div class="tab-wrap"><table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody>${pe}</table></div>`;
}

function deltaHtml(v, sufixo, inverso) {   // inverso = true quando menos e melhor (a cor segue o sentido, nao o sinal)
  return comp(v, sufixo, { inverso });
}

// tooltip unico para qualquer elemento com data-tip (mouse e teclado)
const tip = document.createElement('div'); tip.id = 'tip'; document.body.appendChild(tip);
function mostrarTip(el, x, y) {
  if (!el.dataset.tip) { tip.style.display = 'none'; return; }
  tip.textContent = el.dataset.tip; tip.style.display = 'block';
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - w - 8)) + 'px';
  tip.style.top = Math.max(8, Math.min(y + 14, innerHeight - h - 8)) + 'px';
}
document.addEventListener('mousemove', e => { const m = e.target.closest && e.target.closest('[data-tip]'); if (m) mostrarTip(m, e.clientX, e.clientY); else tip.style.display = 'none'; });
document.addEventListener('focusin', e => { const m = e.target.closest && e.target.closest('[data-tip]'); if (m) { const r = m.getBoundingClientRect(); mostrarTip(m, r.left, r.bottom); } });
document.addEventListener('focusout', () => { tip.style.display = 'none'; });

// ---- filtro de periodo --------------------------------------------------------------------------------------------------------------------
// Barra de filtros igual a das telas do site: atalhos de mes, atalhos de dias e periodo livre (De / Ate, em datas).
// Cada painel tem os meses calculados (D.meses["2026-09"]). Um periodo que nao e um mes ("2026-09..2026-10", varios meses, ou
// "2026-09-10..2026-10-25", dias exatos) e calculado pelo servidor quando pedido (?de=2026-09-10&ate=2026-10-25), com a mesma conta de um mes
// sobre todas as linhas do periodo, e chega em D.meses[chave] + D.periodo. Datas que cobrem meses inteiros viram o filtro por mes.
// O painel chama iniciarPeriodo(D, render) no lugar de montar o seletor "Mes" por conta propria.
const NOMES_MES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
const rotuloMes = ym => `${NOMES_MES[+ym.slice(5) - 1]}/${ym.slice(0, 4)}`;
const rotuloMesCurto = ym => `${NOMES_MES[+ym.slice(5) - 1].slice(0, 3)}/${ym.slice(2, 4)}`;
const ehPeriodo = ym => String(ym).includes('..');
const chavesMeses = D => Object.keys(D.meses).filter(k => !ehPeriodo(k)).sort().reverse();   // so os meses simples, do mais novo ao mais antigo
// mes (ou periodo) anterior ao escolhido: num periodo, e o periodo de mesmo tamanho logo antes (chave_anterior, calculado junto)
const anteriorDe = (D, CHAVES, ym) => { const M = D.meses[ym]; return M && M.periodo ? (D.meses[M.chave_anterior] || null) : (D.meses[CHAVES[CHAVES.indexOf(ym) + 1]] || null); };
const mesesEntre = (a, b) => { const r = []; for (let t = +a.slice(0, 4) * 12 + +a.slice(5, 7) - 1, f = +b.slice(0, 4) * 12 + +b.slice(5, 7) - 1; t <= f; t++) r.push(`${Math.floor(t / 12)}-${String(t % 12 + 1).padStart(2, '0')}`); return r; };

const ehMesTxt = s => /^\d{4}-(0[1-9]|1[0-2])$/.test(s);
const ehDiaTxt = s => /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(s) && new Date(s + 'T12:00:00').getMonth() + 1 === +s.slice(5, 7);
const ultimoDiaDoMes = ym => new Date(+ym.slice(0, 4), +ym.slice(5, 7), 0).getDate();
const dia2 = n => String(n).padStart(2, '0');
const somarDias = (iso, n) => { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${dia2(d.getMonth() + 1)}-${dia2(d.getDate())}`; };
// a mesma regra do servidor (painel_comum.Periodo): meses inteiros viram o filtro por mes; o resto e um recorte de dias
function normalizarPeriodo(de, ate) {
  if (!(ehMesTxt(de) || ehDiaTxt(de)) || !(ehMesTxt(ate) || ehDiaTxt(ate))) return null;
  const ini = x => x.length === 7 ? x + '-01' : x, fim = x => x.length === 7 ? `${x}-${dia2(ultimoDiaDoMes(x))}` : x;
  let a = ini(de), b = fim(ate);
  if (a > b) { a = ini(ate); b = fim(de); }
  const mA = a.slice(0, 7), mB = b.slice(0, 7);
  const inteiro = a.endsWith('-01') && +b.slice(8) === ultimoDiaDoMes(mB);
  return inteiro ? { de: mA, ate: mB, exato: false, chave: mA === mB ? mA : `${mA}..${mB}`, dia_de: a, dia_ate: b }
    : { de: a, ate: b, exato: true, chave: `${a}..${b}`, dia_de: a, dia_ate: b };
}
function datasDoPeriodo(diaDe, diaAte, hojeIso) {   // primeiro e ultimo dia do periodo; se hoje cai dentro dele, o ultimo dia com dado e hoje
  const parcial = !!hojeIso && hojeIso >= diaDe && hojeIso < diaAte;
  return { ini: diaDe, fim: parcial ? hojeIso : diaAte, parcial };
}
window.PERIODO_TXT = '';   // "de 01/09/2026 a 30/09/2026": o gerador de PDF le daqui para escrever o periodo no rodape

function iniciarPeriodo(D, render, o = {}) {
  const sel = $('mes'), lab = sel.closest('label');
  const consulta = new URLSearchParams(location.search);
  let P = D.periodo || null;
  if (!P) {   // um mes inteiro so (?de=2026-09&ate=2026-09 ou de 01 a 30/09, como o PDF e o filtro dos outros menus pedem): a pagina de sempre ja o traz
    const n = normalizarPeriodo(consulta.get('de') || '', consulta.get('ate') || '');
    if (n && !n.exato && ehMesTxt(n.chave))
      P = D.meses[n.chave] ? { de: n.de, ate: n.ate, dia_de: n.dia_de, dia_ate: n.dia_ate, exato: false, chave: n.chave, vazio: false, recortado: false }
        : { de: n.de, ate: n.ate, dia_de: n.dia_de, dia_ate: n.dia_ate, exato: false, vazio: true, pedido_de: n.de, pedido_ate: n.ate };
  }
  const simples = chavesMeses(D).slice().reverse();
  const todos = D.todos_meses && D.todos_meses.length ? D.todos_meses : simples;
  const baseTxt = ((lab && lab.firstChild && lab.firstChild.textContent) || '').trim().toLowerCase().replace(/^mês de /, '').replace(/^mês$/, '');
  const rotuloBase = ((lab && lab.firstChild && lab.firstChild.textContent) || '').trim() || 'Mês';
  const pedido = P ? { de: P.pedido_dia_de || P.dia_de || P.pedido_de || P.de, ate: P.pedido_dia_ate || P.dia_ate || P.pedido_ate || P.ate } : null;
  const pedDe = P ? (P.pedido_de || P.de) : D.mes_padrao, pedAte = P ? (P.pedido_ate || P.ate) : D.mes_padrao;
  const lista = mesesEntre([todos[0], pedDe].sort()[0], [todos[todos.length - 1], pedAte].sort().reverse()[0]).reverse();
  const hoje = D.hoje || new Date().toISOString().slice(0, 10);
  const minDia = `${lista[lista.length - 1]}-01`, maxDia = `${lista[0]}-${dia2(ultimoDiaDoMes(lista[0]))}`;

  // ---- barra de filtros (a mesma das telas do site)
  let barraF = $('toolbar');
  if (!barraF) { barraF = document.createElement('section'); barraF.className = 'toolbar'; barraF.id = 'toolbar'; barraF.setAttribute('aria-label', 'Período'); (document.querySelector('header.top') || document.body).after(barraF); }
  const hojeYm = hoje.slice(0, 7);
  const SEIS = lista.filter(m => m <= hojeYm).slice(0, 6);   // os 6 meses ate o atual; meses futuros (previsoes) e antigos ficam em "Outros meses"
  const caixa = document.createElement('div');
  caixa.style.display = 'contents'; caixa.id = 'periodo-pick';
  caixa.innerHTML =
    `<div><span class="toolbar-label" id="rot-meses">${esc(rotuloBase)}</span><div class="seg" role="group" aria-labelledby="rot-meses">` +
      SEIS.map(m => `<button type="button" class="seg-item" data-mes="${m}">${esc(rotuloMesCurto(m))}</button>`).join('') + `</div></div>` +
    (lista.length > SEIS.length ? `<label class="mes-pick">Outros meses <select id="p-outros" aria-label="Escolher outro mês"><option value="">Escolher…</option>${lista.filter(m => !SEIS.includes(m)).map(m => `<option value="${m}">${esc(rotuloMes(m))}</option>`).join('')}</select></label>` : '') +
    `<div><span class="toolbar-label" id="rot-atalhos">Últimos dias</span><div class="seg" role="group" aria-labelledby="rot-atalhos">` +
      [[7, '7 dias'], [30, '30 dias'], [90, '90 dias']].map(([n, t]) => `<button type="button" class="seg-item" data-dias="${n}">${t}</button>`).join('') + `</div></div>` +
    `<form class="range-form" id="p-form" aria-label="Período livre"><div class="field"><label class="field-label" for="p-de">De</label><input id="p-de" class="input" type="date" min="${minDia}" max="${maxDia}" required></div>` +
    `<div class="field"><label class="field-label" for="p-ate">Até</label><input id="p-ate" class="input" type="date" min="${minDia}" max="${maxDia}" required></div>` +
    `<button type="submit" class="btn btn-primary">Aplicar</button></form>`;
  lab.before(caixa); lab.style.display = 'none';
  const iDe = $('p-de'), iAte = $('p-ate'), outros = $('p-outros');
  let linha = $('periodo-ativo'), aviso = $('periodo-aviso');
  if (!linha) { linha = document.createElement('div'); linha.id = 'periodo-ativo'; linha.className = 'periodo-ativo'; ($('sub') || document.querySelector('header.top > div')).after(linha); }
  if (!aviso) { aviso = document.createElement('div'); aviso.id = 'periodo-aviso'; aviso.className = 'periodo-aviso'; aviso.hidden = true; ($('aviso') || $('conteudo')).before(aviso); }
  const barra = barraCarregando();
  const ajuda = document.querySelector('details.ajuda .corpo ul');
  if (ajuda && !ajuda.querySelector('[data-periodo]')) ajuda.insertAdjacentHTML('afterbegin', '<li data-periodo><b>Período:</b> use os botões de <b>mês</b> ou os <b>últimos dias</b>, ou escolha livremente a data inicial e a final em <b>De</b> e <b>Até</b> e clique em <b>Aplicar</b>. Com vários meses ou dias soltos, os números são os do período inteiro e as comparações são com o período anterior de mesmo tamanho; o que só existe dentro de um mês (ritmo dia a dia, projeção de fechamento) aparece quando o filtro é um mês só. Informações que o Klingo só entrega por mês inteiro (quando houver) são avisadas no alto da página. O período fica escrito no alto da página e em todas as folhas do PDF.</li>');

  function mostrarLinha(n) {
    const t = datasDoPeriodo(n.dia_de, n.dia_ate, D.hoje);
    window.PERIODO_TXT = t.ini === t.fim ? `em ${dataBR(t.ini)}` : `de ${dataBR(t.ini)} a ${dataBR(t.fim)}`;
    linha.innerHTML = `Período: <b>${window.PERIODO_TXT}</b>` + (t.parcial ? ' <small>(o período ainda não terminou: só há dados até hoje)</small>' : '') +
      (baseTxt ? ` <small>· meses contados por ${esc(baseTxt)}</small>` : '');
  }
  function marcar(n) {   // botoes de mes e de dias acesos conforme o periodo ativo; datas preenchidas com o periodo
    iDe.value = n.dia_de; iAte.value = n.dia_ate;
    caixa.querySelectorAll('[data-mes]').forEach(b => b.setAttribute('aria-current', !n.exato && n.chave === b.dataset.mes ? 'true' : 'false'));
    caixa.querySelectorAll('[data-dias]').forEach(b => { const d = +b.dataset.dias; b.setAttribute('aria-current', n.exato && n.dia_ate === hoje && n.dia_de === somarDias(hoje, 1 - d) ? 'true' : 'false'); });
    if (outros) outros.value = !n.exato && outros.querySelector(`option[value="${n.chave}"]`) ? n.chave : '';
  }
  function escolher(n) {
    window.PERIODO_CHAVE = n.chave;   // quem precisa redesenhar por outro motivo (ex.: trocar de responsavel no Atendimento) usa esta chave
    marcar(n);
    mostrarLinha(n);
    render(n.chave);
  }
  function pedir(de, ate) {   // de / ate: mes (AAAA-MM) ou dia (AAAA-MM-DD)
    const n = normalizarPeriodo(de, ate);
    if (!n) return;
    const q = new URLSearchParams(location.search); q.set('de', n.de); q.set('ate', n.ate);
    try { parent.postMessage({ tipo: 'periodo', de: n.de, ate: n.ate }, location.origin); } catch (e) {}
    if (D.meses[n.chave]) {   // ja esta na pagina (um mes simples ou o periodo que o servidor montou): nao precisa buscar
      history.replaceState(null, '', location.pathname + '?' + q.toString());
      aviso.hidden = true; escolher(n);
    } else {                  // periodo novo: o servidor refaz a conta e devolve a pagina
      marcar(n); barra.mostrar();
      aviso.hidden = false; aviso.textContent = 'Calculando o período…';
      location.search = q.toString();
    }
  }
  caixa.addEventListener('click', e => {
    const bm = e.target.closest('[data-mes]'), bd = e.target.closest('[data-dias]');
    if (bm) pedir(bm.dataset.mes, bm.dataset.mes);
    else if (bd) { const d = +bd.dataset.dias; const ini = somarDias(hoje, 1 - d); pedir(ini < minDia ? minDia : ini, hoje); }
  });
  if (outros) outros.addEventListener('change', () => { if (outros.value) pedir(outros.value, outros.value); });
  $('p-form').addEventListener('submit', e => {
    e.preventDefault();
    if (!iDe.value || !iAte.value) return;
    pedir(iDe.value, iAte.value);
  });

  const notas = (P && P.notas) || [];
  function avisos(extra) {
    const t = [...(extra ? [extra] : []), ...notas];
    aviso.hidden = !t.length; aviso.innerHTML = t.map(x => esc(x)).join('<br>');
  }
  if (P && P.vazio) {   // nada do painel cai dentro do periodo pedido
    const n = normalizarPeriodo(pedido.de, pedido.ate) || { dia_de: minDia, dia_ate: maxDia, chave: '', exato: false };
    marcar(n); mostrarLinha(n);
    aviso.hidden = false;
    aviso.textContent = `Este painel não tem dados entre ${dataBR(n.dia_de)} e ${dataBR(n.dia_ate)}. Os dados vão de ${rotuloMes(todos[0])} a ${rotuloMes(todos[todos.length - 1])}: escolha outro período.`;
    $('conteudo').innerHTML = '';
    return;
  }
  const inicial = P && P.chave ? { de: P.exato ? P.dia_de : P.de, ate: P.exato ? P.dia_ate : P.ate } : { de: D.mes_padrao, ate: D.mes_padrao };
  const n0 = normalizarPeriodo(inicial.de, inicial.ate);
  if (P && P.recortado) avisos(`O painel só tem dados de ${dataBR(P.dia_de)} a ${dataBR(P.dia_ate)}; é esse o recorte mostrado (você pediu ${dataBR(pedido.de.length === 7 ? pedido.de + '-01' : pedido.de)} a ${dataBR(pedido.ate.length === 7 ? pedido.ate + '-' + dia2(ultimoDiaDoMes(pedido.ate)) : pedido.ate)}).`);
  else avisos('');
  escolher(n0);
}

// barra fina no topo da pagina, para mostrar que algo esta carregando (ex.: "Atualizar agora")
function barraCarregando() {
  let b = $('barra-carregando');
  if (!b) {
    b = document.createElement('div'); b.id = 'barra-carregando'; b.innerHTML = '<div class="mov"></div>';
    document.body.appendChild(b);
  }
  return { mostrar: () => b.classList.add('ativa'), esconder: () => b.classList.remove('ativa') };
}

// botao "Atualizar agora" + verificacao periodica (precisa do servidor do portal)
function iniciarAtualizacao(versaoAtual) {
  const servido = location.protocol.startsWith('http');
  const btn = $('btn-atualizar');
  const barra = barraCarregando();
  const aviso = (html, tipo) => { const a = $('aviso'); a.innerHTML = html || ''; a.dataset.tipo = tipo || ''; a.hidden = !html; };
  try { const m = sessionStorage.getItem('msg_painel'); if (m) { aviso(esc(m), 'ok'); sessionStorage.removeItem('msg_painel'); } } catch (e) {}
  if (!servido) {
    btn.disabled = true;
    aviso('Para usar o botão <b>Atualizar agora</b>, abra o painel pelo <b>Indicadores CSI</b>. Aberto direto do arquivo, esta página só mostra os dados da última atualização.', 'info');
    return;
  }
  if (window.PAINEL_NUVEM && window.PAINEL_ADMIN === false) {   // na Vercel so administrador consulta o Klingo (protege a cota da API)
    btn.disabled = true;
    aviso('Só administradores podem usar <b>Atualizar agora</b>. Os dados mostrados são os da última atualização.', 'info');
    return;
  }
  btn.addEventListener('click', async () => {
    btn.disabled = true; btn.classList.add('girando'); $('btn-texto').textContent = 'Atualizando…';
    barra.mostrar();
    aviso('Consultando o Klingo para buscar os dados mais recentes…', 'info');
    try {
      const r = await fetch(apiPainel('atualizar'), { method: 'POST', headers: { 'X-Painel': '1' } });
      const j = await r.json();
      if (j.ok && j.atualizou === false) {
        // nao consultou o Klingo: alguem atualizou ha pouco ou ja ha uma atualizacao em andamento (varias pessoas usam o portal).
        // Nao recarrega a pagina: so explica. Quando uma atualizacao terminar, a verificacao abaixo recarrega sozinha.
        aviso(esc(j.mensagem), 'info');
      } else if (j.ok) {
        try { sessionStorage.setItem('msg_painel', j.mensagem); } catch (e) {}
        location.reload();
        return;
      } else {
        aviso(esc(j.mensagem), 'erro');
      }
    } catch (e) {
      aviso(window.PAINEL_NUVEM ? 'Não consegui concluir a atualização (pode ter passado do tempo limite ou a conexão caiu). Recarregue a página e clique em Atualizar agora de novo: o que já foi baixado ficou guardado.'
        : 'Não consegui falar com o servidor do portal. O computador dele está ligado e o Indicadores CSI Servidor está aberto? Se continuar, avise quem cuida do portal.', 'erro');
    }
    barra.esconder();
    btn.disabled = false; btn.classList.remove('girando'); $('btn-texto').textContent = 'Atualizar agora';
  });
  setInterval(async () => {      // se a verificacao automatica (de qualquer painel) trouxe dados novos, recarrega
    try {
      const j = await (await fetch(apiPainel('estado'), { cache: 'no-store' })).json();
      if (j.atualizando) barra.mostrar(); else barra.esconder();
      if (j.versao !== versaoAtual && !j.atualizando) location.reload();
      else if (j.aviso) aviso(esc(j.aviso), 'erro');
    } catch (e) {}
  }, 30000);
}

// ---- itens da pagina, para a tela de Inicio do site
// Cada grafico/bloco com titulo, agrupado pela aba (Resumo, Analise, Detalhes...), pode ser escolhido la como favorito. A tela do site
// carrega esta mesma pagina num quadro e (1) pergunta a lista (mensagem "itens") e (2) pede um so item (?aba=...&item=...), e a pagina
// esconde o resto. Tudo sai do HTML ja montado: um grafico novo nos modelos aparece na lista sem mexer aqui.
const MESES_NOME = /\b(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\/\d{4}\b/gi;
// o titulo muda com o mes ("Ritmo dos dias em Outubro/2026") e com contagens ("Os 12 exames..."): a chave ignora isso para o favorito seguir valendo
const chaveDoItem = t => String(t).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(MESES_NOME, '').replace(/\d+/g, '#').replace(/\s+/g, ' ').trim();
const h2Soltos = el => [...el.querySelectorAll('h2')].filter(h => !h.closest('details'));

function itensDaPagina() {
  const itens = [], vistos = new Set();
  const acrescentar = (aba, titulo, els, h2) => {
    titulo = String(titulo).replace(/\s+/g, ' ').trim();
    const chave = chaveDoItem(titulo), id = aba + '\u0001' + chave;
    if (!titulo || !chave || vistos.has(id)) return;   // dois blocos com o mesmo titulo na mesma aba: vale o primeiro
    vistos.add(id);
    itens.push({ aba, titulo, chave, els, h2 });
  };
  document.querySelectorAll('#conteudo .tier').forEach(tier => {
    const aba = (tier.querySelector('.tier-h b') || {}).textContent || '';
    if (!aba.trim()) return;
    [...tier.children].forEach(filho => {
      if (filho.matches('.kpis')) acrescentar(aba.trim(), 'Números principais', [filho], null);
    });
    tier.querySelectorAll('details.acord').forEach(d => {
      const s = d.querySelector(':scope > summary');
      if (!s) return;
      const c = s.cloneNode(true);
      c.querySelectorAll('small').forEach(x => x.remove());
      acrescentar(aba.trim(), c.textContent, [d], null);
    });
    h2Soltos(tier).forEach(h => {
      let c = h;   // sobe enquanto o pai so tem este titulo: o bloco inteiro do grafico (cartao, nota, grafico)
      while (c.parentElement && c.parentElement !== tier && h2Soltos(c.parentElement).length === 1) c = c.parentElement;
      let els = [c];
      if (c === h) {   // titulo solto entre outros: o bloco vai ate o proximo titulo
        els = [h];
        for (let n = h.nextElementSibling; n && !n.matches('h2') && !h2Soltos(n).length; n = n.nextElementSibling) els.push(n);
      }
      acrescentar(aba.trim(), h.textContent, els, h);
    });
  });
  return itens;
}

// deixa visivel so o caminho ate os elementos escolhidos e o que tem dentro deles
function isolarItem(els) {
  const caminho = new Set();
  els.forEach(e => { for (let n = e; n; n = n.parentElement) caminho.add(n); });
  const passar = pai => [...pai.children].forEach(c => {
    if (c.tagName === 'SCRIPT' || c.tagName === 'STYLE') return;
    if (!caminho.has(c)) c.style.display = 'none';
    else if (!els.includes(c)) passar(c);
  });
  passar(document.body);
}

(function itensParaOInicio() {
  const alvo = $('conteudo');
  if (!alvo) return;
  const q = new URLSearchParams(location.search), pedidoAba = q.get('aba'), pedidoItem = q.get('item');
  const modoItem = pedidoAba != null && pedidoItem != null;
  if (modoItem) document.documentElement.classList.add('modo-item');
  let ocupado = false;
  const observador = new MutationObserver(() => {
    if (ocupado) return;
    ocupado = true;
    try {
      const itens = itensDaPagina();
      if (modoItem) {
        const achado = itens.find(i => i.aba === pedidoAba && i.chave === pedidoItem);
        if (achado) {
          if (achado.h2) achado.h2.setAttribute('data-item-titulo', '');
          achado.els.forEach(e => { if (e.matches('details')) e.open = true; });
          isolarItem(achado.els);
        } else {
          observador.disconnect();   // trocar o conteudo abaixo nao pode chamar este mesmo observador de novo
          alvo.innerHTML = '<p class="nota item-ausente">Este bloco não aparece neste momento (o painel só o mostra quando há dados para ele). Use “Abrir painel” para ver tudo.</p>';
          isolarItem([alvo]);
        }
      }
      if (window.parent !== window) {
        window.parent.postMessage({ tipo: 'itens', painel: painelAtual(), itens: itens.map(({ aba, titulo, chave }) => ({ aba, titulo, chave })) }, location.origin);
      }
    } finally {
      ocupado = false;
    }
  });
  observador.observe(alvo, { childList: true });
})();
