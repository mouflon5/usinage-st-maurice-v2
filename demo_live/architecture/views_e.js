"use strict";
/* ============ Processus d'affaires N1 → N5 (3.4) ============ */
const LVL_COL = ["", "#0d9488", "#3b82c4", "#7aa91a", "#d99a00", "#c2410c"];
const LVL_NAME = ["", "Flux de valeur", "Étape du flux", "Processus", "Sous-processus", "Tâche"];
state.proc = { pid: "pr1", focus: "pr1", level: 3, open: new Set(), sel: null, sx: 0 };
PROCS.forEach(p => { state.proc.open.add(p.id); p.kids.forEach(k => state.proc.open.add(k.id)); });

const taskEff = (t, del) => { let f = 1; Object.entries(t.init).forEach(([i, g]) => { if (del.has(i)) f *= 1 - g; }); return { min: t.min * f, wait: t.wait * f, f }; };
const effSys = (t, del) => { for (const [i, a] of Object.entries(t.sys2 || {})) if (del.has(i)) return a; return t.sys; };
function roll(node, del) {
  const L = leaves(node); const r = { n: L.length, min0: 0, min1: 0, w0: 0, w1: 0, manual: 0, fragile: 0, improved: 0, byRole: {} };
  L.forEach(t => {
    const e = taskEff(t, del); r.min0 += t.min; r.min1 += e.min; r.w0 += t.wait; r.w1 += e.wait;
    const sy = effSys(t, del); if (!sy) r.manual++; else if (APPS.find(a => a.id === sy).debt >= 4) r.fragile++;
    if (e.f < 1) r.improved++;
    const br = (r.byRole[t.role] = r.byRole[t.role] || { a: 0, b: 0 }); br.a += t.min; br.b += e.min;
  });
  return r;
}
const hh = (m) => fmt(m / 60, 1) + " h";
function procRerender() { const c = document.getElementById("swim"); if (c) state.proc.sx = c.scrollLeft; const y = window.scrollY; rerender(); window.scrollTo(0, y); }
const lvlBadge = (l) => h("span", { class: "tag", style: { background: LVL_COL[l], marginRight: "6px" } }, "N" + l);
const pcrumb = (n) => pathOf(n).map(x => h("span", { class: "chip", onclick: () => { state.proc.focus = x.id; state.proc.level = Math.min(5, x.lvl + 1); state.proc.sel = x.id; procRerender(); } }, lvlBadge(x.lvl), x.name || x.name1));
const nm = (n) => n.name || n.name1;

