"use strict";
/* ============ Cycle achats-décaissements dans l'architecture d'affaires ============
   Le flux de valeur « Acheter et payer », ses capacités, ses rôles (RACI), ses concepts d'information et les tables qui les portent,
   ses politiques et contrôles, avec les indicateurs mesurés sur les données du cycle (vue « Achats et paiements » de l'application). */
const RACI_ROLES = ["Demandeur (production)", "Approvisionnements", "Comptes fournisseurs", "Contrôleur financier", "Trésorier", "Direction", "Fournisseur"];
const RACI = {
  h1: ["R", "C", "", "A", "", "A", ""], h2: ["I", "R", "C", "A", "", "I", "C"], h3: ["R", "A", "I", "", "", "", "C"],
  h4: ["", "I", "R", "A", "", "", "C"], h5: ["", "", "R", "A", "I", "I", ""], h6: ["", "", "R", "C", "A", "I", "I"],
};
const P2P_TABLES = [
  ["ic_fou", "Fournisseur", "mdm_fournisseur", "Fiche maître : statut, condition de paiement, TPS/TVQ, coordonnées bancaires masquées"],
  ["ic_cdp", "Condition de paiement", "ref_condition_paiement", "Comptant, net 30, net 45, 2 % à 10 jours net 30"],
  ["ic_evf", "Évaluation du fournisseur", "mdm_fournisseur_evaluation", "Qualité, délais, prix et conformité par trimestre"],
  ["ic_bca", "Commande d'achat", "core_commande_achat · core_commande_achat_ligne", "Niveau d'approbation selon le montant, lignes, prix convenu"],
  ["ic_rec", "Réception (contrôle matière)", "core_reception", "Quantité pesée, bon de livraison, certificat matière"],
  ["ic_ffa", "Facture fournisseur", "core_facture_fournisseur · mart_appariement_3_voies · mart_echeancier_fournisseurs", "Taxes, échéance, escompte, écarts de prix et de quantité"],
  ["ic_lop", "Lot et paiement fournisseur", "core_lot_paiement · core_paiement_fournisseur", "Double approbation, escompte pris, rapprochement bancaire"],
  ["ic_ecr", "Écriture comptable du cycle", "core_ecriture_achat · ref_compte_comptable", "Réception, facture et paiement ; débits égaux aux crédits"],
];
const P2P_ECRITURES = [
  ["Réception", "Stocks (1300) ou charge", "Achats reçus non facturés (2105)"],
  ["Facture sur commande", "Achats reçus non facturés (2105) + écart de prix (5190) + TPS (1210) + TVQ (1220)", "Comptes fournisseurs (2100)"],
  ["Facture sans commande (services publics, assurance)", "Charge (5400 ou 5300) + TPS + TVQ", "Comptes fournisseurs (2100)"],
  ["Paiement", "Comptes fournisseurs (2100)", "Encaisse (1000) + escomptes sur achats (5900)"],
];

