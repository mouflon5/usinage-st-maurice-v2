"use strict";
/* ============ 5. Flux de valeur (2.4) ============ */
let playTimer = null;
registerView("value", "5 · Flux de valeur", (el) => {
  const d = derive();
  const vsId = state.sub.vs || "vs_acq";
  const vs = VSMAP.get(vsId);
  const n = vs.stages.length;
  const prog = state.sub.prog === undefined ? n : clamp(state.sub.prog, 0, n);
  const stopAt = state.sub.stop === undefined ? n : state.sub.stop;
  const reached = Math.min(prog, stopAt);
  el.append(...section("Flux de valeur et croisement avec les capacités (section 2.4)",
    "Un flux de valeur décrit, de bout en bout et du point de vue de la partie prenante qui le déclenche, comment la valeur est obtenue. Chaque étape livre un élément de valeur ; la proposition de valeur est atteinte à la fin. Chaque étape est habilitée par des capacités."));
  el.append(h("div", { class: "row" }, seg(VSS.map(v => [v.id, v.name]), vsId, (k) => { state.sub.vs = k; state.sub.prog = undefined; state.sub.stop = undefined; state.sub.vfocus = null; state.sub.vi = -1; stopPlay(); stopVPlay(); rerender(); })));

  /* chevrons */
  const row = h("div", { class: "stages" });
  vs.stages.forEach((st, i) => {
    row.append(h("div", { class: "stage" + (i < reached ? " done" : "") + (i === reached - 1 ? " cur" : ""), onclick: () => select(st.id) },
      h("div", { class: "n" }, `Étape ${i + 1}`), h("b", {}, st.name),
      h("div", { class: "small", style: { marginTop: "4px", color: i < reached ? "var(--good)" : "var(--muted)" } }, i < reached ? "✔ " + st.item : "valeur : " + st.item)));
  });
  const full = reached === n;
  const trig = NODES.get(vs.trigger);
  el.append(h("div", { class: "card" },
    h("div", { class: "row" }, h("span", {}, "Déclenché par ", chip(vs.trigger)), h("span", { class: "muted small" }, vs.ext ? "(partie prenante externe)" : "(partie prenante interne)")),
    row,
    h("div", { class: "row", style: { marginTop: "8px" } },
      h("button", { class: "btn primary", onclick: () => startPlay(vs, stopAt) }, "▶ Dérouler le flux"),
      h("button", { class: "btn", onclick: () => { stopPlay(); state.sub.prog = 0; rerender(); } }, "↺ Remettre à zéro"),
      h("span", {}, "Avancement : ", h("input", { type: "range", min: 0, max: n, value: reached, onchange: (e) => { stopPlay(); state.sub.prog = +e.target.value; rerender(); } })),
      h("span", {}, "Le flux s'arrête à l'étape : ", h("select", { onchange: (e) => { state.sub.stop = +e.target.value; rerender(); } },
        [...vs.stages.map((st, i) => h("option", { value: i + 1, selected: stopAt === i + 1 }, `${i + 1}. ${st.name}`))]))),
    h("div", { class: "kpi", style: { marginTop: "6px", borderColor: full ? "var(--good)" : "var(--line)" } },
      h("b", {}, "Proposition de valeur : "), vs.proposition, " — ",
      full ? h("b", { class: "good" }, "atteinte ✔") : h("b", { class: "warnc" }, "non atteinte"),
      h("div", { class: "small muted" }, `Éléments de valeur accumulés : ${reached} / ${n}` + (full ? "" : " — un arrêt anticipé laisse quand même une partie de la valeur (jugement de valeur « value item »)."))),
    vs.id === "vs_app" ? note(h("b", {}, "Rôle de mandataire (proxy) : "), "ce flux est déclenché par l'équipe de production, mais le bénéficiaire ultime est le client industriel qui recevra ses pièces à temps.") : null,
    vs.id === "vs_dep" ? note("Flux interne déclenché par la direction : ses quatre étapes correspondent aux agents de l'orchestrateur de trésorerie (A1 acquisition, A2 extraction, A3 réconciliation, A4 prévision, A5 écarts, A6 contrôle, A8 relecture, A7 reporting). C'est le projet de trésorerie lui-même, vu comme un flux de valeur.") : null,
    src("2.4 « Defining Value, Value Proposition, and Value Item », fig. 2.4.1 et 2.4.4")));

  el.append(...vsProcessBlocks(vs, d));

  /* croisement flux × capacités */
  const capIds = [...new Set(vs.stages.flatMap(st => st.caps))];
  const tbl = h("table", { style: { fontSize: ".82rem" } },
    h("thead", {}, h("tr", {}, h("th", {}, "Capacité habilitante"), vs.stages.map((st, i) => h("th", { style: { cursor: "pointer", textAlign: "center" }, onclick: () => select(st.id) }, (i + 1) + ". " + st.name)), h("th", {}, "Efficacité"))));
  const tb = h("tbody", {});
  capIds.forEach(cid => {
    const c = CAPMAP.get(cid);
    tb.append(h("tr", {}, h("td", { style: { cursor: "pointer" }, onclick: () => select(cid) }, c.name),
      vs.stages.map(st => h("td", { style: { textAlign: "center", background: st.caps.includes(cid) ? heat(d.effTar[cid]) : "transparent", color: "#111" } }, st.caps.includes(cid) ? "●" : "")),
      h("td", { style: { fontWeight: 600 } }, fmt(d.effCur[cid]) + " → " + fmt(d.effTar[cid]))));
  });
  const stageMin = vs.stages.map(st => ({ st, v: Math.min(...st.caps.map(c => d.effTar[c])) }));
  const weakest = stageMin.reduce((a, b) => (b.v < a.v ? b : a));
  tbl.append(tb);
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Croisement flux de valeur × capacités"), legendHeat("Couleur = efficacité cible (selon la simulation) :"), tbl,
    note(h("b", {}, "Étape la plus fragile : "), `« ${weakest.st.name} » — sa capacité la plus faible a une efficacité de ${fmt(weakest.v)}/5. C'est là qu'une initiative a le plus d'effet sur la valeur reçue.`),
    src("2.4 : le croisement flux de valeur / capacités est un composant clé de l'architecture d'affaires")));

  /* Lean (3.4 / 3.6) pour vs_acq */
  if (vs.id === "vs_acq") {
    const W = 900, bh = 26, H = 36 + vs.stages.length * (bh * 2 + 18) + 30;
    const maxV = Math.max(...vs.stages.map(st => st.touch + st.wait));
    const sx = (v) => 200 + (v / maxV) * 600;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });
    vs.stages.forEach((st, i) => {
      const y = 30 + i * (bh * 2 + 18);
      svg.append(s("text", { x: 8, y: y + bh, "font-size": 12, fill: "var(--ink)" }, (i + 1) + ". " + st.name));
      svg.append(s("rect", { x: sx(0), y, width: sx(st.touch) - sx(0), height: bh - 4, fill: "#2563eb", opacity: 0.35 }),
        s("rect", { x: sx(st.touch), y, width: sx(st.wait) - sx(0), height: bh - 4, fill: "#d03b3b", opacity: 0.25 }),
        s("text", { x: sx(st.touch + st.wait) + 6, y: y + 14, "font-size": 11, fill: "var(--muted)" }, `avant : ${st.touch} + ${st.wait} j`));
      const w = d.waits[st.id];
      svg.append(s("rect", { x: sx(0), y: y + bh - 2, width: sx(st.touch) - sx(0), height: bh - 4, fill: "#2563eb" }),
        s("rect", { x: sx(st.touch), y: y + bh - 2, width: sx(w) - sx(0), height: bh - 4, fill: "#d03b3b" }),
        s("text", { x: sx(st.touch + w) + 6, y: y + bh + 12, "font-size": 11, fill: "var(--ink)" }, `après : ${st.touch} + ${w} j`));
    });
    svg.append(s("text", { x: 8, y: 16, "font-size": 12, fill: "var(--muted)" }, "bleu = temps de travail · rouge = temps d'attente (gaspillage)"));
    const eff0 = d.touch / (d.touch + d.waitBase), eff1 = d.touch / d.kpi.k_delai;
    el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Où le temps se perd (alignement avec Lean Six Sigma, section 3.6)"),
      h("div", { class: "row" }, h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Délai total"), h("div", { class: "v" }, `${d.touch + d.waitBase} → ${d.kpi.k_delai} j`)),
        h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Efficacité du flux (travail ÷ délai)"), h("div", { class: "v" }, `${fmt(eff0 * 100, 0)} % → ${fmt(eff1 * 100, 0)} %`)),
        h("div", { class: "kpi" }, h("div", { class: "small muted" }, "Cible de l'objectif 1"), h("div", { class: "v" }, "≤ 49 j"))),
      svg, note("La même carte de flux sert de pont vers Lean Six Sigma : l'architecture d'affaires dit OÙ améliorer (étape, capacité), LSS dit COMMENT réduire l'attente. Les gains viennent des initiatives sélectionnées à l'onglet Initiatives."),
      src("3.4 (processus) et 3.6 (Lean Six Sigma)")));
  }
});
function stopPlay() { if (playTimer) { clearInterval(playTimer); playTimer = null; } }
function startPlay(vs, stopAt) {
  stopPlay(); state.sub.prog = 0; rerender();
  playTimer = setInterval(() => {
    state.sub.prog = (state.sub.prog || 0) + 1; rerender();
    if (state.sub.prog >= Math.min(vs.stages.length, stopAt || vs.stages.length)) stopPlay();
  }, 900);
}