registerView("process", "Processus N1 → N5", processView, "value");
function processView(el) {
  const P = state.proc; const proc = PNODES.get(P.pid);
  let focus = PNODES.get(P.focus) || proc; if (focus.pid !== P.pid) focus = proc;
  P.level = clamp(P.level, Math.min(focus.lvl + 1, 5), 5);
  const del = new Set(derive().del.map(i => i.id));
  el.append(...section("Processus d'affaires détaillés, du flux de valeur (N1) à la tâche (N5)",
    "Un flux de valeur se décompose en étapes (N2), chaque étape en processus (N3) qui réalisent des capacités, puis en sous-processus (N4) et en tâches (N5). Choisissez un exemple, descendez de niveau en cliquant, et observez les gains quand les initiatives de la feuille de route sont livrées."));
  el.append(h("div", { class: "row" }, seg(PROCS.map(p => [p.id, p.name]), P.pid, (k) => { P.pid = k; P.focus = k; P.level = 3; P.sel = null; P.sx = 0; procRerender(); })));
  el.append(h("div", { class: "card" }, h("div", { class: "row" }, h("b", {}, "Position : "), pcrumb(focus)),
    h("div", { class: "row" }, h("b", {}, "Niveau affiché :"), seg([2, 3, 4, 5].map(l => [l, `N${l} · ${LVL_NAME[l]}`]).filter(([l]) => l >= focus.lvl + 1 || l === 5), P.level, (k) => { P.level = +k; procRerender(); }),
      h("span", { class: "muted small" }, "Cliquez un élément pour descendre dans sa décomposition.")),
    bandAt(focus, P.level, del)));

  /* cumuls */
  const r = roll(focus, del), pct = (x) => fmt((100 * x) / Math.max(1, r.n), 0) + " %";
  const kp = (lab, v, sub) => h("div", { class: "kpi" }, h("div", { class: "small muted" }, lab), h("div", { class: "v" }, v), sub ? h("div", { class: "small muted" }, sub) : null);
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, `Cumul pour « ${nm(focus)} » (${LVL_NAME[focus.lvl].toLowerCase()})`),
    h("div", { class: "row" },
      kp("Tâches (N5)", r.n), kp("Temps de travail", r.min0 === r.min1 ? hh(r.min0) : `${hh(r.min0)} → ${hh(r.min1)}`, r.min0 !== r.min1 ? `−${fmt(100 * (1 - r.min1 / r.min0), 0)} %` : "aucune initiative livrée"),
      kp("Attente", r.w0 === r.w1 ? fmt(r.w0 / 24, 1) + " j" : `${fmt(r.w0 / 24, 1)} → ${fmt(r.w1 / 24, 1)} j`),
      kp("Tâches sans système (manuelles)", pct(r.manual), `${r.manual} sur ${r.n}`), kp("Tâches sur outil fragile (Excel, papier)", pct(r.fragile), `${r.fragile} sur ${r.n}`), kp("Tâches améliorées", `${r.improved}`, "par les initiatives livrées")),
    h("h3", {}, "Temps de travail par rôle (barre foncée = après initiatives)"),
    ...Object.entries(r.byRole).sort((a, b) => b[1].a - a[1].a).map(([role, v]) => {
      const mx = Math.max(...Object.values(r.byRole).map(x => x.a));
      return h("div", { class: "row", style: { margin: "2px 0" } }, h("div", { style: { width: "250px" } }, chip(role, { short: true })),
        h("div", { style: { width: "300px", position: "relative", height: "12px", background: "var(--line)", borderRadius: "6px", overflow: "hidden" } },
          h("i", { style: { position: "absolute", inset: "0 auto 0 0", width: (100 * v.a / mx) + "%", background: "#d03b3b55" } }), h("i", { style: { position: "absolute", inset: "0 auto 0 0", width: (100 * v.b / mx) + "%", background: "var(--accent)" } })),
        h("span", { class: "small" }, v.a === v.b ? hh(v.a) : `${hh(v.a)} → ${hh(v.b)}`));
    }),
    note(h("b", {}, "Deux lectures du même processus : "), "ce qui est fait (capacités, N3) et comment c'est fait (tâches, N5). Le temps d'attente, souvent plus grand que le temps de travail, est ce que Lean Six Sigma cible ; ici il baisse seulement quand une initiative l'automatise.")));

  /* couloirs */
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Diagramme de couloirs (N5) — qui fait quoi, avec quel système"),
    h("div", { class: "legend" }, h("span", {}, "bordure verte = système en place"), h("span", {}, "rouge = outil fragile (Excel, papier)"), h("span", {}, "pointillé = tâche manuelle"), h("span", {}, "losange = décision"), h("span", {}, "⏳ = attente"), h("span", {}, "pastille rose = initiative qui l'améliore (pleine si livrée)")),
    swimlane(focus, del)));

  /* arbre + détail */
  const tree = h("div", { style: { fontSize: ".88rem" } });
  const walk = (n, depth) => {
    const open = P.open.has(n.id), has = n.kids.length > 0, rr = roll(n, del);
    tree.append(h("div", { class: "row", style: { margin: "1px 0", marginLeft: depth * 18 + "px", background: P.sel === n.id ? "color-mix(in srgb,var(--accent) 14%,transparent)" : "", borderRadius: "6px", padding: "1px 4px", cursor: "pointer", flexWrap: "nowrap" },
      onclick: () => { P.sel = n.id; P.focus = n.id; P.level = Math.min(5, n.lvl + 1); procRerender(); } },
      h("span", { style: { width: "16px", color: "var(--muted)" }, onclick: (e) => { e.stopPropagation(); if (!has) return; open ? P.open.delete(n.id) : P.open.add(n.id); procRerender(); } }, has ? (open ? "▾" : "▸") : "•"),
      lvlBadge(n.lvl), h("span", {}, nm(n)), h("span", { class: "muted small", style: { marginLeft: "auto", whiteSpace: "nowrap" } }, n.lvl === 5 ? `${fmt(n.min, 0)} min` + (n.wait ? ` + ${n.wait} h d'attente` : "") : `${rr.n} tâches · ${hh(rr.min0)}`)));
    if (has && open) n.kids.forEach(k => walk(k, depth + 1));
  };
  walk(proc, 0);
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Hiérarchie complète"),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: () => { PNODES.forEach(n => { if (n.pid === P.pid && n.kids.length) P.open.add(n.id); }); procRerender(); } }, "Tout déplier"),
        h("button", { class: "btn", onclick: () => { PNODES.forEach(n => { if (n.pid === P.pid) P.open.delete(n.id); }); P.open.add(P.pid); procRerender(); } }, "Replier")), tree),
    detailCard(P.sel ? PNODES.get(P.sel) : null, del)));

  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Comment les niveaux se rattachent à l'architecture d'affaires"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Niveau", "Quoi", "Lien avec les cartographies"].map(t => h("th", {}, t)))),
      h("tbody", {}, [[1, "Flux de valeur", "Valeur obtenue par la partie prenante déclencheuse (2.4)"], [2, "Étape du flux", "Une étape = un élément de valeur livré ; habilitée par des capacités"], [3, "Processus", "Réalise des capacités : le « comment » de ce que la carte des capacités décrit comme le « quoi » (3.4)"],
        [4, "Sous-processus", "Regroupement d'activités ; unité de gestion et de mesure"], [5, "Tâche", "Un rôle, un système, un temps ; c'est là que les applications (6.4) et les initiatives (2.6) agissent"]].map(([l, a, b]) => h("tr", {}, h("td", {}, lvlBadge(l)), h("td", {}, a), h("td", {}, b))))),
    note("Les capacités sont stables, les processus changent souvent : une même capacité peut être réalisée par plusieurs processus, et un processus peut en solliciter plusieurs. Regardez les capacités reliées aux N3 dans l'onglet Graphe (type « Processus »). ", src("3.4 Business Architecture and Business Process Modeling and Management"))));
}

