"use strict";
/* ---------- Utilitaires DOM ---------- */
const SVGNS = "http://www.w3.org/2000/svg";
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  return el;
}
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.appendChild(typeof k === "object" ? k : document.createTextNode(String(k)));
  }
}
const $ = (sel, root) => (root || document).querySelector(sel);
const fmt = (n, d = 1) => (Math.round(n * 10 ** d) / 10 ** d).toString().replace(".", ",");
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/* ---------- Modèle dérivé ---------- */
const CAPMAP = new Map(CAPS.map(c => [c.id, c]));
const VSMAP = new Map(VSS.map(v => [v.id, v]));
const INITMAP = new Map(INITS.map(i => [i.id, i]));
const OBJMAP = new Map(OBJS.map(o => [o.id, o]));
const STAGEMAP = new Map(); VSS.forEach(v => v.stages.forEach(st => STAGEMAP.set(st.id, st)));
const BUMAP = new Map(BUS.concat(BU_TREE).map(b => [b.id, b]));

const ADJ = new Map();
EDGES.forEach(e => {
  if (!ADJ.has(e.a)) ADJ.set(e.a, []);
  if (!ADJ.has(e.b)) ADJ.set(e.b, []);
  ADJ.get(e.a).push({ id: e.b, rel: e.rel, out: true });
  ADJ.get(e.b).push({ id: e.a, rel: e.rel, out: false });
});
const nbrs = (id) => ADJ.get(id) || [];

function bfs(seeds, depth, skipTypes) {
  const dist = new Map(); const q = [];
  seeds.forEach(sd => { if (NODES.has(sd)) { dist.set(sd, 0); q.push(sd); } });
  while (q.length) {
    const cur = q.shift(); const d = dist.get(cur);
    if (d >= depth) continue;
    for (const n of nbrs(cur)) {
      if (dist.has(n.id)) continue;
      if (skipTypes && skipTypes.has(NODES.get(n.id).type)) continue;
      dist.set(n.id, d + 1); q.push(n.id);
    }
  }
  return dist;
}

/* ---------- État global et simulation ---------- */
const state = {
  tab: "overview", sel: null,
  sim: { selected: new Set(INITS.map(i => i.id)), cursor: QTR_TO, delay: {} },
  capMode: "eff", sub: {},
};
/* Calendrier effectif : retards saisis + propagation des dépendances entre initiatives (FS, FF, SS). */
function schedule(delays, only) {
  const res = {};
  INITS.forEach(i => { const dl = (delays && delays[i.id]) || 0; res[i.id] = { start: qIndex(i.start) + dl, end: qIndex(i.end) + dl, b0: qIndex(i.start), b1: qIndex(i.end), cause: null, shift: dl }; });
  for (let pass = 0; pass < 14; pass++) {
    let changed = false;
    DEPS.forEach(dp => {
      if (only && (!only.has(dp.from) || !only.has(dp.to))) return;
      const A = res[dp.from], B = res[dp.to];
      if (dp.t === "FS") { const need = A.end + 1; if (B.start < need) { const sh = need - B.start; B.start += sh; B.end += sh; B.cause = dp.from; changed = true; } }
      else if (dp.t === "SS") { if (B.start < A.start) { const sh = A.start - B.start; B.start += sh; B.end += sh; B.cause = dp.from; changed = true; } }
      else if (dp.t === "FF") { const need = A.end + 1; if (B.end < need) { B.end = need; B.cause = dp.from; changed = true; } }
    });
    if (!changed) break;
  }
  return res;
}
const currentSchedule = () => schedule(state.sim.delay, state.sim.selected);
function delivered(cursor) {
  const sc = currentSchedule(), c = cursor === undefined ? state.sim.cursor : cursor;
  return INITS.filter(i => state.sim.selected.has(i.id) && sc[i.id].end <= c);
}
function objAtDue(o) { return objMet(o, derive(qIndex(o.due)).kpi[o.kpi]); }
function derive(cursor) {
  const del = delivered(cursor);
  const effCur = {}, effTar = {};
  CAPS.forEach(c => {
    const vals = Object.values(c.inst);
    effCur[c.id] = vals.reduce((a, b) => a + b, 0) / vals.length;
    let gain = 0; del.forEach(i => { gain += i.caps[c.id] || 0; });
    effTar[c.id] = clamp(effCur[c.id] + gain, 1, 5);
  });
  const acq = VSMAP.get("vs_acq");
  const waits = {}; acq.stages.forEach(st => { waits[st.id] = st.wait; });
  del.forEach(i => Object.entries(i.wait || {}).forEach(([k, v]) => { waits[k] = Math.max(0, waits[k] + v); }));
  const touch = acq.stages.reduce((a, st) => a + st.touch, 0);
  const waitSum = Object.values(waits).reduce((a, b) => a + b, 0);
  const waitBase = acq.stages.reduce((a, st) => a + st.wait, 0);
  const kpi = {};
  Object.keys(KPIS).forEach(k => {
    if (k === "k_delai") { kpi[k] = touch + waitSum; return; }
    let v = KPIS[k].base; del.forEach(i => { v += (i.kpi && i.kpi[k]) || 0; });
    kpi[k] = Math.round(v * 100) / 100;
  });
  return { del, effCur, effTar, waits, touch, waitSum, waitBase, kpi, kpiBase: Object.assign({}, ...Object.keys(KPIS).map(k => ({ [k]: k === "k_delai" ? touch + waitBase : KPIS[k].base }))) };
}
function objMet(o, v) { return o.dir === "max" ? v <= o.target + 1e-9 : v >= o.target - 1e-9; }
function objProgress(o, d) {
  const base = d.kpiBase[o.kpi], cur = d.kpi[o.kpi];
  const total = Math.abs(o.target - base); if (total < 1e-9) return 1;
  return clamp(Math.abs(cur - base) / total, 0, 1);
}