registerView("p2p", "Achats-décaissements", p2pView, "treso");
function p2pView(el) {
  const vs = VSMAP.get("vs_p2p"), d = derive(), n = vs.stages.length;
  const A = ACH;                                              // indicateurs mesurés, ou null si l'exemple du cycle n'est pas encore créé
  const kp = (lab, v, sub, cls) => h("div", { class: "kpi" }, h("div", { class: "small muted" }, lab), h("div", { class: "v " + (cls || "") }, v), sub ? h("div", { class: "small muted" }, sub) : null);
  el.append(...section("Le cycle achats-décaissements, de la commande au paiement du fournisseur",
    "Du besoin d'achat au débit bancaire : approvisionnement, réception, comptes fournisseurs et paiement. Cette vue relie le flux de valeur « Acheter et payer » aux capacités, aux rôles, à l'information, aux politiques et aux contrôles, avec les mesures prises sur l'exemple complet de la base (vue « Achats et paiements » du menu Piloter)."));

  /* indicateurs mesurés */
  if (A) {
    const ouv = A.solde_ouvert_cents / 100, ech = A.echu_cents / 100;
    el.append(h("div", { class: "card" },
      h("div", { class: "row" }, h("b", {}, "Mesures sur les données du cycle"), h("span", { class: "muted small" }, `date de référence ${A.date_reference} · ${A.fournisseurs} fournisseurs · ${A.commandes} commandes · ${A.factures} factures · ${A.ecritures} écritures`)),
      h("div", { class: "row" },
        kp("Comptes fournisseurs ouverts", kmoney(ouv), ech > 0 ? `dont ${kmoney(ech)} échu` : "rien d'échu", ech > 0 ? "warnc" : "good"),
        kp("Délai moyen de paiement", A.dpo !== null ? fmt(A.dpo, 0) + " j" : "—", "date de facture → paiement"),
        kp("Appariées du premier coup", A.premiere !== null ? fmt(A.premiere, 0) + " %" : "—", `${A.ecarts_ouverts} écart(s) ouvert(s) · objectif 95 %`, A.premiere !== null && A.premiere >= 95 ? "good" : "warnc"),
        kp("Escomptes captés", A.escompte_capte_pct !== null ? fmt(A.escompte_capte_pct, 0) + " %" : "—", `${kmoney(A.escompte_pris_cents / 100)} pris · objectif 95 %`, A.escompte_capte_pct !== null && A.escompte_capte_pct >= 95 ? "good" : "warnc"),
        A.top_source ? kp("Première source de produits", fmt(A.top_source.part, 0) + " %", `${A.top_source.nom} · plafond 40 %`, A.top_source.part > 40 ? "bad" : "good") : null),
      h("div", { class: "row" }, "Objectifs : ", chip("o7", { short: true }), chip("o8", { short: true }), " · stratégie : ", chip("s5", { short: true }), " · initiatives : ", chip("i9", { short: true }), chip("i10", { short: true })),
      h("div", { class: "small muted" }, "Ces mesures servent de point de départ aux indicateurs k_app et k_esc de la simulation (onglet Initiatives) : la feuille de route montre ce que l'automatisation du cycle ajoute.")));
  } else {
    el.append(note("L'exemple du cycle n'est pas encore créé dans la base : ouvrez une fois la vue « Achats et paiements » (menu Piloter), puis revenez ici pour voir les mesures réelles."));
  }

  /* flux de valeur */
  const row = h("div", { class: "stages" });
  vs.stages.forEach((st, i) => row.append(h("div", { class: "stage", onclick: () => select(st.id) }, h("div", { class: "n" }, `Étape ${i + 1}`), h("b", {}, st.name), h("div", { class: "small muted", style: { marginTop: "4px" } }, "valeur : " + st.item))));
  el.append(h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Flux de valeur « Acheter et payer »"),
    h("div", { class: "row" }, h("span", {}, "Déclenché par ", chip(vs.trigger)), h("span", { class: "muted small" }, "(partie prenante interne : la production qui a besoin de la matière)")),
    row, h("div", { class: "kpi", style: { marginTop: "6px" } }, h("b", {}, "Proposition de valeur : "), vs.proposition),
    h("div", { class: "row" }, "Processus détaillé N1 → N5 : ", h("button", { class: "btn", onclick: () => { state.proc.pid = "pr5"; state.proc.focus = "pr5"; state.proc.level = 3; state.proc.sel = null; goTab("process"); } }, "Ouvrir « De la commande d'achat au paiement du fournisseur » →")),
    src("2.4 Value Stream Mapping et 3.4 Business Process")));

  /* capacités par étape */
  const caps = [...new Set(vs.stages.flatMap(st => st.caps))];
  const tbl = h("table", { style: { fontSize: ".82rem" } }, h("thead", {}, h("tr", {}, h("th", {}, "Capacité"), vs.stages.map((st, i) => h("th", { style: { textAlign: "center", cursor: "pointer" }, onclick: () => select(st.id) }, `${i + 1}`)), h("th", {}, "Importance"), h("th", {}, "Efficacité"))));
  const tb = h("tbody", {});
  caps.forEach(cid => {
    const c = CAPMAP.get(cid);
    tb.append(h("tr", {}, h("td", { style: { cursor: "pointer" }, onclick: () => select(cid) }, c.name),
      vs.stages.map(st => h("td", { style: { textAlign: "center", background: st.caps.includes(cid) ? heat(d.effTar[cid]) : "transparent", color: "#111" } }, st.caps.includes(cid) ? "●" : "")),
      h("td", { style: { textAlign: "center" } }, c.imp), h("td", { style: { fontWeight: 600 } }, fmt(d.effCur[cid]) + " → " + fmt(d.effTar[cid]))));
  });
  tbl.append(tb);
  const weak = caps.map(c => ({ c, gap: CAPMAP.get(c).imp - d.effTar[c] })).sort((a, b) => b.gap - a.gap)[0];
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Capacités qui habilitent chaque étape"), legendHeat("Couleur = efficacité cible (selon la simulation) :"), tbl,
    note(h("b", {}, "Écart le plus grand : "), `« ${CAPMAP.get(weak.c).name} » — importance ${CAPMAP.get(weak.c).imp}/5 pour une efficacité cible de ${fmt(d.effTar[weak.c])}/5. L'initiative `, chip("i9", { short: true }), " vise ces capacités."),
    src("2.2 Capability Mapping et 2.4 : croisement flux de valeur / capacités")));

  /* RACI */
  const raciCol = { R: "#2563eb", A: "#d03b3b", C: "#d9930a", I: "#8f9aa8" };
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Qui fait quoi : rôles par étape (RACI)"),
    h("div", { class: "legend" }, ["R réalise", "A responsable ultime", "C consulté", "I informé"].map(t => h("span", {}, h("span", { class: "swatch", style: { background: raciCol[t[0]] } }), t))),
    h("table", { style: { fontSize: ".82rem" } }, h("thead", {}, h("tr", {}, h("th", {}, "Étape"), RACI_ROLES.map(r => h("th", { style: { textAlign: "center" } }, r)))),
      h("tbody", {}, vs.stages.map((st, i) => h("tr", {}, h("td", { style: { cursor: "pointer" }, onclick: () => select(st.id) }, `${i + 1}. ${st.name}`),
        RACI[st.id].map(v => h("td", { style: { textAlign: "center" } }, v ? h("span", { class: "tag", style: { background: raciCol[v] } }, v) : ""))))) ),
    note(h("b", {}, "Séparation des tâches : "), "la personne qui demande n'approuve pas la commande, celle qui réceptionne ne paie pas, celle qui prépare un lot ne l'approuve pas. Le tableau le rend visible : aucune ligne n'a un seul rôle qui cumule R et A sur les étapes critiques (commande, facture, paiement). Politique : ", chip("p_sod", { short: true })),
    src("3.2 Governance : rôles et responsabilités")));

  /* information et tables */
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "L'information du cycle et les tables qui la portent"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Concept d'information", "Tables du modèle gouverné", "Contenu"].map(t => h("th", {}, t)))),
      h("tbody", {}, P2P_TABLES.map(([ic, nom, tables, contenu]) => h("tr", {}, h("td", {}, chip(ic, { short: true })), h("td", { class: "small" }, tables), h("td", { class: "small muted" }, contenu))))),
    note("Chaque table est documentée au dictionnaire de données (propriétaire, sensibilité, règle de validation) et surveillée par six règles de qualité propres au cycle : doublon de facture, total incohérent, facture sans commande, écart accepté sans motif, surpaiement, fournisseur non vérifié. Voir « Gouvernance des données » › « Modèles de données » pour le graphe des liens."),
    src("2.5 Information Mapping ; DAMA-DMBOK : données de référence, maîtres et transactionnelles")));

  /* écritures */
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Écritures comptables types du cycle (NCECF)"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Événement", "Débit", "Crédit"].map(t => h("th", {}, t)))),
      h("tbody", {}, P2P_ECRITURES.map(r => h("tr", {}, r.map((c, i) => h("td", { class: i ? "small" : "" }, c)))))),
    h("p", { class: "small muted" }, "Les achats reçus non facturés (compte 2105) sont une provision de fin de période. La TPS et la TVQ payées sont récupérables (comptes 1210 et 1220). Les escomptes pris réduisent le coût d'achat. Politique : "), chip("p_tax", { short: true })));

  /* politiques et contrôles */
  const m = (f) => A ? f(A) : null;
  const ctl = [
    ["Délégation d'autorité à trois niveaux", "Engagement au-delà de l'autorité", "p_del", "c_cmd_app", m(a => `${a.commandes_en_attente} commande(s) en attente d'approbation`)],
    ["Séparation des tâches (demander, réceptionner, approuver, payer)", "Fraude et erreur de saisie", "p_sod", "c_con_ctl", null],
    ["Appariement à trois voies, tolérances 2 % et 1 %", "Payer ce qui n'est pas reçu ou au mauvais prix", "p_app", "c_fin_app", m(a => `${a.ecarts_ouverts} écart(s) à trancher`)],
    ["Détection des factures en double", "Double paiement", "p_app", "c_fin_apa", m(a => `${a.doublons} doublon(s) détecté(s) et contesté(s)`)],
    ["Rappel de vérification des coordonnées bancaires", "Fraude au faux changement de coordonnées", "p_bnk", "c_fou_int", m(a => `${a.fournisseurs_suspendus} fournisseur(s) suspendu(s), ${a.fournisseurs_a_valider} en intégration`)],
    ["Double approbation des lots importants", "Paiement de grande valeur frauduleux", "p_pay", "c_tre_pai", m(a => `${a.lots_en_cours} lot(s) en cours d'approbation`)],
    ["Escompte pris selon le rendement", "Coût financier inutile", "p_pay", "c_tre_esc", m(a => a.escompte_capte_pct !== null ? `${fmt(a.escompte_capte_pct, 0)} % des escomptes captés` : "—")],
    ["Numéros de TPS et de TVQ des fournisseurs", "Taxes sur les intrants non récupérables", "p_tax", "c_fin_tax", null],
    ["Plafond de 40 % par source de produits", "Dépendance à un fournisseur", "p_ach", "c_fou_src", m(a => a.top_source ? `première source : ${fmt(a.top_source.part, 0)} %` : "—")],
  ];
  el.append(h("div", { class: "card", style: { overflowX: "auto" } }, h("h3", { style: { marginTop: 0 } }, "Politiques et contrôles du cycle"),
    h("table", {}, h("thead", {}, h("tr", {}, ["Contrôle", "Risque couvert", "Politique", "Capacité", "Mesure actuelle"].map(t => h("th", {}, t)))),
      h("tbody", {}, ctl.map(([c, r, p, cap, mes]) => h("tr", {}, h("td", {}, c), h("td", { class: "small muted" }, r), h("td", {}, chip(p, { short: true })), h("td", {}, chip(cap, { short: true })), h("td", { class: "small" }, mes || "—"))))),
    h("div", { class: "row" }, "Scénarios d'analyse d'impact : ", h("button", { class: "btn", onclick: () => { state.sub.scen = "sc9"; goTab("scenarios"); } }, "Fraude au changement de coordonnées →"), h("button", { class: "btn", onclick: () => { state.sub.scen = "sc10"; goTab("scenarios"); } }, "Fonds de roulement fournisseurs →")),
    src("2.9 Policy Mapping ; 3.8 Requirements")));

  /* exigences, initiatives, applications */
  const rqs = REQS.filter(r => r.stage && r.stage.startsWith("h"));
  el.append(h("div", { class: "cols" },
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Exigences d'affaires"),
      h("ul", { class: "tight" }, rqs.map(r => h("li", {}, r.name, h("div", {}, r.caps.map(c => chip(c, { short: true })), chip(r.init, { short: true }), chip(r.obj, { short: true })))))),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Applications et dette technique"),
      h("table", {}, h("thead", {}, h("tr", {}, ["Application", "Dette", "Capacités"].map(t => h("th", {}, t)))),
        h("tbody", {}, ["app_ach", "app_ap", "app_bnq", "app_erp", "app_cyc"].map(id => { const a = APPS.find(x => x.id === id); return h("tr", {}, h("td", {}, chip(id, { short: true })), h("td", { style: { background: heat(6 - a.debt), color: "#111", textAlign: "center" } }, a.debt), h("td", { class: "small muted" }, `${a.caps.length} capacités`)); }))),
      h("p", { class: "small muted" }, "La dette technique va de 1 (saine) à 5 (critique). Le chiffrier de suivi des comptes fournisseurs est l'outil à remplacer : "), chip("i9", { short: true }))));
}
