/* Biblioteca comum dos paineis Clinica CSI (kpi, graficos, tabelas, alertas, periodo De/ate, atualizacao).
   Reconstruida a partir do uso nos modelos HTML: o painel_base.js original nao veio na copia recebida (ver docs/PREMISSAS.md). */
'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _nf = {};
const _fmt = d => _nf[d] || (_nf[d] = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }));
const ok_ = v => v != null && v !== '' && isFinite(v);
const num = (v, d = 0) => ok_(v) ? _fmt(d).format(Number(v)) : '—';
const pct = (v, d = 1) => ok_(v) ? num(v, d) + '%' : '—';
const brl = v => ok_(v) ? (v < 0 ? '−' : '') + 'R$ ' + _fmt(2).format(Math.abs(Number(v))) : '—';
const _compacto = v => { const a = Math.abs(v); return a >= 1e6 ? num(a / 1e6, a >= 1e7 ? 1 : 2) + ' mi' : a >= 1e4 ? num(a / 1e3, 1) + ' mil' : a >= 1e3 ? num(a / 1e3, 2) + ' mil' : num(a, 0); };
const brlc = v => ok_(v) ? (v < 0 ? '−' : '') + 'R$ ' + _compacto(Number(v)) : '—';
const rotEixo = v => ok_(v) ? (v < 0 ? '−' : '') + _compacto(Number(v)) : '—';
const dataBR = v => { if (!v) return '—'; const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/); return m ? `${m[3]}/${m[2]}/${m[1]}` : esc(v); };
const soma = (a, f) => (a || []).reduce((t, x) => { const v = f ? f(x) : x; return t + (ok_(v) ? Number(v) : 0); }, 0);
const varPct = (a, b) => ok_(a) && ok_(b) && Number(b) !== 0 ? (Number(a) / Number(b) - 1) * 100 : null;
const ehPeriodo = k => String(k).includes('..');

// ---------------------------------------------------------------- blocos
function comp(v, contra, o = {}) {
  if (!ok_(v)) return o.vazio ? `<span class="delta igual">${o.vazio}</span>` : '';
  const d = o.d == null ? 1 : o.d, a = Math.abs(v);
  const txt = o.fmt ? o.fmt(a) : o.unidade === 'pp' ? num(a, d) + ' pp' : pct(a, d);
  const nulo = Number(a.toFixed(d)) === 0;
  const bom = o.inverso ? v < 0 : v > 0;
  const cls = nulo ? 'igual' : bom ? 'sobe' : 'desce';
  const seta = nulo ? '▬' : v > 0 ? '▲' : '▼';
  return `<span class="delta ${cls}">${seta} ${nulo ? '' : v > 0 ? '+' : '−'}${txt}</span>${contra ? ' <span class="cont">' + contra + '</span>' : ''}`;
}
function kpi(rotulo, valor, o = {}) {
  return `<div class="kpi${o.destaque ? ' destaque' : ''}${o.classe ? ' ' + o.classe : ''}"><div class="kpi-r">${rotulo}</div>` +
    `<div class="kpi-num"${o.titulo ? ` title="${esc(o.titulo)}"` : ''}>${valor}</div>` +
    `<div class="kpi-comp">${o.comp || ''}</div>${o.sub ? `<div class="kpi-sub">${o.sub}</div>` : ''}</div>`;
}
function tier(titulo, sub, html) {
  return `<div class="tier"><div class="tier-h"><h2>${esc(titulo)}</h2><span>${esc(sub)}</span></div>${html}</div>`;
}
function acordeao(titulo, corpo, o = {}) {
  return `<details class="acord"${o.aberto ? ' open' : ''}><summary>${titulo}${o.dica ? `<span class="dica">${o.dica}</span>` : ''}</summary><div class="corpo">${corpo}</div></details>`;
}
function tabela(cols, linhas, rodape) {
  const c = cols.map(x => typeof x === 'string' ? { t: x } : x);
  const cl = x => (x.n ? 'n' : x.txt ? 'txt' : '');
  const cab = c.map(x => `<th class="${x.n ? 'n' : ''}">${x.t}</th>`).join('');
  const corpo = linhas.map(l => '<tr>' + c.map((x, i) => `<td class="${cl(x)}">${l[i] == null ? '' : l[i]}</td>`).join('') + '</tr>').join('');
  const rod = rodape ? '<tfoot><tr>' + c.map((x, i) => `<td class="${x.n ? 'n' : ''}">${rodape[i] == null ? '' : rodape[i]}</td>`).join('') + '</tr></tfoot>' : '';
  return `<div class="tab-wrap"><table class="t"><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody>${rod}</table></div>`;
}
// tabela de evidencia dos alertas (gp.tabela do servidor): {cab, linhas, total, numericas}
function tabelaItens(t) {
  if (!t || !t.cab || !t.cab.length) return '';
  const num_ = new Set(t.numericas || []);
  const mais = t.total > t.linhas.length ? `<p class="micro">Mostrando ${t.linhas.length} de ${num(t.total)}.</p>` : `<p class="micro">${num(t.total)} no total.</p>`;
  return tabela(t.cab.map((h, i) => ({ t: esc(h), n: num_.has(i) })), t.linhas.map(l => l.map(c => esc(c))), null) + mais;
}

