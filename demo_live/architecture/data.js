/* Groupe Usinage Saint-Maurice inc. — architecture d'affaires (BIZBOK v11), ancrée dans le projet de trésorerie.
   Entreprise fictive : usinage de précision et ensembles mécanosoudés, Trois-Rivières (Mauricie). Clients, fournisseurs, banques,
   catégories de flux et agents A1 à A8 proviennent du projet (tresorerie.db, orchestrateur). Le reste est illustratif. */
"use strict";

/* Part observée des contrats récurrents dans le journal de trésorerie (si les données sont injectées), sinon valeur d'exemple. */
const REC_BASE = (typeof USM_DATA !== "undefined" && USM_DATA.part_recurrents) ? Math.round(USM_DATA.part_recurrents) : 25;
/* Cycle achats-décaissements observé dans la base (tables core_ du cycle), sinon valeurs d'exemple. */
const ACH = (typeof USM_DATA !== "undefined" && USM_DATA.achats && USM_DATA.achats.disponible) ? USM_DATA.achats : null;
const APP_BASE = ACH && ACH.premiere !== null && ACH.premiere !== undefined ? Math.round(ACH.premiere) : 84;
const ESC_BASE = ACH && ACH.escompte_capte_pct !== null && ACH.escompte_capte_pct !== undefined ? Math.round(ACH.escompte_capte_pct) : 70;

const COMPANY = {
  nom: "Groupe Usinage Saint-Maurice inc.", court: "Groupe Usinage Saint-Maurice",
  secteur: "Usinage de précision et ensembles mécanosoudés, Trois-Rivières (Mauricie)",
  entites: ["Gestion Saint-Maurice (société de portefeuille)", "Usinage Saint-Maurice (opérante)", "Immeubles Saint-Maurice", "Soudure Bécancour (80 %, acquise le 1er avril 2025)", "USM Precision Inc. (États-Unis, USD)"],
  /* Offre : même découpage que les produits. Cas fictif, inspiré de l'usinage de précision au Québec. */
  offre: [
    ["Usinage sur mesure", "pièces de précision à la commande : fraisage 3 et 5 axes, tournage, rectification, ensembles mécanosoudés"],
    ["Contrats récurrents (aéro et rail)", "pièces certifiées en série (trains d'atterrissage, composants de bogies) avec traçabilité matière et contrôle à 100 %"],
    ["Pièces de rechange et service", "pièces de rechange pour équipements industriels, remise en état et dépannage d'atelier"],
    ["Prototypage et ingénierie", "prototypes, études techniques, programmation FAO et conception pour la fabrication"],
    ["Matières et traitements", "acier, aluminium, inox et titane ; traitement thermique, galvanisation et finition en sous-traitance"],
    ["Certifications", "AS9100 (aéronautique), ISO 9001, soudage CWB"],
  ],
  sites: [
    ["Trois-Rivières (Mauricie)", "siège social, usine d'usinage et bureau d'estimation"],
    ["Trois-Rivières — atelier de finition", "finition, contrôle dimensionnel (MMT) et expédition"],
    ["Bécancour (Centre-du-Québec)", "atelier de soudure (Soudure Bécancour, 80 %)"],
    ["Shawinigan (Mauricie)", "entrepôt de matières, d'outillage et de pièces de rechange"],
    ["États-Unis", "USM Precision Inc., filiale américaine tenue en dollars américains"],
  ],
};

const TYPES = {
  strat: { label: "Stratégie", color: "#7c5cff" },
  obj: { label: "Objectif", color: "#a07bf0" },
  vs: { label: "Flux de valeur", color: "#0d9488" },
  stage: { label: "Étape de flux", color: "#5eb8b0" },
  cap: { label: "Capacité", color: "#2563eb" },
  bu: { label: "Unité d'affaires", color: "#e08a00" },
  info: { label: "Concept d'information", color: "#16a34a" },
  init: { label: "Initiative", color: "#db2777" },
  prod: { label: "Produit", color: "#a8531a" },
  ent: { label: "Droit de service (entitlement)", color: "#c98a5a" },
  stk: { label: "Partie prenante", color: "#0891b2" },
  pol: { label: "Politique", color: "#64748b" },
  app: { label: "Application", color: "#475569" },
  proc: { label: "Processus (N3)", color: "#7aa91a" },
};

/* ---------- Unités d'affaires (2.3) ---------- */
const BUS = [
  { id: "bu_ven", name: "Ventes et service à la clientèle", parent: "bu_dg" },
  { id: "bu_ing", name: "Tarification et planification des produits", parent: "bu_dg" },
  { id: "bu_app", name: "Approvisionnements", parent: "bu_ops" },
  { id: "bu_pro", name: "Production — Usinage Saint-Maurice", parent: "bu_ops" },
  { id: "bu_sb", name: "Soudure Bécancour (80 %)", parent: "bu_ops" },
  { id: "bu_us", name: "USM Precision (États-Unis)", parent: "bu_ops" },
  { id: "bu_log", name: "Expéditions et logistique", parent: "bu_ops" },
  { id: "bu_qua", name: "Qualité et CND", parent: "bu_dg" },
  { id: "bu_adm", name: "Finances et trésorerie", parent: "bu_dg" },
  { id: "bu_ap", name: "Comptes fournisseurs et paiements", parent: "bu_dg" },
  { id: "bu_ia", name: "Données et agents IA de trésorerie", parent: "bu_dg" },
  { id: "bu_ext", name: "Sous-traitants de traitement (Mauricie)", parent: "bu_ops", external: true },
];
const BU_TREE = [
  { id: "bu_dg", name: "Groupe Usinage Saint-Maurice inc. — Direction", parent: null },
  { id: "bu_ops", name: "Opérations (regroupement)", parent: "bu_dg", group: true },
];

