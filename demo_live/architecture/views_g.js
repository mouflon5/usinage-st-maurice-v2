"use strict";
/* Trésorerie ↔ architecture : les flux réels du journal général (tresorerie.db) reliés aux capacités, produits,
   flux de valeur, parties prenantes, agents et à la gouvernance des données. */
const CAT_RULES = [
  [/marge de cr/i, "cap", "c_tre_fin"], [/achats de produits p[ée]troliers/i, "cap", "c_fou_src"], [/salaires.*op[ée]rations/i, "cap", "c_pro_exe"],
  [/salaires.*administration/i, "cap", "c_fin_cou"], [/sous-traitance/i, "cap", "c_pro_exe"], [/[ée]quipements et consommables/i, "cap", "c_pro_out"],
  [/fret/i, "cap", "c_log_exp"], [/[ée]nergie/i, "cap", "c_pro_exe"], [/loyer/i, "cap", "c_act_mai"], [/entretien/i, "cap", "c_act_mai"],
  [/location d/i, "cap", "c_tre_fin"], [/emprunt/i, "cap", "c_tre_fin"], [/assurances/i, "cap", "c_con_rg"], [/honoraires/i, "cap", "c_fin_con"],
  [/t[ée]l[ée]communications|erp/i, "cap", "c_don_gov"], [/int[ée]r[êe]ts/i, "cap", "c_tre_fin"], [/formation/i, "cap", "c_rh_com"],
  [/d[ée]veloppement des affaires/i, "cap", "c_ent_sou"], [/d[ée]placement/i, "cap", "c_cli_rel"],
  [/usinage sur mesure/i, "prod", "pr_sur"], [/r[ée]currents/i, "prod", "pr_rec"], [/rechange/i, "prod", "pr_pdr"], [/prototypage/i, "prod", "pr_pro"],
  [/subventions/i, "cap", "c_prd_def"], [/autres revenus|r[ée]cup[ée]ration/i, "cap", "c_stk_cmp"],
];
const mapCat = (cat) => { const r = CAT_RULES.find(x => x[0].test(cat)); return r ? { kind: r[1], id: r[2] } : null; };
const STK_RULES = [
  [/kruger|marmen|arcelor|rio tinto|scierie|innovation mauricie|american iron/i, "st_cli"], [/bombardier|alstom/i, "st_exp"],
  [/acier russel|alcan|m[ée]taux solutions|sandvik|kennametal|[ée]lectro-m[ée]canique|morneau|transport robert/i, "st_fou"],
  [/galvanisation|traitement thermique/i, "st_par"], [/desjardins|banque de d[ée]veloppement/i, "st_ban"],
  [/remises rq|rsde|revenu qu[ée]bec/i, "st_reg"], [/d[ée]p[ôo]t direct/i, "st_emp"],
];
const stkOf = (nom) => { const r = STK_RULES.find(x => x[0].test(nom)); return r ? r[1] : null; };
const money = (n) => Math.round(n).toLocaleString("fr-CA").replace(/ | /g, " ") + " $";
const kmoney = (n) => (Math.abs(n) >= 1e6 ? fmt(n / 1e6, 2) + " M$" : fmt(n / 1e3, 0) + " k$");

const AGENTS_MAP = [
  ["A1", "Acquisition", "d1", ["c_tre_rap", "c_don_gov"]], ["A2", "Extraction", "d2", ["c_tre_rap", "c_don_qua"]], ["A3", "Réconciliation", "d2", ["c_tre_enc", "c_tre_dec", "c_don_qua"]],
  ["A4", "Prévision", "d3", ["c_tre_pre"]], ["A5", "Écarts", "d3", ["c_tre_ecr", "c_fin_cou"]], ["A6", "Contrôle", "d4", ["c_don_qua", "c_con_pol"]],
  ["A8", "Relecture", "d4", ["c_don_qua"]], ["A7", "Reporting", "d4", ["c_tre_fin", "c_tre_pre"]],
];