// ---------------------------------------------------------------- tooltip
(function () {
  let tip;
  const mostra = (el, ev) => {
    if (!tip) { tip = document.createElement('div'); tip.id = 'tip'; document.body.appendChild(tip); }
    tip.textContent = el.getAttribute('data-tip'); tip.classList.add('on');
    const r = ev && ev.clientX != null && ev.type !== 'focusin' ? { x: ev.clientX, y: ev.clientY } : (() => { const b = el.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top }; })();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(4, Math.min(innerWidth - w - 4, r.x + 12)) + 'px';
    tip.style.top = Math.max(4, r.y - h - 10 < 4 ? r.y + 16 : r.y - h - 10) + 'px';
  };
  const esconde = () => tip && tip.classList.remove('on');
  document.addEventListener('mousemove', e => { const el = e.target.closest && e.target.closest('[data-tip]'); el ? mostra(el, e) : esconde(); });
  document.addEventListener('focusin', e => { const el = e.target.closest && e.target.closest('[data-tip]'); if (el) mostra(el, e); });
  document.addEventListener('focusout', esconde);
  document.addEventListener('scroll', esconde, true);
})();

// ---------------------------------------------------------------- graficos
const COR_PADRAO = 'var(--neutro-2)';
function barras(itens, vazio = '', larg = '40%', o = {}) {
  if (!itens || !itens.length) return vazio ? `<p class="vazio">${esc(vazio)}</p>` : '';
  const max = o.max || Math.max(...itens.map(i => i.valor || 0), 1e-9);
  const ESC = 62;   // a barra mais longa ocupa ate 62% da pista: o resto e do rotulo colado na ponta
  const pos = v => Math.max(0, Math.min(100, (v || 0) / max * 100)) * ESC / 100;
  return `<div class="rank" style="--rot:${larg}">` + itens.map(i => {
    const w = pos(i.valor), cor = i.cor || (i.destaque ? 'var(--accent)' : COR_PADRAO);
    return `<div class="lin"><div class="rot">${esc(i.rotulo)}</div><div class="barra" tabindex="0"${i.tip ? ` data-tip="${esc(i.tip)}"` : ''}>` +
      `<i style="width:${w.toFixed(2)}%;background:${cor}"></i>` +
      (i.marca != null ? `<span class="marca" style="left:${pos(i.marca).toFixed(2)}%"></span>` : '') +
      `<span class="v" style="left:${w.toFixed(2)}%">${i.texto != null ? i.texto : num(i.valor)}${i.extra ? `<small>${esc(i.extra)}</small>` : ''}</span></div></div>`;
  }).join('') + '</div>';
}
function donut(itens, o = {}) {
  const fmt = o.fmt || (v => num(v));
  let L = (itens || []).filter(i => i.valor > 0).sort((a, b) => b.valor - a.valor);
  if (!L.length) return `<p class="vazio">${esc(o.vazio || 'Sem dados.')}</p>`;
  if (L.length > 4) { const resto = L.slice(3).reduce((t, i) => t + i.valor, 0); L = [...L.slice(0, 3), { rotulo: 'Outros', valor: resto, tip: `Outros\n${fmt(resto)}` }]; }
  const total = L.reduce((t, i) => t + i.valor, 0);
  const CORES = ['var(--accent)', 'var(--neutro)', 'var(--neutro-2)', 'var(--neutro-3)'];
  const R = 60, C = 2 * Math.PI * R;
  let acc = 0;
  const arcos = L.map((i, k) => {
    const f = i.valor / total, seg = `<circle cx="80" cy="80" r="${R}" fill="none" stroke="${i.cor || CORES[k]}" stroke-width="22" stroke-dasharray="${(f * C).toFixed(3)} ${(C - f * C).toFixed(3)}" stroke-dashoffset="${(-acc * C).toFixed(3)}" transform="rotate(-90 80 80)" tabindex="0" data-tip="${esc(i.tip || `${i.rotulo}\n${fmt(i.valor)} (${pct(f * 100)})`)}"/>`;
    acc += f; return seg;
  }).join('');
  const centro = o.centro ? `<text class="centro-n" x="80" y="82" text-anchor="middle">${esc(o.centro.num)}</text><text class="centro-r" x="80" y="97" text-anchor="middle">${esc(o.centro.rot || '')}</text>` : '';
  const leg = L.map((i, k) => `<li><i style="background:${i.cor || CORES[k]}"></i><span>${esc(i.rotulo)}</span><span class="p">${fmt(i.valor)} · ${pct(i.valor / total * 100, 0)}</span></li>`).join('');
  return `<div class="donut-box"><svg viewBox="0 0 160 160" role="img" aria-label="${esc(o.aria || 'Composição')}">${arcos}${centro}</svg><ul class="leg">${leg}</ul></div>`;
}
function empilhada(itens, fmt = brlc) {
  const t = itens.reduce((s, i) => s + Math.max(i.valor || 0, 0), 0);
  if (!t) return '';
  return `<div class="empilhada">${itens.filter(i => i.valor > 0).map(i => `<i style="width:${(i.valor / t * 100).toFixed(2)}%;background:${i.cor || 'var(--neutro)'}" data-tip="${esc(i.rotulo + '\n' + fmt(i.valor))}"></i>`).join('')}</div>` +
    `<div class="emp-leg">${itens.map(i => `<span><i style="background:${i.cor || 'var(--neutro)'}"></i>${esc(i.rotulo)} ${fmt(i.valor)}</span>`).join('')}</div>`;
}
function linhas(o) {
  const W = o.W || 720, H = o.H || 240, ml = o.ml == null ? 30 : o.ml, mr = o.mr == null ? 80 : o.mr, mt = o.mt == null ? 18 : o.mt, mb = o.mb == null ? 26 : o.mb;
  const fmt = o.fmt || (v => num(v));
  const S = (o.series || []).map(s => ({ ...s, pontos: (s.pontos || []).filter(p => p.y != null && isFinite(p.y)) })).filter(s => s.pontos.length);
  if (!S.length) return '<p class="vazio">Sem dados.</p>';
  const todos = S.flatMap(s => s.pontos);
  const xs = todos.map(p => p.x), ys = todos.map(p => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys, y0 + 1e-9) * 1.06;
  const X = x => ml + (x1 === x0 ? (W - ml - mr) / 2 : (x - x0) / (x1 - x0) * (W - ml - mr));
  const Y = y => mt + (1 - (y - y0) / (y1 - y0)) * (H - mt - mb);
  const ordem = [...S.filter(s => !s.principal), ...S.filter(s => s.principal)];
  const path = ordem.map(s => {
    const pts = s.pontos.slice().sort((a, b) => a.x - b.x);
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');
    const larg = s.larg || (s.principal ? 2.8 : 1.8);
    const unico = pts.length === 1 ? `<circle cx="${X(pts[0].x).toFixed(1)}" cy="${Y(pts[0].y).toFixed(1)}" r="3.5" fill="${s.cor}"/>` : '';
    return `<path d="${d}" fill="none" stroke="${s.cor}" stroke-width="${larg}" stroke-linejoin="round" stroke-linecap="round"${s.traco ? ' stroke-dasharray="6 4"' : ''}/>${unico}`;
  }).join('');
  // rotulo na ponta de cada serie, sem sobrepor (afasta os que ficam a menos de 13 px)
  const pontas = S.map(s => { const p = s.pontos.reduce((a, b) => b.x >= a.x ? b : a); return { s, p, y: Y(p.y) + (s.rotuloEmbaixo ? 12 : 0) }; }).sort((a, b) => a.y - b.y);
  for (let i = 1; i < pontas.length; i++) if (pontas[i].y - pontas[i - 1].y < 13) pontas[i].y = pontas[i - 1].y + 13;
  const rot = pontas.map(({ s, p, y }) => `<text x="${(X(p.x) + 7).toFixed(1)}" y="${(y + 4).toFixed(1)}" style="${s.principal ? 'font-weight:700;fill:var(--ink)' : ''}"><tspan>${esc(fmt(p.y))}</tspan><tspan dx="5" fill="${s.cor}" style="font-weight:600">${esc(s.nome || '')}</tspan></text>`).join('');
  const todosRot = o.rotulosEm === 'todos' ? ordem.map(s => s.pontos.map(p => `<text x="${X(p.x).toFixed(1)}" y="${(Y(p.y) - 7).toFixed(1)}" text-anchor="middle" style="font-size:10px">${esc(fmt(p.y))}</text>`).join('')).join('') : '';
  const xr = (o.xRot || []).map(r => `<text class="xr" x="${X(r.x).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(r.t)}</text>`).join('');
  const dist = [...new Set(xs)].sort((a, b) => a - b);
  const hits = o.tipX ? dist.map((x, i) => {
    const a = i ? (X(dist[i - 1]) + X(x)) / 2 : ml, b = i < dist.length - 1 ? (X(x) + X(dist[i + 1])) / 2 : W - mr;
    return `<g class="px"><line class="guia-x" x1="${X(x).toFixed(1)}" x2="${X(x).toFixed(1)}" y1="${mt}" y2="${H - mb}"/><rect x="${a.toFixed(1)}" y="0" width="${Math.max(b - a, 2).toFixed(1)}" height="${H - mb}" fill="transparent" tabindex="0" data-tip="${esc(o.tipX(x))}"/></g>`;
  }).join('') : '';
  return `<svg class="linhas" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || 'Gráfico de linhas')}">${hits}${path}${rot}${todosRot}${xr}</svg>`;
}
function miniLinha(titulo, dias, campo, o = {}) {
  const v = (dias || []).map((d, i) => ({ i, y: d[campo], d })).filter(p => p.y != null);
  if (!v.length) return '';
  const fmt = o.fmt || (x => num(x)), W = 220, H = 44, max = Math.max(...v.map(p => p.y), 1e-9);
  const X = i => 3 + i / Math.max(dias.length - 1, 1) * (W - 6), Y = y => H - 4 - y / max * (H - 10);
  const d = v.map((p, k) => `${k ? 'L' : 'M'}${X(p.i).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');
  const pts = v.map(p => `<circle cx="${X(p.i).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="4" fill="transparent" tabindex="0" data-tip="${esc(`Dia ${p.d.d != null ? p.d.d : p.i + 1}: ${fmt(p.y)}`)}"/>`).join('');
  return `<div><div class="mini-tit">${esc(titulo)}</div><svg class="mini" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${d}" fill="none" stroke="${o.cor || 'var(--neutro)'}" stroke-width="1.8" vector-effect="non-scaling-stroke"/>${pts}</svg>` +
    `<div class="mini-v">Último: ${fmt(v[v.length - 1].y)} · pico ${fmt(max)}</div></div>`;
}

// ---------------------------------------------------------------- alertas e pendencias (Como achar / Marcar como resolvido)
const ICONES_NIVEL = {
  critico: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="8" fill="currentColor"/><path d="M5.3 5.3l5.4 5.4M10.7 5.3l-5.4 5.4" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  atencao: '<svg viewBox="0 0 16 16"><path d="M8 .8l7.6 13.4H.4z" fill="currentColor"/><path d="M8 5.8v4M8 11.7v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
  ok: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="8" fill="currentColor"/><path d="M4.4 8.3l2.3 2.3 4.8-5" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  info: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="8" fill="currentColor"/><path d="M8 7v4.5M8 4.6v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
};
const ROTULO_NIVEL = { critico: 'Crítico', atencao: 'Atenção', ok: 'Ok', info: 'Informação' };
const chip = n => `<span class="chip n-${n}">${ICONES_NIVEL[n] || ''}${ROTULO_NIVEL[n] || esc(n)}</span>`;

const PEND = { lista: [], mapa: {}, carregado: false };
const _D = () => (typeof D !== 'undefined' ? D : window.D);   // o modelo declara "const D": visivel aqui so como binding global
function carregarPendencias() {
  if (!_D() || !_D().menu) return Promise.resolve();
  return fetch('/api/pendencias?painel=' + encodeURIComponent(_D().menu), { credentials: 'same-origin' })
    .then(r => r.ok ? r.json() : { itens: [] }).catch(() => ({ itens: [] }))
    .then(j => { PEND.lista = j.itens || []; PEND.mapa = Object.fromEntries(PEND.lista.map(x => [x.chave, x])); PEND.carregado = true; });
}
function _postar(url, corpo) {
  return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Painel': '1' }, body: JSON.stringify(corpo) })
    .then(r => r.json().catch(() => ({}))).catch(() => ({ erro: 'Sem conexão.' }));
}
const _quando = iso => { try { return new Date(iso).toLocaleDateString('pt-BR'); } catch (e) { return ''; } };
function guiaHtml(a) {
  const g = a.guia; if (!g) return '';
  return `<div class="guia" hidden><div class="rel"><b>Onde ver no Klingo:</b> ${g.url ? `<a href="${esc(g.url)}" target="_blank" rel="noopener">relatório ${esc(g.relatorio)}</a>` : esc(g.relatorio)}</div>` +
    `<ol>${g.passos.map(p => `<li>${esc(p)}</li>`).join('')}</ol><p><b>O painel considera resolvido quando:</b> ${esc(g.resolvido_quando)}</p>${tabelaItens(a.itens)}</div>`;
}
function alertaLi(a, ctx) {
  const problema = a.chave && (a.nivel === 'critico' || a.nivel === 'atencao');
  const rec = problema ? PEND.mapa[a.chave] : null;
  const botoes = problema && a.guia && !window.PAINEL_FILTRADO
    ? `<div class="acoes-alerta"><button class="btn sec pq" type="button" data-acao="guia">Como achar o problema</button>` +
      `<button class="btn sec pq" type="button" data-acao="resolver" data-chave="${esc(a.chave)}" data-titulo="${esc(a.titulo)}">Marcar como resolvido</button></div>${guiaHtml(a)}`
    : (problema && a.guia ? `<div class="acoes-alerta"><button class="btn sec pq" type="button" data-acao="guia">Como achar o problema</button></div>${guiaHtml(a)}` : '');
  const volta = rec && rec.versao !== _D().versao ? `<p class="reaparece">Marcado como resolvido por ${esc(rec.usuario)} em ${_quando(rec.quando)}, mas ainda aparece depois da atualização dos dados.</p>` : '';
  return `<li class="alerta n-${esc(a.nivel)}" data-chave="${esc(a.chave || '')}">${chip(a.nivel)}<div><span class="tit">${esc(a.titulo)}</span>` +
    (a.prioridade ? ` <span class="prio">Prioridade ${esc(a.prioridade)}</span>` : '') + `<p>${a.texto || ''}</p>${volta}${botoes}</div></li>`;
}
function _particionar(alertas) {
  const aguardando = [], ativos = [];
  (alertas || []).forEach(a => {
    const rec = a.chave && PEND.mapa[a.chave];
    if (rec && rec.versao === _D().versao && (a.nivel === 'critico' || a.nivel === 'atencao')) aguardando.push({ a, rec }); else ativos.push(a);
  });
  return { aguardando, ativos };
}
function _resolvidosHtml(aguardando, alertas) {
  const escopo = (window.PERIODO_CHAVE || '') + '|';
  const vivos = new Set((alertas || []).map(a => a.chave).filter(Boolean));
  const sumiram = PEND.lista.filter(r => String(r.chave).startsWith(escopo) && !vivos.has(r.chave) && Date.now() - new Date(r.quando).getTime() < 30 * 864e5);
  let html = '';
  if (aguardando.length) html += acordeao(`Resolvidos (aguardando atualização) (${aguardando.length})`, '<ul class="alertas">' + aguardando.map(({ a, rec }) =>
    `<li class="alerta n-ok"><div><span class="tit">${esc(a.titulo)}</span><p>Marcado por ${esc(rec.usuario)} em ${_quando(rec.quando)}. O alerta some quando os dados forem atualizados e o problema não aparecer mais.</p>` +
    (window.PAINEL_FILTRADO ? '' : `<div class="acoes-alerta"><button class="btn sec pq" type="button" data-acao="reabrir" data-chave="${esc(a.chave)}">Reabrir</button></div>`) + '</div></li>').join('') + '</ul>');
  if (sumiram.length) html += acordeao(`Resolvido: não aparece mais (${sumiram.length})`, '<ul class="alertas">' + sumiram.map(r =>
    `<li class="alerta n-ok"><div><span class="tit">${esc(r.titulo)}</span><p>Marcado por ${esc(r.usuario)} em ${_quando(r.quando)}; depois da atualização, o problema deixou de aparecer.</p></div></li>`).join('') + '</ul>');
  return html ? `<div class="resolvidos">${html}</div>` : '';
}
function alertasHtml(alertas) {
  if (!alertas || !alertas.length) return '<p class="vazio">Nada a apontar.</p>';
  return '<ul class="alertas">' + alertas.map(a => alertaLi(a)).join('') + '</ul>';
}
function alertasTopo(alertas, ym) {
  const { aguardando, ativos } = _particionar(alertas);
  const topo = ativos.slice(0, 3), resto = ativos.slice(3);
  let html = ativos.length ? '<ul class="alertas">' + topo.map(a => alertaLi(a)).join('') + '</ul>' : '<p class="vazio">Nada a apontar neste mês.</p>';
  if (resto.length) html += acordeao(`Mais ${resto.length} alerta(s)`, '<ul class="alertas">' + resto.map(a => alertaLi(a)).join('') + '</ul>', { dica: 'do mais urgente ao menos' });
  return html + _resolvidosHtml(aguardando, alertas);
}
document.addEventListener('click', ev => {
  const b = ev.target.closest && ev.target.closest('[data-acao]'); if (!b) return;
  const acao = b.getAttribute('data-acao');
  if (acao === 'guia') { const g = b.closest('li').querySelector('.guia'); if (g) { g.hidden = !g.hidden; b.textContent = g.hidden ? 'Como achar o problema' : 'Esconder o guia'; } return; }
  if (acao === 'resolver' || acao === 'reabrir') {
    b.disabled = true;
    _postar('/api/pendencias/' + acao, { painel: _D().menu, chave: b.getAttribute('data-chave'), titulo: b.getAttribute('data-titulo') || '', versao: _D().versao })
      .then(j => { if (j && j.erro) { b.disabled = false; mostrarAviso(j.erro, 'erro'); return; } return carregarPendencias().then(() => window.__render && window.__render(window.PERIODO_CHAVE)); });
  }
});

// ---------------------------------------------------------------- periodo De/ate
const chavesMeses = D => Object.keys(D.meses || {}).filter(k => !ehPeriodo(k)).sort();
function _mesMais(ym, n) { const t = +ym.slice(0, 4) * 12 + (+ym.slice(5, 7) - 1) + n; return `${String(Math.floor(t / 12)).padStart(4, '0')}-${String(t % 12 + 1).padStart(2, '0')}`; }
function anteriorDe(D, CHAVES, ym) {
  const m = D.meses[ym];
  if (m && m.periodo) return D.meses[m.chave_anterior] || null;
  return D.meses[_mesMais(ym, -1)] || null;
}
function mostrarAviso(txt, tipo) {
  const a = $('aviso'); if (!a) return;
  if (!txt) { a.hidden = true; return; }
  a.className = 'aviso' + (tipo ? ' ' + tipo : ''); a.textContent = txt; a.hidden = false;
}
function _linhaPeriodo(D, chave) {
  const [ini, fim] = chave.includes('..') ? chave.split('..') : [chave, chave];
  const hoje = D.hoje ? new Date(D.hoje + 'T12:00:00') : new Date();
  const ultimo = new Date(+fim.slice(0, 4), +fim.slice(5, 7), 0, 12);
  const f = d => d.toLocaleDateString('pt-BR');
  return `Período: de ${f(new Date(+ini.slice(0, 4), +ini.slice(5, 7) - 1, 1, 12))} a ${f(ultimo < hoje ? ultimo : hoje)}`;
}
const _LS_PERIODO = 'csi.periodo';
function iniciarPeriodo(D, render) {
  window.D = D; window.__render = render;
  const cs = chavesMeses(D);
  const selDe = $('mes');
  let selAte = $('mes-ate');
  if (!selAte) {
    const lab = document.createElement('label'); lab.className = 'mes-pick'; lab.innerHTML = 'até <select id="mes-ate"></select>';
    selDe.closest('label').after(lab); selAte = lab.querySelector('select');
  }
  const rotulo = k => (D.meses[k] && D.meses[k].rotulo) || k;
  const opcoes = [...cs].reverse().map(k => `<option value="${k}">${esc(rotulo(k))}</option>`).join('');
  selDe.innerHTML = opcoes; selAte.innerHTML = opcoes;
  const padrao = D.mes_padrao || cs[cs.length - 1];
  const [d0, a0] = String(padrao).includes('..') ? padrao.split('..') : [padrao, padrao];
  selDe.value = d0; selAte.value = a0;
  const url = new URL(location.href);
  const mostrar = chave => {
    window.PERIODO_CHAVE = chave;
    if (!$('periodo-linha')) { const p = document.createElement('div'); p.id = 'periodo-linha'; p.className = 'periodo-linha'; ($('sub').parentNode || document.body).appendChild(p); }
    $('periodo-linha').textContent = _linhaPeriodo(D, chave);
    const av = D.periodo && D.periodo.aviso;
    mostrarAviso(av || '', av ? '' : null);
    render(chave);
  };
  const guardar = (de, ate) => { try { localStorage.setItem(_LS_PERIODO, JSON.stringify({ de, ate })); } catch (e) { /* sem armazenamento */ } try { parent !== window && parent.postMessage({ tipo: 'periodo', de, ate }, location.origin); } catch (e) { /* fora de iframe */ } };
  const aplicar = () => {
    let de = selDe.value, ate = selAte.value;
    if (de > ate) { if (document.activeElement === selAte) de = ate; else ate = de; selDe.value = de; selAte.value = ate; }
    guardar(de, ate);
    const chave = de === ate ? de : `${de}..${ate}`;
    if (D.meses[chave]) { mostrar(chave); return; }
    url.searchParams.set('de', de); url.searchParams.set('ate', ate); location.assign(url.toString());   // periodo de varios meses: o servidor calcula
  };
  selDe.addEventListener('change', aplicar); selAte.addEventListener('change', aplicar);
  // o periodo escolhido vale para as outras abas: sem pedido no endereco, usa o ultimo escolhido neste navegador
  let inicial = padrao;
  if (!url.searchParams.get('de') && !url.searchParams.get('ate')) {
    try {
      const g = JSON.parse(localStorage.getItem(_LS_PERIODO) || 'null');
      if (g && g.de && g.ate) {
        const ch = g.de === g.ate ? g.de : `${g.de}..${g.ate}`;
        if (D.meses[ch]) inicial = ch;
        else if (g.de !== g.ate && !(D.periodo && D.periodo.pedido)) { url.searchParams.set('de', g.de); url.searchParams.set('ate', g.ate); location.replace(url.toString()); return; }
      }
    } catch (e) { /* preferencia ilegivel: usa o padrao */ }
  }
  const [i0, i1] = String(inicial).includes('..') ? inicial.split('..') : [inicial, inicial];
  selDe.value = i0; selAte.value = i1;
  carregarPendencias().finally(() => mostrar(inicial));
}

// ---------------------------------------------------------------- atualizacao
function iniciarAtualizacao(versao) {
  const btn = $('btn-atualizar'), txt = $('btn-texto');
  if (!btn) return;
  const menu = _D() && _D().menu;
  let ocupado = false, timer = null;
  const estado = () => fetch('/api/estado?menu=' + encodeURIComponent(menu), { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null);
  const parar = () => { ocupado = false; btn.disabled = false; btn.classList.remove('girando'); txt.textContent = 'Atualizar agora'; clearInterval(timer); timer = null; };
  const acompanhar = () => {
    clearInterval(timer);
    timer = setInterval(() => estado().then(e => {
      if (!e) return;
      if (e.atualizando) { txt.textContent = `Atualizando… (${e.atualizando.modulo || ''})`; return; }
      parar();
      if (e.versao && e.versao !== versao) location.reload();
    }), 3000);
  };
  btn.addEventListener('click', () => {
    if (ocupado) return;
    ocupado = true; btn.disabled = true; btn.classList.add('girando'); txt.textContent = 'Atualizando…';
    _postar('/api/atualizar', { menu }).then(j => {
      if (j.erro) { parar(); mostrarAviso(j.erro, 'erro'); return; }
      if (j.atualizou === false) { parar(); mostrarAviso(j.mensagem || 'Os dados já estão em dia.', 'ok'); return; }   // nada mudou: nao recarrega
      mostrarAviso(j.mensagem || 'Atualização iniciada.', 'ok'); acompanhar();
    });
  });
  // outra pessoa pode estar atualizando, ou a verificacao automatica pode ter trazido dados novos
  setInterval(() => { if (ocupado) return; estado().then(e => { if (!e) return; if (e.token_invalido) mostrarAviso('O Klingo recusou o token de acesso. Peça a um administrador para atualizá-lo.', 'erro'); if (e.versao && e.versao !== versao && !e.atualizando) location.reload(); }); }, 60000);
  estado().then(e => { if (e && e.atualizando) { ocupado = true; btn.disabled = true; btn.classList.add('girando'); txt.textContent = 'Atualizando…'; acompanhar(); } if (e && e.token_invalido) mostrarAviso('O Klingo recusou o token de acesso. Peça a um administrador para atualizá-lo.', 'erro'); });
}
