"use strict";
/* ============ 9. Pratique (partie 3) ============ */
registerView("practice", "9 · Pratique", (el) => {
  const k = state.sub.prac || "bmc";
  el.append(...section("Le guide de pratique (partie 3)",
    "L'architecture d'affaires ne vit pas seule : elle s'arrime au modèle d'affaires, aux exigences, aux règles de routage, à la performance, à l'expérience client et à la gouvernance."));
  el.append(h("div", { class: "sub" }, seg([["bmc", "Modèle d'affaires (3.3)"], ["req", "Exigences (3.8)"], ["route", "Routage dynamique (3.5)"], ["perf", "Performance (3.7)"], ["cx", "Expérience client (3.13)"], ["gov", "Gouvernance et maturité (3.2, 3.9)"]], k, (x) => { state.sub.prac = x; rerender(); })));
  ({ bmc: pracBmc, req: pracReq, route: pracRoute, perf: pracPerf, cx: pracCx, gov: pracGov })[k](el);
});

function pracBmc(el) {
  const d = derive(); const sel = state.sub.bmc ?? 3;
  const grid = h("div", { class: "cols" });
  BMC.forEach((b, i) => {
    const a = b.caps.reduce((x, c) => x + d.effTar[c], 0) / b.caps.length;
    grid.append(h("div", { class: "card", style: { cursor: "pointer", outline: i === sel ? "3px solid var(--accent)" : "none", marginBottom: 0 }, onclick: () => { state.sub.bmc = i; rerender(); } },
      h("b", {}, b.k), h("ul", { class: "tight small" }, b.items.map(x => h("li", {}, x))),
      h("div", { class: "bar" }, h("i", { style: { width: a * 20 + "%", background: heat(a) } })), h("div", { class: "small muted" }, "solidité des capacités : " + fmt(a))));
  });
  const b = BMC[sel];
  el.append(h("div", { class: "card" }, h("b", {}, "Canevas du modèle d'affaires de Groupe Usinage Saint-Maurice"), h("p", { class: "small muted" }, "Le modèle d'affaires décrit comment l'organisation crée, livre et capture de la valeur. Chaque bloc se rattache à des capacités."), grid),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, `Bloc « ${b.k} » → capacités qui le rendent possible`), h("div", {}, b.caps.map(c => chip(c, { short: true }))),
      note("Tester une stratégie contre le modèle d'affaires (3.3) : si le modèle exige une capacité faible, la stratégie n'est pas encore faisable. Ici, la proposition de valeur « précision et qualité sur mesure, estimées vite » repose sur ", chip("c_prd_cfg", { short: true }), ", l'une des capacités les plus faibles de la carte."),
      src("3.3 Business Architecture and Business Models")));
}

