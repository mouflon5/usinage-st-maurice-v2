"use strict";
/* Intégration des processus (N2 → N5) dans la vue « Flux de valeur » : diagramme en icicle zoomable, lecture animée, réseau flux ↔ processus ↔ capacités. */
let vplayTimer = null;
const stopVPlay = () => { if (vplayTimer) { clearInterval(vplayTimer); vplayTimer = null; } };
function vsRerender() { const y = window.scrollY; rerender(); window.scrollTo(0, y); }

function vsTree(vs) {
  const all = [...PNODES.values()];
  const kids = vs.stages.map(st => all.find(n => n.lvl === 2 && n.stage === st.id) || { lvl: 2, id: "ph:" + st.id, name: st.name, stage: st.id, kids: [], placeholder: true });
  return { lvl: 1, id: "vsroot:" + vs.id, name: vs.name, vs: vs.id, kids, root: true };
}
function icicleSpans(root, metric, del) {
  const wcache = new Map();
  const w = (n) => {
    if (wcache.has(n)) return wcache.get(n);
    let v;
    if (n.lvl === 5) { const e = taskEff(n, del); v = metric === "n" ? 1 : metric === "min" ? Math.max(e.min, 4) : Math.max(e.wait, 0.4); }
    else if (n.placeholder) v = 0;
    else v = n.kids.reduce((a, k) => a + w(k), 0);
    wcache.set(n, v); return v;
  };
  const real = root.kids.filter(k => !k.placeholder).map(w), avg = real.length ? real.reduce((a, b) => a + b, 0) / real.length : 1;
  root.kids.forEach(k => { if (k.placeholder) wcache.set(k, avg * 0.4); });
  wcache.set(root, root.kids.reduce((a, k) => a + wcache.get(k), 0));
  const span = new Map();
  (function lay(n, a, b) {
    span.set(n, [a, b]);
    const tot = n.kids.reduce((x, k) => x + wcache.get(k), 0); let x = a;
    n.kids.forEach(k => { const e = x + ((b - a) * wcache.get(k)) / (tot || 1); lay(k, x, e); x = e; });
  })(root, 0, 1);
  return { span, w: (n) => wcache.get(n) };
}
function nodeStats(n, del) {
  const L = n.placeholder ? [] : leaves(n); let ok = 0, frag = 0, man = 0, imp = 0, min = 0, wait = 0;
  L.forEach(t => { const e = taskEff(t, del); min += e.min; wait += e.wait; const sy = effSys(t, del); if (!sy) man++; else if (APPS.find(a => a.id === sy).debt >= 4) frag++; else ok++; if (e.f < 1) imp++; });
  return { n: L.length, ok, frag, man, imp, min, wait };
}