/* ---------- Capacités (2.2) : L1 > L2. inst = instances par unité d'affaires (efficacité 1-5) ---------- */
const CAP_L1 = {
  CLI: "Gestion des clients", PRD: "Gestion des produits", ENT: "Gestion des ententes", CMD: "Gestion des commandes",
  FOU: "Gestion des fournisseurs", PRO: "Gestion des opérations de distribution", STK: "Gestion des stocks", QUA: "Gestion de la qualité et de la sécurité",
  LOG: "Gestion de la logistique", ACT: "Gestion des actifs", FIN: "Gestion financière", TRE: "Gestion de la trésorerie",
  DON: "Gestion des données", CON: "Gestion de la conformité", RH: "Gestion des ressources humaines", IA: "Gestion des agents IA",
};
const CAPS = [
  { id: "c_cli_info", l1: "CLI", name: "Gestion de l'information client", imp: 3, inst: { bu_ven: 3, bu_adm: 3 } },
  { id: "c_cli_rel", l1: "CLI", name: "Gestion des relations clients", imp: 4, inst: { bu_ven: 3 } },
  { id: "c_prd_def", l1: "PRD", name: "Définition des produits et des grilles tarifaires", imp: 5, inst: { bu_ing: 4 } },
  { id: "c_prd_spec", l1: "PRD", name: "Gestion des spécifications des produits (qualité, additifs, normes)", imp: 5, inst: { bu_ing: 3, bu_qua: 3 } },
  { id: "c_prd_cfg", l1: "PRD", name: "Estimation et chiffrage de pièce", imp: 5, inst: { bu_ven: 2, bu_ing: 2 } },
  { id: "c_prd_cyc", l1: "PRD", name: "Gestion des gammes et des programmes CNC", imp: 4, inst: { bu_ing: 3, bu_pro: 2 } },
  { id: "c_ent_sou", l1: "ENT", name: "Gestion des offres de prix et soumissions", imp: 5, inst: { bu_ven: 2, bu_ing: 3 } },
  { id: "c_ent_con", l1: "ENT", name: "Gestion des contrats clients", imp: 4, inst: { bu_ven: 4, bu_adm: 3 } },
  { id: "c_ent_fou", l1: "ENT", name: "Gestion des ententes fournisseurs", imp: 4, inst: { bu_app: 3 } },
  { id: "c_cmd_cli", l1: "CMD", name: "Gestion des commandes clients", imp: 4, inst: { bu_ven: 4, bu_sb: 3 } },
  { id: "c_cmd_ach", l1: "CMD", name: "Gestion des commandes d'achat", imp: 4, inst: { bu_app: 4, bu_us: 3 } },
  { id: "c_fou_eva", l1: "FOU", name: "Évaluation des fournisseurs", imp: 4, inst: { bu_app: 2, bu_qua: 3 } },
  { id: "c_fou_src", l1: "FOU", name: "Gestion des sources d'approvisionnement (acier, alu, inox)", imp: 5, inst: { bu_app: 2 } },
  { id: "c_fou_rel", l1: "FOU", name: "Gestion des relations fournisseurs", imp: 3, inst: { bu_app: 3 } },
  { id: "c_pro_pla", l1: "PRO", name: "Planification de la production", imp: 5, inst: { bu_pro: 3, bu_sb: 2, bu_us: 3 } },
  { id: "c_pro_exe", l1: "PRO", name: "Exécution de la production (découpe, soudage, usinage)", imp: 5, inst: { bu_pro: 4, bu_sb: 3, bu_us: 3, bu_ext: 3 } },
  { id: "c_pro_out", l1: "PRO", name: "Gestion des outillages et plaquettes", imp: 3, inst: { bu_pro: 3 } },
  { id: "c_stk_cmp", l1: "STK", name: "Gestion des stocks de matières", imp: 4, inst: { bu_app: 3, bu_pro: 3, bu_us: 2 } },
  { id: "c_stk_fin", l1: "STK", name: "Gestion des stocks de pièces finies", imp: 3, inst: { bu_log: 3 } },
  { id: "c_qua_ins", l1: "QUA", name: "Inspection des pièces (CND, métrologie)", imp: 5, inst: { bu_qua: 4, bu_pro: 3, bu_ext: 2 } },
  { id: "c_qua_nc", l1: "QUA", name: "Gestion des incidents et des non-conformités (déversements, écarts de qualité)", imp: 5, inst: { bu_qua: 2, bu_pro: 2 } },
  { id: "c_qua_cer", l1: "QUA", name: "Gestion des certifications (soudeurs, procédés)", imp: 5, inst: { bu_qua: 2, bu_ing: 2 } },
  { id: "c_qua_tra", l1: "QUA", name: "Gestion de la traçabilité (coulées, certificats matières)", imp: 4, inst: { bu_qua: 2, bu_pro: 3 } },
  { id: "c_log_exp", l1: "LOG", name: "Gestion des expéditions", imp: 4, inst: { bu_log: 4 } },
  { id: "c_log_ret", l1: "LOG", name: "Gestion des retours et des retouches", imp: 3, inst: { bu_log: 2, bu_ven: 2 } },
  { id: "c_act_mai", l1: "ACT", name: "Maintenance des machines et du bâtiment", imp: 4, inst: { bu_pro: 3, bu_sb: 3 } },
  { id: "c_fin_fac", l1: "FIN", name: "Gestion de la facturation", imp: 4, inst: { bu_adm: 4, bu_us: 3 } },
  { id: "c_fin_cou", l1: "FIN", name: "Gestion des coûts", imp: 4, inst: { bu_adm: 3, bu_pro: 2 } },
  { id: "c_fin_con", l1: "FIN", name: "Consolidation financière du groupe", imp: 4, inst: { bu_adm: 3 } },
  { id: "c_tre_pre", l1: "TRE", name: "Prévision de trésorerie", imp: 5, inst: { bu_adm: 3 } },
  { id: "c_tre_ecr", l1: "TRE", name: "Analyse des écarts de trésorerie", imp: 4, inst: { bu_adm: 3 } },
  { id: "c_tre_rap", l1: "TRE", name: "Rapprochement bancaire", imp: 5, inst: { bu_adm: 2, bu_us: 2 } },
  { id: "c_tre_fin", l1: "TRE", name: "Gestion du financement (marge, BDC, crédit-bail)", imp: 5, inst: { bu_adm: 3 } },
  { id: "c_tre_enc", l1: "TRE", name: "Gestion des encaissements", imp: 5, inst: { bu_adm: 3, bu_us: 2 } },
  { id: "c_tre_dec", l1: "TRE", name: "Gestion des décaissements", imp: 4, inst: { bu_adm: 3, bu_app: 3 } },
  { id: "c_don_gov", l1: "DON", name: "Gouvernance des données", imp: 4, inst: { bu_adm: 2 } },
  { id: "c_don_qua", l1: "DON", name: "Gestion de la qualité des données", imp: 4, inst: { bu_adm: 2 } },
  { id: "c_con_pol", l1: "CON", name: "Gestion des politiques et des normes", imp: 4, inst: { bu_qua: 3, bu_adm: 3 } },
  { id: "c_con_rg", l1: "CON", name: "Gestion de la conformité réglementaire (SST, environnement, fiscalité)", imp: 4, inst: { bu_qua: 3, bu_adm: 3 } },
  { id: "c_rh_com", l1: "RH", name: "Gestion des compétences (soudeurs, machinistes)", imp: 4, inst: { bu_pro: 2, bu_qua: 3, bu_sb: 2 } },
  /* Cycle achats-décaissements */
  { id: "c_fou_int", l1: "FOU", name: "Intégration et qualification des fournisseurs (fiche maître, vérifications, rappel bancaire)", imp: 4, inst: { bu_app: 2, bu_ap: 2 } },
  { id: "c_cmd_app", l1: "CMD", name: "Approbation des commandes d'achat (délégation d'autorité)", imp: 4, inst: { bu_app: 3, bu_adm: 3 } },
  { id: "c_stk_rec", l1: "STK", name: "Réception et contrôle des matières", imp: 5, inst: { bu_pro: 3, bu_us: 2, bu_sb: 3 } },
  { id: "c_fin_app", l1: "FIN", name: "Appariement à trois voies (commande, réception, facture)", imp: 5, inst: { bu_ap: 2 } },
  { id: "c_fin_apa", l1: "FIN", name: "Comptes fournisseurs et échéancier de paiement", imp: 5, inst: { bu_ap: 3, bu_adm: 3 } },
  { id: "c_fin_tax", l1: "FIN", name: "Fiscalité indirecte (TPS et TVQ, crédits de taxe sur les intrants)", imp: 3, inst: { bu_adm: 3 } },
  { id: "c_tre_pai", l1: "TRE", name: "Exécution des paiements fournisseurs (lots, double approbation, EFT)", imp: 5, inst: { bu_ap: 3, bu_adm: 3 } },
  { id: "c_tre_esc", l1: "TRE", name: "Gestion des escomptes et du fonds de roulement fournisseurs", imp: 3, inst: { bu_adm: 2 } },
  { id: "c_con_ctl", l1: "CON", name: "Contrôle interne des achats et des paiements (séparation des tâches)", imp: 5, inst: { bu_adm: 3, bu_qua: 2 } },
  /* Spécialisation des agents IA de trésorerie */
  { id: "c_ia_cad", l1: "IA", name: "Cadrage et gouvernance des agents IA (tâche, risque, registre)", imp: 4, inst: { bu_ia: 2, bu_adm: 3 } },
  { id: "c_ia_don", l1: "IA", name: "Constitution des jeux de données annotés", imp: 5, inst: { bu_ia: 2, bu_adm: 2 } },
  { id: "c_ia_eva", l1: "IA", name: "Évaluation et mesure de la précision des agents", imp: 5, inst: { bu_ia: 2 } },
  { id: "c_ia_amel", l1: "IA", name: "Spécialisation des agents (consignes, contexte, règles, entraînement)", imp: 5, inst: { bu_ia: 2 } },
  { id: "c_ia_prod", l1: "IA", name: "Déploiement et surveillance des agents en production", imp: 5, inst: { bu_ia: 2, bu_adm: 2 } },
];

/* ---------- Parties prenantes (2.8) : contreparties fictives, alignées sur les libellés de tresorerie.db ---------- */
const STKS = [
  { id: "st_cli", name: "Client industriel (Kruger, Marmen, ArcelorMittal)", cat: "Client externe" },
  { id: "st_exp", name: "Client récurrent aéro et rail (Bombardier Aéro, Alstom)", cat: "Client externe" },
  { id: "st_fou", name: "Fournisseur d'acier et de consommables (Acier Russel, Alcan, Sandvik, Kennametal)", cat: "Partenaire" },
  { id: "st_par", name: "Sous-traitant de traitement (Galvanisation Shawinigan, Traitement thermique Mauricie)", cat: "Partenaire" },
  { id: "st_emp", name: "Équipe de production et d'atelier", cat: "Interne" },
  { id: "st_pm", name: "Direction et contrôleur financier", cat: "Interne" },
  { id: "st_cert", name: "Organisme de certification (CWB, exigences aéronautiques)", cat: "Réglementaire" },
  { id: "st_reg", name: "Autorités fiscales et de santé-sécurité (ARC, Revenu Québec, CNESST)", cat: "Réglementaire" },
  { id: "st_act", name: "Actionnaires (Gestion Saint-Maurice)", cat: "Interne" },
  { id: "st_aud", name: "Auditeurs externes (CPA) et comité de vérification", cat: "Réglementaire" },
  { id: "st_ban", name: "Prêteurs (Desjardins, BDC, crédit-bail)", cat: "Partenaire" },
];

