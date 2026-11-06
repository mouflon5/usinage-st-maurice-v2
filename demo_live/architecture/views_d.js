"use strict";
/* ============ 12. Graphe de connaissances (5.1) : réseau « neuronal » en physique continue ============ */
state.graphPos = new Map();
state.graphView = { k: 1, x: 0, y: 0 };
state.graphHidden = new Set(["stage", "ent"]);
state.graphMode = "all"; state.graphDepth = 2;

registerView("graph", "12 · Graphe", (el) => {
  el.append(...section("Base de connaissances : le réseau des dépendances (section 5.1)",
    "Toutes les cartographies précédentes sont des vues d'un même graphe : des éléments typés reliés par les relations du métamodèle. Attrapez un nœud et tirez : ses voisins suivent comme des neurones reliés par des ressorts."));
  if (state.graphFocus) { state.sel = state.graphFocus; state.graphMode = "near"; state.graphFocus = null; renderPanel(); }
  const mode = state.graphMode, types = Object.keys(TYPES);
  el.append(h("div", { class: "card" }, h("div", { class: "row" }, seg([["all", "Tout le réseau"], ["near", "Voisinage de la sélection"]], mode, (k) => { state.graphMode = k; if (k === "near" && !state.sel) state.sel = "c_qua_nc"; rerender(); }),
    mode === "near" ? h("span", {}, "Portée : ", h("input", { type: "range", min: 1, max: 3, value: state.graphDepth, onchange: (e) => { state.graphDepth = +e.target.value; rerender(); } }), h("b", {}, state.graphDepth)) : null),
    h("div", { class: "row" }, types.map(t => h("span", { class: "chip" + (state.graphHidden.has(t) ? "" : " on"), onclick: () => { state.graphHidden.has(t) ? state.graphHidden.delete(t) : state.graphHidden.add(t); rerender(); } }, h("i", { style: { background: tcolor(t) } }), TYPES[t].label)))));

  let ids;
  if (mode === "near" && state.sel) ids = [...bfs([state.sel], state.graphDepth).keys()];
  else ids = [...NODES.keys()].filter(id => !state.graphHidden.has(NODES.get(id).type));
  const set = new Set(ids);
  const nodes = ids.map(id => {
    const n = NODES.get(id), dg = nbrs(id).length;
    return { id, label: shortName(n.name).slice(0, 28), title: `${TYPES[n.type].label} : ${n.name}`, color: tcolor(n.type), r: 5 + Math.sqrt(dg) * 1.5 + (id === state.sel ? 3 : 0), big: n.type === "strat" || n.type === "vs" || id === state.sel };
  });
  const links = EDGES.filter(e => set.has(e.a) && set.has(e.b)).map(e => ({ a: e.a, b: e.b, label: e.rel }));
  const live = liveGraph({ key: "g", width: 1000, height: 640, maxHeight: "74vh", store: state.graphPos, viewStore: state.graphView, selected: state.sel,
    nodes, links, labels: ids.length <= 45 ? "always" : "hover", linkLabels: "hover", onClick: select });
  el.append(h("div", { class: "card" }, liveControls(live.api), live.svg,
    h("div", { class: "src" }, `${nodes.length} neurones · ${links.length} synapses affichés sur ${NODES.size} éléments et ${EDGES.length} relations. La taille d'un nœud reflète son nombre de relations. ${LIVE_HELP}`)));

  /* Pivots */
  const deg = [...NODES.values()].map(n => ({ n, d: nbrs(n.id).length })).sort((a, b) => b.d - a.d).slice(0, 8);
  const caps = deg.filter(x => x.n.type === "cap").length;
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Les éléments les plus reliés (points de pivot)"),
      h("table", {}, h("tbody", {}, deg.map(x => h("tr", {}, h("td", {}, chip(x.n.id, { short: true })), h("td", {}, TYPES[x.n.type].label), h("td", {}, h("b", {}, x.d + " relations")))))),
      note(`Parmi les 8 éléments les plus connectés, ${caps} sont des capacités : la capacité est le pivot qui relie organisation, flux de valeur et information, comme le dit le guide.`)),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Lire une relation"),
      h("ul", { class: "tight" }, h("li", {}, "Stratégie ", h("i", {}, "atteint"), " un objectif ; elle ", h("i", {}, "impacte"), " flux et capacités."), h("li", {}, "Unité d'affaires ", h("i", {}, "livre"), " une capacité."), h("li", {}, "Capacité ", h("i", {}, "utilise / modifie"), " un concept d'information."),
        h("li", {}, "Partie prenante ", h("i", {}, "déclenche"), " un flux ; capacité ", h("i", {}, "habilite"), " une étape."), h("li", {}, "Initiative ", h("i", {}, "impacte"), " capacités et flux ; politique ", h("i", {}, "encadre"), " capacités.")),
      src("5.1 « Business Architecture Metamodel Definition », fig. 5.1.2"),
      h("p", { class: "small muted" }, "Outillage (5.2) : un tableur ou un outil de dessin n'interroge pas ces relations ; une base de connaissances structurée permet l'analyse d'impact que vous venez de faire."))));
});