function pracReq(el) {
  const d = derive(); const id = state.sub.req || "rq1"; const r = REQS.find(x => x.id === id);
  const init = INITMAP.get(r.init), live = d.del.some(i => i.id === r.init);
  const arrow = h("span", { class: "muted", style: { fontSize: "1.3rem" } }, "→");
  el.append(h("div", { class: "card" }, h("div", { class: "row" }, "Exigence : ", h("select", { onchange: (e) => { state.sub.req = e.target.value; rerender(); } }, REQS.map(x => h("option", { value: x.id, selected: x.id === id }, x.name)))),
    h("div", { class: "row", style: { alignItems: "flex-start" } },
      h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Exigence d'affaires"), h("b", {}, r.name)), arrow,
      h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Capacités"), h("div", {}, r.caps.map(c => chip(c, { short: true })))), arrow,
      h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Étape de flux de valeur"), chip(r.stage)), arrow,
      h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Initiative"), chip(r.init), h("div", { class: "small " + (live ? "good" : "muted") }, live ? "livrée à cette date ✔" : "pas encore livrée")), arrow,
      h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Objectif servi"), chip(r.obj))),
    note(h("b", {}, "Alignement des exigences : "), "une exigence qui ne se rattache à aucune capacité, étape ou objectif est probablement hors sujet ; une capacité sans exigence est peut-être mal servie. La traçabilité va de l'exigence jusqu'à l'objectif stratégique, dans les deux sens."),
    src("3.8 Business Architecture and Requirements Alignment")));
}

const ROUTES = {
  r1: { name: "Escalade immédiate au VP Qualité et sécurité + gel du lot", why: "Gravité critique : sécurité, déversement ou conformité en jeu", caps: ["c_qua_nc", "c_qua_tra"] },
  r2: { name: "Comité de conformité (CWB, AS9100) + notification de l'organisme", why: "Défaut de certification", caps: ["c_qua_cer", "c_con_rg"] },
  r3: { name: "Enquête qualité niveau 2 + appel du directeur de compte", why: "Gravité majeure chez un client stratégique", caps: ["c_qua_nc", "c_cli_rel"] },
  r4: { name: "Enquête qualité niveau 1", why: "Gravité majeure", caps: ["c_qua_nc"] },
  r5: { name: "Remplacement standard sous 48 h (automatique)", why: "Erreur de livraison mineure", caps: ["c_log_ret"] },
  r6: { name: "Crédit ou remplacement (automatique)", why: "Défaut mineur sans risque", caps: ["c_log_ret", "c_fin_fac"] },
};
const RULES = [
  { id: "R1", txt: "Gravité = critique", test: (x) => x.grav === "critique", route: "r1" },
  { id: "R2", txt: "Défaut = certification", test: (x) => x.defaut === "certification", route: "r2" },
  { id: "R3", txt: "Gravité = majeure ET client stratégique", test: (x) => x.grav === "majeure" && x.strat, route: "r3" },
  { id: "R4", txt: "Gravité = majeure", test: (x) => x.grav === "majeure", route: "r4" },
  { id: "R5", txt: "Gravité = mineure ET défaut = livraison", test: (x) => x.grav === "mineure" && x.defaut === "livraison", route: "r5" },
  { id: "R6", txt: "Sinon (mineure)", test: () => true, route: "r6" },
];
function pracRoute(el) {
  const x = state.sub.claim || { grav: "majeure", defaut: "qualité", strat: true };
  const set = (p) => { state.sub.claim = Object.assign({}, x, p); rerender(); };
  const match = RULES.find(r => r.test(x)); const route = ROUTES[match.route];
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Réclamation d'un client : simulez le routage selon des règles"),
    h("div", { class: "row" }, "Gravité", seg([["mineure", "mineure"], ["majeure", "majeure"], ["critique", "critique"]], x.grav, (v) => set({ grav: v })),
      "Défaut", seg([["usinage", "usinage"], ["soudure", "soudure"], ["certification", "certification"], ["livraison", "livraison"]], x.defaut, (v) => set({ defaut: v })),
      "Client stratégique", seg([[true, "oui"], [false, "non"]], x.strat, (v) => set({ strat: v }))),
    h("table", {}, h("thead", {}, h("tr", {}, ["#", "Règle (évaluée dans l'ordre)", "Résultat"].map(t => h("th", {}, t)))),
      h("tbody", {}, RULES.map(r => { const hit = r === match, passed = RULES.indexOf(r) < RULES.indexOf(match);
        return h("tr", { style: { background: hit ? "color-mix(in srgb,var(--good) 18%,var(--surface))" : "" } }, h("td", {}, r.id), h("td", {}, r.txt), h("td", {}, hit ? h("b", { class: "good" }, "✔ déclenchée → " + ROUTES[r.route].name) : passed ? h("span", { class: "muted" }, "non applicable") : h("span", { class: "muted" }, "non évaluée")));
      }))),
    h("div", { class: "kpi", style: { marginTop: "8px" } }, h("b", {}, "Route : "), route.name, h("div", { class: "small muted" }, route.why),
      h("div", { class: "small" }, "Capacités sollicitées : ", route.caps.map(c => chip(c, { short: true })), " · étape du flux : ", chip("r3"))),
    note(h("b", {}, "Routage dynamique fondé sur des règles : "), "la route n'est pas figée dans un diagramme de processus ; l'état du dossier (gravité, type, client) détermine la prochaine étape. Les règles se changent sans redessiner le flux de valeur. Comparez avec le flux ", chip("vs_rec", { short: true }), "."),
    src("3.5 Business Architecture, Case Management, and Dynamic Rules-Based Routing; annexe B.5")));
}