/* ---------- Flux de valeur (2.4). touch/wait en jours (flux 1 seulement) ---------- */
const VSS = [
  { id: "vs_acq", name: "Acquérir une pièce usinée sur mesure", trigger: "st_cli", ext: true,
    proposition: "Produit conforme livré à temps, au prix convenu, et encaissé",
    stages: [
      { id: "a1", name: "Soumettre la demande de prix", item: "Demande reçue et comprise", caps: ["c_cli_info", "c_ent_sou"], stk: ["st_cli"], touch: 1, wait: 3 },
      { id: "a2", name: "Valider la faisabilité", item: "Faisabilité confirmée", caps: ["c_prd_spec", "c_prd_cfg", "c_fou_src"], stk: ["st_cli", "st_fou"], touch: 3, wait: 6 },
      { id: "a3", name: "Conclure l'entente", item: "Prix et fréquence garantis", caps: ["c_ent_sou", "c_ent_con", "c_fin_cou"], stk: ["st_cli"], touch: 2, wait: 8 },
      { id: "a4", name: "Approuver le premier article", item: "Premier article conforme", caps: ["c_prd_def", "c_qua_ins", "c_qua_cer", "c_pro_exe"], stk: ["st_cli", "st_cert"], touch: 5, wait: 12 },
      { id: "a5", name: "Recevoir la production", item: "Lots livrés, conformes et traçables", caps: ["c_cmd_cli", "c_pro_pla", "c_pro_exe", "c_stk_cmp", "c_qua_ins", "c_qua_tra", "c_log_exp"], stk: ["st_cli", "st_par"], touch: 12, wait: 14 },
      { id: "a6", name: "Encaisser le paiement", item: "Facture soldée, encaissement identifié", caps: ["c_fin_fac", "c_tre_enc", "c_ent_con"], stk: ["st_cli", "st_ban"], touch: 1, wait: 3 },
    ] },
  { id: "vs_dep", name: "Piloter la trésorerie", trigger: "st_pm", ext: false,
    proposition: "Rapport de trésorerie approuvé : solde prévu à 13 semaines au-dessus du seuil de sécurité",
    stages: [
      { id: "d1", name: "Acquérir les relevés bancaires", item: "Relevés complets et authentiques", caps: ["c_tre_rap", "c_don_gov"], stk: ["st_ban"] },
      { id: "d2", name: "Extraire et rapprocher les mouvements", item: "Mouvements classés et rapprochés", caps: ["c_tre_rap", "c_don_qua", "c_tre_enc", "c_tre_dec"], stk: ["st_ban"] },
      { id: "d3", name: "Prévoir et analyser les écarts", item: "Prévision à 13 semaines et écarts expliqués", caps: ["c_tre_pre", "c_tre_ecr", "c_fin_cou"], stk: ["st_pm"] },
      { id: "d4", name: "Contrôler et rapporter", item: "Rapport de trésorerie approuvé", caps: ["c_tre_fin", "c_con_pol", "c_don_qua"], stk: ["st_pm", "st_ban"] },
    ] },
  { id: "vs_app", name: "Approvisionner l'acier et les consommables", trigger: "st_emp", ext: false,
    proposition: "Matières conformes disponibles au bon moment",
    stages: [
      { id: "p1", name: "Exprimer le besoin", item: "Besoin confirmé", caps: ["c_pro_pla", "c_stk_cmp"], stk: ["st_emp"] },
      { id: "p2", name: "Sélectionner la source", item: "Source retenue", caps: ["c_fou_eva", "c_fou_src", "c_ent_fou"], stk: ["st_fou"] },
      { id: "p3", name: "Commander le produit", item: "Commande confirmée", caps: ["c_cmd_ach", "c_tre_dec"], stk: ["st_fou"] },
      { id: "p4", name: "Recevoir et inspecter", item: "Matière conforme en stock", caps: ["c_stk_cmp", "c_qua_ins", "c_fou_rel"], stk: ["st_fou", "st_emp"] },
    ] },
  { id: "vs_p2p", name: "Acheter et payer un produit ou un service", trigger: "st_emp", ext: false,
    proposition: "Produit conforme reçu au prix convenu, fournisseur payé à l'échéance, sans fraude ni double paiement",
    stages: [
      { id: "h1", name: "Exprimer et approuver le besoin", item: "Besoin approuvé selon la délégation d'autorité", caps: ["c_pro_pla", "c_stk_cmp", "c_cmd_app"], stk: ["st_emp"] },
      { id: "h2", name: "Choisir le fournisseur et commander", item: "Commande confirmée au prix convenu", caps: ["c_fou_int", "c_fou_eva", "c_fou_src", "c_ent_fou", "c_cmd_ach"], stk: ["st_fou"] },
      { id: "h3", name: "Recevoir et contrôler la matière", item: "Matière conforme au certificat, réception enregistrée", caps: ["c_stk_rec", "c_qua_ins", "c_stk_cmp"], stk: ["st_fou", "st_par", "st_emp"] },
      { id: "h4", name: "Enregistrer et apparier la facture", item: "Facture exacte, appariée à trois voies", caps: ["c_fin_apa", "c_fin_app", "c_fin_tax"], stk: ["st_fou"] },
      { id: "h5", name: "Approuver et planifier le paiement", item: "Paiement approuvé selon l'échéance et l'escompte", caps: ["c_fin_apa", "c_tre_esc", "c_con_ctl", "c_con_pol"], stk: ["st_pm", "st_aud"] },
      { id: "h6", name: "Payer et rapprocher", item: "Fournisseur payé, débit rapproché, écritures équilibrées", caps: ["c_tre_pai", "c_tre_dec", "c_tre_rap", "c_fin_con"], stk: ["st_fou", "st_ban"] },
    ] },
  { id: "vs_ia", name: "Spécialiser un agent de trésorerie", trigger: "st_pm", ext: false,
    proposition: "Agent mesuré, validé et surveillé, dont la précision sur sa tâche respecte le seuil fixé au cadrage",
    stages: [
      { id: "e1", name: "Cadrer le besoin", item: "Fiche de cadrage approuvée : tâche, métriques, seuils, risque", caps: ["c_ia_cad", "c_con_pol"], stk: ["st_pm"] },
      { id: "e2", name: "Constituer les données annotées", item: "Jeu annoté, protégé, découpé et versionné", caps: ["c_ia_don", "c_don_gov", "c_don_qua"], stk: ["st_pm"] },
      { id: "e3", name: "Mesurer la base de référence", item: "Précision de départ et erreurs classées", caps: ["c_ia_eva", "c_don_qua"], stk: ["st_pm"] },
      { id: "e4", name: "Améliorer l'agent", item: "Version améliorée, mesurée sur le jeu de validation", caps: ["c_ia_amel", "c_con_ctl", "c_don_qua"], stk: ["st_pm"] },
      { id: "e5", name: "Valider et déployer", item: "Version approuvée, déployée par étapes, retour arrière prévu", caps: ["c_ia_eva", "c_ia_prod", "c_con_ctl"], stk: ["st_pm", "st_aud"] },
      { id: "e6", name: "Surveiller et améliorer en continu", item: "Qualité suivie, dérive détectée, corrections réintégrées", caps: ["c_ia_prod", "c_ia_don", "c_ia_eva"], stk: ["st_pm"] },
    ] },
  { id: "vs_rec", name: "Traiter une réclamation", trigger: "st_cli", ext: true,
    proposition: "Problème résolu, confiance rétablie",
    stages: [
      { id: "r1", name: "Déposer la réclamation", item: "Réclamation prise en charge", caps: ["c_cli_rel", "c_qua_nc"], stk: ["st_cli"] },
      { id: "r2", name: "Analyser la cause", item: "Cause identifiée", caps: ["c_qua_nc", "c_qua_tra"], stk: ["st_cli"] },
      { id: "r3", name: "Corriger et compenser", item: "Solution livrée", caps: ["c_log_ret", "c_pro_exe"], stk: ["st_cli"] },
      { id: "r4", name: "Confirmer la résolution", item: "Client satisfait", caps: ["c_cli_rel", "c_fin_fac"], stk: ["st_cli"] },
    ] },
];