function vsProcessBlocks(vs, d) {
  const S = state.sub, root = vsTree(vs), described = root.kids.filter(k => !k.placeholder);
  const out = [];
  if (!described.length) {
    out.push(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Du flux de valeur aux tâches"),
      h("p", { class: "muted" }, "Ce flux n'est pas encore décomposé en processus dans l'exemple. Trois flux le sont : « Acquérir une pièce usinée sur mesure », « Piloter la trésorerie » et « Traiter une réclamation »."),
      h("div", { class: "row" }, [["vs_acq", "Acquérir une pièce usinée sur mesure"], ["vs_dep", "Piloter la trésorerie"], ["vs_rec", "Traiter une réclamation"]].map(([k, l]) => h("button", { class: "btn primary", onclick: () => { stopVPlay(); S.vs = k; S.prog = undefined; S.stop = undefined; S.vfocus = null; S.vi = -1; vsRerender(); } }, "Voir : " + l)))));
    return out;
  }
  const metric = S.vmetric || "min", cmode = S.vcolor || "lvl", depth = S.vdepth || 4, after = S.vafter !== false;
  const del = after ? new Set(d.del.map(i => i.id)) : new Set();
  const { span } = icicleSpans(root, metric, del);
  const byId = new Map(); (function reg(n) { byId.set(n.id, n); n.kids.forEach(reg); })(root);
  const focus = byId.get(S.vfocus) || root;
  const chain = []; (function find(n, trail) { if (n === focus) { chain.push(...trail); return true; } return n.kids.some(k => find(k, trail.concat(n))); })(root, []);
  const maxLvl = Math.max(depth, Math.min(5, focus.lvl + 1));
  const W = 1000, rowH = 50, anc = chain.length, ancH = 22, pad = 4;
  const [fa, fb] = span.get(focus), proj = (v) => ((v - fa) / (fb - fa)) * W;

  /* lecture animée : jeton sur les tâches, dans l'ordre */
  const order = leaves(root.kids.filter(k => !k.placeholder).reduce((acc, k) => (acc.kids.push(k), acc), { lvl: 0, kids: [] }));
  const vi = S.vi === undefined ? -1 : S.vi, cur = vi >= 0 ? order[Math.min(vi, order.length - 1)] : null;
  const idxOf = new Map(order.map((t, i) => [t, i]));
  const lastIdx = (n) => Math.max(...leaves(n).map(t => idxOf.get(t)));
  const firstIdx = (n) => Math.min(...leaves(n).map(t => idxOf.get(t)));
  const stageDone = root.kids.map((k, i) => {
    if (vi < 0) return false;
    if (!k.placeholder) return vi >= lastIdx(k);
    const prev = i > 0 ? root.kids[i - 1] : null, next = root.kids.slice(i + 1).find(x => !x.placeholder);
    const prevDone = !prev || (prev.placeholder ? true : vi >= lastIdx(prev));
    return prevDone && (next ? vi >= firstIdx(next) : vi >= order.length - 1);
  });

  const showValue = focus.lvl <= 2;
  const visRows = maxLvl - focus.lvl + 1, H = anc * ancH + visRows * (rowH + pad) + (showValue ? 52 : 0) + 8;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", style: "background:var(--surface);border:1px solid var(--line);border-radius:10px" });
  svg.append(s("defs", {}, s("pattern", { id: "hatch", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, s("rect", { width: 8, height: 8, fill: "var(--bg)" }), s("line", { x1: 0, y1: 0, x2: 0, y2: 8, stroke: "var(--line)", "stroke-width": 3 }))));
  chain.forEach((n, i) => svg.append(s("g", { class: "node", onclick: () => { S.vfocus = n.root ? null : n.id; vsRerender(); } },
    s("rect", { x: 2, y: i * ancH, width: W - 4, height: ancH - 3, rx: 4, fill: LVL_COL[n.lvl], opacity: 0.35 }),
    s("text", { x: 10, y: i * ancH + 14, "font-size": 11, fill: "var(--ink)" }, `N${n.lvl} · ${nm(n)}  ↑ remonter`))));
  const prevStore = (state.live = state.live || {}).icl || new Map(), newStore = new Map(), anim = [];
  const visible = [];
  byId.forEach((n) => { if (n.lvl < focus.lvl || n.lvl > maxLvl) return; const [a, b] = span.get(n); if (b <= fa + 1e-9 || a >= fb - 1e-9) return; if (n.lvl === focus.lvl && n !== focus) return; visible.push(n); });
  visible.forEach(n => {
    const [a, b] = span.get(n), x0 = Math.max(0, proj(a)), x1 = Math.min(W, proj(b)), y = anc * ancH + (n.lvl - focus.lvl) * (rowH + pad), st = nodeStats(n, del);
    let fill, op = 0.9;
    if (n.placeholder) fill = "url(#hatch)";
    else if (cmode === "lvl") fill = LVL_COL[n.lvl];
    else if (cmode === "auto") { const sc = st.n ? (st.ok * 5 + st.frag * 2.2 + st.man * 1) / st.n : 3; fill = heat(sc); }
    else { fill = tcolor("init"); op = st.n ? 0.12 + 0.88 * (st.imp / st.n) : 0.1; }
    const isCur = cur && !n.placeholder && n.lvl >= 2 && (n === cur || (n.lvl < 5 && leaves(n).includes(cur)));
    const g = s("g", { class: "node", onclick: () => { if (n.placeholder) return; S.vfocus = n.root ? null : n.id; vsRerender(); } });
    const rect = s("rect", { x: x0 + 1, y, width: Math.max(1, x1 - x0 - 2), height: rowH, rx: 5, fill, opacity: op, stroke: isCur ? "var(--ink)" : "var(--surface)", "stroke-width": isCur ? 3 : 1, style: "transition:x .45s ease,width .45s ease,opacity .3s" });
    const pv = prevStore.get(n.id); if (pv) { rect.setAttribute("x", pv.x0 + 1); rect.setAttribute("width", Math.max(1, pv.x1 - pv.x0 - 2)); anim.push([rect, x0 + 1, Math.max(1, x1 - x0 - 2)]); }
    newStore.set(n.id, { x0, x1 });
    g.append(rect, s("title", {}, `${LVL_NAME[n.lvl]} — ${nm(n)}\n${n.placeholder ? "processus non décrits dans l'exemple" : `${st.n} tâches · ${hh(st.min)} de travail · ${fmt(st.wait / 24, 1)} j d'attente`}`));
    if (x1 - x0 > 56) {
      const dark = cmode === "init" ? op > 0.5 : cmode === "lvl";
      g.append(s("foreignObject", { x: x0 + 4, y: y + 2, width: x1 - x0 - 8, height: rowH - 4, style: "pointer-events:none" }, h("div", { style: { font: "600 10.5px/1.15 system-ui", color: n.placeholder ? "var(--muted)" : dark ? "#fff" : "#111", overflow: "hidden", height: (rowH - 6) + "px" } },
        h("span", { style: { opacity: 0.8 } }, "N" + n.lvl + " "), nm(n), n.placeholder ? h("div", { style: { fontWeight: 400 } }, "non décrit") : st.n && n.lvl < 5 ? h("div", { style: { fontWeight: 400, opacity: 0.85 } }, `${st.n} tâches · ${hh(st.min)}`) : null)));
    }
    svg.append(g);
  });
  state.live.icl = newStore;
  if (anim.length) setTimeout(() => anim.forEach(([r, x, w]) => { r.setAttribute("x", x); r.setAttribute("width", w); }), 30);

  /* ligne de valeur sous les étapes */
  if (showValue) {
    const yv = anc * ancH + visRows * (rowH + pad) + 4;
    root.kids.forEach((k, i) => {
      const [a, b] = span.get(k); if (b <= fa + 1e-9 || a >= fb - 1e-9) return; if (focus.lvl === 2 && k !== focus) return;
      const x0 = Math.max(0, proj(a)), x1 = Math.min(W, proj(b)), done = stageDone[i], it = vs.stages.find(st => st.id === k.stage).item;
      svg.append(s("rect", { x: x0 + 1, y: yv, width: Math.max(1, x1 - x0 - 2), height: 42, rx: 6, fill: done ? "var(--good)" : "var(--bg)", opacity: done ? 0.9 : 1, stroke: "var(--line)" }),
        x1 - x0 > 60 ? s("foreignObject", { x: x0 + 4, y: yv + 2, width: x1 - x0 - 8, height: 38, style: "pointer-events:none" }, h("div", { style: { font: "600 10.5px/1.15 system-ui", color: done ? "#fff" : "var(--muted)" } }, done ? "✔ valeur : " + it : "valeur : " + it)) : null);
    });
  }
  /* jeton */
  if (cur) {
    const sp = span.get(cur), cx = proj((sp[0] + sp[1]) / 2);
    if (sp[1] > fa && sp[0] < fb) svg.append(s("line", { x1: cx, y1: anc * ancH, x2: cx, y2: H - 4, stroke: "var(--accent)", "stroke-width": 2, "stroke-dasharray": "5 3" }), s("circle", { cx, cy: anc * ancH + 2, r: 6, fill: "var(--accent)" }));
  }

  /* commandes */
  const ctl = h("div", {},
    h("div", { class: "row" }, h("b", {}, "Largeur ="), seg([["min", "temps de travail"], ["wait", "attente"], ["n", "nombre de tâches"]], metric, (k) => { S.vmetric = k; vsRerender(); }),
      h("b", {}, "Couleur ="), seg([["lvl", "niveau"], ["auto", "automatisation"], ["init", "effet des initiatives"]], cmode, (k) => { S.vcolor = k; vsRerender(); })),
    h("div", { class: "row" }, h("b", {}, "Profondeur :"), seg([[2, "N2"], [3, "N3"], [4, "N4"], [5, "N5"]], depth, (k) => { S.vdepth = +k; vsRerender(); }),
      h("b", {}, "Données :"), seg([[false, "avant initiatives"], [true, "après initiatives livrées"]], after, (k) => { S.vafter = k; vsRerender(); }),
      focus !== root ? h("button", { class: "btn", onclick: () => { S.vfocus = null; vsRerender(); } }, "⤴ Vue d'ensemble") : null),
    h("div", { class: "row" }, h("button", { class: "btn primary", onclick: () => { stopVPlay(); S.vi = 0; vsRerender(); vplayTimer = setInterval(() => { S.vi = (S.vi || 0) + 1; vsRerender(); if (S.vi >= order.length - 1) stopVPlay(); }, 520); } }, "▶ Dérouler le flux tâche par tâche"),
      h("button", { class: "btn", onclick: () => { stopVPlay(); S.vi = -1; vsRerender(); } }, "↺ Effacer"),
      h("span", {}, "Position : ", h("input", { type: "range", min: -1, max: order.length - 1, value: vi, style: { width: "220px" }, onchange: (e) => { stopVPlay(); S.vi = +e.target.value; vsRerender(); } }))));

  /* tâche en cours */
  let info = h("div", { class: "muted small" }, "Lancez la lecture ou déplacez le curseur : un jeton parcourt les tâches dans l'ordre, et la valeur de chaque étape apparaît quand elle est terminée.");
  if (cur) {
    const upTo = order.slice(0, vi + 1).map(t => taskEff(t, del)), work = upTo.reduce((a, e) => a + e.min, 0), wait = upTo.reduce((a, e) => a + e.wait, 0), tot = order.map(t => taskEff(t, del)), tw = tot.reduce((a, e) => a + e.min, 0), tt = tot.reduce((a, e) => a + e.wait, 0);
    const trail = pathOf(cur);
    info = h("div", {}, h("div", { class: "row small muted" }, trail.slice(1).map(x => h("span", {}, lvlBadge(x.lvl), nm(x), " ›"))),
      h("div", { class: "row" }, h("b", {}, cur.name), chip(cur.role, { short: true }), effSys(cur, del) ? chip(effSys(cur, del), { short: true }) : h("span", { class: "warnc small" }, "tâche manuelle"), h("span", { class: "small" }, `${fmt(taskEff(cur, del).min, 0)} min` + (cur.wait ? ` · attente ${fmt(taskEff(cur, del).wait, 0)} h` : ""))),
      h("div", { class: "row" }, h("div", { class: "bar", style: { width: "260px" } }, h("i", { style: { width: (100 * (vi + 1) / order.length) + "%", background: "var(--accent)" } })),
        h("span", { class: "small" }, `tâche ${vi + 1} / ${order.length} · travail cumulé ${hh(work)} sur ${hh(tw)} · attente cumulée ${fmt(wait / 24, 1)} j sur ${fmt(tt / 24, 1)} j`)),
      h("div", { class: "small" }, h("b", {}, "Valeur livrée jusqu'ici : "), root.kids.filter((k, i) => stageDone[i]).map(k => h("span", { class: "chip" }, "✔ " + vs.stages.find(st => st.id === k.stage).item)), root.kids.every((k, i) => stageDone[i]) ? h("b", { class: "good" }, "  → proposition de valeur atteinte : " + vs.proposition) : null));
  }

  /* détail du nœud ciblé */
  const st = nodeStats(focus, del), detail = h("div", { class: "row small" }, lvlBadge(focus.lvl), h("b", {}, nm(focus)), `${st.n} tâches · ${hh(st.min)} de travail · ${fmt(st.wait / 24, 1)} j d'attente · ${st.man} manuelles · ${st.frag} sur outil fragile`,
    focus.lvl === 3 ? [" · réalise ", focus.caps.map(c => chip(c, { short: true }))] : null,
    !focus.root && !focus.placeholder ? h("button", { class: "btn", onclick: () => { Object.assign(state.proc, { pid: focus.pid, focus: focus.id, level: Math.min(5, focus.lvl + 1), sel: focus.id, sx: 0 }); goTab("process"); } }, "Ouvrir dans « Processus N1 → N5 » →") : null);

  out.push(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Du flux de valeur aux tâches : les processus N2 → N5 dans le flux"),
    h("p", { class: "small muted" }, "Chaque étape du flux se décompose en processus (N3), sous-processus (N4) et tâches (N5). La largeur d'une boîte reflète son poids ; cliquez une boîte pour zoomer dans sa décomposition, cliquez une barre du haut pour remonter."),
    ctl, svg,
    h("div", { class: "legend", style: { marginTop: "6px" } }, cmode === "auto" ? [legendHeat("Automatisation :"), h("span", {}, "1 = tâches manuelles · 5 = tâches sur système en place")] : cmode === "init" ? "Rose plus foncé = plus de tâches améliorées par les initiatives livrées (déplacez la date et les retards à l'onglet Initiatives)" : Object.keys(LVL_NAME).slice(1).map((n, i) => h("span", {}, h("span", { class: "swatch", style: { background: LVL_COL[i + 1] } }), `N${i + 1} ${LVL_NAME[i + 1]}`))),
    h("div", { style: { marginTop: "8px" } }, detail), h("div", { class: "kpi", style: { marginTop: "8px" } }, info),
    note("Le flux de valeur dit POURQUOI et POUR QUI (la valeur reçue) ; les processus disent COMMENT le travail est fait. Passer de l'un à l'autre se fait par les étapes (N2) et les capacités (N3), pas par un nouveau dessin : c'est ce que le guide appelle l'alignement avec la modélisation des processus. ", src("2.4 et 3.4 Business Architecture and Business Process Modeling and Management"))));

  /* réseau flux ↔ étapes ↔ processus ↔ capacités ↔ initiatives */
  const allowed = new Set(["vs", "stage", "proc", "cap", "init"]), skip = new Set(Object.keys(TYPES).filter(t => !allowed.has(t)));
  const dist = bfs([vs.id], 3, skip), ids = [...dist.keys()], set = new Set(ids);
  const nodes = ids.map(id => { const n = NODES.get(id), k = dist.get(id); return { id, label: shortName(n.name).slice(0, 24), title: `${TYPES[n.type].label} : ${n.name}`, color: tcolor(n.type), r: n.type === "vs" ? 13 : n.type === "stage" ? 9 : 6.5, big: n.type === "vs" || n.type === "stage" || n.type === "proc", x: 500 + Math.cos(k * 2 + ids.indexOf(id)) * 130 * k, y: 260 + Math.sin(k * 2 + ids.indexOf(id)) * 95 * k }; });
  const links = EDGES.filter(e => set.has(e.a) && set.has(e.b)).map(e => ({ a: e.a, b: e.b, label: e.rel }));
  const lg = liveGraph({ key: "vsn", width: 1000, height: 520, maxHeight: "62vh", store: (state.live["vsn" + vs.id] = state.live["vsn" + vs.id] || new Map()), selected: state.sel, nodes, links, labels: ids.length <= 55 ? "always" : "hover", linkLabels: "hover", charge: 3400, linkLen: 80, onClick: select });
  out.push(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Réseau : flux → étapes → processus → capacités → initiatives"),
    liveControls(lg.api, { charge: 3400, len: 80 }), lg.svg, h("div", { class: "src" }, LIVE_HELP)));
  return out;
}