function bandAt(focus, level, del) {
  const nodes = []; (function go(n) { n.kids.forEach(k => { if (k.lvl === level) nodes.push(k); else if (k.lvl < level) go(k); }); })(focus);
  if (focus.lvl >= level) nodes.push(focus);
  const groups = []; nodes.forEach(n => { const g = groups.find(x => x.p === n.parent); g ? g.items.push(n) : groups.push({ p: n.parent, items: [n] }); });
  return h("div", { style: { overflowX: "auto" } }, h("div", { class: "row", style: { alignItems: "flex-start", flexWrap: "nowrap" } }, groups.map(g =>
    h("div", { style: { border: "1px dashed var(--line)", borderRadius: "10px", padding: "6px 6px 2px", flex: "none" } },
      g.p && g.p !== focus ? h("div", { class: "small muted", style: { margin: "0 4px 4px" } }, h("b", {}, "N" + g.p.lvl + " : "), nm(g.p)) : null,
      h("div", { class: "stages" }, g.items.map(n => {
        const r = roll(n, del);
        return h("div", { class: "stage", style: { borderTopColor: LVL_COL[n.lvl], flex: "0 0 190px" }, title: "Cliquez pour descendre", onclick: () => { state.proc.focus = n.id; state.proc.level = Math.min(5, n.lvl + 1); state.proc.sel = n.id; procRerender(); } },
          h("div", { class: "n" }, lvlBadge(n.lvl), n.lvl === 5 ? (BUMAP.get(n.role) || {}).name.split(" (")[0] : `${r.n} tâches`),
          h("b", {}, nm(n)), h("div", { class: "small muted" }, n.lvl === 5 ? `${fmt(n.min, 0)} min` : hh(r.min0) + (r.min1 < r.min0 ? " → " + hh(r.min1) : "")));
      }))))));
}