/* ---------- Information (2.5) : les concepts de trésorerie correspondent aux tables de tresorerie.db ---------- */
const INFOS = [
  { id: "ic_cli", name: "Client" }, { id: "ic_ent", name: "Entente" }, { id: "ic_prd", name: "Produit énergétique" },
  { id: "ic_spc", name: "Plan et spécification" }, { id: "ic_cmp", name: "Matière première" }, { id: "ic_fou", name: "Fournisseur" },
  { id: "ic_cmd", name: "Commande" }, { id: "ic_opr", name: "Ordre de fabrication" }, { id: "ic_lot", name: "Lot de production" },
  { id: "ic_nc", name: "Non-conformité" }, { id: "ic_cer", name: "Certification" }, { id: "ic_eqp", name: "Machine (CNC)" },
  { id: "ic_fac", name: "Facture client" }, { id: "ic_mvt", name: "Mouvement bancaire" }, { id: "ic_cpt", name: "Compte bancaire" },
  { id: "ic_prv", name: "Prévision de trésorerie" }, { id: "ic_fcl", name: "Facilité de crédit" },
  /* Cycle achats-décaissements : tables core_ et mdm_ du modèle gouverné */
  { id: "ic_dem", name: "Demande d'achat" }, { id: "ic_bca", name: "Commande d'achat" }, { id: "ic_rec", name: "Réception (contrôle matière)" },
  { id: "ic_ffa", name: "Facture fournisseur" }, { id: "ic_lop", name: "Lot et paiement fournisseur" }, { id: "ic_ecr", name: "Écriture comptable du cycle" },
  { id: "ic_evf", name: "Évaluation du fournisseur" }, { id: "ic_cdp", name: "Condition de paiement" },
];
const INFO_REL = [
  ["ic_cli", "ic_ent", "conclut", "1..*"], ["ic_ent", "ic_prd", "porte sur", "1..*"], ["ic_prd", "ic_spc", "est décrit par", "1..*"],
  ["ic_spc", "ic_cmp", "exige", "*..*"], ["ic_fou", "ic_cmp", "livre", "*..*"], ["ic_cli", "ic_cmd", "passe", "1..*"],
  ["ic_cmd", "ic_ent", "s'appuie sur", "*..1"], ["ic_cmd", "ic_opr", "génère", "1..*"], ["ic_opr", "ic_lot", "produit", "1..*"],
  ["ic_opr", "ic_eqp", "utilise", "*..*"], ["ic_lot", "ic_nc", "peut avoir", "0..*"], ["ic_prd", "ic_cer", "exige", "0..*"],
  ["ic_cmd", "ic_fac", "donne lieu à", "1..*"], ["ic_lot", "ic_cmp", "provient de", "*..*"],
  ["ic_fac", "ic_mvt", "est réglée par", "1..*"], ["ic_cpt", "ic_mvt", "contient", "1..*"], ["ic_mvt", "ic_prv", "alimente", "*..*"],
  ["ic_fcl", "ic_cpt", "est adossée à", "*..1"], ["ic_fou", "ic_mvt", "est payé par", "1..*"],
  ["ic_dem", "ic_bca", "devient", "1..1"], ["ic_fou", "ic_bca", "reçoit", "1..*"], ["ic_bca", "ic_rec", "est livrée par", "1..*"], ["ic_rec", "ic_cmp", "met en stock", "*..1"],
  ["ic_fou", "ic_ffa", "émet", "1..*"], ["ic_ffa", "ic_bca", "est appariée à", "*..1"], ["ic_ffa", "ic_rec", "est appariée à", "*..*"],
  ["ic_ffa", "ic_lop", "est réglée par", "*..1"], ["ic_lop", "ic_mvt", "se retrouve dans", "1..*"], ["ic_ffa", "ic_ecr", "génère", "1..*"], ["ic_lop", "ic_ecr", "génère", "1..*"],
  ["ic_fou", "ic_evf", "est évalué par", "1..*"], ["ic_fou", "ic_cdp", "applique", "*..1"], ["ic_cdp", "ic_ffa", "fixe l'échéance de", "1..*"],
];
/* U = utilise, M = modifie (relation capacité → information du métamodèle) */
const CAP_INFO = {
  c_cli_info: { M: ["ic_cli"] }, c_cli_rel: { U: ["ic_cli", "ic_nc"] },
  c_prd_def: { M: ["ic_prd"], U: ["ic_spc"] }, c_prd_spec: { M: ["ic_spc"], U: ["ic_cmp"] },
  c_prd_cfg: { M: ["ic_spc"], U: ["ic_prd", "ic_cmp"] }, c_prd_cyc: { M: ["ic_prd"], U: ["ic_cer", "ic_eqp"] },
  c_ent_sou: { M: ["ic_ent"], U: ["ic_cli", "ic_prd"] }, c_ent_con: { M: ["ic_ent"], U: ["ic_cli"] },
  c_ent_fou: { M: ["ic_ent"], U: ["ic_fou"] }, c_cmd_cli: { M: ["ic_cmd"], U: ["ic_ent", "ic_cli"] },
  c_cmd_ach: { M: ["ic_bca"], U: ["ic_fou", "ic_cmp", "ic_dem", "ic_cdp"] }, c_fou_eva: { M: ["ic_fou", "ic_evf"], U: ["ic_nc"] },
  c_fou_src: { M: ["ic_fou"], U: ["ic_cmp"] }, c_fou_rel: { M: ["ic_fou"] },
  c_pro_pla: { M: ["ic_opr"], U: ["ic_cmd", "ic_eqp"] }, c_pro_exe: { M: ["ic_lot", "ic_opr"], U: ["ic_spc", "ic_cmp"] },
  c_pro_out: { M: ["ic_eqp"] }, c_stk_cmp: { M: ["ic_cmp"], U: ["ic_fou"] }, c_stk_fin: { M: ["ic_lot"] },
  c_qua_ins: { M: ["ic_lot"], U: ["ic_spc"] }, c_qua_nc: { M: ["ic_nc"], U: ["ic_lot", "ic_cmp"] },
  c_qua_cer: { M: ["ic_cer"], U: ["ic_prd"] }, c_qua_tra: { U: ["ic_lot", "ic_cmp", "ic_opr"] },
  c_log_exp: { U: ["ic_lot", "ic_cmd"] }, c_log_ret: { U: ["ic_nc", "ic_cmd"] }, c_act_mai: { M: ["ic_eqp"] },
  c_fin_fac: { M: ["ic_fac"], U: ["ic_cmd", "ic_ent"] }, c_fin_cou: { U: ["ic_opr", "ic_cmp", "ic_prd"] },
  c_fin_con: { U: ["ic_fac", "ic_mvt"] },
  c_tre_pre: { M: ["ic_prv"], U: ["ic_mvt", "ic_fcl"] }, c_tre_ecr: { U: ["ic_prv", "ic_mvt"] },
  c_tre_rap: { M: ["ic_mvt"], U: ["ic_cpt"] }, c_tre_fin: { M: ["ic_fcl"], U: ["ic_prv", "ic_cpt"] },
  c_tre_enc: { M: ["ic_mvt"], U: ["ic_fac", "ic_cli"] }, c_tre_dec: { M: ["ic_mvt", "ic_lop"], U: ["ic_ffa", "ic_fou"] },
  c_fou_int: { M: ["ic_fou", "ic_cdp"], U: ["ic_cpt"] }, c_cmd_app: { M: ["ic_bca"], U: ["ic_dem"] }, c_stk_rec: { M: ["ic_rec", "ic_cmp"], U: ["ic_bca", "ic_lot"] },
  c_fin_app: { M: ["ic_ffa"], U: ["ic_bca", "ic_rec"] }, c_fin_apa: { M: ["ic_ffa", "ic_ecr"], U: ["ic_cdp", "ic_fou"] }, c_fin_tax: { U: ["ic_ffa", "ic_fou"] },
  c_tre_pai: { M: ["ic_lop", "ic_ecr"], U: ["ic_ffa", "ic_fou", "ic_cpt"] }, c_tre_esc: { U: ["ic_ffa", "ic_cdp", "ic_fcl"] }, c_con_ctl: { U: ["ic_bca", "ic_ffa", "ic_lop", "ic_fou"] },
  c_don_gov: { U: ["ic_mvt", "ic_cpt"] }, c_don_qua: { M: ["ic_mvt"], U: ["ic_cpt"] },
  c_con_pol: { U: ["ic_cer"] }, c_con_rg: { U: ["ic_prd", "ic_cmp"] }, c_rh_com: { U: ["ic_cer"] },
};