function pracPerf(el) {
  const d = derive();
  const rows = OBJS.map(o => {
    const st = STRATS.find(s2 => s2.objs.includes(o.id));
    const inits = INITS.filter(i => i.kpi && i.kpi[o.kpi] || (o.kpi === "k_delai" && Object.keys(i.wait || {}).length));
    return { o, st, inits, v: d.kpi[o.kpi] };
  });
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Tableau de bord stratégique : objectifs → indicateurs → initiatives"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Objectif", "Indicateur", "Valeur", "Cible", "Stratégie", "Initiatives qui l'influencent"].map(t => h("th", {}, t)))),
      h("tbody", {}, rows.map(r => h("tr", {}, h("td", {}, chip(r.o.id, { short: true })), h("td", {}, KPIS[r.o.kpi].name), h("td", { class: objMet(r.o, r.v) ? "good" : "bad" }, fmt(r.v, 1) + " " + r.o.unit),
        h("td", {}, (r.o.dir === "max" ? "≤ " : "≥ ") + r.o.target), h("td", {}, r.st ? chip(r.st.id, { short: true }) : "—"), h("td", {}, r.inits.map(i => chip(i.id, { short: true }))))))),
    note("Chaque indicateur est rattaché à un objectif, une stratégie et des initiatives : on voit tout de suite quels leviers déplacent quel chiffre. Modifiez la simulation à l'onglet Initiatives pour voir la table réagir."),
    src("3.7 Business Architecture and Business Performance Management")));
}

function pracCx(el) {
  const d = derive(); const W = 880, H = 260, L = 50, R = 20, T = 20, B = 60;
  const stages = VSMAP.get("vs_acq").stages; const sel = state.sub.cxSel || "a2";
  const x = (i) => L + (i * (W - L - R)) / (stages.length - 1), y = (v) => T + (5 - v) * ((H - T - B) / 4);
  const after = stages.map(st => clamp(CX[st.id].s + st.caps.reduce((a, c) => a + (d.effTar[c] - d.effCur[c]), 0) * 0.35, 1, 5));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
  for (let v = 1; v <= 5; v++) svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "var(--line)" }), s("text", { x: 20, y: y(v) + 4, "font-size": 11, fill: "var(--muted)" }, v));
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  svg.append(s("path", { d: path(stages.map(st => CX[st.id].s)), fill: "none", stroke: "var(--bad)", "stroke-width": 2.5 }), s("path", { d: path(after), fill: "none", stroke: "var(--good)", "stroke-width": 2.5, "stroke-dasharray": "6 4" }));
  stages.forEach((st, i) => {
    svg.append(s("g", { class: "node", onclick: () => { state.sub.cxSel = st.id; select(st.id); rerender(); } }, s("circle", { cx: x(i), cy: y(CX[st.id].s), r: st.id === sel ? 9 : 6, fill: "var(--bad)" }), s("circle", { cx: x(i), cy: y(after[i]), r: 5, fill: "var(--good)" }),
      s("text", { x: x(i), y: H - 36, "text-anchor": "middle", "font-size": 11, fill: "var(--ink)" }, st.name)));
  });
  const stg = STAGEMAP.get(sel);
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Parcours du client industriel — satisfaction par étape du flux « Acquérir une pièce usinée sur mesure »"), svg,
    h("div", { class: "legend" }, h("span", { style: { color: "var(--bad)" } }, "● ligne pleine = aujourd'hui"), h("span", { style: { color: "var(--good)" } }, "● pointillés = estimation après les initiatives livrées")),
    h("div", { class: "kpi", style: { marginTop: "8px" } }, h("b", {}, stg.name), " — satisfaction " + CX[sel].s + "/5", h("div", {}, "Point de friction : " + CX[sel].pain), h("div", { class: "small" }, "Capacités à améliorer : ", stg.caps.map(c => chip(c, { short: true })))),
    note("Un parcours client (3.13) n'est utile que s'il s'appuie sur le flux de valeur : chaque point de friction se rattache à une étape, donc à des capacités concrètes à renforcer. L'estimation après initiatives est un modèle simple : gain des capacités × 0,35."),
    src("3.13 Business Architecture and Customer Experience Design")));
}