/* ============ 6. Information (2.5) ============ */
registerView("info", "6 · Information", (el) => {
  const sel = state.sub.info || "ic_lot";
  el.append(...section("Carte de l'information (section 2.5)",
    "La carte d'information représente les concepts d'affaires (pas des tables de base de données) et leurs relations. Chaque capacité utilise ou modifie des concepts : c'est ce lien qui révèle les risques de gouvernance des données."));
  const P = { ic_fac: [70, 190], ic_cmd: [230, 190], ic_cli: [110, 60], ic_ent: [330, 60], ic_prd: [540, 60], ic_spc: [740, 60], ic_cer: [540, 190], ic_cmp: [740, 190], ic_fou: [890, 190], ic_eqp: [70, 320], ic_opr: [230, 320], ic_lot: [470, 320], ic_nc: [700, 320], ic_mvt: [110, 420], ic_cpt: [360, 420], ic_prv: [620, 420], ic_fcl: [860, 330],
    ic_evf: [890, 60], ic_cdp: [890, 260], ic_dem: [90, 540], ic_bca: [250, 540], ic_rec: [410, 540], ic_ffa: [570, 540], ic_lop: [730, 540], ic_ecr: [890, 540] };
  const W = 960, H = 600;
  state.live = state.live || {};
  const live = liveGraph({ key: "in", width: W, height: H, maxHeight: "680px", store: (state.live.in = state.live.in || new Map()), viewStore: (state.live.inV = state.live.inV || { k: 1, x: 0, y: 0 }),
    selected: sel, arrows: true, linkLabels: "hover", charge: 5200, linkLen: 150, homeK: 0.03,
    nodes: INFOS.map(i => ({ id: i.id, label: i.name.replace(" technique", " tech."), title: i.name, color: tcolor("info"), w: 108, h: 40, x: P[i.id][0], y: P[i.id][1], hx: P[i.id][0], hy: P[i.id][1] })),
    links: INFO_REL.map(([a, b, v, card]) => ({ a, b, label: `${v} (${card})`, width: 1.3 })),
    onClick: (id) => { state.sub.info = id; select(id); } });
  const svg = live.svg;
  const mod = CAPS.filter(c => (CAP_INFO[c.id].M || []).includes(sel)), use = CAPS.filter(c => (CAP_INFO[c.id].U || []).includes(sel));
  el.append(h("div", { class: "card" }, liveControls(live.api, { charge: 5200, len: 150 }), svg, h("div", { class: "small muted" }, LIVE_HELP), h("div", { class: "src" }, "Les cardinalités (1..*, 0..*, *..*) indiquent combien d'instances d'un concept se rattachent à l'autre.")));
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, `« ${NODES.get(sel).name} » — qui le modifie ?`),
      h("div", {}, mod.map(c => chip(c.id, { short: true }))), h("h3", {}, "Qui l'utilise ?"), h("div", {}, use.map(c => chip(c.id, { short: true }))),
      mod.length >= 3 ? note(h("b", {}, "Risque de gouvernance : "), `${mod.length} capacités modifient ce concept. Sans propriétaire unique, les définitions et valeurs peuvent diverger (alignement données, section 6.6).`) : note("Peu de capacités le modifient : propriétaire de la donnée facile à désigner.")),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Qui modifie quoi ? (nombre de capacités)"),
      h("table", {}, h("thead", {}, h("tr", {}, ["Concept", "Modifié par", "Utilisé par"].map(t => h("th", {}, t)))),
        h("tbody", {}, INFOS.map(i => {
          const m = CAPS.filter(c => (CAP_INFO[c.id].M || []).includes(i.id)).length, u = CAPS.filter(c => (CAP_INFO[c.id].U || []).includes(i.id)).length;
          return h("tr", { style: { cursor: "pointer", background: i.id === sel ? "var(--bg)" : "" }, onclick: () => { state.sub.info = i.id; rerender(); } }, h("td", {}, i.name), h("td", { class: m >= 3 ? "bad" : "" }, m), h("td", {}, u));
        }))), src("2.5 et 6.6 (alignement information et architecture de données)"))));
});