/* ---------- Politiques (2.9) ---------- */
const POLS = [
  { id: "p_iso", name: "ISO 9001 — système de gestion de la qualité", caps: ["c_qua_nc", "c_qua_ins", "c_con_pol"] },
  { id: "p_ipc", name: "CSA W47.1 — certification des soudeurs et des procédés", caps: ["c_pro_exe", "c_qua_ins", "c_qua_cer", "c_rh_com"] },
  { id: "p_ul", name: "AS9100 — exigences aéronautiques (Bombardier Aéro)", caps: ["c_qua_cer", "c_prd_def", "c_qua_tra"] },
  { id: "p_rohs", name: "Exigences environnementales (rejets, métaux, matières dangereuses)", caps: ["c_fou_eva", "c_con_rg"] },
  { id: "p_l25", name: "Loi 25 — renseignements personnels", caps: ["c_cli_info", "c_don_gov"] },
  { id: "p_cred", name: "Politique de crédit client", caps: ["c_ent_con", "c_fin_fac", "c_tre_enc"] },
  { id: "p_ach", name: "Politique d'achat : aucune source d'approvisionnement au-delà de 40 %", caps: ["c_fou_src", "c_cmd_ach"] },
  { id: "p_seu", name: "Seuil de sécurité de trésorerie : 200 000 $", caps: ["c_tre_pre", "c_tre_fin", "c_tre_dec"] },
  { id: "p_cov", name: "Clauses de la marge de crédit et du prêt BDC (Desjardins, BDC)", caps: ["c_tre_fin", "c_fin_con"] },
  { id: "p_ncecf", name: "NCECF (ASPE) — états financiers et consolidation", caps: ["c_fin_con", "c_fin_fac"] },
  { id: "p_del", name: "Délégation d'autorité d'achat : chef des approvisionnements jusqu'à 25 000 $, contrôleur jusqu'à 100 000 $, direction au-delà", caps: ["c_cmd_app", "c_cmd_ach", "c_tre_pai"] },
  { id: "p_sod", name: "Séparation des tâches : demander, réceptionner, approuver et payer sont faits par des personnes différentes", caps: ["c_con_ctl", "c_cmd_app", "c_fin_app", "c_tre_pai"] },
  { id: "p_app", name: "Appariement à trois voies : tolérance de 2 % sur le prix et de 1 % sur la quantité, sinon facture retenue", caps: ["c_fin_app", "c_fin_apa"] },
  { id: "p_pay", name: "Paiement : jeudi, double approbation au-delà de 50 000 $, escompte pris quand son rendement dépasse le coût de la marge", caps: ["c_tre_pai", "c_tre_esc"] },
  { id: "p_bnk", name: "Coordonnées bancaires d'un fournisseur : changement confirmé par rappel avant tout paiement (prévention de la fraude)", caps: ["c_fou_int", "c_con_ctl"] },
  { id: "p_tax", name: "TPS et TVQ : numéros d'inscription du fournisseur exigés pour récupérer les taxes sur les intrants", caps: ["c_fin_tax", "c_con_rg"] },
];

/* ---------- Produits et droits de service (2.7) : les quatre lignes de revenus de la trésorerie ---------- */
const PRODS = [
  { id: "pr_sur", name: "Usinage sur mesure", bu: "bu_pro", ents: ["e_tec", "e_gar", "e_tra"] },
  { id: "pr_rec", name: "Contrats récurrents (aéro et rail)", bu: "bu_ven", ents: ["e_tec", "e_gar", "e_jat", "e_tra"] },
  { id: "pr_pdr", name: "Pièces de rechange et service", bu: "bu_pro", ents: ["e_tec", "e_gar", "e_jat"] },
  { id: "pr_pro", name: "Prototypage et ingénierie", bu: "bu_ing", ents: ["e_tec", "e_tra"] },
];
const ENTS = [
  { id: "e_tec", name: "Soutien technique et conseil énergétique", caps: ["c_cli_rel", "c_prd_spec"] },
  { id: "e_gar", name: "Garantie de qualité et corrections", caps: ["c_log_ret", "c_qua_nc", "c_ent_con"] },
  { id: "e_jat", name: "Livraison juste-à-temps", caps: ["c_stk_fin", "c_log_exp", "c_pro_pla"] },
  { id: "e_tra", name: "Certificats de qualité et dossier de traçabilité", caps: ["c_qua_tra", "c_qua_cer"] },
];

/* ---------- Stratégie (2.1) ---------- */
const PERSP = ["Financier", "Client", "Processus internes", "Apprentissage et croissance"];
const OBJS = [
  { id: "o1", name: "Réduire le délai demande → livraison de 30 %", due: "2028-T2", persp: 1, kpi: "k_delai", dir: "max", target: 49, unit: "jours" },
  { id: "o2", name: "Ramener la non-conformité sous 0,5 %", due: "2029-T2", persp: 2, kpi: "k_nc", dir: "max", target: 0.5, unit: "%" },
  { id: "o3", name: "Porter les contrats récurrents (aéro et rail) à 40 % des ventes", due: "2029-T2", persp: 0, kpi: "k_rec", dir: "min", target: 40, unit: "%" },
  { id: "o4", name: "Ramener le délai d'encaissement à 45 jours", due: "2028-T1", persp: 0, kpi: "k_dso", dir: "max", target: 45, unit: "jours" },
  { id: "o5", name: "Prévoir la trésorerie à 13 semaines avec un écart sous 5 %", due: "2029-T1", persp: 2, kpi: "k_prev", dir: "max", target: 5, unit: "%" },
  { id: "o6", name: "Atteindre 98 % de qualité des données de trésorerie", due: "2028-T1", persp: 3, kpi: "k_dq", dir: "min", target: 98, unit: "%" },
  { id: "o7", name: "Apparier automatiquement 95 % des factures fournisseurs, sans écart non justifié", due: "2028-T4", persp: 2, kpi: "k_app", dir: "min", target: 95, unit: "%" },
  { id: "o8", name: "Capter 95 % des escomptes de paiement rapide offerts par les fournisseurs", due: "2029-T1", persp: 0, kpi: "k_esc", dir: "min", target: 95, unit: "%" },
];
const OBJ_CAUSE = [["o6", "o5"], ["o6", "o2"], ["o5", "o4"], ["o2", "o1"], ["o1", "o3"], ["o1", "o4"], ["o4", "o3"], ["o6", "o7"], ["o7", "o8"], ["o8", "o5"]];
const STRATS = [
  { id: "s1", name: "Estimer et soumissionner plus vite", objs: ["o1", "o3"], caps: ["c_prd_cfg", "c_ent_sou", "c_pro_pla"], vs: ["vs_acq"] },
  { id: "s2", name: "Qualité, sécurité et traçabilité de bout en bout", objs: ["o2"], caps: ["c_qua_nc", "c_qua_tra", "c_qua_cer", "c_rh_com"], vs: ["vs_rec"] },
  { id: "s3", name: "Piloter la trésorerie par les données", objs: ["o4", "o5", "o6"], caps: ["c_tre_pre", "c_tre_ecr", "c_tre_rap", "c_tre_enc", "c_don_gov", "c_don_qua", "c_ia_cad", "c_ia_don", "c_ia_eva", "c_ia_amel", "c_ia_prod"], vs: ["vs_dep", "vs_ia"] },
  { id: "s4", name: "Développer les contrats récurrents aéro et rail", objs: ["o3", "o2"], caps: ["c_ent_con", "c_qua_cer", "c_prd_def"], vs: ["vs_acq"], prods: ["pr_rec", "pr_pro"] },
  { id: "s5", name: "Acheter et payer avec rigueur : contrôler les achats, capter les escomptes, protéger la trésorerie", objs: ["o7", "o8"],
    caps: ["c_fin_app", "c_fin_apa", "c_tre_pai", "c_tre_esc", "c_con_ctl", "c_fou_int"], vs: ["vs_p2p"] },
];
const KPIS = {
  k_delai: { name: "Délai demande → livraison", unit: "jours", base: null /* calculé (Lean) */ },
  k_nc: { name: "Taux de non-conformité", unit: "%", base: 0.9 },
  k_rec: { name: "Contrats récurrents (aéro et rail), part des ventes", unit: "%", base: REC_BASE },
  k_dso: { name: "Délai moyen d'encaissement", unit: "jours", base: 58 },
  k_prev: { name: "Écart de prévision à 13 semaines", unit: "%", base: 12 },
  k_dq: { name: "Qualité des données de trésorerie (score)", unit: "%", base: 91.5 },
  k_app: { name: "Factures sur commande appariées dans les tolérances", unit: "%", base: APP_BASE },
  k_esc: { name: "Escomptes de paiement rapide captés", unit: "%", base: ESC_BASE },
};