/* ---------- Couleurs ---------- */
const HEAT = ["#d03b3b", "#ee8a3a", "#f2cc4a", "#a8cf5a", "#3aa65a"];
function heat(v) { // v entre 1 et 5, interpolé
  const x = clamp(v, 1, 5) - 1, i = Math.min(3, Math.floor(x)), t = x - i;
  const a = HEAT[i], b = HEAT[i + 1];
  const mix = (p, q) => Math.round(parseInt(a.substr(p, 2), 16) * (1 - t) + parseInt(b.substr(p, 2), 16) * t);
  return `rgb(${mix(1, 3)},${mix(3, 5)},${mix(5, 7)})`;
}
const tcolor = (t) => TYPES[t].color;

/* ---------- Éléments communs ---------- */
function typeTag(t) { return h("span", { class: "tag", style: { background: tcolor(t) } }, TYPES[t].label); }
function chip(id, opts) {
  const n = NODES.get(id); if (!n) return null;
  return h("span", { class: "chip" + (state.sel === id ? " on" : ""), title: TYPES[n.type].label, onclick: (e) => { e.stopPropagation(); select(id); } },
    h("i", { style: { background: tcolor(n.type) } }), (opts && opts.short) ? shortName(n.name) : n.name);
}
const shortName = (nm) => nm.length > 34 ? nm.slice(0, 32) + "…" : nm;
function seg(options, current, onPick) {
  return h("div", { class: "seg" }, options.map(([k, label]) => h("button", { "aria-pressed": String(k === current), onclick: () => onPick(k) }, label)));
}
function legendHeat(label) {
  return h("div", { class: "legend" }, label, [1, 2, 3, 4, 5].map(v => h("span", {}, h("span", { class: "swatch", style: { background: heat(v) } }), v)));
}
function note(...kids) { return h("div", { class: "note" }, kids); }
function src(txt) { return h("div", { class: "src" }, "Réf. BIZBOK v11 — ", txt); }
function section(title, lead, ...rest) { return [h("h2", {}, title), lead ? h("p", { class: "lead" }, lead) : null, ...rest]; }

