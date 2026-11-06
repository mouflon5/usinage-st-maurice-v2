"use strict";
/* ============ 1. Vue d'ensemble : domaines et métamodèle (parties 1 et 5.1) ============ */
registerView("overview", "1 · Vue d'ensemble", (el) => {
  const dsel = state.sub.domain || "d_cap";
  el.append(...section("Les domaines de l'architecture d'affaires",
    "Une architecture d'affaires représente des vues d'affaires holistiques : capacités, flux de valeur, information et structure organisationnelle (les quatre domaines noyau, relativement stables), reliées aux stratégies, produits, politiques, initiatives et parties prenantes (domaines étendus, plus changeants). Cliquez sur un domaine."));
  const W = 760, H = 520, cx = W / 2, cy = H / 2;
  const core = DOMAINS.filter(d => d.core), ext = DOMAINS.filter(d => !d.core);
  const pos = {};
  core.forEach((d, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / core.length + Math.PI / 4; pos[d.id] = [cx + 105 * Math.cos(a), cy + 105 * Math.sin(a)]; });
  ext.forEach((d, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / ext.length; pos[d.id] = [cx + 215 * Math.cos(a), cy + 195 * Math.sin(a)]; });
  state.live = state.live || {};
  const live = liveGraph({ key: "ov", width: W, height: H, maxHeight: "560px", store: (state.live.ov = state.live.ov || new Map()), viewStore: (state.live.ovV = state.live.ovV || { k: 1, x: 0, y: 0 }),
    selected: dsel, arrows: true, linkLabels: "hover", charge: 4200, linkLen: 150, homeK: 0.035,
    background: (g) => g.append(s("ellipse", { cx, cy, rx: 150, ry: 150, fill: "none", stroke: "var(--line)", "stroke-dasharray": "5 5" }), s("text", { x: cx, y: cy + 4, "text-anchor": "middle", fill: "var(--muted)", "font-size": 12 }, "noyau")),
    nodes: DOMAINS.map(d => ({ id: d.id, label: d.name, title: d.def, color: tcolor(d.t), w: 96, h: 44, x: pos[d.id][0], y: pos[d.id][1], hx: pos[d.id][0], hy: pos[d.id][1] })),
    links: META_EDGES.map(([a, b, v]) => ({ a, b, label: v, width: 1.4 })),
    onClick: (id) => { state.sub.domain = id; rerender(); } });
  const svg = live.svg;
  const dom = DOMAINS.find(d => d.id === dsel);
  const inst = [...NODES.values()].filter(n => n.type === dom.t);
  const rels = META_EDGES.filter(([a, b]) => a === dsel || b === dsel).map(([a, b, v]) => a === dsel
    ? `${dom.name} ${v} ${DOMAINS.find(x => x.id === b).name.toLowerCase()}` : `${DOMAINS.find(x => x.id === a).name} ${v} ${dom.name.toLowerCase()}`);
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, liveControls(live.api, { charge: 4200, len: 150 }), svg, h("div", { class: "small muted" }, LIVE_HELP), h("div", { class: "src" }, "Figure inspirée de la fig. 1.1 (domaines) et de la fig. 5.1.2 (métamodèle), BIZBOK v11, parties 1 et 5.1.")),
    h("div", {},
      h("div", { class: "card" }, h("div", {}, typeTag(dom.t), " ", dom.core ? h("span", { class: "tag", style: { background: "#555" } }, "domaine noyau") : h("span", { class: "tag", style: { background: "#888" } }, "domaine étendu")),
        h("h3", {}, dom.name), h("p", {}, dom.def), h("p", { class: "small" }, h("b", {}, "Exemple chez " + COMPANY.court + " : "), dom.ex),
        h("h3", {}, `Instances dans le cas (${inst.length})`), h("div", {}, inst.slice(0, 18).map(n => chip(n.id, { short: true })), inst.length > 18 ? h("span", { class: "muted small" }, ` … +${inst.length - 18}`) : null)),
      h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Relations du métamodèle"), h("ul", { class: "tight" }, rels.map(r => h("li", {}, r)))))));
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "À quoi ça sert ? Répondre aux questions de base"),
    h("div", { class: "cols" },
      ...[["Qui ?", "Parties prenantes, unités d'affaires"], ["Quoi ?", "Capacités, produits, information"], ["Où ?", "Organisation, sites, partenaires"], ["Quand ?", "Flux de valeur, initiatives"], ["Pourquoi ?", "Stratégies, objectifs, politiques"], ["Comment ?", "Capacités en action : flux, processus, applications"]]
        .map(([q, a]) => h("div", {}, h("b", {}, q), " ", a))),
    note("Un plan sans architecture d'affaires, c'est des décisions prises avec une vue partielle. Ici, tout est dans un seul graphe de connaissances : essayez l'onglet ", h("b", {}, "Graphe"), " ou changez d'onglet — la sélection reste dans le panneau de droite."),
    src("partie 1, « What is Business Architecture? »")));
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Offre, réseau et bureaux de " + COMPANY.court),
    h("div", { class: "cols" },
      h("div", {}, h("b", {}, "Produits et services"), h("ul", { class: "tight" }, COMPANY.offre.map(([k, v]) => h("li", {}, h("b", {}, k + " : "), v)))),
      h("div", {}, h("b", {}, "Sites"), h("ul", { class: "tight" }, COMPANY.sites.map(([k, v]) => h("li", {}, h("b", {}, k), " — " + v))))),
    note("Cas fictif inspiré de la distribution d'énergie au Québec : les produits, marques, sites et noms de contreparties sont illustratifs.")));
});

