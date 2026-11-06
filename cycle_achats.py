"""Cycle achats-décaissements de Groupe Usinage Saint-Maurice : de la commande d'achat au paiement du fournisseur.

Exemple complet et cohérent, rejouable, stocké dans la base (tables gouvernées de sql/07_achats.sql) :

  1 Besoin et commande d'achat   approbation selon la délégation d'autorité (3 niveaux)
  2 Réception                    contrôle à la réception, bon de livraison, certificat matière
  3 Facture du fournisseur       enregistrement, TPS et TVQ, échéance, escompte
  4 Appariement à trois voies    commande / réception / facture, tolérances de prix et de quantité
  5 Approbation et échéance      écarts tranchés par le contrôleur, comptes fournisseurs
  6 Paiement                     lot préparé, double approbation (séparation des tâches), exécution, escompte
  7 Rapprochement et écritures   débit bancaire retrouvé au relevé, écritures équilibrées

Les montants sont des entiers en cents. Les dates de l'exemple sont calculées à partir d'une date de référence (aujourd'hui à la génération)
pour que l'échéancier ait toujours des factures courantes, échues et à venir. Les fonctions d'action (`approuver_facture`, `creer_lot`,
`approuver_lot`, `executer_lot`) appliquent les contrôles du cycle et lèvent `ErreurCycle` quand une règle est violée.
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import date, timedelta

_DOSSIER = os.path.dirname(os.path.abspath(__file__))
SQL = os.path.join(_DOSSIER, "tresorerie_gouvernance", "sql", "07_achats.sql")
TABLES = ["core_ecriture_achat", "core_paiement_fournisseur", "core_lot_paiement", "core_facture_fournisseur", "core_reception",
          "core_commande_achat_ligne", "core_commande_achat", "mdm_fournisseur_evaluation", "mdm_fournisseur"]

PARAMETRES = {
    "tolerance_prix_pct": ("2", "Tolérance d'appariement sur le prix (%)"),
    "tolerance_quantite_pct": ("1", "Tolérance d'appariement sur la quantité (%)"),
    "seuil_niveau_1": ("25000", "Commande jusqu'à ce montant : approuvée par le chef des approvisionnements ($)"),
    "seuil_niveau_2": ("100000", "Commande jusqu'à ce montant : approuvée par le contrôleur financier ($)"),
    "seuil_niveau_3": ("250000", "Au-delà du niveau 2 : approuvée par la direction générale ($)"),
    "seuil_double_approbation": ("50000", "Lot de paiement dont le total exige deux approbateurs ($)"),
    "taux_tps_pct": ("5", "Taux de TPS (%)"),
    "taux_tvq_pct": ("9.975", "Taux de TVQ (%)"),
}
ROLES = {1: "Chef des approvisionnements", 2: "Contrôleur financier", 3: "Direction générale"}
PREPARATEUR = "Commis aux comptes fournisseurs"
ETAPES = [
    ("besoin", "Besoin d'achat", "Responsable de la production", "La production exprime le besoin (stock de barres sous le seuil, programme de fabrication)."),
    ("commande", "Commande d'achat", "Chef des approvisionnements", "Commande émise au fournisseur retenu, avec prix, quantité et date."),
    ("approbation_commande", "Approbation de la commande", "Selon le montant", "Délégation d'autorité à trois niveaux, jamais le demandeur."),
    ("reception", "Réception et contrôle matière", "Magasinier", "Quantité reçue pesée ou comptée, bon de livraison, certificat de conformité matière."),
    ("facture", "Facture du fournisseur", "Commis aux comptes fournisseurs", "Enregistrement : numéro, taxes, échéance, escompte."),
    ("appariement", "Appariement à trois voies", "Système (puis contrôleur)", "Commande, réception et facture comparées ; écarts hors tolérance retenus."),
    ("approbation_facture", "Approbation et échéance", "Contrôleur financier", "Facture approuvée, mise à l'échéancier des comptes fournisseurs."),
    ("paiement", "Lot de paiement", "Commis, puis deux approbateurs", "Lot préparé selon l'échéance et l'escompte ; double approbation au-delà du seuil."),
    ("rapprochement", "Rapprochement et écritures", "Trésorier", "Débit retrouvé au relevé bancaire ; écritures équilibrées."),
]


class ErreurCycle(Exception):
    """Une règle de contrôle du cycle empêche l'action demandée."""


# --------------------------------------------------------------------------- #
# Connexion et état
# --------------------------------------------------------------------------- #
def connecter(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=15)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def schema_present(c: sqlite3.Connection) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE name = 'core_facture_fournisseur'").fetchone() is not None


def gouvernance_presente(c: sqlite3.Connection) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE name = 'mdm_contrepartie'").fetchone() is not None


def parametres(c: sqlite3.Connection) -> dict:
    p = {k: float(v[0]) for k, v in PARAMETRES.items()}
    try:
        for cle, val in c.execute("SELECT cle, valeur FROM parametres WHERE domaine = 'achats'"):
            try:
                p[cle] = float(val)
            except ValueError:
                p[cle] = val
    except sqlite3.Error:
        pass
    return p


def date_reference(c: sqlite3.Connection) -> date:
    p = parametres(c)
    try:
        return date.fromisoformat(str(p.get("date_reference")))
    except (TypeError, ValueError):
        return date.today()


def assurer(db: str) -> bool:
    """Crée le schéma si besoin, génère l'exemple s'il est absent, synchronise dictionnaire et règles qualité. Retourne True si l'exemple est prêt."""
    c = connecter(db)
    try:
        if not gouvernance_presente(c):
            return False
        if not schema_present(c):
            c.executescript(open(SQL, encoding="utf-8").read())
            c.execute("PRAGMA foreign_keys = ON")
            _synchroniser_gouvernance(c)
        if c.execute("SELECT COUNT(*) FROM mdm_fournisseur").fetchone()[0] == 0:
            generer(c)
        return True
    finally:
        c.close()


def _synchroniser_gouvernance(c: sqlite3.Connection) -> None:
    gouv = os.path.join(_DOSSIER, "tresorerie_gouvernance")
    if gouv not in sys.path:
        sys.path.insert(0, gouv)
    try:
        import dictionnaire
        import dq_runner
        dq_runner.charger_regles(c)
        dictionnaire.construire_dictionnaire(c)
    except Exception:                                                     # noqa: BLE001  l'exemple reste utilisable sans la synchronisation
        pass