/* ---------- Initiatives (2.6) : la feuille de route du projet de trésorerie et de l'exploitation. Trimestres "AAAA-Tn" ---------- */
const INITS = [
  { id: "i1", name: "Gouvernance des données — vague 1 (métadonnées, référence, données maîtres)", short: "Gouv. V1", start: "2026-T4", end: "2027-T1", cost: 0.15, strat: ["s3"],
    caps: { c_don_gov: 2, c_tre_rap: 1, c_fin_con: 1 }, vs: ["vs_dep"], kpi: { k_dq: 2.5 }, wait: {}, replaces: [] },
  { id: "i2", name: "Gouvernance des données — vague 2 (qualité, couches stg / core / mart)", short: "Gouv. V2", start: "2027-T2", end: "2027-T4", cost: 0.2, strat: ["s3"],
    caps: { c_don_qua: 2, c_tre_rap: 1, c_tre_ecr: 1 }, vs: ["vs_dep"], kpi: { k_dq: 3, k_prev: -1 }, wait: {}, replaces: [] },
  { id: "i3", name: "Orchestrateur multi-agents A1 → A8 en production (relevés Desjardins)", short: "Agents", start: "2027-T1", end: "2028-T1", cost: 0.4, strat: ["s3"],
    caps: { c_tre_rap: 2, c_tre_pre: 1, c_tre_ecr: 1, c_tre_enc: 1 }, vs: ["vs_dep"], kpi: { k_dq: 1, k_prev: -2, k_dso: -3 }, wait: {}, replaces: [] },
  { id: "i4", name: "Intégration bancaire automatisée (fichiers Desjardins, fin des relevés PDF)", short: "Banque", start: "2027-T2", end: "2027-T4", cost: 0.3, strat: ["s3"],
    caps: { c_tre_rap: 2, c_tre_enc: 1, c_tre_dec: 1 }, vs: ["vs_dep", "vs_acq"], kpi: { k_dso: -7 }, wait: {}, replaces: ["app_bnq"] },
  { id: "i5", name: "Prévision SARIMAX et scénarios calibrés (agents A4 et A5)", short: "Prévision", start: "2028-T2", end: "2029-T1", cost: 0.25, strat: ["s3"],
    caps: { c_tre_pre: 2, c_tre_ecr: 2, c_tre_fin: 1 }, vs: ["vs_dep"], kpi: { k_prev: -4 }, wait: {}, replaces: [] },
  { id: "i6", name: "Estimation paramétrée et soumission rapide", short: "Estimation", start: "2027-T1", end: "2027-T4", cost: 0.9, strat: ["s1"],
    caps: { c_prd_cfg: 2, c_ent_sou: 2, c_prd_spec: 1, c_cli_info: 1 }, vs: ["vs_acq"], kpi: { k_rec: 4, k_nc: -0.1, k_dso: -3 }, wait: { a1: -2, a2: -3, a3: -5 }, replaces: ["app_xls"] },
  { id: "i7", name: "Suivi de production et traçabilité des coulées (MES léger)", short: "MES", start: "2027-T1", end: "2028-T2", cost: 1.6, strat: ["s2", "s1"],
    caps: { c_pro_pla: 1, c_pro_exe: 1, c_qua_tra: 2, c_qua_ins: 1 }, vs: ["vs_acq", "vs_rec"], kpi: { k_nc: -0.2 }, wait: { a4: -3, a5: -8 }, replaces: ["app_prod"] },
  { id: "i8", name: "Certification AS9100 et développement des contrats aéro et rail", short: "AS9100", start: "2027-T3", end: "2029-T2", cost: 1.2, strat: ["s4", "s2"],
    caps: { c_qua_cer: 2, c_prd_def: 1, c_ent_con: 1, c_rh_com: 2, c_qua_nc: 2 }, vs: ["vs_acq", "vs_rec"], prods: ["pr_rec", "pr_pro"], kpi: { k_rec: 40 - REC_BASE - 4, k_nc: -0.1 }, wait: {}, replaces: ["app_qual"] },
  { id: "i9", name: "Cycle achats-décaissements automatisé (appariement à trois voies, lots à double approbation, escomptes)", short: "Achats", start: "2027-T2", end: "2028-T1", cost: 0.45, strat: ["s5", "s3"],
    caps: { c_fin_app: 2, c_fin_apa: 1, c_tre_pai: 2, c_tre_esc: 2, c_con_ctl: 1, c_fou_int: 1, c_cmd_app: 1 }, vs: ["vs_p2p"], kpi: { k_app: Math.max(1, 95 - APP_BASE - 1), k_esc: 20 }, wait: {}, replaces: ["app_ap"] },
  { id: "i10", name: "Portail fournisseurs et paiements EFT intégrés à la banque (fin des chèques et des changements de coordonnées par courriel)", short: "Portail fournisseurs", start: "2028-T2", end: "2028-T4", cost: 0.3, strat: ["s5"],
    caps: { c_fou_int: 2, c_tre_pai: 1, c_fou_rel: 1, c_con_ctl: 1 }, vs: ["vs_p2p"], kpi: { k_app: 1, k_esc: Math.max(1, 95 - ESC_BASE - 20) }, wait: {}, replaces: [] },
];
const QTR_FROM = 2026 * 4 + 3, QTR_TO = 2030 * 4 + 3; // 2026-T4 .. 2030-T4
const qIndex = (s) => { const [y, t] = s.split("-T"); return +y * 4 + (+t - 1); };
const qLabel = (i) => `${Math.floor(i / 4)}-T${(i % 4) + 1}`;

/* Dépendances entre initiatives. FS : l'aval démarre après la fin de l'amont ; FF : l'aval ne peut finir qu'après la fin de l'amont ; SS : l'aval démarre au plus tôt avec l'amont. */
const DEPS = [
  { from: "i1", to: "i2", t: "FS", why: "Les schémas stg_ / core_ de la vague 2 s'appuient sur les métadonnées et les référentiels de la vague 1." },
  { from: "i2", to: "i3", t: "FF", why: "Les agents écrivent dans stg_ / core_mouvement : la mise en production suit la vague 2." },
  { from: "i4", to: "i3", t: "FF", why: "L'intégration bancaire alimente les agents sans passer par les PDF : elle doit être prête avant leur mise en production." },
  { from: "i3", to: "i5", t: "FS", why: "La prévision calibrée s'appuie sur l'historique propre que produisent les agents en production." },
  { from: "i6", to: "i7", t: "FF", why: "Le suivi de production consomme les gammes et les nomenclatures de l'estimation paramétrée." },
  { from: "i7", to: "i8", t: "FF", why: "La certification AS9100 exige la traçabilité complète des coulées." },
  { from: "i6", to: "i8", t: "SS", why: "Les offres de prix pour contrats récurrents passent par le nouvel outil de tarification." },
  { from: "i5", to: "i8", t: "FF", why: "Les contrats récurrents sont pilotés avec les prévisions de trésorerie (marge, crédit-bail)." },
  { from: "i2", to: "i9", t: "FF", why: "Les tables core_ du cycle (commandes, factures, paiements) reposent sur les couches et les règles de qualité de la vague 2." },
  { from: "i4", to: "i9", t: "FF", why: "Le paiement par lots exige l'intégration bancaire : fichiers EFT et relevés automatiques pour le rapprochement." },
  { from: "i9", to: "i10", t: "FS", why: "Le portail fournisseurs s'appuie sur la fiche maître, l'appariement et les lots du cycle automatisé." },
  { from: "i9", to: "i5", t: "SS", why: "Les décaissements fournisseurs prévus (échéancier) alimentent la prévision de trésorerie à 13 semaines." },
];