/* ============ 2. Stratégie (2.1) ============ */
registerView("strategy", "2 · Stratégie", (el) => {
  const d = derive();
  el.append(...section("Cartographie de la stratégie (section 2.1)",
    "La stratégie se traduit en objectifs mesurables et en lignes de conduite. Une carte stratégique de style Norton-Kaplan montre les liens de cause à effet entre les perspectives ; l'architecture d'affaires relie ensuite chaque objectif aux flux de valeur et aux capacités visés."));
  const W = 900, rowH = 112, H = rowH * 4 + 10;
  const place = {};
  PERSP.forEach((_, pi) => {
    const here = OBJS.filter(o => o.persp === pi);
    here.forEach((o, k) => { place[o.id] = [(W / (here.length + 1)) * (k + 1), pi * rowH + 64]; });
  });
  state.live = state.live || {};
  const live = liveGraph({ key: "st", width: W, height: H, maxHeight: "560px", store: (state.live.st = state.live.st || new Map()), viewStore: (state.live.stV = state.live.stV || { k: 1, x: 0, y: 0 }),
    selected: state.sel, arrows: true, linkLabels: "hover", charge: 2400, linkLen: 130, homeK: 0.09, gravity: 0,
    background: (g) => PERSP.forEach((p, i) => g.append(s("rect", { x: 0, y: i * rowH + 4, width: W, height: rowH - 6, rx: 8, fill: i % 2 ? "var(--surface)" : "var(--bg)", stroke: "var(--line)" }),
      s("text", { x: 10, y: i * rowH + 22, "font-size": 12, fill: "var(--muted)", "font-weight": 600 }, p))),
    nodes: OBJS.map(o => ({ id: o.id, label: o.name, title: o.name, color: tcolor("obj"), w: 236, h: 56, x: place[o.id][0], y: place[o.id][1], hx: place[o.id][0], hy: place[o.id][1] })),
    links: OBJ_CAUSE.map(([a, b]) => ({ a, b, label: "cause \u2192 effet", width: 1.4, color: "var(--muted)" })),
    renderNode: (n, g) => {
      const o = OBJMAP.get(n.id), prog = objProgress(o, d), met = objMet(o, d.kpi[o.kpi]);
      g.append(s("rect", { x: -118, y: -28, width: 236, height: 56, rx: 9, fill: "var(--surface)", stroke: tcolor("obj"), "stroke-width": 1.6 }),
        s("foreignObject", { x: -114, y: -26, width: 228, height: 40, style: "pointer-events:none" }, h("div", { style: { font: "600 11px/1.2 system-ui", color: "var(--ink)", overflow: "hidden", height: "36px" } }, o.name)),
        s("rect", { x: -108, y: 16, width: 216, height: 6, rx: 3, fill: "var(--line)" }),
        s("rect", { x: -108, y: 16, width: 216 * prog, height: 6, rx: 3, fill: met ? "var(--good)" : "var(--accent)" }));
    },
    onClick: select });
  const svg = live.svg;
  el.append(h("div", { class: "card" }, liveControls(live.api, { charge: 2400, len: 130 }), svg, h("div", { class: "legend" }, "Barre = progression vers la cible selon la simulation des initiatives (onglet Initiatives). Les flèches vont de la cause vers l'effet. " + LIVE_HELP)));

  el.append(h("h3", {}, "Stratégies (lignes de conduite) et leur portée"));
  const tbl = h("table", {}, h("thead", {}, h("tr", {}, ["Stratégie", "Atteint les objectifs", "Impacte les flux de valeur", "Impacte les capacités"].map(t => h("th", {}, t)))));
  const tb = h("tbody", {});
  STRATS.forEach(st => tb.append(h("tr", {}, h("td", {}, chip(st.id)), h("td", {}, st.objs.map(o => chip(o))), h("td", {}, st.vs.map(v => chip(v))), h("td", {}, st.caps.map(c => chip(c, { short: true }))))));
  tbl.append(tb); el.append(h("div", { class: "card" }, tbl));

  const pick = state.sub.obj || "o1";
  const sel = h("select", { onchange: (e) => { state.sub.obj = e.target.value; rerender(); } }, OBJS.map(o => h("option", { value: o.id, selected: o.id === pick }, o.name)));
  const dist = bfs([pick], 4, new Set(["bu", "info", "pol", "app", "ent", "prod", "stk", "init", "obj"]));
  const chain = { strat: [], vs: [], stage: [], cap: [] };
  dist.forEach((dd, id) => { const t = NODES.get(id).type; if (chain[t]) chain[t].push(id); });
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Analyse d'impact : de l'objectif aux capacités"),
    h("div", { class: "row" }, "Objectif :", sel),
    h("div", { class: "cols" },
      ...[["strat", "Stratégies qui l'atteignent"], ["vs", "Flux de valeur ciblés"], ["cap", "Capacités à renforcer"]].map(([t, lbl]) =>
        h("div", {}, h("b", {}, lbl, ` (${chain[t].length})`), h("div", {}, chain[t].map(id => chip(id, { short: true })))))),
    note(h("b", {}, "Pourquoi par les flux de valeur ? "), "Une stratégie vise d'abord la valeur livrée aux parties prenantes ; les flux et leurs capacités habilitantes révèlent ensuite quoi changer, sans parler tout de suite de structure organisationnelle."),
    src("2.1 « Using Business Architecture for Strategy Justification and Interpretation » et principes de la cartographie stratégique")));
});