# --------------------------------------------------------------------------- #
# Calculs purs (utilisés par la génération, les actions et le simulateur)
# --------------------------------------------------------------------------- #
def taxes(ht_cents: int, tps_pct: float = 5.0, tvq_pct: float = 9.975) -> tuple[int, int, int]:
    """(TPS, TVQ, total) en cents. Les deux taxes sont calculées sur le montant avant taxes."""
    tps = int(round(ht_cents * tps_pct / 100))
    tvq = int(round(ht_cents * tvq_pct / 100))
    return tps, tvq, ht_cents + tps + tvq


def niveau_approbation(montant_ht_cents: int, p: dict | None = None) -> int:
    p = p or {k: float(v[0]) for k, v in PARAMETRES.items()}
    m = montant_ht_cents / 100
    return 1 if m <= p["seuil_niveau_1"] else 2 if m <= p["seuil_niveau_2"] else 3


def simuler_appariement(qte_commandee: float, prix_commande: float, qte_recue: float, qte_facturee: float, prix_facture: float,
                        tol_prix_pct: float = 2.0, tol_qte_pct: float = 1.0) -> dict:
    """Appariement à trois voies sur une ligne. Prix en cents par unité. Le prix est comparé à la commande, la quantité facturée à la quantité reçue
    (on ne paie que ce qui est entré au magasin). Retourne les écarts, la valeur payable et la décision."""
    ecart_prix = 0.0 if prix_commande == 0 else (prix_facture - prix_commande) / prix_commande * 100
    ecart_qte = 0.0 if qte_recue == 0 else (qte_facturee - qte_recue) / qte_recue * 100
    sur_commande = qte_facturee > qte_commandee * (1 + tol_qte_pct / 100)
    motifs = []
    if abs(ecart_prix) > tol_prix_pct:
        motifs.append(f"prix facturé {ecart_prix:+.1f} % par rapport à la commande (tolérance {tol_prix_pct:g} %)")
    if abs(ecart_qte) > tol_qte_pct:
        motifs.append(f"quantité facturée {ecart_qte:+.1f} % par rapport à la quantité reçue (tolérance {tol_qte_pct:g} %)")
    if sur_commande:
        motifs.append("quantité facturée supérieure à la quantité commandée")
    facture = qte_facturee * prix_facture
    commande = qte_commandee * prix_commande
    recu = qte_recue * prix_commande
    return {"ecart_prix_pct": round(ecart_prix, 2), "ecart_quantite_pct": round(ecart_qte, 2), "conforme": not motifs, "motifs": motifs,
            "facture_cents": round(facture), "commande_cents": round(commande), "recu_cents": round(recu),
            "ecart_cents": round(facture - recu), "decision": "appariée : prête à approuver" if not motifs else "retenue : écart à trancher"}


def escompte_annualise_pct(escompte_pct: float, jours_escompte: int, jours_net: int) -> float:
    """Rendement annualisé de l'escompte : 2/10 net 30 vaut environ 37 % par an. Compare au coût de la marge de crédit."""
    if jours_net <= jours_escompte or escompte_pct <= 0:
        return 0.0
    return escompte_pct / (100 - escompte_pct) * 365 / (jours_net - jours_escompte) * 100


def ecritures_facture(facture: dict, recu_ht: int | None, compte_charge: str = "5400") -> list[tuple]:
    """Lignes d'écriture (compte, débit, crédit, libellé) à l'enregistrement d'une facture. Équilibrées par construction."""
    ht, tps, tvq, total = facture["montant_ht_cents"], facture["tps_cents"], facture["tvq_cents"], facture["total_cents"]
    lignes = []
    if recu_ht is not None:                                              # facture sur commande : la réception avait inscrit 2105
        lignes.append(("2105", recu_ht, 0, "Solde des achats reçus non facturés"))
        ecart = ht - recu_ht
        if ecart > 0:
            lignes.append(("5190", ecart, 0, "Écart sur prix d'achat"))
        elif ecart < 0:
            lignes.append(("5190", 0, -ecart, "Écart sur prix d'achat"))
    else:
        lignes.append((compte_charge, ht, 0, "Charge facturée sans commande"))
    lignes += [("1210", tps, 0, "TPS à recevoir"), ("1220", tvq, 0, "TVQ à recevoir"), ("2100", 0, total, "Comptes fournisseurs")]
    return lignes


# --------------------------------------------------------------------------- #
# Génération de l'exemple
# --------------------------------------------------------------------------- #
# nom, famille, condition, statut, produits [(produit, unité, prix en cents par unité, compte, qté min, qté max)], nb de commandes, note de base, courriel
FOURNISSEURS = [
    ("Acier Russel Trois-Rivières", "matiere_premiere", "N30", "actif",
     [("Acier 1018 — barre ronde", "kg", 285.0, "1300", 6000, 18000), ("Acier 4140 — barre ronde", "kg", 345.0, "1300", 4000, 14000), ("Acier mécanosoudé — plaque", "kg", 265.0, "1300", 8000, 24000)], 30, 4.2),
    ("Alcan Distribution", "matiere_premiere", "2_10_N30", "actif",
     [("Aluminium 6061-T6 — barre", "kg", 780.0, "1300", 2400, 8000), ("Aluminium 7075-T651 — plaque", "kg", 1150.0, "1300", 1600, 5000)], 16, 4.0),
    ("Métaux Solutions Québec", "matiere_premiere", "N30", "actif",
     [("Inox 304/316 — barre", "kg", 1250.0, "1300", 1200, 4000), ("Titane Ti-6Al-4V — barre", "kg", 6800.0, "1300", 160, 600)], 12, 4.4),
    ("Groupe Morneau", "transport", "N45", "actif", [("Transport par camion remorque (voyage)", "voyage", 142000.0, "5200", 1, 4)], 8, 3.8),
    ("Transport Robert", "transport", "N30", "actif", [("Livraison de pièces usinées (tournée)", "tournée", 38500.0, "5200", 2, 10)], 14, 4.1),
    ("Kennametal Canada", "fournitures", "N30", "actif", [("Plaquettes de carbure et fraises", "lot", 42500.0, "1310", 1, 6)], 6, 4.3),
    ("Sandvik Coromant Canada", "fournitures", "N30", "actif", [("Outils de coupe et porte-outils", "lot", 31500.0, "1310", 2, 8)], 6, 3.9),
    ("Hydro-Québec", "service_public", "N30", "actif", [], 0, 4.5),
    ("CSMO-M (formation industrielle)", "services_professionnels", "N30", "actif", [("Formation SST et usinage CNC (session)", "session", 168700.0, "5300", 1, 2)], 3, 4.6),
    ("Assurance Intact", "services_professionnels", "COMPTANT", "actif", [], 0, 4.2),
    ("Galvanisation Shawinigan", "sous_traitance", "N30", "actif", [("Galvanisation à chaud (lot)", "lot", 185000.0, "5300", 1, 3)], 8, 3.7),
    ("Traitement thermique Mauricie", "sous_traitance", "N30", "actif", [("Traitement thermique (charge)", "charge", 96000.0, "5300", 1, 4)], 6, 4.0),
    ("Vidéotron Affaires", "service_public", "N30", "actif", [], 0, 3.6),
    ("Outillage Sorel inc.", "fournitures", "N30", "a_valider", [], 0, None),
    ("Genius ERP", "services_professionnels", "N30", "suspendu", [("Soutien ERP (forfait)", "forfait", 640000.0, "5300", 1, 1)], 1, 3.2),
]
SITES = ["Trois-Rivières (usine)", "Trois-Rivières (finition)", "Bécancour (soudure)", "Shawinigan (entrepôt)"]
DEMANDEURS = ["Responsable de la production (usine)", "Responsable de la finition", "Planificateur de production", "Responsable de l'atelier de soudure"]
RECURRENTS = {"Hydro-Québec": (1180000, "5400", "Électricité de l'usine"), "Vidéotron Affaires": (420000, "5400", "Téléphonie et Internet"),
              "Assurance Intact": (3850000, "5300", "Prime d'assurance mensuelle")}