function pracGov(el) {
  const dims = state.sub.bamm || BAMM_DIMS.map(() => 2);
  const avg = dims.reduce((a, b) => a + b, 0) / dims.length, lvl = BAMM[clamp(Math.round(avg), 1, 5) - 1];
  const W = 340, cx = 170, cy = 160, R = 110, nD = BAMM_DIMS.length;
  const pt = (i, v) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / nD; return [cx + (R * v / 5) * Math.cos(a), cy + (R * v / 5) * Math.sin(a)]; };
  const svg = s("svg", { viewBox: `0 0 ${W} 320`, width: "100%", style: "max-width:380px" });
  [1, 2, 3, 4, 5].forEach(v => svg.append(s("polygon", { points: BAMM_DIMS.map((_, i) => pt(i, v).join(",")).join(" "), fill: "none", stroke: "var(--line)" })));
  svg.append(s("polygon", { points: dims.map((v, i) => pt(i, v).join(",")).join(" "), fill: "var(--accent)", opacity: 0.35, stroke: "var(--accent)", "stroke-width": 2 }));
  BAMM_DIMS.forEach((t, i) => { const [x, y] = pt(i, 5.9); svg.append(s("text", { x, y, "font-size": 9.5, "text-anchor": "middle", fill: "var(--muted)" }, t.length > 22 ? t.slice(0, 20) + "…" : t)); });
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Maturité de la pratique d'architecture d'affaires (BAMM)"),
      ...BAMM_DIMS.map((t, i) => h("div", { class: "row", style: { margin: "2px 0" } }, h("span", { style: { width: "250px" } }, t), h("input", { type: "range", min: 1, max: 5, value: dims[i], onchange: (e) => { const n2 = dims.slice(); n2[i] = +e.target.value; state.sub.bamm = n2; rerender(); } }), h("b", {}, dims[i]))),
      svg, h("div", { class: "kpi" }, h("b", {}, `Niveau ${lvl.n} — ${lvl.name} `), `(moyenne ${fmt(avg)})`, h("div", { class: "small" }, lvl.d)),
      note("Le modèle mesure la maturité de la PRATIQUE d'architecture d'affaires, pas celle de l'entreprise. Les dimensions du radar sont illustratives ; les critères exigés se trouvent à l'annexe B.3."),
      src("3.9 Business Architecture Maturity Model (BAMM), fig. 3.9.1")),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Gouvernance de la base de connaissances (3.2)"),
      h("table", {}, h("thead", {}, h("tr", {}, ["Domaine", "Propriétaire", "Instance", "Révision"].map(t => h("th", {}, t)))), h("tbody", {}, GOV.map(g => h("tr", {}, h("td", {}, g.dom), h("td", {}, g.owner), h("td", {}, g.comite), h("td", {}, g.freq))))),
      note("Les domaines noyau (capacités, information) changent peu et se révisent rarement ; les domaines étendus (initiatives, politiques) demandent une révision plus fréquente. Propriétaires et fréquences ci-dessus sont des choix illustratifs pour Groupe Usinage Saint-Maurice."),
      h("h3", {}, "Niveaux du modèle de maturité"), h("ol", { class: "tight small" }, BAMM.map(b => h("li", {}, h("b", {}, b.name + " : "), b.d))))));
}