/* ============ 3. Capacités (2.2) ============ */
registerView("capabilities", "3 · Capacités", (el) => {
  const d = derive();
  const mode = state.capMode;
  el.append(...section("Carte des capacités (section 2.2)",
    "Une capacité dit CE QUE l'entreprise fait (jamais où, pourquoi ou comment). La carte est stable : on la colore selon l'efficacité, l'importance stratégique ou l'écart pour en faire une carte thermique (heat map)."));
  el.append(h("div", { class: "row" }, seg([["eff", "Efficacité actuelle"], ["imp", "Importance stratégique"], ["gap", "Écart à combler"], ["tar", "Cible (initiatives)"]], mode, (k) => { state.capMode = k; rerender(); }),
    mode === "gap" ? h("span", { class: "legend" }, "rouge = grand écart entre importance et efficacité cible") : legendHeat("échelle :")));
  const valOf = (c) => mode === "eff" ? d.effCur[c.id] : mode === "imp" ? c.imp : mode === "tar" ? d.effTar[c.id] : 5 - clamp(c.imp - d.effTar[c.id], 0, 4);
  const related = new Set();
  if (state.sel) { const nodeT = NODES.get(state.sel).type; if (nodeT === "cap") related.add(state.sel); else bfs([state.sel], 2).forEach((_, id) => { if (NODES.get(id).type === "cap") related.add(id); }); }
  const grid = h("div", { class: "capgrid" });
  Object.keys(CAP_L1).forEach(k => {
    const box = h("div", { class: "l1" }, h("h4", {}, CAP_L1[k]));
    CAPS.filter(c => c.l1 === k).forEach(c => {
      const v = valOf(c); const dim = state.sel && related.size && !related.has(c.id);
      const ninst = Object.keys(c.inst).length;
      box.append(h("button", { class: "l2" + (dim ? " dim" : "") + (state.sel === c.id ? " sel" : ""), style: { background: heat(v) }, title: `Importance ${c.imp} · efficacité ${fmt(d.effCur[c.id])} → ${fmt(d.effTar[c.id])} · ${ninst} instance(s)`, onclick: () => { select(c.id); } },
        c.name, h("b", {}, fmt(v, 1))));
    });
    grid.append(box);
  });
  el.append(grid);

  /* Instances et comportement */
  const selCap = state.sel && NODES.get(state.sel).type === "cap" ? CAPMAP.get(state.sel) : CAPMAP.get("c_qua_nc");
  const vals = Object.values(selCap.inst);
  const div = Math.max(...vals) - Math.min(...vals);
  el.append(h("div", { class: "card", style: { marginTop: "12px" } }, h("h3", { style: { marginTop: 0 } }, `Instances de « ${selCap.name} » (cliquez une autre capacité)`),
    ...Object.entries(selCap.inst).map(([b, v]) => h("div", { class: "row", style: { margin: "3px 0" } }, h("div", { style: { width: "260px" } }, chip(b, { short: true })),
      h("div", { class: "bar", style: { width: "180px" } }, h("i", { style: { width: v * 20 + "%", background: heat(v) } })), h("b", {}, v + " / 5"))),
    note(h("b", {}, "Instance de capacité : "), "réalisation précise d'une capacité dans une unité d'affaires. ",
      Object.keys(selCap.inst).length > 1 ? (div >= 2 ? h("span", { class: "bad" }, `Comportement divergent (écart de ${div} points) : à traiter en priorité, surtout si le résultat doit être identique d'une unité à l'autre.`) : "Comportements proches : fragmentation limitée.") : "Une seule instance : pas de fragmentation à craindre.")));

  /* Testeur de principes */
  const inp = h("input", { type: "text", value: state.sub.capName || "Usiner des pièces", size: 40, id: "capName" });
  const out = h("div", {});
  const run = () => { state.sub.capName = inp.value; out.innerHTML = ""; out.append(checkCapName(inp.value)); };
  inp.addEventListener("input", run);
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Testeur : mon nom est-il une bonne capacité ?"),
    h("div", { class: "row" }, inp, ...["Usiner des pièces", "Logiciel de soumission", "Gestion des soumissions", "Gestion des brevets"].map(x => h("button", { class: "btn", onclick: () => { inp.value = x; run(); } }, x))),
    out, src("« Principles of Business Capability » : basées sur des objets d'affaires, définies une fois, stables, centrées sur le quoi, sans gérondif")));
  run();
});
function normTxt(t) { return t.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim(); }
function checkCapName(name) {
  const n = normTxt(name), words = n.split(" ").filter(Boolean);
  const first = words[0] || "";
  const checks = [
    [!/(er|ir|re|ant)$/.test(first) || ["gestion", "definition", "evaluation", "planification", "execution", "inspection", "maintenance", "configuration"].includes(first),
      "Basée sur un objet d'affaires (nom), pas sur un verbe ou un gérondif", `« ${words[0] || ""} » ressemble à un verbe : un flux ou un processus s'écrit « Fabriquer… », une capacité « Gestion des… » (objet + action au repos).`],
    [!/(systeme|logiciel|application|processus|procedure|manuel|automatique|excel|sap|base de donnees|outil)/.test(n),
      "Dit ce qui est fait, pas comment", "Le nom mentionne un outil ou une manière de faire. Une capacité reste la même qu'elle soit manuelle ou automatisée."],
    [!/(departement|equipe|direction|division|service des)/.test(n) && !BUS.some(b => normTxt(b.name) === n), "N'est pas une unité d'affaires", "Une capacité n'est pas une équipe : l'unité d'affaires LIVRE la capacité, elle ne l'est pas."],
    [!CAPS.some(c => normTxt(c.name) === n), "Définie une seule fois pour l'entreprise", "Cette capacité existe déjà sur la carte : une capacité n'apparaît qu'une fois, même si plusieurs unités la possèdent."],
    [words.length > 0 && words.length <= 6, "Courte et compréhensible par l'affaire", "Trop longue ou vide : visez un nom concis que tout gestionnaire reconnaît."],
  ];
  const ok = checks.every(c => c[0]);
  return h("div", {}, h("ul", { class: "tight" }, checks.map(([pass, t, why]) => h("li", { class: pass ? "good" : "bad" }, (pass ? "✓ " : "✗ ") + t, pass ? null : h("div", { class: "small muted" }, why)))),
    h("b", { class: ok ? "good" : "bad" }, ok ? "Bonne candidate : l'ajout à la carte est défendable." : "À reformuler avant de l'ajouter à la carte."));
}