def _jeudi_suivant(d: date) -> date:
    return d + timedelta(days=(3 - d.weekday()) % 7)


def _jeudi_precedent(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 3) % 7)


def generer(c: sqlite3.Connection, ref: date | None = None, graine: int = 20261028) -> dict:
    """(Re)génère l'exemple complet. Retourne les compteurs par table."""
    rnd = random.Random(graine)
    ref = ref or date.today()
    p = {k: float(v[0]) for k, v in PARAMETRES.items()}
    for t in TABLES:
        c.execute(f"DELETE FROM {t}")
    c.execute("CREATE TABLE IF NOT EXISTS parametres (domaine TEXT NOT NULL, cle TEXT NOT NULL, valeur TEXT NOT NULL, type_valeur TEXT NOT NULL, libelle TEXT, PRIMARY KEY (domaine, cle))")
    for cle, (val, lib) in PARAMETRES.items():
        c.execute("INSERT OR REPLACE INTO parametres (domaine, cle, valeur, type_valeur, libelle) VALUES ('achats', ?, ?, 'float', ?)", (cle, val, lib))
    c.execute("INSERT OR REPLACE INTO parametres (domaine, cle, valeur, type_valeur, libelle) VALUES ('achats', 'date_reference', ?, 'date', "
              "'Date de référence de l''exemple du cycle achats-décaissements')", (ref.isoformat(),))
    conds = {r[0]: r[1:] for r in c.execute("SELECT code, jours_net, jours_escompte, escompte_pct FROM ref_condition_paiement")}
    sites = {n: s for s, n in c.execute("SELECT site_id, nom FROM mdm_site")}
    compte_banque = (c.execute("SELECT compte_id FROM mdm_compte WHERE actif = 1 ORDER BY compte_id LIMIT 1").fetchone() or [None])[0]
    approb = {1: ROLES[1], 2: ROLES[2], 3: ROLES[3]}

    # -------------------------------------------------- fournisseurs
    ids, produits = {}, {}
    for k, (nom, famille, cond, statut, prods, _n, note) in enumerate(FOURNISSEURS):
        modif = (ref - timedelta(days=9)).isoformat() if statut == "suspendu" else None
        cp = c.execute("SELECT contrepartie_id FROM mdm_contrepartie WHERE upper(nom_canonique) LIKE ? ORDER BY contrepartie_id LIMIT 1",
                       (f"%{nom.upper().split(' - ')[0][:14]}%",)).fetchone()
        cur = c.execute(
            "INSERT INTO mdm_fournisseur (nom_legal, contrepartie_id, famille_achat, condition_code, statut, no_tps, no_tvq, courriel_facturation, compte_bancaire_masque, "
            "coordonnees_modifiees_le, rappel_verifie, note_globale, approuve_par, approuve_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nom, cp[0] if cp else None, famille, cond, statut, f"{rnd.randint(100000000, 999999999)} RT0001", f"{rnd.randint(1000000000, 1999999999)} TQ0001",
             "factures@" + "".join(ch for ch in nom.lower() if ch.isalnum())[:18] + ".example", f"****{rnd.randint(1000, 9999)}", modif,
             0 if statut == "suspendu" else 1, note, None if statut == "a_valider" else ROLES[2], None if statut == "a_valider" else (ref - timedelta(days=200 + k * 7)).isoformat()))
        ids[nom] = cur.lastrowid
        produits[nom] = prods
    # évaluations : trois derniers trimestres
    trimestres = []
    for dec in (2, 1, 0):
        d = ref - timedelta(days=91 * dec)
        trimestres.append(f"{d.year}-T{(d.month - 1) // 3 + 1}")
    for nom, famille, cond, statut, prods, _n, note in FOURNISSEURS:
        if note is None:
            continue
        for tri in trimestres:
            def n(delta=0.0):
                return round(min(5, max(1, note + delta + rnd.uniform(-0.4, 0.4))), 1)
            c.execute("INSERT INTO mdm_fournisseur_evaluation (fournisseur_id, trimestre, note_qualite, note_delai, note_prix, note_conformite) VALUES (?,?,?,?,?,?)",
                      (ids[nom], tri, n(0.1), n(), n(-0.1), n(0.05)))
        dern = c.execute("SELECT (note_qualite + note_delai + note_prix + note_conformite) / 4 FROM mdm_fournisseur_evaluation WHERE fournisseur_id = ? ORDER BY trimestre DESC LIMIT 1",
                         (ids[nom],)).fetchone()[0]
        c.execute("UPDATE mdm_fournisseur SET note_globale = ? WHERE fournisseur_id = ?", (round(dern, 1), ids[nom]))

    # -------------------------------------------------- commandes, réceptions, factures
    no_cmd, no_fact = 400, 61000
    commandes = []                       # (commande_id, nom_fournisseur, [(ligne_id, produit, qte, prix, compte)], statut, date_reception, ht)
    anomalies = {"prix": 0, "quantite": 0}
    for nom, famille, cond, statut, prods, n_cmd, _note in FOURNISSEURS:
        if not prods or statut == "a_valider":
            continue
        for _ in range(n_cmd):
            d0 = ref - timedelta(days=rnd.randint(0, 150))
            if statut == "suspendu":
                d0 = ref - timedelta(days=21)
            lignes = []
            for prod in rnd.sample(prods, k=min(len(prods), 1 if rnd.random() < 0.75 else 2)):
                produit, unite, prix, compte, qmin, qmax = prod
                q = float(rnd.randrange(int(qmin), int(qmax) + 1, 1000 if qmax > 1000 else 1))
                lignes.append((produit, unite, q, prix, compte))
            ht = sum(int(round(q * pr)) for _, _, q, pr, _ in lignes)
            lead = rnd.randint(2, 6) if famille == "matiere_premiere" else rnd.randint(1, 10)
            prevue = d0 + timedelta(days=lead)
            niv = niveau_approbation(ht, p)
            no_cmd += 1
            demandeur = rnd.choice(DEMANDEURS)
            site = rnd.choice(SITES)
            commandes.append((nom, famille, cond, lignes, d0, prevue, ht, niv, no_cmd, demandeur, site))
    # exemple de départ, toujours présent : aluminium d'Alcan Distribution (2/10 net 30) commandé il y a 24 jours ; prix du jour facturé, écart tranché, escompte pris
    no_cmd += 1
    d0 = ref - timedelta(days=24)
    ht = int(round(3200 * 780.0))
    commandes.append(("Alcan Distribution", "matiere_premiere", "2_10_N30", [("Aluminium 6061-T6 — barre", "kg", 3200.0, 780.0, "1300")], d0, d0 + timedelta(days=3), ht,
                      niveau_approbation(ht, p), no_cmd, DEMANDEURS[0], "Trois-Rivières (usine)"))
    phare_no = no_cmd
    commandes.sort(key=lambda x: x[4])

    for nom, famille, cond, lignes, d0, prevue, ht, niv, no, demandeur, site in commandes:
        fid = ids[nom]
        jours_net, jours_esc, esc_pct = conds[cond]
        statut_cmd = "approuvee"
        reception_date = prevue + timedelta(days=rnd.choice([0, 0, 0, 1, 1, 2]))
        recue = statut_cmd != "attente_approbation" and reception_date <= ref
        cur = c.execute(
            "INSERT INTO core_commande_achat (no_commande, fournisseur_id, site_id, site_livraison, demandeur, date_commande, date_livraison_prevue, statut, montant_ht_cents, "
            "approuve_par, approuve_le, niveau_approbation) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"BC-{d0.year}-{no:04d}", fid, sites.get(site), site, demandeur, d0.isoformat(), prevue.isoformat(), statut_cmd, ht,
             None if statut_cmd == "attente_approbation" else approb[niv], None if statut_cmd == "attente_approbation" else d0.isoformat(), niv))
        cid = cur.lastrowid
        lids = []
        for i, (produit, unite, q, prix, compte) in enumerate(lignes, 1):
            lid = c.execute("INSERT INTO core_commande_achat_ligne (commande_id, no_ligne, produit, unite, quantite, prix_unitaire_cents, montant_cents, compte_code) VALUES (?,?,?,?,?,?,?,?)",
                            (cid, i, produit, unite, q, prix, int(round(q * prix)), compte)).lastrowid
            lids.append((lid, produit, q, prix, compte))
        if not recue:
            continue
        # ---- réception
        recues = []
        bl = f"BL-{rnd.randint(70000, 79999)}"
        for lid, produit, q, prix, compte in lids:
            facteur = 1.0
            if famille == "matiere_premiere" and rnd.random() < 0.18:
                facteur = 1 - rnd.uniform(0.012, 0.03)                 # écart de pesée
            qr = round(q * facteur, 0 if q > 100 else 2)
            conforme = 0 if (famille == "matiere_premiere" and rnd.random() < 0.03) else 1
            c.execute("INSERT INTO core_reception (ligne_id, no_bon_livraison, date_reception, quantite_recue, conforme, recu_par, commentaire) VALUES (?,?,?,?,?,?,?)",
                      (lid, bl, reception_date.isoformat(), qr, conforme, "Magasinier" if famille != "sous_traitance" else "Responsable de la production",
                       "Écart de pesée" if facteur < 1 else ("Non-conformité à traiter avec le fournisseur" if not conforme else None)))
            recues.append((lid, produit, q, prix, compte, qr))
        recu_ht = sum(int(round(qr * pr)) for _, _, _, pr, _, qr in recues)
        c.execute("UPDATE core_commande_achat SET statut = ? WHERE commande_id = ?", ("recue", cid))
        _ecriture(c, f"ECR-R-{no}", reception_date, "reception", f"BC-{d0.year}-{no:04d}",
                  [(cmp, int(round(qr * pr)), 0, f"Réception {pr_}") for _, pr_, _, pr, cmp, qr in recues] + [("2105", 0, recu_ht, "Achats reçus non facturés")])
        # ---- facture
        date_fact = reception_date + timedelta(days=rnd.choice([0, 1, 1, 2]))
        if date_fact > ref:
            continue                                                    # reçu non facturé : reste en 2105
        prix_f, qte_f, motif = 1.0, None, None
        tirage = rnd.random()
        recent = (ref - date_fact).days <= 9                              # davantage d'écarts encore ouverts pour la démonstration
        if no == phare_no:
            prix_f, motif = 1.024, "Prix du jour facturé au lieu du prix convenu"
            anomalies["prix"] += 1
        elif famille in ("matiere_premiere", "transport") and tirage < (0.45 if recent else 0.11):
            prix_f = 1 + rnd.uniform(0.022, 0.05)                       # prix du jour facturé au lieu du prix convenu
            motif = "Prix du jour facturé"
            anomalies["prix"] += 1
        elif famille == "matiere_premiere" and tirage < (0.6 if recent else 0.17):
            qte_f = "commande"                                           # facturé sur la quantité commandée au lieu de la quantité reçue
            motif = "Facturé sur la quantité commandée"
            anomalies["quantite"] += 1
        ht_f = 0
        for lid, produit, q, prix, compte, qr in recues:
            qf = q if qte_f == "commande" else qr
            ht_f += int(round(qf * prix * prix_f))
        ep = round((ht_f - recu_ht) / recu_ht * 100, 2) if recu_ht else 0.0
        eq = round((sum(q for _, _, q, _, _, _ in recues) - sum(qr for *_, qr in recues)) / max(sum(qr for *_, qr in recues), 1) * 100, 2) if qte_f == "commande" else 0.0
        if prix_f != 1.0:
            ep, eq = round((prix_f - 1) * 100, 2), 0.0
        elif qte_f == "commande":
            ep = 0.0
        tps, tvq, total = taxes(ht_f, p["taux_tps_pct"], p["taux_tvq_pct"])
        no_fact += 1
        recu_f = date_fact + timedelta(days=rnd.choice([0, 1, 1, 2]))
        echeance = date_fact + timedelta(days=int(jours_net))
        lim_esc = date_fact + timedelta(days=int(jours_esc)) if jours_esc else None
        escompte = int(round(ht_f * esc_pct / 100)) if jours_esc else 0
        hors = abs(ep) > p["tolerance_prix_pct"] or abs(eq) > p["tolerance_quantite_pct"]
        _facture(c, rnd, ref, fid, nom, cond, str(no_fact), cid, date_fact, recu_f, echeance, lim_esc, ht_f, tps, tvq, total, escompte, ep, eq, hors, motif,
                 niv, recu_ht, compte_banque, p, famille, phare=(no == phare_no))

    # -------------------------------------------------- achats récurrents sans commande (services publics, assurance) et cas particuliers
    for nom, (base, compte, lib) in RECURRENTS.items():
        fid = ids[nom]
        jours_net = conds[[f[2] for f in FOURNISSEURS if f[0] == nom][0]][0]
        for m in range(5):
            d = ref.replace(day=1) - timedelta(days=30 * m)
            d = d.replace(day=min(5, 28))
            if d > ref:
                continue
            ht_f = int(base * rnd.uniform(0.92, 1.1))
            tps, tvq, total = taxes(ht_f, p["taux_tps_pct"], p["taux_tvq_pct"])
            no_fact += 1
            _facture(c, rnd, ref, fid, nom, "COMPTANT" if nom == "Assurance Intact" else "N30", str(no_fact), None, d, d + timedelta(days=1), d + timedelta(days=int(jours_net)),
                     None, ht_f, tps, tvq, total, 0, None, None, False, None, 1, None, compte_banque, p, "service_public", compte=compte)
    _cas_particuliers(c, rnd, ref, ids, conds, compte_banque, p)
    _commandes_en_attente(c, ref, ids, sites, p)
    _lot_en_cours(c, rnd, ref, compte_banque, p)
    c.commit()
    return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES[::-1]}