/* ============ 10. Alignement TI (partie 6) ============ */
registerView("it", "10 · Alignement TI", (el) => {
  const d = derive();
  const gone = new Set(d.del.flatMap(i => i.replaces || []));
  el.append(...section("Architecture d'affaires et architecture TI (partie 6)",
    "Les capacités servent de pont entre l'affaire et la technologie : on voit quelles applications automatisent quelles capacités, où la dette technique est concentrée et quelles capacités communes sont de bonnes candidates à des services partagés."));
  const grid = h("div", { class: "cols" });
  APPS.forEach(a => {
    const out = gone.has(a.id);
    grid.append(h("div", { class: "card", style: { opacity: out ? 0.55 : 1, marginBottom: 0 } }, h("div", {}, typeTag("app"), out ? h("span", { class: "tag", style: { background: "#2f9e5f", marginLeft: "6px" } }, "remplacée") : null),
      h("h3", { style: { margin: ".3rem 0" } }, chip(a.id)), h("div", { class: "small" }, "Dette technique : ", h("b", { style: { color: a.debt >= 4 ? "var(--bad)" : "var(--ink)" } }, a.debt + " / 5")),
      h("div", { class: "bar", style: { margin: "3px 0" } }, h("i", { style: { width: a.debt * 20 + "%", background: heat(6 - a.debt) } })),
      h("div", { class: "small" }, "Capacités automatisées :"), h("div", {}, a.caps.map(c => chip(c, { short: true }))),
      INITS.filter(i => (i.replaces || []).includes(a.id)).map(i => h("div", { class: "small muted" }, "Remplacée par ", chip(i.id, { short: true })))));
  });
  const none = CAPS.filter(c => !APPS.some(a => a.caps.includes(c.id)));
  const risky = CAPS.filter(c => c.imp >= 5 && APPS.some(a => a.caps.includes(c.id) && a.debt >= 4 && !gone.has(a.id)));
  const shared = CAPS.filter(c => Object.keys(c.inst).length >= 2);
  el.append(grid, h("div", { class: "cols", style: { marginTop: "12px" } },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, `Capacités critiques sur une application à forte dette (${risky.length})`), h("div", {}, risky.map(c => chip(c.id, { short: true }))),
      h("p", { class: "small muted" }, "Importance stratégique 5 sur une application dont la dette est ≥ 4, et non remplacée à la date de la simulation.")),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, `Capacités sans application dédiée (${none.length})`), h("div", {}, none.map(c => chip(c.id, { short: true }))), h("p", { class: "small muted" }, "Rien ne les automatise : travail manuel ou outils personnels.")),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, `Candidates à un service partagé (${shared.length})`), h("div", {}, shared.map(c => chip(c.id, { short: true }))),
      h("p", { class: "small muted" }, "Capacités présentes dans plusieurs unités : un service d'entreprise automatiserait « une manière commune de faire la même chose » (orientation services, 6.5)."))),
    note("Le portefeuille d'applications se rationalise à partir des capacités, pas des logiciels : une capacité fragmentée sur plusieurs applications est un signal ; une application unique qui en porte six est un risque de concentration.", " ", src("6.4 Application Portfolio Management, 6.5 Service-Oriented Architecture Alignment")));
});