/* ---------- Applications (6.4) : inclut les composants du projet de trésorerie ---------- */
const APPS = [
  { id: "app_erp", name: "Genius ERP (facturation, achats, commandes, stocks)", debt: 3, caps: ["c_fin_fac", "c_fin_cou", "c_cmd_ach", "c_stk_cmp", "c_cmd_cli", "c_ent_con"] },
  { id: "app_crm", name: "Suivi des clients (chiffrier partagé)", debt: 4, caps: ["c_cli_info", "c_cli_rel"] },
  { id: "app_xls", name: "Chiffriers de tarification", debt: 5, caps: ["c_ent_sou", "c_prd_cfg"] },
  { id: "app_cao", name: "CAO/FAO (plans et programmes CNC)", debt: 2, caps: ["c_prd_def", "c_prd_spec", "c_prd_cyc"] },
  { id: "app_qual", name: "Registres papier et Excel de qualité et de sécurité", debt: 5, caps: ["c_qua_nc", "c_qua_ins", "c_qua_cer", "c_qua_tra"] },
  { id: "app_wms", name: "Planification des expéditions", debt: 3, caps: ["c_stk_fin", "c_log_exp", "c_log_ret"] },
  { id: "app_prod", name: "Planification de production sur Excel", debt: 5, caps: ["c_pro_pla", "c_pro_exe"] },
  { id: "app_bnq", name: "Desjardins AccèsD Affaires (relevés PDF, virements)", debt: 4, caps: ["c_tre_enc", "c_tre_dec", "c_tre_fin", "c_tre_pai"] },
  { id: "app_ach", name: "Module Achats de Genius ERP (demandes, commandes d'achat, réceptions)", debt: 3, caps: ["c_cmd_ach", "c_cmd_app", "c_stk_rec", "c_fou_src"] },
  { id: "app_ap", name: "Chiffrier de suivi des comptes fournisseurs et des échéances", debt: 5, caps: ["c_fin_apa", "c_fin_app", "c_tre_esc", "c_fin_tax"] },
  { id: "app_cyc", name: "Cycle achats-décaissements (cycle_achats.py, tables gouvernées, vue « Achats et paiements »)", debt: 1, caps: ["c_fin_app", "c_fin_apa", "c_tre_pai", "c_tre_esc", "c_con_ctl", "c_fou_int"] },
  { id: "app_orc", name: "Orchestrateur de trésorerie (agents A1 → A8)", debt: 1, caps: ["c_tre_rap", "c_tre_pre", "c_tre_ecr", "c_tre_enc"] },
  { id: "app_db", name: "Base tresorerie.db et gouvernance des données", debt: 1, caps: ["c_don_gov", "c_don_qua"] },
  { id: "app_banc", name: "Banc d'essai et journal des appels LLM (banc_essai/, table llm_traces)", debt: 2, caps: ["c_ia_eva", "c_ia_prod"] },
  { id: "app_cons", name: "Chiffrier de consolidation du groupe", debt: 3, caps: ["c_fin_con"] },
];

/* ---------- Exigences (3.8) ---------- */
const REQS = [
  { id: "rq1", name: "Calculer un prix et un délai à partir des plans du client", caps: ["c_ent_sou", "c_prd_cfg"], stage: "a3", init: "i6", obj: "o1" },
  { id: "rq2", name: "Tracer chaque pièce jusqu'à la coulée d'acier d'origine", caps: ["c_qua_tra", "c_stk_cmp"], stage: "a5", init: "i7", obj: "o2" },
  { id: "rq3", name: "Identifier automatiquement chaque encaissement client sur la facture", caps: ["c_tre_enc", "c_tre_rap"], stage: "a6", init: "i4", obj: "o4" },
  { id: "rq4", name: "Alerter quand le solde prévu passe sous le seuil de 200 000 $", caps: ["c_tre_pre", "c_tre_fin"], stage: "d3", init: "i5", obj: "o5" },
  { id: "rq5", name: "Router une réclamation selon sa gravité et le client", caps: ["c_qua_nc", "c_cli_rel"], stage: "r1", init: "i8", obj: "o2" },
  { id: "rq6", name: "Retenir toute facture hors tolérance (2 % prix, 1 % quantité) tant qu'un approbateur n'a pas tranché avec motif", caps: ["c_fin_app", "c_con_ctl"], stage: "h4", init: "i9", obj: "o7" },
  { id: "rq7", name: "Exiger deux approbateurs distincts, différents du préparateur, pour tout lot de paiement supérieur à 50 000 $", caps: ["c_tre_pai", "c_con_ctl"], stage: "h6", init: "i9", obj: "o7" },
  { id: "rq8", name: "Prendre l'escompte 2/10 net 30 dès que son rendement annualisé dépasse le coût de la marge de crédit", caps: ["c_tre_esc", "c_tre_pai"], stage: "h5", init: "i9", obj: "o8" },
  { id: "rq9", name: "Suspendre tout paiement après un changement de coordonnées bancaires non confirmé par rappel", caps: ["c_fou_int", "c_con_ctl"], stage: "h2", init: "i10", obj: "o7" },
];

/* ---------- Expérience client (3.13) : satisfaction du client commercial par étape (1-5) ---------- */
const CX = {
  a1: { s: 3, pain: "Demandes de prix reçues par téléphone et courriel, accusé de réception manuel" },
  a2: { s: 2, pain: "Aucune réponse de faisabilité pendant 6 jours" },
  a3: { s: 2, pain: "Prix du jour recalculé à la main dans plusieurs versions du chiffrier" },
  a4: { s: 3, pain: "Premier article conforme mais rapport d'inspection tardif" },
  a5: { s: 3, pain: "Livraisons partielles, certificats matières fournis sur demande" },
  a6: { s: 4, pain: "Facture exacte ; relances de paiement parfois mal ciblées" },
};

/* ---------- Modèle d'affaires (3.3) ---------- */
const BMC = [
  { k: "Partenaires clés", items: ["Acier Russel, Alcan, Métaux Solutions (matières)", "Galvanisation Shawinigan, Traitement thermique Mauricie", "Desjardins, BDC (financement)"], caps: ["c_fou_src", "c_fou_rel", "c_tre_fin"] },
  { k: "Activités clés", items: ["Découpe, roulage et soudage", "Usinage CNC de précision", "Contrôle non destructif (CND)"], caps: ["c_pro_exe", "c_prd_def", "c_qua_ins"] },
  { k: "Ressources clés", items: ["Centres d'usinage CNC et robots de soudage", "Soudeurs et machinistes certifiés", "Plans, gammes et programmes CAO/FAO"], caps: ["c_pro_out", "c_rh_com", "c_prd_cyc"] },
  { k: "Propositions de valeur", items: ["Précision et qualité sur mesure", "Traçabilité complète des matières", "Installation et service après-vente"], caps: ["c_prd_cfg", "c_qua_tra", "c_qua_cer"] },
  { k: "Relations clients", items: ["Représentants régionaux", "Offres de prix personnalisées", "Service à la clientèle"], caps: ["c_cli_rel", "c_log_ret"] },
  { k: "Canaux", items: ["Bureau d'estimation", "Salon industriel de Montréal", "Contrats-cadres (aéro, rail)"], caps: ["c_ent_sou", "c_cmd_cli"] },
  { k: "Segments de clientèle", items: ["Pâtes et papiers (Kruger)", "Éolien et sidérurgie (Marmen, ArcelorMittal)", "Aéronautique et ferroviaire (Bombardier, Alstom)"], caps: ["c_cli_info", "c_ent_con"] },
  { k: "Structure de coûts", items: ["Matières premières et sous-traitance", "Salaires, énergie Hydro-Québec", "Crédit-bail CNC, emprunt BDC, intérêts"], caps: ["c_fin_cou", "c_cmd_ach", "c_tre_dec"] },
  { k: "Sources de revenus", items: ["Usinage sur mesure", "Contrats récurrents (aéro et rail)", "Pièces de rechange, prototypage, RS&DE"], caps: ["c_fin_fac", "c_tre_enc", "c_ent_con"] },
];

/* ---------- Scénarios (partie 4) ---------- */
const SCENARIOS = [
  { id: "sc1", name: "Analyse d'investissement en initiatives", desc: "Vérifier que les initiatives sont alignées sur les objectifs et sans chevauchement (scénario 1).", seeds: [], special: "overlap" },
  { id: "sc2", name: "Lancement d'une ligne de prototypage et d'ingénierie", desc: "Quels flux, capacités et unités sont touchés par la croissance des contrats aéro et du prototypage ? (scénario 4).", seeds: ["pr_pro", "s4"] },
  { id: "sc3", name: "Rationalisation de la chaîne d'approvisionnement", desc: "Le fournisseur d'acier principal tombe en rupture (scénario 7).", seeds: ["st_fou", "vs_app"] },
  { id: "sc4", name: "Externalisation d'une capacité", desc: "Confier davantage de traitements et d'usinage aux sous-traitants de la Mauricie (scénario 6).", seeds: ["bu_ext", "c_pro_exe"] },
  { id: "sc5", name: "Conformité réglementaire", desc: "Nouvelle exigence environnementale sur les rejets et les métaux (scénario 9).", seeds: ["p_rohs"] },
  { id: "sc6", name: "Réduction des coûts opérationnels", desc: "Cibler les capacités à forte importance et faible efficacité (scénario 11).", seeds: [], special: "gap" },
  { id: "sc7", name: "Resserrement de la marge de crédit", desc: "Les prêteurs durcissent les clauses de la marge : que touche la trésorerie ?", seeds: ["st_ban", "p_cov"] },
  { id: "sc8", name: "Intégration d'une acquisition (Soudure Bécancour)", desc: "Consolider une filiale acquise : capacités, données et initiatives touchées (scénario 3).", seeds: ["bu_sb", "c_fin_con"] },
  { id: "sc9", name: "Fraude au faux changement de coordonnées bancaires d'un fournisseur", desc: "Un courriel demande de payer un fournisseur sur un nouveau compte : quels contrôles, capacités et politiques sont sollicités ?", seeds: ["c_fou_int", "p_bnk", "st_fou"] },
  { id: "sc10", name: "Optimisation du fonds de roulement fournisseurs", desc: "Payer plus tôt pour capter les escomptes, ou plus tard pour préserver la trésorerie : quels flux, politiques et initiatives sont touchés ?", seeds: ["c_tre_esc", "p_pay", "c_tre_pai"] },
];