def _ecriture(c, no, d, evenement, ref_doc, lignes):
    for compte, deb, cred, lib in lignes:
        if deb or cred:
            c.execute("INSERT INTO core_ecriture_achat (no_ecriture, date_ecriture, evenement, document_ref, compte_code, debit_cents, credit_cents, libelle) VALUES (?,?,?,?,?,?,?,?)",
                      (no, d.isoformat(), evenement, ref_doc, compte, deb, cred, lib))


def _facture(c, rnd, ref, fid, nom, cond, no_f, cid, date_fact, recu_f, echeance, lim_esc, ht, tps, tvq, total, escompte, ep, eq, hors, motif, niv, recu_ht, banque, p, famille,
             compte="5400", phare=False):
    """Insère la facture dans l'état qu'elle aurait à la date de référence (appariée, retenue, approuvée, en lot ou payée) et ses écritures."""
    anc = (ref - recu_f).days
    approb = ROLES[2]
    statut, par, le, mot = "recue", None, None, None
    if anc >= 1:
        statut = "appariee" if not hors else "ecart"
    if not hors and anc >= 2:
        statut, par, le = "approuvee", approb, (recu_f + timedelta(days=2)).isoformat()
    if hors:
        mot = motif
        if anc >= 11 and rnd.random() < 0.8:
            statut, par, le = "approuvee", approb, (recu_f + timedelta(days=rnd.randint(3, 8))).isoformat()    # tranché par le contrôleur
        elif anc >= 11:
            statut = "contestee"
        if phare:                                                        # tranché vite : l'escompte est encore à prendre
            statut, par, le = "approuvee", approb, (recu_f + timedelta(days=2)).isoformat()
    cur = c.execute(
        "INSERT INTO core_facture_fournisseur (no_facture, fournisseur_id, commande_id, date_facture, date_reception_facture, date_echeance, date_limite_escompte, montant_ht_cents, tps_cents, tvq_cents, "
        "total_cents, escompte_cents, ecart_prix_pct, ecart_quantite_pct, statut, approuve_par, approuve_le, motif_ecart) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (no_f, fid, cid, date_fact.isoformat(), recu_f.isoformat(), echeance.isoformat(), lim_esc.isoformat() if lim_esc else None, ht, tps, tvq, total, escompte, ep, eq, statut, par, le, mot))
    fact_id = cur.lastrowid
    fact = {"montant_ht_cents": ht, "tps_cents": tps, "tvq_cents": tvq, "total_cents": total}
    _ecriture(c, f"ECR-F-{fact_id:05d}", recu_f, "facture", no_f, [(a, b, cc, d) for a, b, cc, d in ecritures_facture(fact, recu_ht, compte)])
    if statut == "approuvee":
        _planifier_paiement(c, rnd, ref, fact_id, fid, cond, echeance, lim_esc, ht, total, escompte, banque, p, date.fromisoformat(le))


def _planifier_paiement(c, rnd, ref, fact_id, fid, cond, echeance, lim_esc, ht, total, escompte, banque, p, approuvee_le):
    """Paiement le jeudi qui précède l'échéance (ou la date limite d'escompte), jamais avant l'approbation. Exécuté si la date est passée, sinon la facture reste approuvée."""
    cible = lim_esc if (lim_esc and escompte) else echeance
    jeudi = _jeudi_precedent(cible)
    if jeudi <= approuvee_le:
        jeudi = _jeudi_suivant(approuvee_le + timedelta(days=1))
    retard = rnd.random() < 0.06                                         # quelques paiements en retard
    if retard:
        jeudi = jeudi + timedelta(days=14)
    if jeudi > ref:
        return
    row = c.execute("SELECT lot_id FROM core_lot_paiement WHERE date_paiement = ? AND statut = 'execute'", (jeudi.isoformat(),)).fetchone()
    if row:
        lot = row[0]
    else:
        lot = c.execute("INSERT INTO core_lot_paiement (no_lot, date_paiement, mode_paiement, compte_id, statut, prepare_par, approbateur_1, approbateur_2) VALUES (?,?,?,?,?,?,?,?)",
                        (f"LOT-{jeudi:%Y-%m-%d}", jeudi.isoformat(), "EFT", banque, "execute", PREPARATEUR, ROLES[2], ROLES[3])).lastrowid
    prise = escompte if (lim_esc and escompte and jeudi <= lim_esc) else 0
    montant = total - prise
    c.execute("UPDATE core_facture_fournisseur SET statut = 'payee', escompte_cents = ? WHERE facture_id = ?", (escompte, fact_id))
    rapproche = "RAPPROCHE" if (ref - jeudi).days >= 2 else "NON_RAPPROCHE"
    c.execute("INSERT INTO core_paiement_fournisseur (lot_id, facture_id, fournisseur_id, montant_cents, escompte_pris_cents, statut_rapprochement) VALUES (?,?,?,?,?,?)",
              (lot, fact_id, fid, montant, prise, rapproche))
    _ecriture(c, f"ECR-P-{lot}-{fact_id}", jeudi, "paiement", f"LOT-{jeudi:%Y-%m-%d}",
              [("2100", total, 0, "Règlement du fournisseur"), ("1000", 0, montant, "Débit bancaire (EFT)"), ("5900", 0, prise, "Escompte de paiement rapide")])


def _cas_particuliers(c, rnd, ref, ids, conds, banque, p):
    """Cas qui illustrent les contrôles : doublon de facture, facture sans commande hors préautorisé, fournisseur suspendu, produit non conforme."""
    # doublon : même numéro que la plus récente facture de Acier Russel Trois-Rivières
    f = c.execute("SELECT no_facture, commande_id, date_facture, montant_ht_cents, tps_cents, tvq_cents, total_cents, date_echeance FROM core_facture_fournisseur WHERE fournisseur_id = ? "
                  "AND commande_id IS NOT NULL ORDER BY date_facture DESC LIMIT 1", (ids["Acier Russel Trois-Rivières"],)).fetchone()
    if f:
        d = date.fromisoformat(f[2]) + timedelta(days=3)
        c.execute("INSERT INTO core_facture_fournisseur (no_facture, fournisseur_id, commande_id, date_facture, date_reception_facture, date_echeance, montant_ht_cents, tps_cents, tvq_cents, total_cents, "
                  "statut, motif_ecart) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (f[0], ids["Acier Russel Trois-Rivières"], f[1], d.isoformat(), min(d, ref).isoformat(), f[7], f[3], f[4], f[5], f[6], "contestee", "Facture en double : même numéro déjà enregistré"))
    # facture sans bon de commande chez un fournisseur de fournitures
    ht = 214800
    tps, tvq, total = taxes(ht, p["taux_tps_pct"], p["taux_tvq_pct"])
    d = ref - timedelta(days=4)
    cur = c.execute("INSERT INTO core_facture_fournisseur (no_facture, fournisseur_id, commande_id, date_facture, date_reception_facture, date_echeance, montant_ht_cents, tps_cents, tvq_cents, total_cents, "
                    "statut, motif_ecart) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("KC-88214", ids["Kennametal Canada"], None, d.isoformat(), d.isoformat(), (d + timedelta(days=30)).isoformat(), ht, tps, tvq, total, "ecart", "Aucune commande d'achat trouvée"))
    _ecriture(c, f"ECR-F-{cur.lastrowid:05d}", d, "facture", "KC-88214", ecritures_facture({"montant_ht_cents": ht, "tps_cents": tps, "tvq_cents": tvq, "total_cents": total}, None, "5300"))
    # fournisseur suspendu : facture approuvée qui ne pourra pas être payée tant que le rappel n'est pas fait
    cmd = c.execute("SELECT commande_id FROM core_commande_achat WHERE fournisseur_id = ?", (ids["Genius ERP"],)).fetchone()
    if cmd:
        ht = 640000
        tps, tvq, total = taxes(ht, p["taux_tps_pct"], p["taux_tvq_pct"])
        d = ref - timedelta(days=8)
        cur = c.execute("INSERT INTO core_facture_fournisseur (no_facture, fournisseur_id, commande_id, date_facture, date_reception_facture, date_echeance, montant_ht_cents, tps_cents, tvq_cents, total_cents, "
                        "statut, approuve_par, approuve_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("GE-2026-077", ids["Genius ERP"], cmd[0], d.isoformat(), d.isoformat(), (d + timedelta(days=30)).isoformat(), ht, tps, tvq, total, "approuvee", ROLES[2],
                         (d + timedelta(days=2)).isoformat()))
        c.execute("UPDATE core_commande_achat SET statut = 'recue' WHERE commande_id = ?", (cmd[0],))
        _ecriture(c, f"ECR-F-{cur.lastrowid:05d}", d, "facture", "GE-2026-077", ecritures_facture({"montant_ht_cents": ht, "tps_cents": tps, "tvq_cents": tvq, "total_cents": total}, None, "5300"))


def _commandes_en_attente(c, ref, ids, sites, p):
    """Deux commandes récentes qui attendent leur approbation : niveau 3 (direction) et niveau 2 (contrôleur)."""
    for nom, produit, unite, q, prix, compte, site in (("Acier Russel Trois-Rivières", "Acier 4140 — barre ronde", "kg", 70000.0, 345.0, "1300", "Trois-Rivières (usine)"),
                                                      ("Métaux Solutions Québec", "Inox 304/316 — barre", "kg", 3500.0, 1250.0, "1300", "Bécancour (soudure)")):
        ht = int(round(q * prix))
        n = c.execute("SELECT COALESCE(MAX(CAST(substr(no_commande, 9) AS INTEGER)), 400) + 1 FROM core_commande_achat").fetchone()[0]
        cid = c.execute("INSERT INTO core_commande_achat (no_commande, fournisseur_id, site_id, site_livraison, demandeur, date_commande, date_livraison_prevue, statut, montant_ht_cents, niveau_approbation) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (f"BC-{ref.year}-{n:04d}", ids[nom], sites.get(site), site, "Planificateur de production", (ref - timedelta(days=1)).isoformat(), (ref + timedelta(days=4)).isoformat(),
                         "attente_approbation", ht, niveau_approbation(ht, p))).lastrowid
        c.execute("INSERT INTO core_commande_achat_ligne (commande_id, no_ligne, produit, unite, quantite, prix_unitaire_cents, montant_cents, compte_code) VALUES (?,?,?,?,?,?,?,?)",
                  (cid, 1, produit, unite, q, prix, ht, compte))


def exemple_phare(c: sqlite3.Connection) -> int | None:
    """Commande qui sert d'exemple de bout en bout : facture hors tolérance tranchée puis payée ; sinon la plus récente commande payée."""
    base = ("SELECT f.commande_id FROM core_facture_fournisseur f JOIN core_paiement_fournisseur p ON p.facture_id = f.facture_id "
            "JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE f.commande_id IS NOT NULL ")
    for sql in (base + "AND o.famille_achat = 'matiere_premiere' AND ABS(COALESCE(f.ecart_prix_pct, 0)) > 2 AND f.motif_ecart IS NOT NULL AND p.escompte_pris_cents > 0 ORDER BY f.date_facture DESC LIMIT 1",
                base + "AND o.famille_achat = 'matiere_premiere' AND ABS(COALESCE(f.ecart_prix_pct, 0)) > 2 AND f.motif_ecart IS NOT NULL ORDER BY f.date_facture DESC LIMIT 1",
                base + "AND o.famille_achat = 'matiere_premiere' AND p.escompte_pris_cents > 0 ORDER BY f.date_facture DESC LIMIT 1",
                base + "AND o.famille_achat = 'matiere_premiere' ORDER BY f.date_facture DESC LIMIT 1",
                base + "ORDER BY f.date_facture DESC LIMIT 1"):
        r = c.execute(sql).fetchone()
        if r:
            return r[0]
    return None


def _lot_en_cours(c, rnd, ref, banque, p):
    """Prochain lot du jeudi : préparé, première approbation donnée, seconde en attente (démonstration de la double approbation)."""
    jeudi = _jeudi_suivant(ref if ref.weekday() != 3 else ref + timedelta(days=1))
    lim = jeudi + timedelta(days=7)
    rows = c.execute("SELECT f.facture_id FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE f.statut = 'approuvee' AND o.statut = 'actif' "
                     "AND (f.date_echeance <= ? OR (f.date_limite_escompte IS NOT NULL AND f.date_limite_escompte <= ?)) ORDER BY f.date_echeance", (lim.isoformat(), lim.isoformat())).fetchall()
    if not rows:
        return
    lot = c.execute("INSERT INTO core_lot_paiement (no_lot, date_paiement, mode_paiement, compte_id, statut, prepare_par, approbateur_1) VALUES (?,?,?,?,?,?,?)",
                    (f"LOT-{jeudi:%Y-%m-%d}", jeudi.isoformat(), "EFT", banque, "approuve_1", PREPARATEUR, ROLES[2])).lastrowid
    for (fid_,) in rows:
        fa = c.execute("SELECT fournisseur_id, total_cents, escompte_cents, date_limite_escompte FROM core_facture_fournisseur WHERE facture_id = ?", (fid_,)).fetchone()
        prise = fa[2] if (fa[3] and fa[2] and jeudi <= date.fromisoformat(fa[3])) else 0
        c.execute("INSERT INTO core_paiement_fournisseur (lot_id, facture_id, fournisseur_id, montant_cents, escompte_pris_cents) VALUES (?,?,?,?,?)", (lot, fid_, fa[0], fa[1] - prise, prise))
        c.execute("UPDATE core_facture_fournisseur SET statut = 'en_lot' WHERE facture_id = ?", (fid_,))


# --------------------------------------------------------------------------- #
# Actions (avec leurs contrôles)
# --------------------------------------------------------------------------- #
def approuver_facture(db: str, facture_id: int, par: str, motif: str | None = None) -> None:
    """Approuve une facture appariée ou retenue. Un écart exige un motif ; le demandeur de la commande ne peut pas approuver ; fournisseur payable seulement."""
    c = connecter(db)
    try:
        f = c.execute("SELECT f.statut, f.commande_id, f.ecart_prix_pct, f.ecart_quantite_pct, f.fournisseur_id, o.statut FROM core_facture_fournisseur f "
                      "JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE f.facture_id = ?", (facture_id,)).fetchone()
        if not f:
            raise ErreurCycle("Facture introuvable.")
        if f[0] not in ("appariee", "ecart"):
            raise ErreurCycle(f"Une facture au statut « {f[0]} » ne peut pas être approuvée ici.")
        p = parametres(c)
        hors = abs(f[2] or 0) > p["tolerance_prix_pct"] or abs(f[3] or 0) > p["tolerance_quantite_pct"] or f[1] is None
        if hors and not (motif or "").strip():
            raise ErreurCycle("Un écart hors tolérance exige un motif.")
        if f[1] is not None:
            dem = c.execute("SELECT demandeur, approuve_par FROM core_commande_achat WHERE commande_id = ?", (f[1],)).fetchone()
            if dem and par in (dem[0], dem[1]):
                raise ErreurCycle("Séparation des tâches : le demandeur ou l'approbateur de la commande ne peut pas approuver la facture.")
        c.execute("UPDATE core_facture_fournisseur SET statut = 'approuvee', approuve_par = ?, approuve_le = date('now'), motif_ecart = COALESCE(?, motif_ecart) WHERE facture_id = ?",
                  (par, (motif or None), facture_id))
        c.commit()
    finally:
        c.close()


def contester_facture(db: str, facture_id: int, motif: str) -> None:
    if not (motif or "").strip():
        raise ErreurCycle("Une contestation exige un motif.")
    c = connecter(db)
    try:
        c.execute("UPDATE core_facture_fournisseur SET statut = 'contestee', motif_ecart = ? WHERE facture_id = ? AND statut IN ('recue', 'appariee', 'ecart')", (motif, facture_id))
        c.commit()
    finally:
        c.close()


def valider_fournisseur(db: str, fournisseur_id: int, par: str) -> None:
    """Intégration d'un fournisseur : vérifications faites, la fiche devient payable. Le demandeur d'achat ne peut pas la valider."""
    if par in DEMANDEURS:
        raise ErreurCycle("Séparation des tâches : un demandeur d'achat ne peut pas valider la fiche d'un fournisseur.")
    c = connecter(db)
    try:
        c.execute("UPDATE mdm_fournisseur SET statut = 'actif', approuve_par = ?, approuve_le = date('now'), rappel_verifie = 1 WHERE fournisseur_id = ? AND statut = 'a_valider'",
                  (par, fournisseur_id))
        c.commit()
    finally:
        c.close()


def lever_suspension(db: str, fournisseur_id: int, par: str) -> None:
    """Lève la suspension une fois le changement de coordonnées bancaires confirmé par un rappel au numéro connu du fournisseur."""
    c = connecter(db)
    try:
        c.execute("UPDATE mdm_fournisseur SET statut = 'actif', rappel_verifie = 1, approuve_par = ?, approuve_le = date('now') WHERE fournisseur_id = ? AND statut = 'suspendu'",
                  (par, fournisseur_id))
        c.commit()
    finally:
        c.close()


def creer_lot(db: str, facture_ids: list[int], date_paiement: date, mode: str = "EFT", par: str = PREPARATEUR) -> int:
    """Prépare un lot avec des factures approuvées de fournisseurs actifs. Applique l'escompte si la date de paiement est dans le délai."""
    if not facture_ids:
        raise ErreurCycle("Aucune facture sélectionnée.")
    c = connecter(db)
    try:
        lignes = []
        for fid in facture_ids:
            f = c.execute("SELECT f.facture_id, f.statut, f.total_cents, f.escompte_cents, f.date_limite_escompte, f.fournisseur_id, o.statut, o.nom_legal, o.rappel_verifie "
                          "FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE f.facture_id = ?", (fid,)).fetchone()
            if not f or f[1] != "approuvee":
                raise ErreurCycle(f"La facture {fid} n'est pas approuvée : elle ne peut pas être payée.")
            if f[6] != "actif":
                raise ErreurCycle(f"{f[7]} est « {f[6]} » : paiement bloqué tant que la fiche n'est pas validée (rappel de vérification des coordonnées bancaires).")
            lignes.append(f)
        base = f"LOT-{date_paiement:%Y-%m-%d}"
        no = base if not c.execute("SELECT 1 FROM core_lot_paiement WHERE no_lot = ?", (base,)).fetchone() else f"{base}-{c.execute('SELECT COUNT(*) FROM core_lot_paiement').fetchone()[0] + 1}"
        compte = (c.execute("SELECT compte_id FROM mdm_compte WHERE actif = 1 ORDER BY compte_id LIMIT 1").fetchone() or [None])[0]
        lot = c.execute("INSERT INTO core_lot_paiement (no_lot, date_paiement, mode_paiement, compte_id, statut, prepare_par) VALUES (?,?,?,?,?,?)",
                        (no, date_paiement.isoformat(), mode, compte, "prepare", par)).lastrowid
        for f in lignes:
            prise = f[3] if (f[4] and f[3] and date_paiement <= date.fromisoformat(f[4])) else 0
            c.execute("INSERT INTO core_paiement_fournisseur (lot_id, facture_id, fournisseur_id, montant_cents, escompte_pris_cents) VALUES (?,?,?,?,?)", (lot, f[0], f[5], f[2] - prise, prise))
            c.execute("UPDATE core_facture_fournisseur SET statut = 'en_lot' WHERE facture_id = ?", (f[0],))
        c.commit()
        return lot
    finally:
        c.close()


def total_lot(c: sqlite3.Connection, lot_id: int) -> int:
    return c.execute("SELECT COALESCE(SUM(montant_cents), 0) FROM core_paiement_fournisseur WHERE lot_id = ?", (lot_id,)).fetchone()[0]


def approuver_lot(db: str, lot_id: int, par: str) -> str:
    """Approuve un lot. Sous le seuil, une approbation suffit ; au-delà, deux approbateurs distincts, différents du préparateur. Retourne le nouveau statut."""
    c = connecter(db)
    try:
        lot = c.execute("SELECT statut, prepare_par, approbateur_1 FROM core_lot_paiement WHERE lot_id = ?", (lot_id,)).fetchone()
        if not lot:
            raise ErreurCycle("Lot introuvable.")
        statut, prep, a1 = lot
        if statut not in ("prepare", "approuve_1"):
            raise ErreurCycle(f"Le lot est « {statut} » : rien à approuver.")
        if par == prep:
            raise ErreurCycle("Séparation des tâches : le préparateur du lot ne peut pas l'approuver.")
        seuil = parametres(c)["seuil_double_approbation"] * 100
        double = total_lot(c, lot_id) > seuil
        if statut == "prepare":
            nouveau = "approuve_1" if double else "approuve"
            c.execute("UPDATE core_lot_paiement SET statut = ?, approbateur_1 = ? WHERE lot_id = ?", (nouveau, par, lot_id))
        else:
            if par == a1:
                raise ErreurCycle("Double approbation : le second approbateur doit être une autre personne que le premier.")
            nouveau = "approuve"
            c.execute("UPDATE core_lot_paiement SET statut = 'approuve', approbateur_2 = ? WHERE lot_id = ?", (par, lot_id))
        c.commit()
        return nouveau
    finally:
        c.close()


def executer_lot(db: str, lot_id: int) -> int:
    """Exécute un lot approuvé : factures payées, écritures de paiement. Retourne le nombre de paiements."""
    c = connecter(db)
    try:
        lot = c.execute("SELECT statut, date_paiement, no_lot FROM core_lot_paiement WHERE lot_id = ?", (lot_id,)).fetchone()
        if not lot or lot[0] != "approuve":
            raise ErreurCycle("Seul un lot entièrement approuvé peut être exécuté.")
        n = 0
        for pid, fid, montant, prise in c.execute("SELECT paiement_id, facture_id, montant_cents, escompte_pris_cents FROM core_paiement_fournisseur WHERE lot_id = ?", (lot_id,)).fetchall():
            total = montant + prise
            c.execute("UPDATE core_facture_fournisseur SET statut = 'payee' WHERE facture_id = ?", (fid,))
            _ecriture(c, f"ECR-P-{lot_id}-{fid}", date.fromisoformat(lot[1]), "paiement", lot[2],
                      [("2100", total, 0, "Règlement du fournisseur"), ("1000", 0, montant, "Débit bancaire (EFT)"), ("5900", 0, prise, "Escompte de paiement rapide")])
            n += 1
        c.execute("UPDATE core_lot_paiement SET statut = 'execute' WHERE lot_id = ?", (lot_id,))
        c.commit()
        return n
    finally:
        c.close()


def reinitialiser(db: str) -> dict:
    c = connecter(db)
    try:
        if not schema_present(c):
            c.executescript(open(SQL, encoding="utf-8").read())
        return generer(c)
    finally:
        c.close()


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_DOSSIER, "demo_live", "donnees", "base_demo.db")
    print(assurer(base), reinitialiser(base))