function swimlane(focus, del) {
  const T = leaves(focus), roles = [...new Set(T.map(t => t.role))];
  const bw = 156, bh = 54, gap = 34, left = 150, lh = 76, W = left + T.length * (bw + gap) + 10, H = roles.length * lh + 14;
  const svg = s("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: "display:block" });
  svg.append(s("defs", {}, s("marker", { id: "sw", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 6, markerHeight: 6, orient: "auto" }, s("path", { d: "M0,0 L8,4 L0,8 z", fill: "var(--muted)" }))));
  roles.forEach((r, i) => svg.append(s("rect", { x: 0, y: i * lh, width: W, height: lh - 4, fill: i % 2 ? "var(--surface)" : "var(--bg)", stroke: "var(--line)" }),
    s("foreignObject", { x: 6, y: i * lh + 10, width: left - 12, height: lh - 20 }, h("div", { style: { font: "600 11.5px/1.2 system-ui", color: "var(--ink)" } }, (BUMAP.get(r) || {}).name || r))));
  const pos = T.map((t, i) => ({ t, x: left + i * (bw + gap), y: roles.indexOf(t.role) * lh + (lh - 4 - bh) / 2 }));
  pos.forEach((p, i) => { if (i === 0) return; const a = pos[i - 1], x1 = a.x + bw, y1 = a.y + bh / 2, x2 = p.x, y2 = p.y + bh / 2, xm = x1 + gap / 2;
    svg.append(s("path", { d: y1 === y2 ? `M${x1},${y1} L${x2},${y2}` : `M${x1},${y1} L${xm},${y1} L${xm},${y2} L${x2},${y2}`, fill: "none", stroke: "var(--muted)", "stroke-width": 1.4, "marker-end": "url(#sw)" })); });
  pos.forEach(({ t, x, y }) => {
    const e = taskEff(t, del), sy = effSys(t, del), app = sy ? APPS.find(a => a.id === sy) : null, col = !app ? "var(--muted)" : app.debt >= 4 ? "var(--bad)" : "var(--good)";
    const sel = state.proc.sel === t.id, g = s("g", { class: "node", onclick: () => { state.proc.sel = t.id; procRerender(); } });
    g.append(t.dec ? s("polygon", { points: `${x + bw / 2},${y - 4} ${x + bw},${y + bh / 2} ${x + bw / 2},${y + bh + 4} ${x},${y + bh / 2}`, fill: "var(--surface)", stroke: col, "stroke-width": sel ? 3 : 1.6 })
      : s("rect", { x, y, width: bw, height: bh, rx: 8, fill: "var(--surface)", stroke: col, "stroke-width": sel ? 3 : 1.6, "stroke-dasharray": app ? null : "4 3" }));
    g.append(s("foreignObject", { x: x + (t.dec ? 24 : 4), y: y + 1, width: bw - (t.dec ? 48 : 8), height: bh - 14, style: "pointer-events:none" }, h("div", { style: { font: "500 10.5px/1.15 system-ui", color: "var(--ink)", overflow: "hidden", height: (bh - 16) + "px", textAlign: t.dec ? "center" : "left" } }, t.name)));
    g.append(s("text", { x: x + bw / 2, y: y + bh - 4, "text-anchor": "middle", "font-size": 9.5, fill: e.f < 1 ? "var(--good)" : "var(--muted)", style: "pointer-events:none" },
      (e.f < 1 ? `${fmt(t.min, 0)}→${fmt(e.min, 0)} min` : `${fmt(t.min, 0)} min`) + (t.wait ? `  ⏳${fmt(e.wait, 0)} h` : "")));
    Object.keys(t.init).slice(0, 3).forEach((iid, k) => { const done = del.has(iid), ini = INITMAP.get(iid);
      g.append(s("rect", { x: x + 4 + k * 40, y: y - 9, width: 38, height: 13, rx: 6, fill: done ? tcolor("init") : "var(--surface)", stroke: tcolor("init") }),
        s("text", { x: x + 23 + k * 40, y: y + 1, "text-anchor": "middle", "font-size": 8.5, fill: done ? "#fff" : tcolor("init"), style: "pointer-events:none" }, ini.short)); });
    svg.append(g);
  });
  const box = h("div", { id: "swim", style: { overflowX: "auto", paddingTop: "6px" } }, svg);
  setTimeout(() => { box.scrollLeft = state.proc.sx || 0; }, 0);
  return box;
}

function detailCard(n, del) {
  if (!n) return h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Détail"), h("p", { class: "muted" }, "Cliquez une ligne de la hiérarchie ou une tâche du diagramme."));
  const c = h("div", { class: "card" }, lvlBadge(n.lvl), h("span", { class: "muted small" }, LVL_NAME[n.lvl]), h("h3", { style: { margin: ".3rem 0" } }, nm(n)));
  c.append(h("div", { class: "row small muted" }, h("b", {}, "Chemin : "), pathOf(n).map(x => lvlBadge(x.lvl))));
  if (n.lvl === 1) c.append(h("div", {}, "Flux de valeur : ", chip(n.vs)));
  if (n.lvl === 2) c.append(h("div", {}, "Étape : ", chip(n.stage), h("div", { class: "small muted" }, "Valeur livrée : " + STAGEMAP.get(n.stage).item)));
  if (n.lvl === 3) c.append(h("div", {}, "Réalise les capacités : ", n.caps.map(x => chip(x, { short: true }))), h("div", { style: { marginTop: "4px" } }, chip(n.gid, { short: true })));
  if (n.lvl === 5) {
    const e = taskEff(n, del), sy = effSys(n, del), app = sy ? APPS.find(a => a.id === sy) : null;
    c.append(h("div", { class: "row small" }, h("b", {}, "Rôle : "), chip(n.role, { short: true })),
      h("div", { class: "row small" }, h("b", {}, "Système : "), app ? [chip(app.id, { short: true }), h("span", { class: app.debt >= 4 ? "bad" : "good" }, `dette ${app.debt}/5`), sy !== n.sys ? h("span", { class: "small muted" }, "  (relais pris par une initiative livrée)") : null] : h("span", { class: "warnc" }, "aucun : tâche manuelle")),
      h("div", { class: "row small" }, h("b", {}, "Temps : "), e.f < 1 ? `${fmt(n.min, 0)} → ${fmt(e.min, 0)} min` : `${fmt(n.min, 0)} min`, n.wait ? ` · attente ${fmt(n.wait, 0)} → ${fmt(e.wait, 0)} h` : ""),
      n.pol ? h("div", { class: "row small" }, h("b", {}, "Politique ou contrôle : "), chip(n.pol, { short: true })) : null,
      n.dec ? h("div", { class: "small" }, "Point de décision : alimente le routage (voir « Routage dynamique », onglet Pratique).") : null,
      Object.keys(n.init).length ? h("div", { class: "small" }, h("b", {}, "Initiatives qui l'améliorent : "), Object.entries(n.init).map(([i, g]) => h("span", {}, chip(i, { short: true }), h("span", { class: del.has(i) ? "good" : "muted" }, ` −${fmt(g * 100, 0)} % ${del.has(i) ? "(livrée)" : "(à venir)"}  `)))) : h("div", { class: "small muted" }, "Aucune initiative ne touche cette tâche."));
  } else {
    const r = roll(n, del); c.append(h("div", { class: "small", style: { marginTop: "6px" } }, `${r.n} tâches · ${hh(r.min0)} de travail${r.min1 < r.min0 ? " → " + hh(r.min1) : ""} · ${r.manual} manuelles · ${r.fragile} sur outil fragile`));
    const inits = [...new Set(leaves(n).flatMap(t => Object.keys(t.init)))];
    if (inits.length) c.append(h("div", { class: "small", style: { marginTop: "4px" } }, h("b", {}, "Initiatives concernées : "), inits.map(i => chip(i, { short: true }))));
  }
  return c;
}

/* ============ Initiatives et feuille de route avec dépendances (2.6) ============ */
let initPlay = null;
const TASKS_BY_INIT = {}; PNODES.forEach(n => { if (n.lvl === 5) Object.keys(n.init).forEach(i => (TASKS_BY_INIT[i] = TASKS_BY_INIT[i] || []).push(n)); });
const programEnd = (sc, sel) => Math.max(...INITS.filter(i => sel.has(i.id)).map(i => sc[i.id].end), 0);
function slackOf(id) {
  const sel = state.sim.selected, base = programEnd(schedule(state.sim.delay, sel), sel);
  for (let k = 1; k <= 8; k++) { const d2 = Object.assign({}, state.sim.delay, { [id]: (state.sim.delay[id] || 0) + k }); if (programEnd(schedule(d2, sel), sel) > base) return k - 1; }
  return 8;
}
function implicitDeps() {
  const modOf = (i) => new Set(Object.keys(i.caps).flatMap(c => (CAP_INFO[c] || {}).M || [])), useOf = (i) => new Set(Object.keys(i.caps).flatMap(c => [...((CAP_INFO[c] || {}).M || []), ...((CAP_INFO[c] || {}).U || [])]));
  const out = [];
  for (let a = 0; a < INITS.length; a++) for (let b = a + 1; b < INITS.length; b++) {
    const A = INITS[a], B = INITS[b], sh = Object.keys(A.caps).filter(c => B.caps[c]);
    if (sh.length) { out.push({ a: A.id, b: B.id, label: "capacité partagée : " + sh.map(c => CAPMAP.get(c).name).join(", ") }); continue; }
    const ia = [...modOf(A)].filter(x => useOf(B).has(x)), ib = [...modOf(B)].filter(x => useOf(A).has(x)), both = [...new Set([...ia, ...ib])];
    if (both.length) out.push({ a: A.id, b: B.id, label: "donnée partagée : " + both.map(x => NODES.get(x).name).join(", ") });
  }
  return out;
}

registerView("initiatives", "Initiatives et feuille de route", initiativesView, "info");
function initiativesView(el) {
  const S = state.sim, d = derive(), sc = currentSchedule(), sel = S.selected;
  el.append(...section("Initiatives et feuille de route (section 2.6)",
    "Une initiative impacte des capacités et des flux pour atteindre des objectifs, mais elle ne vit pas seule : certaines doivent finir avant d'autres, partagent des capacités ou des données. Retardez une initiative et voyez le retard se propager, jusqu'aux objectifs manqués."));
  el.append(h("div", { class: "card" }, h("div", { class: "row" }, h("b", {}, "Initiatives retenues :"),
    ...INITS.map(i => h("label", { class: "chip" + (sel.has(i.id) ? " on" : ""), style: { cursor: "pointer" } }, h("input", { type: "checkbox", checked: sel.has(i.id), onchange: (e) => { e.target.checked ? sel.add(i.id) : sel.delete(i.id); rerender(); } }), ` ${i.short} (${fmt(i.cost)} M$)`))),
    h("div", { class: "row" }, h("b", {}, "Retards simulés (en trimestres) :"),
      ...INITS.map(i => h("span", { class: "small" }, i.short + " ", h("select", { onchange: (e) => { S.delay[i.id] = +e.target.value; rerender(); } }, [0, 1, 2, 3, 4].map(k => h("option", { value: k, selected: (S.delay[i.id] || 0) === k }, k ? "+" + k + " T" : "0")))))),
    h("div", { class: "row" }, h("b", {}, "Date : "), h("input", { type: "range", min: QTR_FROM, max: QTR_TO, value: S.cursor, style: { width: "300px" }, onchange: (e) => { S.cursor = +e.target.value; rerender(); } }), h("b", {}, qLabel(S.cursor)),
      h("button", { class: "btn primary", onclick: () => { if (initPlay) { clearInterval(initPlay); initPlay = null; return; } S.cursor = QTR_FROM; rerender(); initPlay = setInterval(() => { S.cursor++; rerender(); if (S.cursor >= QTR_TO) { clearInterval(initPlay); initPlay = null; } }, 700); } }, "▶ Dérouler le temps"),
      h("button", { class: "btn", onclick: () => { INITS.forEach(i => sel.add(i.id)); S.cursor = QTR_TO; S.delay = {}; rerender(); } }, "↺ Réinitialiser"),
      h("button", { class: "btn", onclick: () => { sel.clear(); rerender(); } }, "Aucune")),
    h("div", { class: "small muted" }, `Coût retenu : ${fmt(INITS.filter(i => sel.has(i.id)).reduce((a, i) => a + i.cost, 0))} M$ · livrées à cette date : ${d.del.length} · fin du programme : ${qLabel(programEnd(sc, sel))}`)));

  /* feuille de route */
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Feuille de route et dépendances"), roadmapSvg(sc, S, d),
    h("div", { class: "legend" }, h("span", {}, h("b", {}, "FS "), "fin → début"), h("span", {}, h("b", {}, "FF "), "fin → fin"), h("span", {}, h("b", {}, "SS "), "début → début"), h("span", { style: { color: "var(--bad)" } }, "flèche rouge = contrainte serrée (aucune marge)"), h("span", {}, "contour pointillé = date prévue avant retard"))));

  /* objectifs et échéances */
  const grid = h("div", { class: "cols" });
  OBJS.forEach(o => {
    const v = d.kpi[o.kpi], met = objMet(o, v), prog = objProgress(o, d), due = qIndex(o.due), ok = objAtDue(o);
    grid.append(h("div", { class: "kpi", style: { cursor: "pointer", borderColor: ok ? "var(--line)" : "var(--bad)" }, onclick: () => select(o.id) }, h("div", { class: "small muted" }, o.name),
      h("div", { class: "v" }, fmt(v, o.unit === "jours" ? 0 : 1) + " " + o.unit, " ", h("span", { class: met ? "good" : "muted", style: { fontSize: ".8rem" } }, met ? "✔ atteint" : `cible ${o.dir === "max" ? "≤" : "≥"} ${o.target}`)),
      h("div", { class: "bar", style: { marginTop: "4px" } }, h("i", { style: { width: prog * 100 + "%", background: met ? "var(--good)" : "var(--accent)" } })),
      h("div", { class: "small " + (ok ? "good" : "bad") }, `Échéance ${o.due} : ` + (ok ? "respectée ✔" : "manquée ✖ "), !ok && sel.size ? h("span", { class: "muted" }, ` (atteinte plus tard ou jamais)`) : null)));
  });
  el.append(h("h3", {}, "Objectifs : atteints à l'échéance ?"), grid);

  /* tableau */
  const rows = INITS.map(i => {
    const up = DEPS.filter(x => x.to === i.id), down = DEPS.filter(x => x.from === i.id), r = sc[i.id], on = sel.has(i.id);
    return { i, up, down, r, on, slack: on ? slackOf(i.id) : null, tasks: TASKS_BY_INIT[i.id] || [] };
  });
  const tb = h("tbody", {});
  rows.forEach(({ i, up, down, r, on, slack, tasks }) => tb.append(h("tr", { style: { opacity: on ? 1 : 0.45 } },
    h("td", {}, chip(i.id, { short: true })), h("td", {}, `${i.start} → ${i.end}`), h("td", { class: r.end !== r.b1 || r.start !== r.b0 ? "bad" : "" }, `${qLabel(r.start)} → ${qLabel(r.end)}`, r.cause ? h("div", { class: "small muted" }, "poussée par ", chip(r.cause, { short: true })) : null),
    h("td", {}, on ? (slack === 0 ? h("b", { class: "bad" }, "0 · critique") : slack >= 8 ? "≥ 8 T" : slack + " T") : "—"),
    h("td", {}, up.length ? up.map(x => h("span", { title: x.why }, chip(x.from, { short: true }), h("span", { class: "tag", style: { background: "#666" } }, x.t), " ")) : "—"),
    h("td", {}, down.length ? down.map(x => h("span", { title: x.why }, chip(x.to, { short: true }), h("span", { class: "tag", style: { background: "#666" } }, x.t), " ")) : "—"),
    h("td", {}, tasks.length ? `${tasks.length} tâches` : "—"))));
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Marges, dépendances et tâches touchées"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Initiative", "Prévu", "Effectif", "Marge avant de retarder le programme", "Dépend de (amont)", "Débloque (aval)", "Processus touchés (N5)"].map(t => h("th", {}, t)))), tb),
    h("h3", {}, "Pourquoi ces dépendances ?"), h("ul", { class: "tight" }, DEPS.map(x => h("li", {}, chip(x.from, { short: true }), " → ", chip(x.to, { short: true }), h("span", { class: "tag", style: { background: "#666", margin: "0 6px" } }, x.t), x.why))),
    note("Marge = nombre de trimestres dont on peut retarder l'initiative sans reculer la fin du programme. Une marge de 0 la place sur le chemin critique : tout retard se répercute. Les initiatives sont aussi reliées aux tâches qu'elles améliorent (onglet Processus N1 → N5)."),
    src("2.6 Initiative Mapping et partie 4, scénario 1 : coordonner les initiatives pour éviter fragmentation et redondance")));

  /* graphe de dépendances */
  const impl = !!state.sub.impl, imp = impl ? implicitDeps() : [];
  const nodes = INITS.map(i => ({ id: i.id, label: i.short, title: `${i.name} — ${fmt(i.cost)} M$`, color: tcolor("init"), r: 8 + i.cost * 2.8, big: true, opacity: sel.has(i.id) ? 1 : 0.4 }));
  const links = DEPS.map(x => ({ a: x.from, b: x.to, label: `${x.t} — ${x.why}`, width: 2.4, color: "var(--accent)", len: 120 })).concat(imp.map(x => ({ a: x.a, b: x.b, label: x.label, width: 1.2, dash: "5 4", len: 160 })));
  state.live = state.live || {};
  const lg = liveGraph({ key: "dep", width: 1000, height: 420, maxHeight: "50vh", store: (state.live.dep = state.live.dep || new Map()), viewStore: (state.live.depV = state.live.depV || { k: 1, x: 0, y: 0 }), selected: state.sel,
    nodes, links, labels: "always", linkLabels: "hover", arrows: true, charge: 5200, linkLen: 130, onClick: select });
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Réseau des dépendances entre initiatives"),
    h("div", { class: "row" }, h("label", { class: "small" }, h("input", { type: "checkbox", checked: impl, onchange: (e) => { state.sub.impl = e.target.checked; rerender(); } }), " montrer aussi les liens implicites (capacités et données partagées, en pointillés)")),
    liveControls(lg.api, { charge: 5200, len: 130 }), lg.svg, h("div", { class: "src" }, "Flèche pleine = dépendance de calendrier ; pointillé = lien implicite à coordonner. La taille d'un nœud suit le coût. " + LIVE_HELP)));

  /* chevauchements */
  const byCap = {}; INITS.filter(i => sel.has(i.id)).forEach(i => Object.keys(i.caps).forEach(c => (byCap[c] = byCap[c] || []).push(i.id)));
  const over = Object.entries(byCap).filter(([, v]) => v.length > 1), orphan = CAPS.filter(c => c.imp >= 5 && !byCap[c.id] && d.effTar[c.id] < 4);
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Chevauchements d'initiatives"), over.length ? h("div", {}, over.map(([c, ids]) => h("div", { class: "row" }, chip(c, { short: true }), "←", ids.map(i => chip(i, { short: true }))))) : "Aucun chevauchement dans la sélection.",
      note("Plusieurs initiatives sur une même capacité ne sont pas forcément mauvaises, mais le scénario 1 du guide recommande de les coordonner.")),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Capacités critiques sans initiative"), orphan.length ? h("div", {}, orphan.map(c => chip(c.id, { short: true }))) : "Toutes les capacités critiques (importance 5) ont une initiative ou une efficacité ≥ 4.",
      h("p", { class: "small muted" }, "Importance stratégique 5 et efficacité cible < 4 : lacune de couverture."))));
}