registerView("treso", "Trésorerie ↔ architecture", tresoView, "capabilities");
function tresoView(el) {
  const D = (typeof USM_DATA !== "undefined" && USM_DATA && USM_DATA.disponible) ? USM_DATA : null;
  el.append(...section("La trésorerie réelle reliée à l'architecture d'affaires",
    "Chaque flux de tresorerie.db a une raison d'être dans l'architecture : une capacité qui le consomme, un produit qui le génère, un flux de valeur qui le mobilise. Cette vue fait le lien, avec les vrais montants du journal général : c'est l'analyse d'investissement par capacité que décrit le guide."));
  if (!D) { el.append(note("Aucune donnée de trésorerie n'a été injectée dans la page. Ouvrez-la depuis la démonstration (vue « Architecture d'affaires »), ou régénérez donnees_tresorerie.js avec demo_live/architecture_data.py.")); return; }
  const S = state.sub, d = derive(), yr = S.tyear && D.annees.includes(+S.tyear) ? String(S.tyear) : String(D.exercice), yrs = D.annees.map(String);
  const amt = (c) => c.par_annee[yr] || 0;
  const rev = D.categories.filter(c => c.nature === "Revenu").reduce((a, c) => a + amt(c), 0), chg = -D.categories.filter(c => c.nature !== "Revenu").reduce((a, c) => a + amt(c), 0);
  const marge = D.facilites.find(f => /marge/i.test(f.nom)), visa = D.facilites.find(f => /visa|carte/i.test(f.nom));
  const kp = (lab, v, sub) => h("div", { class: "kpi" }, h("div", { class: "small muted" }, lab), h("div", { class: "v" }, v), sub ? h("div", { class: "small muted" }, sub) : null);
  el.append(h("div", { class: "card" },
    h("div", { class: "row" }, h("b", {}, D.entreprise), h("span", { class: "muted small" }, D.secteur), h("span", { class: "muted small" }, `· ${D.nb_mouvements} mouvements, ${D.annees[0]}–${D.annees[D.annees.length - 1]}`)),
    h("div", { class: "row" }, h("b", {}, "Exercice :"), seg(yrs.map(y => [y, "FY" + y]), yr, (k) => { S.tyear = k; rerender(); })),
    h("div", { class: "row" },
      kp("Revenus", kmoney(rev), "tous les produits"), kp("Charges et financement", kmoney(chg)), kp("Flux net", kmoney(rev - chg), `${fmt(100 * (rev - chg) / rev, 1)} % des revenus`),
      kp("Solde initial", money(D.solde_initial)), kp("Seuil de sécurité", money(D.seuil), "politique de trésorerie"),
      marge ? kp("Marge de crédit utilisée", `${fmt(100 * marge.solde / marge.limite, 0)} %`, `${money(marge.solde)} sur ${money(marge.limite)}`) : null,
      visa ? kp("Carte corporative", `${fmt(100 * visa.solde / visa.limite, 0)} %`, `${money(visa.solde)} sur ${money(visa.limite)}`) : null),
    h("div", { class: "small muted" }, "Les montants viennent de la base de la démonstration (journal général). Chips : ", chip("p_seu", { short: true }), chip("p_cov", { short: true }), chip("c_tre_fin", { short: true }))));

  /* A. charges par capacité */
  const byCap = new Map(), byProd = new Map();
  D.categories.forEach(c => {
    const m = mapCat(c.categorie); if (!m) return; const v = amt(c), tgt = m.kind === "cap" ? byCap : byProd;
    const e = tgt.get(m.id) || { chg: 0, rev: 0, cats: [] }; if (v < 0) e.chg += -v; else e.rev += v; e.cats.push(c.categorie); tgt.set(m.id, e);
  });
  const group = S.tgroup || "l2";
  let rows = [...byCap.entries()].filter(([, e]) => e.chg > 0).map(([id, e]) => ({ id, ...e, c: CAPMAP.get(id) }));
  if (group === "l1") {
    const g = {}; rows.forEach(r => { const k = r.c.l1; (g[k] = g[k] || { id: k, chg: 0, rev: 0, cats: [], caps: [] }); g[k].chg += r.chg; g[k].cats.push(...r.cats); g[k].caps.push(r.c); });
    rows = Object.values(g).map(x => ({ ...x, c: { name: CAP_L1[x.id], l1: x.id, imp: Math.max(...x.caps.map(c => c.imp)), id: null }, avgEff: x.caps.reduce((a, c) => a + d.effTar[c.id], 0) / x.caps.length }));
  } else rows.forEach(r => { r.avgEff = d.effTar[r.id]; });
  rows.sort((a, b) => b.chg - a.chg);
  const maxC = Math.max(...rows.map(r => r.chg), 1), totalC = rows.reduce((a, r) => a + r.chg, 0);
  const tb = h("tbody", {});
  rows.forEach(r => tb.append(h("tr", {}, h("td", {}, r.c.id ? chip(r.c.id, { short: true }) : h("b", {}, r.c.name)), h("td", { class: "small muted" }, [...new Set(r.cats)].map(x => x.split("(")[0].trim()).join(" · ")),
    h("td", { style: { whiteSpace: "nowrap" } }, h("div", { class: "row", style: { margin: 0, flexWrap: "nowrap" } }, h("div", { class: "bar", style: { width: "110px" } }, h("i", { style: { width: (100 * r.chg / maxC) + "%", background: heat(r.avgEff) } })), h("span", { class: "small" }, kmoney(r.chg) + " · " + fmt(100 * r.chg / totalC, 0) + " %"))),
    h("td", {}, r.c.imp), h("td", { style: { background: heat(r.avgEff), color: "#111", textAlign: "center", fontWeight: 600 } }, fmt(r.avgEff)))));
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, `Où va l'argent ? Charges FY${yr} par capacité`),
    h("div", { class: "row" }, seg([["l2", "capacités (N2)"], ["l1", "familles (N1)"]], group, (k) => { S.tgroup = k; rerender(); }), legendHeat("Couleur = efficacité cible :")),
    h("table", {}, h("thead", {}, h("tr", {}, ["Capacité", "Catégories de flux", "Charges", "Importance", "Efficacité"].map(t => h("th", {}, t)))), tb),
    note(h("b", {}, "Investissement par capacité : "), "regrouper les dépenses par capacité plutôt que par service montre où l'argent est réellement dépensé pour une même aptitude. La correspondance catégorie → capacité est un choix de modélisation, modifiable."),
    src("2.2 « Capabilities enable laser-like business investment focus »")));

  /* B. priorités */
  const prio = [...byCap.entries()].map(([id, e]) => ({ id, chg: e.chg, c: CAPMAP.get(id), gap: Math.max(0, CAPMAP.get(id).imp - d.effTar[id]) })).filter(x => x.gap > 0.4).map(x => ({ ...x, score: x.chg * x.gap / 4 })).sort((a, b) => b.score - a.score).slice(0, 8);
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Dollars mal servis : charges élevées sur des capacités encore faibles"),
      h("table", {}, h("thead", {}, h("tr", {}, ["Capacité", "Charges", "Importance", "Efficacité cible", "Écart"].map(t => h("th", {}, t)))),
        h("tbody", {}, prio.map(x => h("tr", {}, h("td", {}, chip(x.id, { short: true })), h("td", {}, kmoney(x.chg)), h("td", {}, x.c.imp), h("td", { style: { background: heat(d.effTar[x.id]), color: "#111" } }, fmt(d.effTar[x.id])), h("td", { class: "bad" }, fmt(x.gap)))))),
      h("p", { class: "small muted" }, "Score = charges × (importance − efficacité) ÷ 4. Les initiatives livrées à la date de la simulation relèvent l'efficacité et font descendre cette liste.")),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Charges mobilisées par chaque flux de valeur"),
      ...VSS.map(vs => {
        const caps = [...new Set(vs.stages.flatMap(st => st.caps))], tot = caps.reduce((a, c) => a + ((byCap.get(c) || {}).chg || 0), 0), mx = Math.max(...VSS.map(v => [...new Set(v.stages.flatMap(st => st.caps))].reduce((a, c) => a + ((byCap.get(c) || {}).chg || 0), 0)), 1);
        return h("div", { class: "row", style: { margin: "3px 0", flexWrap: "nowrap" } }, h("div", { style: { width: "250px" } }, chip(vs.id, { short: true })), h("div", { class: "bar", style: { width: "180px" } }, h("i", { style: { width: (100 * tot / mx) + "%", background: tcolor("vs") } })), h("span", { class: "small" }, kmoney(tot)));
      }),
      h("p", { class: "small muted" }, "Somme des charges des capacités qui habilitent les étapes du flux ; une capacité partagée compte dans chaque flux qu'elle habilite (double comptage voulu)."))));

  /* C. produits */
  const prow = PRODS.map(p => { const e = byProd.get(p.id); return { p, e, v: yrs.map(y => D.categories.filter(c => (mapCat(c.categorie) || {}).id === p.id).reduce((a, c) => a + (c.par_annee[y] || 0), 0)) }; });
  const ventes = prow.reduce((a, r) => a + (r.e ? r.e.rev : 0), 0);
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Revenus par produit (les quatre lignes de ventes)"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Produit", ...yrs.map(y => "FY" + y), `Part FY${yr}`, "Croissance annuelle", "Droits de service"].map(t => h("th", {}, t)))),
      h("tbody", {}, prow.map(r => { const a = r.v[0], b = r.v[r.v.length - 1], cagr = a > 0 ? (Math.pow(b / a, 1 / (r.v.length - 1)) - 1) * 100 : 0;
        return h("tr", {}, h("td", {}, chip(r.p.id, { short: true })), r.v.map(v => h("td", {}, kmoney(v))), h("td", {}, fmt(100 * (r.e ? r.e.rev : 0) / ventes, 1) + " %"), h("td", { class: cagr > 5 ? "good" : "" }, fmt(cagr, 1) + " %"), h("td", {}, r.p.ents.map(e => chip(e, { short: true }))));
      }))),
    note(h("b", {}, "Contrats récurrents : "), `${fmt(D.part_recurrents, 1)} % des ventes de l'exercice ${D.exercice}. C'est le point de départ de l'objectif `, chip("o3", { short: true }), " (cible 40 %, atteinte par l'estimation rapide et la certification AS9100). Les subventions RS&DE et la récupération de métaux sont rattachées à des capacités, pas à des produits."),
    src("2.7 Product Mapping")));

  /* D. contreparties ↔ parties prenantes */
  const grp = {};
  D.contreparties.forEach(e => { const k = stkOf(e.nom) || "autre"; const g = (grp[k] = grp[k] || { k, n: 0, nb: 0, total: 0, noms: [] }); g.n++; g.nb += e.nb; g.total += e.total; g.noms.push(e.nom); });
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Les contreparties du journal dans la carte des parties prenantes"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Partie prenante", "Contreparties", "Opérations", "Total net (4 ans)", "Exemples"].map(t => h("th", {}, t)))),
      h("tbody", {}, Object.values(grp).sort((a, b) => Math.abs(b.total) - Math.abs(a.total)).map(g => h("tr", {}, h("td", {}, g.k === "autre" ? h("span", { class: "muted" }, "Autres fournisseurs de services") : chip(g.k, { short: true })), h("td", {}, g.n), h("td", {}, g.nb),
        h("td", { class: g.total >= 0 ? "good" : "" }, (g.total >= 0 ? "+" : "−") + kmoney(g.total)), h("td", { class: "small muted" }, g.noms.slice(0, 4).join(" · ") + (g.noms.length > 4 ? " …" : "")))))),
    note("Le module de gouvernance des données (vague 1) reconnaît ces mêmes contreparties comme données maîtres : une contrepartie ambiguë devient « à valider » plutôt que d'être fusionnée en silence. Ici elles sont reliées aux parties prenantes qui déclenchent ou habilitent les flux de valeur."),
    src("2.8 Stakeholder Mapping et 5.1 (données maîtres)")));

  /* E. agents */
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Les agents du projet dans l'architecture"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Agent", "Étape du flux « Piloter la trésorerie »", "Capacités mises en œuvre", "Application"].map(t => h("th", {}, t)))),
      h("tbody", {}, AGENTS_MAP.map(([a, n, st, caps]) => h("tr", {}, h("td", {}, h("b", {}, a), " " + n), h("td", {}, chip(st, { short: true })), h("td", {}, caps.map(c => chip(c, { short: true }))), h("td", {}, chip("app_orc", { short: true })))))),
    note("L'orchestrateur est une application de l'architecture : il automatise des capacités (rapprochement, prévision, écarts, contrôle), il n'en est pas une. Remplacer un agent ne change pas la capacité, seulement la façon dont elle est réalisée.")));

  /* F. gouvernance */
  const G = D.gouvernance || {};
  if (G.initialisee) {
    const o6 = OBJMAP.get("o6"), ok = G.dq_score !== undefined && G.dq_score >= o6.target;
    el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Gouvernance des données dans l'architecture"),
      h("div", { class: "row" }, kp("Champs documentés", G.nb_champs), kp("Règles de qualité actives", G.nb_regles), kp("Exécutions tracées", G.nb_runs), kp("Fichiers sources", G.nb_fichiers), kp("Mouvements dans core_", G.nb_mouvements_core, G.nb_quarantaine ? `${G.nb_quarantaine} en quarantaine` : "aucune quarantaine"), kp("Contreparties (données maîtres)", G.nb_contreparties),
        G.dq_score !== undefined ? kp("Score de qualité (dernier contrôle)", fmt(G.dq_score, 1) + " %", ok ? "cible atteinte" : `cible ${o6.target} %`) : kp("Score de qualité", "—", "aucun contrôle exécuté")),
      h("div", { class: "row" }, "Capacités : ", chip("c_don_gov", { short: true }), chip("c_don_qua", { short: true }), " · initiatives : ", chip("i1", { short: true }), chip("i2", { short: true }), " · objectif : ", chip("o6", { short: true })),
      note("Les vagues 1 et 2 de gouvernance sont des initiatives de la feuille de route, avec des dépendances (la vague 2 suit la vague 1 ; les agents ne vont en production qu'après la vague 2). Le score observé ici est mesuré sur la base de la démonstration ; l'objectif O6 en suit la progression.")));
  }
}