/* ============ 8. Produits · Parties prenantes · Politiques (2.7 à 2.9) ============ */
registerView("extended", "8 · Produits, parties prenantes, politiques", (el) => {
  const d = derive(); const k = state.sub.ext || "prod";
  el.append(...section("Domaines étendus : produits, parties prenantes et politiques (sections 2.7 à 2.9)",
    "Les domaines étendus changent plus souvent que le noyau, mais se rattachent aux mêmes capacités : un produit offre des droits de service habilités par des capacités ; une partie prenante déclenche ou participe aux flux ; une politique encadre des capacités."));
  el.append(h("div", { class: "row" }, seg([["prod", "Produits"], ["stk", "Parties prenantes"], ["pol", "Politiques"]], k, (x) => { state.sub.ext = x; rerender(); })));
  const avg = (ids) => ids.reduce((a, c) => a + d.effTar[c], 0) / ids.length;
  if (k === "prod") {
    const cards = h("div", { class: "cols" });
    PRODS.forEach(p => {
      const capIds = [...new Set(p.ents.flatMap(e => ENTS.find(x => x.id === e).caps))];
      const a = avg(capIds);
      cards.append(h("div", { class: "card" }, h("div", {}, typeTag("prod")), h("h3", { style: { margin: ".3rem 0" } }, chip(p.id)),
        h("div", { class: "small" }, "Responsable : ", chip(p.bu, { short: true })),
        h("div", { class: "small", style: { marginTop: "6px" } }, h("b", {}, "Droits de service offerts")),
        ...p.ents.map(e => { const en = ENTS.find(x => x.id === e), v = avg(en.caps); return h("div", { class: "row", style: { margin: "2px 0" } }, chip(e), h("div", { class: "bar", style: { width: "80px" } }, h("i", { style: { width: v * 20 + "%", background: heat(v) } })), h("span", { class: "small" }, fmt(v))); }),
        h("div", { class: "small", style: { marginTop: "6px" } }, "Solidité des capacités habilitantes : ", h("b", { style: { color: a < 3 ? "var(--bad)" : "var(--good)" } }, fmt(a) + " / 5"))));
    });
    el.append(cards, note(h("b", {}, "Droit de service (entitlement) : "), "l'aspect service d'un produit — ce que le client est en droit d'attendre — et ce qui le rend possible. Un produit attrayant avec des capacités faibles est une promesse risquée. ", src("2.7")));
  } else if (k === "stk") {
    const tbl = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Partie prenante"), h("th", {}, "Catégorie"), VSS.map(v => h("th", { style: { cursor: "pointer" }, onclick: () => select(v.id) }, v.name)))));
    const tb = h("tbody", {});
    STKS.forEach(sk => tb.append(h("tr", {}, h("td", { style: { cursor: "pointer" }, onclick: () => select(sk.id) }, sk.name), h("td", {}, sk.cat), VSS.map(v => {
      const trig = v.trigger === sk.id, part = v.stages.filter(st => st.stk.includes(sk.id)).length;
      return h("td", { style: { textAlign: "center" } }, trig ? h("b", { class: "good" }, "déclenche") : part ? h("span", { class: "muted" }, `participe (${part})`) : "");
    }))));
    tbl.append(tb);
    el.append(h("div", { class: "card", style: { overflowX: "auto" } }, tbl), note("Chaque partie prenante est reliée aux flux de valeur : on voit qui bénéficie de la valeur et qui contribue à la livrer, y compris l'externe (client, fournisseur, certificateur). ", src("2.8")));
  } else {
    const list = h("div", { class: "cols" });
    POLS.forEach(p => { const a = avg(p.caps);
      list.append(h("div", { class: "card" }, h("div", {}, typeTag("pol")), h("h3", { style: { margin: ".3rem 0" } }, chip(p.id)),
        h("div", { class: "small" }, "Capacités encadrées :"), h("div", {}, p.caps.map(c => chip(c, { short: true }))),
        h("div", { class: "small", style: { marginTop: "6px" } }, "Exposition de conformité : ", h("b", { style: { color: a < 3 ? "var(--bad)" : a < 3.7 ? "var(--warn)" : "var(--good)" } }, a < 3 ? "élevée" : a < 3.7 ? "moyenne" : "faible"), ` (efficacité moy. ${fmt(a)})`),
        h("div", { class: "bar" }, h("i", { style: { width: a * 20 + "%", background: heat(a) } }))));
    });
    el.append(list, note("Une politique n'est pas qu'un document : elle s'applique à des capacités précises. Quand ces capacités sont faibles, le risque de non-conformité l'est aussi — et une nouvelle norme se traduit directement en capacités à renforcer (scénario « Conformité réglementaire »). ", src("2.9")));
  }
});