/* ---------- Panneau d'impact (base de connaissances 5.1) ---------- */
function select(id) { state.sel = id; const y = window.scrollY; rerender(); window.scrollTo(0, y); }
function renderPanel() {
  const p = $("#panel"); p.innerHTML = "";
  const d = derive();
  if (!state.sel) {
    p.append(h("h3", { style: { marginTop: 0 } }, "Analyse d'impact"),
      h("p", { class: "muted" }, "Cliquez sur une capacité, un flux, une initiative, une politique… pour voir toutes ses relations (le métamodèle du guide en action)."),
      h("div", { class: "small" }, h("b", {}, "Simulation active : "), `${state.sim.selected.size} initiative(s), jusqu'à ${qLabel(state.sim.cursor)}. `, "Réglez-la dans l'onglet Initiatives."),
      h("div", { class: "small", style: { marginTop: "6px" } }, `Livrées : ${d.del.length} · Délai demande→livraison : ${d.kpi.k_delai} j`));
    return;
  }
  const n = NODES.get(state.sel);
  p.append(h("div", {}, typeTag(n.type)), h("h3", { style: { margin: ".3rem 0" } }, n.name),
    h("button", { class: "btn small", onclick: () => select(null) }, "Fermer"));
  if (n.type === "cap") {
    const c = CAPMAP.get(n.id);
    p.append(h("div", { class: "small muted", style: { marginTop: "6px" } }, `${CAP_L1[c.l1]} › niveau 2 · importance ${c.imp}/5 · efficacité ${fmt(d.effCur[c.id])} → ${fmt(d.effTar[c.id])}`));
  }
  if (n.type === "obj") {
    const o = OBJMAP.get(n.id);
    p.append(h("div", { class: "small muted", style: { marginTop: "6px" } }, `${KPIS[o.kpi].name} : ${fmt(d.kpi[o.kpi], 2)} ${o.unit} (cible ${o.dir === "max" ? "≤" : "≥"} ${o.target})`));
  }
  if (n.type === "init") {
    const i = INITMAP.get(n.id);
    p.append(h("div", { class: "small muted", style: { marginTop: "6px" } }, `${i.start} → ${i.end} · ${fmt(i.cost)} M$`));
  }
  const groups = {};
  nbrs(n.id).forEach(e => { const t = NODES.get(e.id).type; (groups[t] = groups[t] || []).push(e); });
  Object.keys(TYPES).forEach(t => {
    if (!groups[t]) return;
    p.append(h("div", { class: "small", style: { marginTop: "8px", fontWeight: 600 } }, TYPES[t].label + "s (" + groups[t].length + ")"),
      h("div", {}, groups[t].map(e => h("span", { title: e.out ? n.name + " " + e.rel : NODES.get(e.id).name + " " + e.rel + " → " + n.name }, chip(e.id, { short: true })))));
  });
  const dist = bfs([n.id], 2);
  const counts = {}; dist.forEach((dd, id) => { if (dd > 0) { const t = NODES.get(id).type; counts[t] = (counts[t] || 0) + 1; } });
  p.append(h("div", { class: "small muted", style: { marginTop: "10px" } }, "Portée à 2 sauts : " + (Object.entries(counts).map(([t, c]) => `${c} ${TYPES[t].label.toLowerCase()}`).join(", ") || "aucune")));
  p.append(h("button", { class: "btn small", style: { marginTop: "8px" }, onclick: () => { state.graphFocus = n.id; goTab("graph"); } }, "Voir dans le graphe →"));
}

/* ---------- Onglets ---------- */
const VIEWS = [];
function registerView(id, label, render, after) {
  const v = { id, label, render }, k = after ? VIEWS.findIndex(x => x.id === after) : -1;
  if (k >= 0) VIEWS.splice(k + 1, 0, v); else VIEWS.push(v);
}
function goTab(id) { state.tab = id; try { history.replaceState(null, "", "#" + id); } catch (e) { /* file:// */ } buildNav(); rerender(); window.scrollTo({ top: 0 }); }
function buildNav() {
  const nav = $("#nav"); nav.innerHTML = "";
  VIEWS.forEach((v, i) => nav.append(h("button", { role: "tab", "aria-selected": String(v.id === state.tab), onclick: () => goTab(v.id) }, `${i + 1} · ${v.label.replace(/^\d+ · /, "")}`)));
}
function rerender() {
  const v = VIEWS.find(x => x.id === state.tab) || VIEWS[0];
  const main = $("#main"); main.innerHTML = "";
  try { v.render(main); } catch (err) { main.append(h("pre", { class: "bad" }, String(err.stack || err))); console.error(err); }
  renderPanel();
}
function boot() {
  const th = (() => { try { return localStorage.getItem("hz-theme") || "auto"; } catch (e) { return "auto"; } })();
  function applyTheme(t) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
    document.querySelectorAll("#themeSeg button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.th === t)));
    try { localStorage.setItem("hz-theme", t); } catch (e) { /* ignore */ }
  }
  document.querySelectorAll("#themeSeg button").forEach(b => b.addEventListener("click", () => { applyTheme(b.dataset.th); rerender(); }));
  applyTheme(th);
  const hash = (location.hash || "").slice(1);
  if (VIEWS.some(v => v.id === hash)) state.tab = hash;
  buildNav(); rerender();
}