/* ============ 4. Organisation (2.3) ============ */
registerView("organization", "4 · Organisation", (el) => {
  const d = derive();
  el.append(...section("Cartographie de l'organisation (section 2.3)",
    "Le croisement unités d'affaires × capacités montre qui livre quoi : où une même capacité est dupliquée, où elle est externalisée et où son efficacité diverge. Cliquez un en-tête ou une ligne."));
  const cols = BUS;
  const tbl = h("table", { style: { fontSize: ".83rem" } });
  tbl.append(h("thead", {}, h("tr", {}, h("th", {}, "Capacité"), cols.map(b => h("th", { style: { cursor: "pointer", minWidth: "78px" }, onclick: () => select(b.id), title: b.name }, b.external ? "⚑ " : "", b.name.split(" (")[0].replace("Ventes et service client", "Ventes").replace("Finances et administration", "Finances").replace("Ingénierie et conception", "Ingénierie").replace("Logistique et expédition", "Logistique").replace("Qualité et conformité", "Qualité"))), h("th", {}, "Instances"))));
  const tb = h("tbody", {});
  Object.keys(CAP_L1).forEach(k => {
    tb.append(h("tr", {}, h("td", { colspan: cols.length + 2, style: { background: "var(--bg)", fontWeight: 600 } }, CAP_L1[k])));
    CAPS.filter(c => c.l1 === k).forEach(c => {
      const n = Object.keys(c.inst).length, vals = Object.values(c.inst), div = Math.max(...vals) - Math.min(...vals);
      tb.append(h("tr", { style: state.sel === c.id ? { outline: "2px solid var(--ink)" } : {} },
        h("td", { style: { cursor: "pointer" }, onclick: () => select(c.id) }, c.name),
        cols.map(b => c.inst[b.id] ? h("td", { style: { background: heat(c.inst[b.id]), color: "#111", textAlign: "center", fontWeight: 600 }, title: `${c.name} — ${b.name} : ${c.inst[b.id]}/5` }, c.inst[b.id]) : h("td", {})),
        h("td", {}, n > 1 ? h("span", { class: div >= 2 ? "bad" : "warnc" }, `×${n}${div >= 2 ? " ⚠ écart " + div : ""}`) : "—")));
    });
  });
  tbl.append(tb);
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, legendHeat("Efficacité de l'instance :"), tbl));

  const stats = BUS.map(b => { const mine = CAPS.filter(c => c.inst[b.id]); return { b, n: mine.length, avg: mine.reduce((a, c) => a + c.inst[b.id], 0) / (mine.length || 1) }; });
  const byId = {}; BUS.forEach(b => byId[b.id] = []);
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Organigramme et capacités livrées"),
      ...BU_TREE.filter(x => x.parent === null).map(root => h("div", {}, h("b", {}, root.name),
        ...BU_TREE.concat(BUS).filter(x => x.parent === root.id).map(x => orgBranch(x, stats))))),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Ce que révèle le croisement"),
      h("ul", { class: "tight" },
        h("li", {}, "Capacités livrées par plusieurs unités : ", h("b", {}, CAPS.filter(c => Object.keys(c.inst).length > 1).length + " sur " + CAPS.length), " — redondance à examiner, pas toujours un problème."),
        h("li", {}, "Instances externalisées chez le partenaire : ", h("b", {}, CAPS.filter(c => c.inst.bu_ext).length), " capacités, avec une efficacité moyenne de ", h("b", {}, fmt(CAPS.filter(c => c.inst.bu_ext).reduce((a, c) => a + c.inst.bu_ext, 0) / CAPS.filter(c => c.inst.bu_ext).length))),
        h("li", {}, "Capacités au comportement divergent : ", h("b", {}, CAPS.filter(c => { const v = Object.values(c.inst); return v.length > 1 && Math.max(...v) - Math.min(...v) >= 2; }).map(c => c.name).join(" · ") || "aucune"))),
      note("Le partenaire externe fait partie de l'architecture : le guide parle d'écosystème d'affaires, pas seulement des frontières légales de l'entreprise."),
      src("2.3 et principe de l'écosystème d'affaires (partie 1)"))));
});
function orgBranch(x, stats) {
  const st = stats.find(s2 => s2.b.id === x.id);
  const kids = BU_TREE.concat(BUS).filter(y => y.parent === x.id);
  return h("div", { style: { marginLeft: "18px", borderLeft: "2px solid var(--line)", paddingLeft: "10px", marginTop: "4px" } },
    x.group ? h("b", {}, x.name) : h("div", {}, chip(x.id), " ", h("span", { class: "muted small" }, st ? `${st.n} capacité(s) · efficacité moy. ${fmt(st.avg)}` : ""), x.external ? h("span", { class: "tag", style: { background: "#888", marginLeft: "6px" } }, "externe") : null),
    ...kids.map(k => orgBranch(k, stats)));
}