function roadmapSvg(sc, S, d) {
  const nQ = QTR_TO - QTR_FROM + 1, W = 1000, left = 215, cw = (W - left - 10) / nQ, rh = 36, H = 44 + INITS.length * rh + 8, sel = S.selected;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  svg.append(s("defs", {}, s("marker", { id: "rmg", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 6, markerHeight: 6, orient: "auto" }, s("path", { d: "M0,0 L8,4 L0,8 z", fill: "var(--muted)" })),
    s("marker", { id: "rmr", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 6, markerHeight: 6, orient: "auto" }, s("path", { d: "M0,0 L8,4 L0,8 z", fill: "#d03b3b" }))));
  const xs = (q) => left + (q - QTR_FROM) * cw, yOf = (k) => 34 + k * rh;
  for (let q = 0; q < nQ; q++) {
    const lab = qLabel(QTR_FROM + q);
    svg.append(s("line", { x1: left + q * cw, y1: 26, x2: left + q * cw, y2: H, stroke: "var(--line)", "stroke-width": lab.endsWith("T1") ? 1 : 0.4 }));
    svg.append(s("text", { x: left + q * cw + cw / 2, y: 38 - 12, "text-anchor": "middle", "font-size": 9, fill: "var(--muted)" }, lab.endsWith("T1") || q === 0 ? lab.slice(0, 4) : ""));
    svg.append(s("text", { x: left + q * cw + cw / 2, y: 28, "text-anchor": "middle", "font-size": 8.5, fill: "var(--muted)" }, "T" + lab.slice(-1)));
  }
  const rowOf = new Map(INITS.map((i, k) => [i.id, k]));
  INITS.forEach((i, k) => {
    const r = sc[i.id], on = sel.has(i.id), y = yOf(k), done = on && r.end <= S.cursor, run = on && r.start <= S.cursor && r.end > S.cursor, late = r.end !== r.b1 || r.start !== r.b0;
    svg.append(s("g", { class: "node", onclick: () => select(i.id) },
      s("text", { x: 6, y: y + 15, "font-size": 12, fill: on ? "var(--ink)" : "var(--muted)" }, `${i.short} — ${shortName(i.name).slice(0, 24)}`),
      late ? s("rect", { x: xs(r.b0), y, width: (r.b1 - r.b0 + 1) * cw, height: 22, rx: 5, fill: "none", stroke: tcolor("init"), "stroke-dasharray": "4 3", opacity: on ? 0.8 : 0.2 }) : null,
      s("rect", { x: xs(r.start), y, width: (r.end - r.start + 1) * cw, height: 22, rx: 5, fill: tcolor("init"), opacity: on ? (done ? 1 : run ? 0.65 : 0.35) : 0.1 }),
      on && late ? s("text", { x: xs(r.end + 1) + 4, y: y + 15, "font-size": 10, fill: "var(--bad)" }, r.cause ? `décalée par ${INITMAP.get(r.cause).short}` : `retard +${r.shift} T`) : null));
  });
  DEPS.forEach(dp => {
    if (!sel.has(dp.from) || !sel.has(dp.to)) return;
    const A = sc[dp.from], B = sc[dp.to], ya = yOf(rowOf.get(dp.from)) + 11, yb = yOf(rowOf.get(dp.to)) + 11;
    let d0, tight;
    if (dp.t === "FS") { const x1 = xs(A.end + 1), x2 = xs(B.start); tight = B.start === A.end + 1; d0 = `M${x1},${ya} C${x1 + 24},${ya} ${x2 - 24},${yb} ${x2},${yb}`; }
    else if (dp.t === "FF") { const x1 = xs(A.end + 1), x2 = xs(B.end + 1); tight = B.end === A.end + 1; const xm = Math.max(x1, x2) + 16; d0 = `M${x1},${ya} L${xm},${ya} L${xm},${yb} L${x2},${yb}`; }
    else { const x1 = xs(A.start), x2 = xs(B.start); tight = B.start === A.start; const xm = Math.min(x1, x2) - 10; d0 = `M${x1},${ya} L${xm},${ya} L${xm},${yb} L${x2},${yb}`; }
    svg.append(s("path", { d: d0, fill: "none", stroke: tight ? "#d03b3b" : "var(--muted)", "stroke-width": tight ? 2 : 1.2, "marker-end": tight ? "url(#rmr)" : "url(#rmg)", opacity: 0.9 }, s("title", {}, `${dp.t} : ${dp.why}`)));
  });
  const cx = xs(S.cursor) + cw / 2;
  svg.append(s("line", { x1: cx, y1: 24, x2: cx, y2: H - 2, stroke: "var(--accent)", "stroke-width": 2 }));
  return svg;
}