/* ============ 11. Scénarios (partie 4) ============ */
registerView("scenarios", "11 · Scénarios", (el) => {
  const d = derive();
  const id = state.sub.scen || "sc3"; const sc = SCENARIOS.find(x => x.id === id);
  const depth = state.sub.depth || 3;
  el.append(...section("Scénarios d'architecture d'affaires (partie 4)",
    "Un scénario donne un contexte d'usage aux cartographies : on part d'un événement (rupture, nouvelle norme, nouveau produit, externalisation) et on suit les dépendances pour voir ce qui est touché."));
  el.append(h("div", { class: "card" }, h("div", { class: "row" }, "Scénario : ", h("select", { onchange: (e) => { state.sub.scen = e.target.value; rerender(); } }, SCENARIOS.map(x => h("option", { value: x.id, selected: x.id === id }, x.name))),
    !sc.special ? h("span", {}, "Portée (sauts) : ", h("input", { type: "range", min: 1, max: 4, value: depth, onchange: (e) => { state.sub.depth = +e.target.value; rerender(); } }), h("b", {}, depth)) : null),
    h("p", { class: "muted" }, sc.desc)));
  if (sc.special === "overlap") {
    const by = {}; INITS.forEach(i => Object.keys(i.caps).forEach(c => (by[c] = by[c] || []).push(i.id)));
    const over = Object.entries(by).filter(([, v]) => v.length > 1);
    el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Capacités visées par plusieurs initiatives"), over.map(([c, ids]) => h("div", { class: "row" }, chip(c, { short: true }), "←", ids.map(i => chip(i, { short: true })), h("span", { class: "small muted" }, "→ coordonner : même équipe, même calendrier ?"))),
      h("h3", {}, "Initiatives sans lien avec une stratégie"), INITS.filter(i => !i.strat.length).length ? "" : h("span", { class: "good" }, "Aucune : toutes les initiatives sont rattachées à une stratégie."),
      note("Le scénario 1 du guide décrit un cas où trois initiatives parallèles coûtent très cher parce qu'elles visent la même capacité sans coordination. La cartographie rend cette redondance visible avant le lancement.")));
  } else if (sc.special === "gap") {
    const rows = CAPS.map(c => ({ c, gap: c.imp - d.effTar[c.id] })).sort((a, b) => b.gap - a.gap).slice(0, 10);
    el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Capacités à forte importance et faible efficacité"),
      h("table", {}, h("thead", {}, h("tr", {}, ["Capacité", "Importance", "Efficacité (cible)", "Écart", "Unités", "Applications"].map(t => h("th", {}, t)))),
        h("tbody", {}, rows.map(({ c, gap }) => h("tr", {}, h("td", {}, chip(c.id, { short: true })), h("td", {}, c.imp), h("td", { style: { background: heat(d.effTar[c.id]), color: "#111" } }, fmt(d.effTar[c.id])), h("td", { class: gap >= 2 ? "bad" : "" }, fmt(gap)),
          h("td", {}, Object.keys(c.inst).map(b => chip(b, { short: true }))), h("td", {}, APPS.filter(a => a.caps.includes(c.id)).map(a => chip(a.id, { short: true }))))))),
      note("Réduire les coûts sans abîmer la valeur : on agit d'abord sur les capacités peu importantes et très coûteuses, et on protège celles à forte importance.")));
  } else {
    const dist = bfs(sc.seeds, depth);
    const groups = {}; dist.forEach((dd, nid) => { if (dd > 0) { const t = NODES.get(nid).type; (groups[t] = groups[t] || []).push({ id: nid, d: dd }); } });
    const vsHit = (groups.vs || []).map(x => VSMAP.get(x.id)); const inits = (groups.init || []).length;
    el.append(h("div", { class: "card" }, h("div", { class: "row" }, h("b", {}, "Point de départ :"), sc.seeds.map(sd => chip(sd))),
      h("div", { class: "row" }, ...Object.keys(TYPES).filter(t => groups[t]).map(t => h("div", { class: "kpi" }, h("div", { class: "small muted" }, TYPES[t].label + "s touchés"), h("div", { class: "v" }, groups[t].length)))),
      vsHit.length ? note(h("b", {}, "Valeur exposée : "), vsHit.map(v => `« ${v.name} » (${v.proposition})`).join(" · ")) : null,
      ...Object.keys(TYPES).filter(t => groups[t]).map(t => h("div", {}, h("div", { class: "small", style: { fontWeight: 600, marginTop: "8px" } }, TYPES[t].label + "s"), groups[t].sort((a, b) => a.d - b.d).map(x => h("span", { title: "distance " + x.d }, chip(x.id, { short: true }))))),
      note("Plus la portée augmente, plus on remonte la chaîne de dépendances : partie prenante → flux → étape → capacité → unité, information, application, initiative. C'est l'analyse d'impact que permet la base de connaissances (5.1).", ` ${inits ? inits + " initiative(s) déjà en cours touchent ce périmètre." : "Aucune initiative n'est actuellement en cours dans ce périmètre."} `),
      src("Partie 4 : scénarios 1, 4, 6, 7, 9 et 11")));
    /* propagation de l'impact : réseau vivant, un anneau par saut */
    state.live = state.live || {};
    const ids = [...dist.keys()], ring = {}; ids.forEach(i => { const k = dist.get(i); ring[k] = (ring[k] || 0) + 1; });
    const seen = {};
    const sNodes = ids.map(id => {
      const k = dist.get(id), idx = (seen[k] = (seen[k] || 0) + 1) - 1, a = (idx / ring[k]) * Math.PI * 2 + k, n = NODES.get(id);
      return { id, label: shortName(n.name).slice(0, 26), title: `${TYPES[n.type].label} — ${k} saut(s)`, color: tcolor(n.type), r: k === 0 ? 12 : 6.5, big: k === 0, x: 500 + Math.cos(a) * 110 * k, y: 300 + Math.sin(a) * 85 * k };
    });
    const sSet = new Set(ids), sLinks = EDGES.filter(e => sSet.has(e.a) && sSet.has(e.b)).map(e => ({ a: e.a, b: e.b, label: e.rel }));
    const lg = liveGraph({ key: "sc", width: 1000, height: 600, maxHeight: "70vh", store: (state.live["sc" + id + depth] = state.live["sc" + id + depth] || new Map()), selected: state.sel,
      nodes: sNodes, links: sLinks, labels: ids.length <= 40 ? "always" : "hover", linkLabels: "hover", charge: 3000, linkLen: 70, onClick: select });
    el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Propagation de l'impact (un anneau par saut)"), liveControls(lg.api, { charge: 3000, len: 70 }), lg.svg, h("div", { class: "src" }, LIVE_HELP)));
  }
});