/* ---------- Pratique : niveaux du BAMM (3.9) ---------- */
const BAMM = [
  { n: 1, name: "Initial", d: "Aucune discipline d'architecture d'affaires, ou démarche informelle et déconnectée." },
  { n: 2, name: "Géré", d: "Quelques cartographies et pratiques ; gouvernance définie mais pas toujours appliquée ; mandat clair." },
  { n: 3, name: "Défini", d: "Domaines noyau cartographiés dans la base de connaissances (capacités, flux, information, organisation) ; rôles formels." },
  { n: 4, name: "Exécuté stratégiquement", d: "L'architecture d'affaires oriente la transformation et les initiatives ; gouvernance d'entreprise." },
  { n: 5, name: "Pleinement intégré", d: "La performance des capacités et des flux pilote la sélection de projets ; fonction reconnue comme partenaire stratégique." },
];
const BAMM_DIMS = ["Cartographie des domaines noyau", "Gouvernance", "Rôles et compétences", "Base de connaissances", "Alignement (Lean, BPM, expérience client)", "Usage dans la stratégie"];

/* ---------- Gouvernance (3.2) ---------- */
const GOV = [
  { dom: "Capacités", owner: "Contrôleur financier (architecte d'affaires)", comite: "Comité de direction", freq: "Annuelle (stable)" },
  { dom: "Flux de valeur", owner: "Propriétaires de flux", comite: "Comité de direction", freq: "Semestrielle" },
  { dom: "Information", owner: "Gouvernance des données (module de gouvernance)", comite: "Comité des données", freq: "Annuelle" },
  { dom: "Organisation", owner: "Direction générale", comite: "Direction", freq: "À chaque acquisition ou réorganisation" },
  { dom: "Stratégie et initiatives", owner: "Direction et contrôleur financier", comite: "Comité d'investissement", freq: "Trimestrielle" },
  { dom: "Politiques", owner: "Qualité, sécurité et environnement, finances", comite: "Comité de conformité", freq: "À chaque changement de norme ou de clause" },
  { dom: "Cycle achats-décaissements", owner: "Contrôleur financier (propriétaire du flux « Acheter et payer »)", comite: "Comité de vérification", freq: "Contrôles : trimestrielle ; délégation d'autorité : annuelle" },
];

/* ---------- Définitions des domaines (fig. 1.1 et 5.1.1) ---------- */
const DOMAINS = [
  { id: "d_cap", core: true, name: "Capacités", t: "cap", def: "Ce que l'entreprise fait (aptitude ou capacité), jamais le comment.", ex: "Prévision de trésorerie" },
  { id: "d_vs", core: true, name: "Flux de valeur", t: "vs", def: "Description de bout en bout de la façon dont une partie prenante obtient de la valeur.", ex: "Acquérir une pièce usinée sur mesure" },
  { id: "d_org", core: true, name: "Organisation", t: "bu", def: "Unités d'affaires, internes ou externes, qui livrent les capacités.", ex: "Production — Usinage Saint-Maurice" },
  { id: "d_inf", core: true, name: "Information", t: "info", def: "Concepts d'affaires et leur sémantique, utilisés ou modifiés par les capacités.", ex: "Mouvement bancaire, Lot livré" },
  { id: "d_str", core: false, name: "Stratégie", t: "strat", def: "Plan qui intègre buts, politiques et séquences d'actions ; atteint des objectifs mesurables.", ex: "Piloter la trésorerie par les données" },
  { id: "d_ini", core: false, name: "Initiatives", t: "init", def: "Ligne de conduite exécutée ou retenue pour exécution ; touche capacités et flux.", ex: "Orchestrateur multi-agents A1 → A8" },
  { id: "d_pro", core: false, name: "Produits", t: "prod", def: "Expérience globale offerte par la combinaison de biens et de services.", ex: "Contrats récurrents (aéro et rail)" },
  { id: "d_stk", core: false, name: "Parties prenantes", t: "stk", def: "Individus ou organisations ayant un intérêt dans l'obtention de valeur.", ex: "Desjardins, BDC, Kruger" },
  { id: "d_pol", core: false, name: "Politiques", t: "pol", def: "Principes d'action adoptés par l'organisation ou imposés à elle.", ex: "Seuil de sécurité de 200 000 $" },
];
/* relations du métamodèle (fig. 5.1.2) — sens : [de, vers, verbe] */
const META_EDGES = [
  ["d_str", "d_ini", "est réalisée par"], ["d_str", "d_vs", "impacte"], ["d_str", "d_cap", "impacte"],
  ["d_org", "d_cap", "livre"], ["d_cap", "d_inf", "utilise / modifie"], ["d_stk", "d_vs", "déclenche"],
  ["d_vs", "d_cap", "est habilité par"], ["d_ini", "d_vs", "impacte"], ["d_ini", "d_cap", "impacte"],
  ["d_pro", "d_org", "appartient à"], ["d_pro", "d_cap", "est habilité par"], ["d_pol", "d_cap", "encadre"],
];

/* ---------- Construction du graphe de connaissances (5.1) ---------- */
const NODES = new Map();
const EDGES = [];
function addNode(id, type, name, extra) { NODES.set(id, Object.assign({ id, type, name }, extra || {})); }
function addEdge(a, b, rel) { if (NODES.has(a) && NODES.has(b)) EDGES.push({ a, b, rel }); else console.warn("arête ignorée", a, b); }

STRATS.forEach(s => addNode(s.id, "strat", s.name));
OBJS.forEach(o => addNode(o.id, "obj", o.name));
BUS.forEach(b => addNode(b.id, "bu", b.name, { external: !!b.external }));
CAPS.forEach(c => addNode(c.id, "cap", c.name, { l1: c.l1 }));
STKS.forEach(s => addNode(s.id, "stk", s.name));
VSS.forEach(v => { addNode(v.id, "vs", v.name); v.stages.forEach(s => addNode(s.id, "stage", s.name, { vs: v.id })); });
INFOS.forEach(i => addNode(i.id, "info", i.name));
POLS.forEach(p => addNode(p.id, "pol", p.name));
PRODS.forEach(p => addNode(p.id, "prod", p.name));
ENTS.forEach(e => addNode(e.id, "ent", e.name));
INITS.forEach(i => addNode(i.id, "init", i.name));
APPS.forEach(a => addNode(a.id, "app", a.name));

STRATS.forEach(s => {
  s.objs.forEach(o => addEdge(s.id, o, "atteint"));
  s.caps.forEach(c => addEdge(s.id, c, "impacte"));
  s.vs.forEach(v => addEdge(s.id, v, "impacte"));
  (s.prods || []).forEach(p => addEdge(s.id, p, "cible"));
});
CAPS.forEach(c => Object.keys(c.inst).forEach(b => addEdge(b, c.id, "livre")));
VSS.forEach(v => {
  addEdge(v.trigger, v.id, "déclenche");
  v.stages.forEach(s => {
    addEdge(v.id, s.id, "contient");
    s.caps.forEach(c => addEdge(c, s.id, "habilite"));
    s.stk.forEach(k => { if (k !== v.trigger) addEdge(k, s.id, "participe à"); });
  });
});
Object.entries(CAP_INFO).forEach(([c, r]) => { (r.U || []).forEach(i => addEdge(c, i, "utilise")); (r.M || []).forEach(i => addEdge(c, i, "modifie")); });
POLS.forEach(p => p.caps.forEach(c => addEdge(p.id, c, "encadre")));
PRODS.forEach(p => { addEdge(p.bu, p.id, "possède"); p.ents.forEach(e => addEdge(p.id, e, "offre")); });
ENTS.forEach(e => e.caps.forEach(c => addEdge(c, e.id, "habilite")));
INITS.forEach(i => {
  i.strat.forEach(s => addEdge(i.id, s, "réalise"));
  Object.keys(i.caps).forEach(c => addEdge(i.id, c, "impacte"));
  i.vs.forEach(v => addEdge(i.id, v, "impacte"));
  (i.prods || []).forEach(p => addEdge(i.id, p, "livre"));
  (i.replaces || []).forEach(a => addEdge(i.id, a, "remplace"));
});
APPS.forEach(a => a.caps.forEach(c => addEdge(a.id, c, "automatise")));
INFO_REL.forEach(([a, b, v]) => addEdge(a, b, v));
