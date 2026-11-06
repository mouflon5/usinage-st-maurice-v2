"""Rapports de coûts de revient pour trois niveaux de décision — stratégique, tactique et opérationnel — construits à partir du moteur couts_revient.py.

Chaque rapport suit la même charpente, celle d'un rapport de gestion : à qui il s'adresse et à quelle fréquence, quelques indicateurs avec leur seuil (vert, jaune, rouge),
les messages à retenir, l'analyse qui les soutient, puis un plan d'action chiffré avec un responsable et une échéance. Le commentaire est généré à partir des chiffres :
changer une hypothèse (marge visée, capacité, seuils d'investigation, écarts du mois) change les constats.

  Stratégique   conseil d'administration et direction : rentabilité réelle par ligne, prix, portefeuille, capacité, risques        annuel, revue trimestrielle
  Tactique      directeurs de production, des ventes et des finances : écarts du mois, soumissions, capacité et mix, processus, qualité    mensuel
  Opérationnel  superviseurs d'atelier et planificateurs : indicateurs de la semaine, alertes, barème d'impact, standards, actions       hebdomadaire

Exports : Markdown, HTML autonome (imprimable) et PDF.
"""
from __future__ import annotations

import html
import io
from dataclasses import dataclass, field

import pandas as pd

import couts_revient as C

STATUTS = {"ok": "Conforme", "att": "À surveiller", "crit": "Critique", "info": "Information"}
COULEURS_STATUT = {"ok": "#1baf7a", "att": "#d9930a", "crit": "#d03b3b", "info": "#5b6573"}


@dataclass
class Kpi:
    libelle: str
    valeur: str
    cible: str = ""
    statut: str = "info"
    note: str = ""


@dataclass
class Section:
    titre: str
    paragraphes: list[str] = field(default_factory=list)
    tableau: pd.DataFrame | None = None
    legende: str = ""


@dataclass
class Action:
    action: str
    responsable: str
    echeance: str
    impact: str
    priorite: str = "Moyenne"


@dataclass
class Rapport:
    niveau: str
    titre: str
    destinataires: str
    frequence: str
    periode: str
    objectif: str
    kpis: list[Kpi]
    messages: list[str]
    sections: list[Section]
    actions: list[Action]
    methode: str = ""


@dataclass
class Parametres:
    marge_visee: float = 0.15                # marge visée sur le coût complet ABC (prix cible)
    capacite_cnc: float = 40000.0            # heures-machine normales du centre d'usinage
    croissance_max: float = 0.20             # croissance de la demande supposée par ligne pour le mix
    seuil_pct: float = 0.05                  # un écart est à investiguer s'il dépasse ce % du standard...
    seuil_dollars: float = 2500.0            # ... et ce montant
    var_marche: float = 0.03                 # variation du prix du métal depuis la fixation du standard
    part_matiere: float = 0.55               # part du prix d'achat qui suit le marché
    reduction_abm: float = 0.50              # réduction visée sur les activités sans valeur ajoutée
    periode: str = "septembre 2026"
    pieces: float = 2000.0                   # production du mois et coûts réels (même exemple que l'onglet « Standards et écarts »)
    kg_achetes: float = 5010.0
    prix_reel: float = 8.05
    heures_reelles: float = 1830.0
    taux_reel: float = 60.5
    variable_reel: float = 6900.0
    fixes_reels: float = 31900.0             # frais généraux fixes de fabrication dépensés dans le mois (budget : 30 800 $ pour une production normale de 2 200 pièces)
    seuil_devis: float = 0.05                # une commande qui dépasse son devis de plus de ce % est « à revoir »


# --- mise en forme ------------------------------------------------------------------------------------------------------------------------------
def fk(v: float, signe: bool = False) -> str:
    s = f"{abs(v):,.0f}".replace(",", " ")
    pre = ("+" if v >= 0 else "−") if signe else ("−" if v < 0 else "")
    return f"{pre}{s} k$"


def fd(v: float, dec: int = 0, signe: bool = False) -> str:
    s = f"{abs(v):,.{dec}f}".replace(",", " ").replace(".", ",")
    pre = ("+" if v >= 0 else "−") if signe else ("−" if v < 0 else "")
    return f"{pre}{s} $"


def fp(v: float, dec: int = 1, signe: bool = False) -> str:
    s = f"{abs(v) * 100:.{dec}f}".replace(".", ",")
    pre = ("+" if v >= 0 else "−") if signe else ("−" if v < 0 else "")
    return f"{pre}{s} %"


def _tab(df: pd.DataFrame, formats: dict[str, str]) -> pd.DataFrame:
    """Tableau prêt à publier : chaque colonne mise en forme selon son format (k = milliers de dollars, d = dollars, d2 = dollars et cents, p = pourcentage, n = nombre)."""
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        f = formats.get(c)
        if f == "k":
            out[c] = [fk(v) for v in df[c]]
        elif f == "ks":
            out[c] = [fk(v, True) for v in df[c]]
        elif f == "d":
            out[c] = [fd(v) for v in df[c]]
        elif f == "d2":
            out[c] = [fd(v, 2) for v in df[c]]
        elif f == "p":
            out[c] = [fp(v) for v in df[c]]
        elif f == "ps":
            out[c] = [fp(v, 1, True) for v in df[c]]
        elif f == "n":
            out[c] = [f"{v:,.0f}".replace(",", " ") for v in df[c]]
        elif f == "n1":
            out[c] = [f"{v:,.1f}".replace(",", " ").replace(".", ",") for v in df[c]]
        else:
            out[c] = df[c]
    return out.reset_index(drop=True)


def _statut(v: float, ok: tuple[float, float] | None = None, haut_ok: float | None = None, haut_att: float | None = None, bas_ok: float | None = None, bas_att: float | None = None) -> str:
    """Feu selon un seuil : « plus c'est haut, mieux c'est » (bas_ok, bas_att) ou « plus c'est bas, mieux c'est » (haut_ok, haut_att) ; ok = zone cible [min, max]."""
    if ok is not None:
        return "ok" if ok[0] <= v <= ok[1] else "att"
    if haut_ok is not None:
        return "ok" if v <= haut_ok else ("att" if v <= haut_att else "crit")
    return "ok" if v >= bas_ok else ("att" if v >= bas_att else "crit")


def _base(p: Parametres) -> dict:
    """Tous les calculs dont les trois rapports ont besoin, faits une seule fois."""
    rent = C.rentabilite_produits()
    plan = C.planchers_prix(p.marge_visee)
    contrib = C.contribution()
    pm = C.resultat_et_point_mort(contrib)
    e = C.ecarts(p.pieces, p.kg_achetes, p.prix_reel, p.heures_reelles, p.taux_reel, p.variable_reel)
    ecarts = {k: v for k, v in e.items() if not k.startswith("_")}
    hist = C.historique_ecarts(courant=ecarts)
    return {"rent": rent, "plan": plan, "contrib": contrib, "pm": pm, "lev": C.levier_exploitation(), "sens": C.sensibilite_resultat(0.10), "pmp": C.point_mort_produits(),
            "mix": C.mix_capacite(p.capacite_cnc, p.croissance_max), "cap": C.capacite_centres({**C.CAPACITE_NORMALE, "Usinage CNC": p.capacite_cnc}), "coq": C.cout_qualite(),
            "abm": C.scenario_abm({a: p.reduction_abm for a, k in zip(C.ACTIVITES["Activité"], C.ACTIVITES["Classe"]) if k == "Sans valeur"}), "ecarts": ecarts, "e": e,
            "lim": C.limites_controle(hist), "hist": hist, "ventes": float(rent["Ventes (k$)"].sum()), "ff": C.ecarts_frais_fixes(p.pieces, p.fixes_reels),
            "cmd": C.commandes(), "prec": C.precision_soumissions(p.seuil_devis),
            "dec": C.decomposer_ecart_prix(ecarts["Prix de la matière"], p.var_marche, p.part_matiere, C.STANDARD["prix"], p.kg_achetes)}


# --- rapport stratégique -------------------------------------------------------------------------------------------------------------------------
def rapport_strategique(p: Parametres | None = None) -> Rapport:
    p = p or Parametres()
    b = _base(p)
    rent, plan, pm, lev, sens, cap, coq, mix, abm = b["rent"], b["plan"], b["pm"], b["lev"], b["sens"], b["cap"], b["coq"], b["mix"], b["abm"]
    ventes = b["ventes"]
    negatives = rent[rent["Marge complète ABC (k$)"] < 0]
    positives = rent[rent["Marge complète ABC (k$)"] > 0]
    subv = float(rent["Distorsion (k$)"].clip(lower=0).sum())
    sous_act = float(cap["Coût de sous-activité (k$)"].clip(lower=0).sum())
    va_sans = float(abm.groupby("Classe")["Coût (k$)"].sum().get("Sans valeur", 0.0))
    cout_abm = float(abm["Coût (k$)"].sum())
    util = float(cap.set_index("Centre").loc["Usinage CNC", "Utilisation"])
    cmd, prec = b["cmd"], b["prec"]
    ecart_devis = float(cmd["Écart ($)"].sum() / cmd["Coût estimé ($)"].sum())
    marge_prevue = float(1 - cmd["Coût estimé ($)"].sum() / cmd["Prix soumis ($)"].sum())
    marge_reelle = float(1 - cmd["Coût réel ($)"].sum() / cmd["Prix soumis ($)"].sum())
    pire_ligne = prec.sort_values("Écart moyen pondéré", ascending=False).iloc[0]
    kpis = [
        Kpi("Ventes", fk(ventes), "—", "info"),
        Kpi("Résultat d'exploitation", fk(pm["resultat"]), f"≥ {fp(0.08, 0)} des ventes", _statut(pm["resultat"] / ventes, bas_ok=0.08, bas_att=0.04), f"{fp(pm['resultat'] / ventes)} des ventes (modèle de marge)"),
        Kpi("Marge de sécurité", fp(pm["marge_securite"]), "≥ 20 %", _statut(pm["marge_securite"], bas_ok=0.20, bas_att=0.10), f"point mort à {fk(pm['point_mort'])} de ventes"),
        Kpi("Degré de levier d'exploitation", f"{lev['degre_levier']:.1f}".replace(".", ",") + " ×", "≤ 3 ×", _statut(lev["degre_levier"], haut_ok=3, haut_att=5), "1 % de volume = " + fp(lev["degre_levier"] / 100, 1) + " de résultat"),
        Kpi("Lignes déficitaires au coût complet ABC", f"{len(negatives)} sur {len(rent)}", "0", "ok" if len(negatives) == 0 else ("att" if len(negatives) == 1 else "crit"),
            ", ".join(negatives.index) if len(negatives) else "aucune"),
        Kpi("Subvention croisée entre lignes", fk(subv), "≤ 3 % des ventes", _statut(subv / ventes, haut_ok=0.03, haut_att=0.06), f"{fp(subv / ventes)} des ventes : coût sous-évalué par les centres d'analyse"),
        Kpi("Utilisation du centre d'usinage CNC", fp(util, 0), "80 % à 95 %", _statut(util, ok=(0.80, 0.95)), f"{fd(cap['Coût de sous-activité (k$)'].sum() * 1000)} de sous-activité, tous centres"),
        Kpi("Coût de la qualité", fp(coq["pct_ventes"]), "≤ 5 % des ventes", _statut(coq["pct_ventes"], haut_ok=0.05, haut_att=0.10), f"{fp(coq['ratio_non_conformite'], 0)} en non-conformité"),
        Kpi("Fiabilité des soumissions (dépassement moyen du devis)", fp(ecart_devis, 1, True), "≤ 5 %", _statut(ecart_devis, haut_ok=0.05, haut_att=0.10),
            f"marge soumise {fp(marge_prevue)} → marge réelle {fp(marge_reelle)} sur les commandes suivies"),
    ]
    meilleure = rent["Marge complète ABC (%)"].idxmax()
    part_meilleure = float(rent.loc[meilleure, "Marge complète ABC (k$)"] / positives["Marge complète ABC (k$)"].sum()) if len(positives) else 0
    centre_neg_trad = [i for i in rent.index if rent.loc[i, "Marge selon centres (k$)"] > 0 and rent.loc[i, "Marge complète ABC (k$)"] < 0]
    pire_prix = plan.sort_values("Écart prix / cible (%)").iloc[0]
    messages = [
        f"La rentabilité réelle repose sur une seule ligne : **{meilleure}** dégage {fk(rent.loc[meilleure, 'Marge complète ABC (k$)'])} de marge complète ABC, soit {fp(part_meilleure, 0)} des marges positives du groupe. "
        f"Le résultat est donc très sensible à la santé de cette ligne.",
        (f"Les centres d'analyse traditionnels font paraître rentables des lignes que l'ABC révèle déficitaires : **{', '.join(centre_neg_trad)}**. La distorsion déplace {fk(subv)} de coûts d'une ligne à l'autre ; "
         "fixer les prix sur l'ancienne méthode sous-tarife les lignes qui consomment le plus de contrôle, d'ingénierie et de soudure.") if centre_neg_trad else
        "Les centres d'analyse et l'ABC s'entendent sur la rentabilité de chaque ligne : la distorsion est faible.",
        f"Prix : **{pire_prix['Produit']}** se vend {fp(-pire_prix['Écart prix / cible (%)'], 0)} sous le prix qui donnerait {fp(p.marge_visee, 0)} de marge sur son coût complet ABC "
        f"({fd(pire_prix['Prix actuel ($)'], 2)} contre {fd(pire_prix['Prix cible ($)'], 2)}).",
        f"Capacité : les quatre centres tournent sous leur capacité normale et la sous-activité coûte {fk(sous_act)} par année. Tout investissement en capacité devrait attendre que la demande remplisse l'existant.",
        f"Soumissions : les commandes suivies dépassent leur devis de {fp(ecart_devis, 1)} en moyenne et la marge soumise de {fp(marge_prevue)} tombe à {fp(marge_reelle)}. "
        f"**{pire_ligne['Ligne']}** est la ligne la moins bien estimée ({fp(pire_ligne['Écart moyen pondéré'], 0, True)} sur le coût estimé, dérive surtout sur « {pire_ligne['Poste qui dérive'].lower()} »).",
        f"Risque : le levier d'exploitation de {str(round(lev['degre_levier'], 1)).replace('.', ',')} × signifie qu'une baisse de 10 % des volumes coûterait {fk(-sens.set_index('Facteur').loc['Volumes', 'Défavorable (k$)'])} (soit {fp(-sens.set_index('Facteur').loc['Volumes', 'Défavorable (k$)'] / pm['resultat'], 0)} du résultat) ; "
        f"une baisse de 10 % des prix, {fk(-sens.set_index('Facteur').loc['Prix de vente', 'Défavorable (k$)'])}.",
    ]
    t_rent = _tab(rent.reset_index(names="Ligne")[["Ligne", "Ventes (k$)", "Taux de MCV", "Marge complète ABC (k$)", "Marge complète ABC (%)", "Marge selon centres (k$)", "Distorsion (k$)"]],
                  {"Ventes (k$)": "k", "Taux de MCV": "p", "Marge complète ABC (k$)": "ks", "Marge complète ABC (%)": "ps", "Marge selon centres (k$)": "ks", "Distorsion (k$)": "ks"})
    t_prix = _tab(plan[["Produit", "Prix actuel ($)", "Plancher variable ($)", "Plancher spécifique ($)", "Plancher complet ABC ($)", "Prix cible ($)", "Écart prix / cible (%)", "Position"]],
                  {"Prix actuel ($)": "d2", "Plancher variable ($)": "d2", "Plancher spécifique ($)": "d2", "Plancher complet ABC ($)": "d2", "Prix cible ($)": "d2", "Écart prix / cible (%)": "ps"})
    t_cap = _tab(cap[["Centre", "Utilisation", "Capacité normale", "Activité réelle", "Charges fixes (k$)", "Coût de sous-activité (k$)"]],
                 {"Utilisation": "p", "Capacité normale": "n", "Activité réelle": "n", "Charges fixes (k$)": "k", "Coût de sous-activité (k$)": "k"})
    t_sens = _tab(sens[["Facteur", "Défavorable (k$)", "Favorable (k$)"]], {"Défavorable (k$)": "ks", "Favorable (k$)": "ks"})
    proto = rent.loc["Prototypage"] if "Prototypage" in rent.index else None
    abandon_proto = C.abandon("Prototypage", b["contrib"])
    sections = [
        Section("1. Où le groupe gagne et perd vraiment de l'argent", [
            "Le tableau compare la marge par ligne selon les centres d'analyse (une seule unité d'œuvre par centre) et selon l'ABC (les inducteurs réels : heures-machine, heures de soudage, inspections, heures d'ingénierie). "
            "La distorsion, en k$, mesure ce que chaque ligne reçoit (+) ou accorde (−) aux autres sans que personne ne le voie."], t_rent,
                "Marge complète ABC = ventes − coûts directs − charges indirectes réparties selon les inducteurs. Les charges indirectes totalisent 7,1 M$ dans les deux méthodes."),
        Section("2. Politique de prix : trois planchers et un prix cible", [
            "Le **plancher variable** est le prix en dessous duquel chaque vente fait perdre de l'argent dès la première pièce. Le **plancher spécifique** couvre aussi les charges fixes de la ligne. "
            "Le **plancher complet ABC** couvre la part de tous les frais. Le **prix cible** donne la marge visée sur le coût complet. Une ligne sous son plancher spécifique détruit de la valeur à chaque commande, "
            "sans espoir de la rattraper par le volume."], t_prix, f"Marge visée : {fp(p.marge_visee, 0)} sur le coût complet ABC."),
        Section("3. Portefeuille et capacité", [
            (f"**Prototypage** : abandonner la ligne améliorerait le résultat de {fk(abandon_proto)}, car sa marge sur coûts variables ne couvre pas ses fixes spécifiques. La décision n'est pas mécanique : "
             "les prototypes alimentent les séries d'usinage sur mesure et les contrats récurrents, et l'équipe d'ingénierie sert aussi les soumissions. "
             "Recommandation : la maintenir comme **investissement commercial budgété**, tarifé au coût complet, et mesurer sa conversion en commandes de série.") if abandon_proto > 0 else
            "Aucune ligne n'est candidate à l'abandon sur la seule base de sa marge sur coûts variables.",
            f"**Capacité** : sous-activité totale de {fk(sous_act)} par année. À {p.capacite_cnc:,.0f} heures-machine normales, chaque heure supplémentaire vendue rapporte en moyenne "
            f"{fd(mix.attrs['prix_ombre'], 0)} de marge sur coûts variables lorsque la capacité est contrainte (prix implicite).".replace(",", " ")], t_cap,
                "Sous-activité = charges fixes du centre × (1 − utilisation). Elle est passée en charge de la période (imputation rationnelle), pas dans le coût des pièces."),
        Section("4. Risques et sensibilités du résultat d'exploitation", [
            f"Résultat de base : {fk(pm['resultat'])}. Le tableau montre l'effet d'une variation de ±10 % de chaque facteur. Le prix de vente et les volumes dominent ; "
            f"le coût de la matière pèse {fk(-sens.set_index('Facteur').loc['Coût de la matière', 'Défavorable (k$)'])} par tranche de 10 % — l'exposition aux marchés de l'acier et de l'aluminium (vue « Prix des métaux ») "
            "se gère par des clauses d'indexation plutôt que par le prix de base."], t_sens, "Variation défavorable : prix −10 %, volumes −10 %, coûts +10 %. Les autres facteurs sont constants."),
        Section("5. Fiabilité des soumissions : le devis contre le réel", [
            "Une soumission fixe le prix et la marge avant que le travail commence. Le tableau compare, par ligne, la marge soumise à la marge réellement obtenue sur les commandes suivies : "
            "un prix juste sur le papier ne vaut rien si l'estimation sous-évalue les heures-machine, les réglages ou les reprises."],
                _tab(prec[["Ligne", "Commandes", "Écart moyen pondéré", "Marge prévue (%)", "Marge réelle (%)", "Poste qui dérive"]],
                     {"Écart moyen pondéré": "ps", "Marge prévue (%)": "p", "Marge réelle (%)": "p", "Commandes": "n"}),
                "Écart moyen pondéré = (coût réel − coût estimé) ÷ coût estimé, pondéré par le coût des commandes. Taux machine et taux horaire de main-d'œuvre au standard : l'écart mesure le volume de travail, pas son prix."),
        Section("6. Qualité et processus", [
            f"Le coût de la qualité est de {fk(coq['total'])} ({fp(coq['pct_ventes'])} des ventes), dont {fp(coq['ratio_non_conformite'], 0)} en défaillances internes et externes. "
            f"Les activités sans valeur ajoutée coûtent {fk(float(C.ACTIVITES[C.ACTIVITES['Classe'] == 'Sans valeur']['Coût (k$)'].sum()))} par année ; les réduire de {fp(p.reduction_abm, 0)} libère "
            f"{fk(float(C.ACTIVITES[C.ACTIVITES['Classe'] == 'Sans valeur']['Coût (k$)'].sum()) * p.reduction_abm)}."]),
    ]
    gap_contrats = (plan.set_index("Produit").loc["Contrats aéro et rail", "Prix cible ($)"] - plan.set_index("Produit").loc["Contrats aéro et rail", "Prix actuel ($)"]) * C.PRODUITS["Contrats aéro et rail"]["volume"]
    gap_proto = (plan.set_index("Produit").loc["Prototypage", "Prix cible ($)"] - plan.set_index("Produit").loc["Prototypage", "Prix actuel ($)"]) * C.PRODUITS["Prototypage"]["volume"]
    gain_mix = mix.attrs["mcv_optimale"] - mix.attrs["mcv_actuelle"]
    actions = [
        Action("Réviser les prix des contrats aéro et rail vers le prix cible : première hausse de 10 % aux renouvellements, puis clause d'indexation matière", "Vice-président ventes",
               "Renouvellements des 12 à 24 prochains mois", f"+{fk(0.10 * rent.loc['Contrats aéro et rail', 'Ventes (k$)'])} au premier palier (écart total au prix cible : {fk(gap_contrats)})", "Haute"),
        Action("Tarifer le prototypage au coût complet et suivre sa conversion en commandes de série ; plafonner le budget de la ligne", "Direction générale et vice-président ingénierie",
               "Prochain budget annuel", f"jusqu'à +{fk(gap_proto)} si le prix atteint la cible, sinon plafond de perte à {fk(-rent.loc['Prototypage', 'Marge complète ABC (k$)'])}", "Haute"),
        Action("Combler la capacité du centre d'usinage par les lignes les plus rentables à l'heure-machine, avant tout investissement", "Vice-président opérations",
               "4 trimestres", f"+{fk(gain_mix)} de marge sur coûts variables si la demande croît de {fp(p.croissance_max, 0)}", "Haute"),
        Action(f"Recalibrer les gabarits d'estimation de {pire_ligne['Ligne']} (heures-machine, réglages, reprises) sur les commandes terminées, et revoir la marge soumise tant que l'écart dépasse 10 %", "Directeur des ventes et estimateur en chef",
               "2 trimestres", f"ramener la marge réelle de {fp(marge_reelle)} vers la marge soumise de {fp(marge_prevue)} sur les commandes suivies", "Haute"),
        Action("Adopter l'ABC comme base des soumissions et du reporting trimestriel ; maintenir les centres d'analyse seulement pour la valorisation des stocks", "Contrôleur financier",
               "Prochain trimestre", "Supprime une subvention croisée de " + fk(subv), "Moyenne"),
        Action(f"Programme d'ABM : réduire de {fp(p.reduction_abm, 0)} les activités sans valeur ajoutée (attentes, reprises, corrections de factures)", "Vice-président opérations et contrôleur",
               "2 exercices", f"+{fk(float(C.ACTIVITES[C.ACTIVITES['Classe'] == 'Sans valeur']['Coût (k$)'].sum()) * p.reduction_abm)} par année", "Moyenne"),
        Action("Réduire de 25 % les défaillances internes et externes de qualité", "Directeur qualité", "2 exercices", f"+{fk(0.25 * coq['non_conformite'])} par année", "Moyenne"),
    ]
    return Rapport("Stratégique", "Rapport stratégique sur la rentabilité et les coûts de revient", "Conseil d'administration et direction générale", "Annuel, revue trimestrielle",
                   "Exercice en cours, horizon de 1 à 3 ans", "Éclairer les décisions de portefeuille, de prix et de capacité avec la rentabilité réelle de chaque ligne.", kpis, messages, sections, actions,
                   "Coût complet par la méthode ABC (activités et inducteurs), comparé aux centres d'analyse ; marge sur coûts variables et coûts spécifiques évitables pour les décisions d'abandon ; "
                   "planchers de prix par niveau de coût ; levier d'exploitation et sensibilités ; imputation rationnelle des charges fixes pour la sous-activité. Montants fictifs.")


# --- rapport tactique ------------------------------------------------------------------------------------------------------------------------------
def rapport_tactique(p: Parametres | None = None) -> Rapport:
    p = p or Parametres()
    b = _base(p)
    e, ecarts, lim, dec, mix, cap, coq, abm, plan = b["e"], b["ecarts"], b["lim"], b["dec"], b["mix"], b["cap"], b["coq"], b["abm"], b["plan"]
    cout_std, total = e["_cout_standard"], e["_total"]
    a_investiguer = [k for k, v in ecarts.items() if C.investigation(v, cout_std, p.seuil_pct, p.seuil_dollars)]
    hors = [k for k in ecarts if lim.loc[k, "Hors limites"]]
    util = cap.set_index("Centre")["Utilisation"]
    internes = float(coq["par_categorie"]["Défaillance interne"])
    sans_valeur = abm[abm["Classe"] == "Sans valeur"]
    eco_abm = float((sans_valeur["Coût (k$)"] - sans_valeur["Coût après (k$)"]).sum())
    ff, cmd = b["ff"], b["cmd"]
    n_revoir = int((cmd["Écart (%)"] > p.seuil_devis).sum())
    kpis = [
        Kpi("Écart total sur standards", fd(total, 0, True), "± 3 % du standard", _statut(abs(total) / cout_std, haut_ok=0.03, haut_att=0.07), f"{fp(total / cout_std, 1, True)} du coût standard de {fd(cout_std)}"),
        Kpi("Écarts à investiguer", f"{len(a_investiguer)} sur {len(ecarts)}", "0", "ok" if not a_investiguer else ("att" if len(a_investiguer) == 1 else "crit"),
            f"règle : ≥ {fp(p.seuil_pct, 0)} du standard et ≥ {fd(p.seuil_dollars)}"),
        Kpi("Écarts hors des limites de contrôle", f"{len(hors)} sur {len(ecarts)}", "0", "ok" if not hors else "crit", ", ".join(hors) if hors else "dans la variabilité normale"),
        Kpi("Frais fixes de fabrication sous-imputés", fd(ff["sous_imputation"], 0, True), "± 2 % du budget", _statut(abs(ff["sous_imputation"]) / ff["budget"], haut_ok=0.02, haut_att=0.06),
            f"budget {fd(ff['ecart_budget'], 0, True)} · volume {fd(ff['ecart_volume'], 0, True)} (production à {fp(ff['utilisation'], 0)} de la normale)"),
        Kpi("Commandes qui dépassent leur devis", f"{n_revoir} sur {len(cmd)}", "0", "ok" if n_revoir == 0 else ("att" if n_revoir <= 2 else "crit"), f"seuil de {fp(p.seuil_devis, 0)} du coût estimé"),
        Kpi("Utilisation du centre d'usinage CNC", fp(util["Usinage CNC"], 0), "80 % à 95 %", _statut(util["Usinage CNC"], ok=(0.80, 0.95))),
        Kpi("Utilisation du contrôle et de la métrologie", fp(util["Contrôle et métrologie"], 0), "80 % à 95 %", _statut(util["Contrôle et métrologie"], ok=(0.80, 0.95))),
        Kpi("Valeur d'une heure-machine de plus", fd(mix.attrs["prix_ombre"], 0), "—", "info", "marge sur coûts variables de la dernière ligne servie quand la capacité est contrainte"),
        Kpi("Défaillances internes de qualité", fk(internes), "≤ 2 % des ventes", _statut(internes / b["ventes"], haut_ok=0.02, haut_att=0.04), f"{fp(internes / b['ventes'])} des ventes"),
        Kpi("Lignes vendues sous leur plancher complet", f"{int((plan['Prix actuel ($)'] < plan['Plancher complet ABC ($)']).sum())} sur {len(plan)}", "0",
            "ok" if (plan["Prix actuel ($)"] < plan["Plancher complet ABC ($)"]).sum() == 0 else "crit"),
    ]
    pire = max(ecarts, key=lambda k: ecarts[k])
    messages = [
        f"Le coût réel du mois dépasse le standard de **{fd(total)}** ({fp(total / cout_std, 1)}). La cause principale est « {pire} » ({fd(ecarts[pire])}), "
        f"{'hors des limites de contrôle habituelles : ce n\'est pas de la variabilité normale, il faut enquêter.' if pire in hors else 'dans les limites habituelles.'}",
        f"Prix de la matière : sur l'écart de {fd(dec['ecart_total'])}, environ **{fd(dec['effet_marche'])}** s'expliquent par le marché ({fp(p.var_marche, 1, True)} depuis la fixation du standard, "
        f"{fp(p.part_matiere, 0)} du prix suivant le métal) ; le reste, **{fd(dec['effet_achat'])}**, relève de l'achat (surcharges, quantités, délais) et se négocie.",
        f"Frais fixes de fabrication : {fd(ff['sous_imputation'], 0)} {'de sous-imputation' if ff['sous_imputation'] > 0 else 'de sur-imputation'} — {fd(abs(ff['ecart_budget']), 0)} d'écart de budget (dépensé {fd(ff['reel'])} contre {fd(ff['budget'])} budgété) "
        f"et {fd(abs(ff['ecart_volume']), 0)} d'écart de volume (la production est à {fp(ff['utilisation'], 0)} de la normale). Le second n'est pas une inefficacité de dépense : c'est de la capacité non remplie.",
        f"Devis : {n_revoir} commande(s) sur {len(cmd)} dépassent leur devis de plus de {fp(p.seuil_devis, 0)} ; la marge de la plus touchée passe de {fp(cmd.loc[cmd['Écart (%)'].idxmax(), 'Marge prévue (%)'], 0)} à "
        f"{fp(cmd.loc[cmd['Écart (%)'].idxmax(), 'Marge réelle (%)'], 0)} ({cmd.loc[cmd['Écart (%)'].idxmax(), 'Commande']}).",
        f"Capacité : une heure-machine supplémentaire vaut {fd(mix.attrs['prix_ombre'], 0)} de marge sur coûts variables lorsque la capacité est contrainte. Lorsque la charge dépasse la capacité, "
        f"on sert d'abord {mix.iloc[0]['Produit']} ({fd(mix.iloc[0]['MCV par heure-machine ($)'], 0)}/h), et on arbitre les soumissions des lignes les moins rentables à l'heure.",
        f"Soumissions : {int((plan['Prix actuel ($)'] < plan['Plancher complet ABC ($)']).sum())} ligne(s) se vendent sous leur coût complet. Toute soumission sous le plancher complet exige une approbation ; "
        "sous le plancher spécifique, un comité de direction.",
        f"Processus : les activités sans valeur ajoutée (attentes, reprises, corrections de factures) offrent {fk(eco_abm)} d'économies avec une réduction de {fp(p.reduction_abm, 0)}.",
    ]
    t_ec = pd.DataFrame({"Cause": list(ecarts), "Écart ($)": list(ecarts.values()), "Moyenne 11 mois ($)": [lim.loc[k, "Moyenne"] for k in ecarts],
                         "Limite haute ($)": [lim.loc[k, "Limite haute"] for k in ecarts], "À investiguer": ["Oui" if k in a_investiguer else "Non" for k in ecarts],
                         "Hors limites": ["Oui" if k in hors else "Non" for k in ecarts]})
    t_ec = _tab(t_ec, {"Écart ($)": "d", "Moyenne 11 mois ($)": "d", "Limite haute ($)": "d"})
    t_prix = _tab(plan[["Produit", "Prix actuel ($)", "Plancher spécifique ($)", "Plancher complet ABC ($)", "Prix cible ($)", "Position"]],
                  {"Prix actuel ($)": "d2", "Plancher spécifique ($)": "d2", "Plancher complet ABC ($)": "d2", "Prix cible ($)": "d2"})
    t_prix["Remise maximale sans approbation"] = [fp(max(0.0, 1 - r["Plancher complet ABC ($)"] / r["Prix actuel ($)"]), 0) for _, r in plan.iterrows()]
    t_mix = _tab(mix[["Produit", "MCV par heure-machine ($)", "Heures actuelles", "Heures allouées", "Variation vs actuel", "MCV optimale (k$)"]],
                 {"MCV par heure-machine ($)": "d", "Heures actuelles": "n", "Heures allouées": "n", "Variation vs actuel": "ps", "MCV optimale (k$)": "k"})
    t_abm = _tab(sans_valeur[["Processus", "Activité", "Coût (k$)", "Coût après (k$)"]], {"Coût (k$)": "k", "Coût après (k$)": "k"})
    t_coq = _tab(coq["detail"], {"Montant (k$)": "k"})
    ecart_h = ecarts["Rendement (heures)"] - lim.loc["Rendement (heures)", "Moyenne"]
    ecart_t = ecarts["Taux horaire"] - lim.loc["Taux horaire", "Moyenne"]
    sections = [
        Section("1. Écarts du mois sur coûts standards", [
            f"Production de {p.pieces:,.0f} pièces : barre achetée {p.kg_achetes:,.0f} kg à {fd(p.prix_reel, 2)}/kg, {p.heures_reelles:,.0f} heures à {fd(p.taux_reel, 2)}/h, frais variables {fd(p.variable_reel)}.".replace(",", " "),
            "Un écart n'est investigué que s'il dépasse à la fois un pourcentage du standard et un montant minimal ; il est jugé « hors limites » s'il sort de la moyenne des onze mois précédents ± 2 écarts-types."], t_ec,
                "Positif = défavorable. Les limites de contrôle sont calculées sur l'historique des onze mois précédents."),
        Section("1 bis. Frais généraux fixes de fabrication : budget et volume", [
            f"Les frais fixes sont imputés aux pièces à un taux prédéterminé de {fd(ff['taux'], 2)} par pièce (budget de {fd(ff['budget'])} ÷ production normale de {C.FIXES_STANDARD['volume_normal']:,.0f} pièces). "
            "La production de la période en a absorbé moins que le budget : la différence n'est pas un coût de pièce, c'est un coût de période.".replace(",", " ")],
                _tab(pd.DataFrame({"Élément": ["Frais fixes budgétés", "Frais fixes dépensés", "Frais fixes imputés (pièces × taux)", "Écart de budget (dépensé − budgété)", "Écart de volume (budgété − imputé)", "Sous-imputation totale"],
                                   "Montant ($)": [ff["budget"], ff["reel"], ff["imputes"], ff["ecart_budget"], ff["ecart_volume"], ff["sous_imputation"]]}), {"Montant ($)": "d"}),
                "Positif = défavorable. L'écart de budget relève des responsables de dépenses ; l'écart de volume, de la planification de la charge et de la demande."),
        Section("2. Soumissions : planchers, prix cible et marge de manœuvre", [
            "Les vendeurs négocient à l'intérieur d'un couloir : jamais sous le plancher variable, avec approbation sous le plancher complet, et jamais sous le plancher spécifique sans comité. "
            "La dernière colonne donne la remise maximale que le coût complet ABC permet à partir du prix actuel."], t_prix),
        Section("3. Capacité et mix de production", [
            f"Avec {p.capacite_cnc:,.0f} heures-machine normales et une croissance de la demande de {fp(p.croissance_max, 0)} par ligne, le mix qui maximise la marge sur coûts variables est le suivant. "
            "Il ne tient pas compte des charges fixes spécifiques : il guide l'ordonnancement et les soumissions, pas l'abandon d'une ligne.".replace(",", " ")], t_mix,
                f"Contrainte {'active' if mix.attrs['contrainte_active'] else 'inactive'} ; valeur d'une heure-machine de plus : {fd(mix.attrs['prix_ombre'], 0)}."),
        Section("3 bis. Devis contre réel : les commandes suivies", [
            "Chaque commande est comparée à son devis, élément par élément. Une commande « à revoir » dépasse son devis de plus du seuil ; on y cherche l'élément qui dérive (heures-machine, réglages, sous-traitance, reprises) avant la prochaine soumission du même type."],
                _tab(cmd[["Commande", "Prix soumis ($)", "Coût estimé ($)", "Coût réel ($)", "Écart (%)", "Marge prévue (%)", "Marge réelle (%)"]],
                     {"Prix soumis ($)": "d", "Coût estimé ($)": "d", "Coût réel ($)": "d", "Écart (%)": "ps", "Marge prévue (%)": "p", "Marge réelle (%)": "p"}),
                f"Seuil : {fp(p.seuil_devis, 0)} du coût estimé. Taux machine standard : {fd(C.taux_machine(), 2)} par heure ; main-d'œuvre : {fd(C.STANDARD['taux'], 2)} par heure."),
        Section("4. Efficacité des processus (ABM)", [
            "Seules les activités sans valeur ajoutée sont ciblées : on protège le temps de coupe et la finition, on réduit les attentes, les reprises et les corrections."], t_abm,
                f"Réduction visée : {fp(p.reduction_abm, 0)} ; économie annuelle : {fk(eco_abm)}."),
        Section("5. Coût de la qualité", [
            f"Total {fk(coq['total'])} ({fp(coq['pct_ventes'])} des ventes) : conformité {fk(coq['conformite'])}, non-conformité {fk(coq['non_conformite'])}. "
            "Dépenser un peu plus en prévention est presque toujours moins cher que de corriger en atelier ou chez le client."], t_coq),
    ]
    actions = [
        Action(f"Enquêter sur le rendement des heures : réglages, attentes entre opérations, programmes FAO, pannes (écart de {fd(ecarts['Rendement (heures)'])} contre {fd(lim.loc['Rendement (heures)', 'Moyenne'])} en moyenne)",
               "Directeur de production", "30 jours", f"ramener l'écart à la moyenne : {fd(max(ecart_h, 0) * 12)} par année", "Haute"),
        Action(f"Renégocier les surcharges et les conditions d'achat de la matière : {fd(dec['effet_achat'])} d'écart n'est pas expliqué par le marché", "Acheteur principal",
               "60 jours", f"jusqu'à {fd(max(dec['effet_achat'], 0) * 12)} par année", "Haute"),
        Action(f"Vérifier les heures supplémentaires et la répartition des quarts : taux horaire de {fd(p.taux_reel, 2)} contre {fd(C.STANDARD['taux'], 2)} au standard", "Directeur de production et paie",
               "60 jours", f"{fd(max(ecart_t, 0) * 12)} par année", "Moyenne"),
        Action(f"Réviser les gabarits d'estimation des {n_revoir} commande(s) qui dépassent leur devis (heures-machine, réglages) avant la prochaine soumission du même type", "Estimateur en chef et directeur de production",
               "60 jours", f"{fd(float(cmd.loc[cmd['Écart (%)'] > p.seuil_devis, 'Écart ($)'].sum()), 0)} de dépassements sur les commandes suivies", "Haute"),
        Action(f"Remplir la charge du centre d'usinage : la sous-imputation des frais fixes ({fd(ff['sous_imputation'], 0)} ce mois-ci) vient surtout de l'écart de volume", "Planificateur et directeur des ventes",
               "90 jours", f"{fd(max(ff['ecart_volume'], 0) * 12, 0)} par année si l'écart se maintient", "Moyenne"),
        Action("Mettre en place le couloir de prix des soumissions (planchers variable, spécifique, complet) et l'approbation sous le plancher complet", "Directeur des ventes et contrôleur",
               "30 jours", "Évite de vendre à perte les lignes déjà sous leur coût complet", "Haute"),
        Action("Ordonnancer selon la marge par heure-machine quand la charge dépasse la capacité", "Planificateur de production", "Immédiat", f"{fd(mix.attrs['prix_ombre'], 0)} par heure-machine arbitrée", "Moyenne"),
        Action("Lancer un chantier de réduction des attentes entre opérations, des reprises et des corrections de factures", "Directeur de production et comptabilité", "90 jours", f"{fk(eco_abm)} par année", "Moyenne"),
    ]
    return Rapport("Tactique", "Rapport tactique mensuel sur les coûts de revient", "Directeurs de production, des ventes et des finances", "Mensuel", p.periode,
                   "Expliquer les écarts du mois, cadrer les soumissions et arbitrer la capacité et les processus.", kpis, messages, sections, actions,
                   "Coûts standards et écarts (prix, quantité, taux, rendement, frais variables) avec règle d'investigation et limites de contrôle ; décomposition de l'écart de prix entre marché et achat ; "
                   "planchers de prix ; mix sous contrainte de capacité (théorie des contraintes) ; ABM ; coût de la qualité. Montants fictifs.")


# --- rapport opérationnel --------------------------------------------------------------------------------------------------------------------------
def rapport_operationnel(p: Parametres | None = None) -> Rapport:
    p = p or Parametres()
    b = _base(p)
    S, e, ecarts, lim, cap = C.STANDARD, b["e"], b["ecarts"], b["lim"], b["cap"]
    kg_std, h_std = p.pieces * S["kg_par_piece"], p.pieces * S["heures_par_piece"]
    rebut = p.kg_achetes / kg_std - 1
    rend = p.heures_reelles / h_std - 1
    cout_piece_std, cout_piece_reel = e["_cout_standard"] / p.pieces, e["_cout_reel"] / p.pieces
    util_cnc = float(cap.set_index("Centre").loc["Usinage CNC", "Utilisation"])
    qualite_mois = float(b["coq"]["par_categorie"]["Défaillance interne"]) / 12
    kpis = [
        Kpi("Heures de main-d'œuvre : réelles contre standard", f"{p.heures_reelles:,.0f} h".replace(",", " "), f"{h_std:,.0f} h".replace(",", " "), _statut(rend, haut_ok=0.03, haut_att=0.08), f"{fp(rend, 1, True)} du standard"),
        Kpi("Matière achetée contre standard", f"{p.kg_achetes:,.0f} kg".replace(",", " "), f"{kg_std:,.0f} kg".replace(",", " "), _statut(rebut, haut_ok=0.02, haut_att=0.05), f"{fp(rebut, 1, True)} : copeaux, chutes et rebuts"),
        Kpi("Coût par pièce : réel contre standard", fd(cout_piece_reel, 2), fd(cout_piece_std, 2), _statut(cout_piece_reel / cout_piece_std - 1, haut_ok=0.03, haut_att=0.07), f"{fd(cout_piece_reel - cout_piece_std, 2, True)} par pièce"),
        Kpi("Taux horaire réel", fd(p.taux_reel, 2), fd(S["taux"], 2), _statut(p.taux_reel / S["taux"] - 1, haut_ok=0.02, haut_att=0.05), "heures supplémentaires et primes incluses"),
        Kpi("Utilisation du centre d'usinage", fp(util_cnc, 0), "80 % à 95 %", _statut(util_cnc, ok=(0.80, 0.95))),
        Kpi("Reprises, retouches et rebuts (coût mensuel moyen)", fd(qualite_mois * 1000), "—", "info", "à suivre chaque semaine"),
    ]
    alertes = [k for k in ecarts if lim.loc[k, "Hors limites"]]
    messages = [
        f"Le coût réel d'une pièce dépasse le standard de **{fd(cout_piece_reel - cout_piece_std, 2)}** ({fp(cout_piece_reel / cout_piece_std - 1, 1)}).",
        f"Les heures de main-d'œuvre dépassent le standard de {fp(rend, 1)} : à {fd(S['taux'], 0)} l'heure, chaque heure perdue coûte {fd(S['taux'], 0)} avant même de compter la machine immobile.",
        f"La matière achetée dépasse le standard de {fp(rebut, 1)} : chaque kilo de plus coûte {fd(S['prix'], 2)}.",
        ("Alerte : " + ", ".join(alertes) + " sort des limites habituelles — vérifier en priorité.") if alertes else "Aucun écart ne sort des limites habituelles cette semaine.",
    ]
    t_tab = pd.DataFrame({"Indicateur": ["Heures de main-d'œuvre", "Matière achetée (kg)", "Taux horaire ($/h)", "Prix de la matière ($/kg)", "Frais variables ($)"],
                          "Standard": [h_std, kg_std, S["taux"], S["prix"], p.pieces * S["variable_par_piece"]],
                          "Réel": [p.heures_reelles, p.kg_achetes, p.taux_reel, p.prix_reel, p.variable_reel]})
    t_tab["Écart"] = t_tab["Réel"] / t_tab["Standard"] - 1
    t_tab["Statut"] = [STATUTS[_statut(v, haut_ok=0.03, haut_att=0.07)] for v in t_tab["Écart"]]
    t_tab["Standard"] = [f"{v:,.2f}".replace(",", " ").replace(".", ",") for v in t_tab["Standard"]]
    t_tab["Réel"] = [f"{v:,.2f}".replace(",", " ").replace(".", ",") for v in t_tab["Réel"]]
    t_tab["Écart"] = [fp(v, 1, True) for v in t_tab["Écart"]]
    barème = pd.DataFrame({"Si…": ["1 heure de main-d'œuvre perdue", "1 kg de matière perdu (rebut)", "1 point de rebut sur la production annuelle", "1 heure-machine de plus vendue (capacité contrainte)",
                                   "1 point d'utilisation du centre d'usinage", "1 reprise évitée par semaine (2 h de main-d'œuvre)"],
                           "Alors…": [fd(S["taux"], 0), fd(S["prix"], 2), fd(0.01 * kg_std * 12 * S["prix"], 0) + " par année", fd(b["mix"].attrs["prix_ombre"], 0), fd(0.01 * p.capacite_cnc * b["mix"].attrs["prix_ombre"], 0) + " par année",
                                      fd(2 * S["taux"] * 52, 0) + " par année"]})
    t_std = pd.DataFrame({"Standard": ["Barre par pièce (copeaux et chutes compris)", "Main-d'œuvre par pièce", "Taux horaire chargé", "Prix de la matière", "Frais variables par pièce"],
                          "Valeur": [f"{S['kg_par_piece']} kg", f"{S['heures_par_piece']} h", fd(S["taux"], 2) + "/h", fd(S["prix"], 2) + "/kg", fd(S["variable_par_piece"], 2)]})
    checklist = {"Rendement (heures)": "Temps de réglage et de changement d'outil, attentes de matière ou de programme, pannes, premier article refusé, formation du personnel.",
                 "Quantité de matière (rebuts, copeaux)": "Longueur de barre commandée contre longueur utile, chutes réutilisables, pièces rebutées, réglages de départ, cotes mal usinées.",
                 "Taux horaire": "Heures supplémentaires, primes de quart, remplacements, ancienneté de l'équipe affectée.",
                 "Prix de la matière": "Hors du contrôle de l'atelier : signaler tout lot facturé à un prix inhabituel à l'acheteur.",
                 "Frais variables": "Usure d'outils de coupe, consommables, énergie machine, outillage perdu."}
    t_alert = pd.DataFrame({"Cause": list(ecarts), "Statut": ["Hors limites" if k in alertes else "Dans les limites" for k in ecarts], "Quoi vérifier": [checklist[k] for k in ecarts]})
    sections = [
        Section("1. Tableau de bord de la période", ["Standard et réel de l'exemple de production du mois ; l'écart est exprimé en % du standard (seuils : vert jusqu'à 3 %, jaune jusqu'à 7 %)."], t_tab),
        Section("2. Alertes et quoi vérifier", ["Les causes hors des limites habituelles passent en premier. La colonne de droite dit où chercher."], t_alert),
        Section("3. Ce que ça coûte (barème d'impact)", ["Pour savoir si un problème mérite qu'on arrête la ligne ou qu'on attende la fin du quart."], barème),
        Section("3 bis. Commandes à surveiller", ["Les trois commandes qui s'éloignent le plus de leur devis : vérifier les heures-machine et les réglages à chaque quart avant que l'écart ne s'agrandisse."],
                _tab(b["cmd"].sort_values("Écart (%)", ascending=False).head(3)[["Commande", "Écart (%)", "Marge prévue (%)", "Marge réelle (%)"]], {"Écart (%)": "ps", "Marge prévue (%)": "p", "Marge réelle (%)": "p"})),
        Section("4. Les standards en vigueur", ["Ce contre quoi l'atelier est mesuré. Un standard qui ne reflète plus la réalité doit être révisé, pas contourné."], t_std),
    ]
    actions = [
        Action("Relever chaque jour les heures réelles et les kilos de barre sortis par ordre de fabrication, et les comparer au standard", "Chef d'équipe", "Cette semaine", "Détecte l'écart de rendement en cours de quart", "Haute"),
        Action("Revoir les temps de réglage des trois pièces les plus fréquentes (changements d'outil, mise en position, premier article)", "Contremaître et programmeur FAO", "2 semaines",
               f"Chaque heure gagnée = {fd(S['taux'], 0)} de main-d'œuvre", "Haute"),
        Action("Trier et peser les chutes de barre ; réutiliser les longueurs utiles avant de commander", "Magasinier", "2 semaines", f"Chaque point de rebut = {fd(0.01 * kg_std * 12 * S['prix'], 0)} par année", "Moyenne"),
        Action("Vérifier l'équipe affectée aux heures supplémentaires et les primes de quart", "Contremaître", "1 semaine", f"Taux effectif de {fd(p.taux_reel, 2)} contre {fd(S['taux'], 2)}", "Moyenne"),
        Action("Consigner chaque reprise (cause, durée, pièce) pour alimenter le coût de la qualité", "Inspecteur qualité", "Cette semaine", "Rend visible le coût des défaillances internes", "Moyenne"),
    ]
    return Rapport("Opérationnel", "Rapport opérationnel hebdomadaire de l'atelier", "Superviseurs d'atelier, contremaîtres et planificateurs", "Hebdomadaire (suivi quotidien)", p.periode,
                   "Mesurer l'atelier contre ses standards, signaler les écarts hors limites et dire quoi vérifier tout de suite.", kpis, messages, sections, actions,
                   "Coûts standards de la production réelle ; écarts de quantité et de rendement exprimés en heures et en kilos ; limites de contrôle de l'historique ; barème d'impact des principales causes. Montants fictifs.")


RAPPORTS = {"Stratégique": rapport_strategique, "Tactique": rapport_tactique, "Opérationnel": rapport_operationnel}


def construire(niveau: str, p: Parametres | None = None) -> Rapport:
    """Rapport d'un niveau, avec les sections numérotées dans l'ordre."""
    import re
    r = RAPPORTS[niveau](p)
    for i, s in enumerate(r.sections, 1):
        s.titre = f"{i}. " + re.sub(r"^\d+( bis)?\.\s*", "", s.titre)
    return r


# --- exports ----------------------------------------------------------------------------------------------------------------------------------------
def en_markdown(r: Rapport) -> str:
    L = [f"# {r.titre}", "", f"**Niveau :** {r.niveau} · **Destinataires :** {r.destinataires} · **Fréquence :** {r.frequence} · **Période :** {r.periode}", "", f"*{r.objectif}*", "",
         "## Indicateurs", "", "| Indicateur | Valeur | Cible | Statut | Note |", "|---|---|---|---|---|"]
    L += [f"| {k.libelle} | {k.valeur} | {k.cible} | {STATUTS[k.statut]} | {k.note} |" for k in r.kpis]
    L += ["", "## À retenir", ""] + [f"- {m}" for m in r.messages]
    for s in r.sections:
        L += ["", f"## {s.titre}", ""] + [x + "\n" for x in s.paragraphes]
        if s.tableau is not None:
            cols = list(s.tableau.columns)
            L += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(str(v) for v in row) + " |" for row in s.tableau.itertuples(index=False)]
        if s.legende:
            L += ["", f"*{s.legende}*"]
    L += ["", "## Plan d'action", "", "| Action | Responsable | Échéance | Impact | Priorité |", "|---|---|---|---|---|"]
    L += [f"| {a.action} | {a.responsable} | {a.echeance} | {a.impact} | {a.priorite} |" for a in r.actions]
    if r.methode:
        L += ["", "## Méthode", "", r.methode]
    return "\n".join(L).replace("**", "**")


def _gras_html(texte: str) -> str:
    out, ouvert = [], False
    for morceau in html.escape(texte).split("**"):
        out.append(f"<b>{morceau}</b>" if ouvert else morceau)
        ouvert = not ouvert
    return "".join(out)


def en_html(r: Rapport) -> str:
    css = ("body{font-family:Segoe UI,Arial,sans-serif;color:#1b2430;max-width:1100px;margin:24px auto;padding:0 20px;line-height:1.45}h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.12rem;margin:26px 0 8px;"
           "border-bottom:2px solid #1f5f8b;padding-bottom:3px;color:#1f5f8b}.meta{color:#5b6573;font-size:.88rem}.obj{background:#eef3f8;border-left:4px solid #1f5f8b;padding:8px 12px;margin:12px 0}"
           ".kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}.k{border:1px solid #d9dde3;border-top:4px solid var(--c);border-radius:8px;padding:8px 10px}"
           ".k small{color:#5b6573;display:block}.k b{font-size:1.25rem}.k .s{color:var(--c);font-weight:600;font-size:.8rem}table{border-collapse:collapse;width:100%;font-size:.84rem;margin:8px 0}"
           "th{background:#1f5f8b;color:#fff;text-align:left;padding:5px 7px}td{border-bottom:1px solid #e3e6ea;padding:4px 7px;vertical-align:top}.leg{color:#5b6573;font-size:.8rem}li{margin:4px 0}"
           "@media print{body{margin:0}h2{break-after:avoid}}")
    kp = "".join(f'<div class="k" style="--c:{COULEURS_STATUT[k.statut]}"><small>{html.escape(k.libelle)}</small><b>{html.escape(k.valeur)}</b><div class="s">{STATUTS[k.statut]}'
                 f'{" · cible " + html.escape(k.cible) if k.cible and k.cible != "—" else ""}</div><small>{html.escape(k.note)}</small></div>' for k in r.kpis)
    corps = [f"<h1>{html.escape(r.titre)}</h1><div class=meta>{html.escape(r.niveau)} · {html.escape(r.destinataires)} · {html.escape(r.frequence)} · {html.escape(r.periode)}</div>",
             f'<div class="obj">{html.escape(r.objectif)}</div>', "<h2>Indicateurs</h2>", f'<div class="kpis">{kp}</div>', "<h2>À retenir</h2><ul>" + "".join(f"<li>{_gras_html(m)}</li>" for m in r.messages) + "</ul>"]
    for s in r.sections:
        corps.append(f"<h2>{html.escape(s.titre)}</h2>" + "".join(f"<p>{_gras_html(x)}</p>" for x in s.paragraphes))
        if s.tableau is not None:
            corps.append(s.tableau.to_html(index=False, escape=True, border=0))
        if s.legende:
            corps.append(f'<div class="leg">{html.escape(s.legende)}</div>')
    corps.append("<h2>Plan d'action</h2>" + pd.DataFrame([{"Action": a.action, "Responsable": a.responsable, "Échéance": a.echeance, "Impact": a.impact, "Priorité": a.priorite} for a in r.actions]).to_html(index=False, border=0))
    if r.methode:
        corps.append(f"<h2>Méthode</h2><p class=leg>{html.escape(r.methode)}</p>")
    return f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{html.escape(r.titre)}</title><style>{css}</style></head><body>{"".join(corps)}</body></html>'


def _pdf_texte(t: str) -> str:
    """Les polices standard de PDF ne connaissent que le jeu Latin-1 et quelques signes : on remplace le reste."""
    for a, b in (("→", "->"), ("≥", ">="), ("≤", "<="), ("−", "-"), ("×", "x"), ("★", "*"), ("⚠", "!"), ("±", "+/-"), (" ", " "), (" ", " ")):
        t = t.replace(a, b)
    return t.encode("latin-1", "replace").decode("latin-1")


def en_pdf(r: Rapport) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    marque = colors.HexColor("#1f5f8b")
    base = getSampleStyleSheet()
    N = ParagraphStyle("n", parent=base["BodyText"], fontSize=9, leading=12)
    P = ParagraphStyle("p", parent=N, fontSize=7.2, leading=8.8)
    H1 = ParagraphStyle("h1", parent=base["Heading1"], fontSize=16, textColor=marque, spaceAfter=2)
    H2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=11.5, textColor=marque, spaceBefore=10, spaceAfter=4)
    petit = ParagraphStyle("pt", parent=N, fontSize=8, textColor=colors.HexColor("#5b6573"))

    def gras(t: str) -> str:
        out, ouvert = [], False
        for m in _pdf_texte(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").split("**"):
            out.append(f"<b>{m}</b>" if ouvert else m)
            ouvert = not ouvert
        return "".join(out)

    def table(entetes: list[str], lignes: list[list[str]], largeurs: list[float] | None = None) -> Table:
        data = [[Paragraph(f"<b>{_pdf_texte(h)}</b>", ParagraphStyle("th", parent=P, textColor=colors.white)) for h in entetes]] + [[Paragraph(gras(str(c)), P) for c in row] for row in lignes]
        t = Table(data, colWidths=largeurs, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), marque), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f8")]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9dde3")), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        return t

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=_pdf_texte(r.titre), author="Groupe Usinage Saint-Maurice")
    larg = landscape(A4)[0] - 28 * mm
    el = [Paragraph(_pdf_texte(r.titre), H1), Paragraph(_pdf_texte(f"{r.niveau} | {r.destinataires} | {r.frequence} | {r.periode}"), petit), Spacer(1, 3), Paragraph("<i>" + _pdf_texte(r.objectif) + "</i>", N),
          Paragraph("Indicateurs", H2)]
    el.append(table(["Indicateur", "Valeur", "Cible", "Statut", "Note"], [[k.libelle, k.valeur, k.cible, STATUTS[k.statut], k.note] for k in r.kpis], [larg * x for x in (.28, .14, .13, .12, .33)]))
    el.append(Paragraph("À retenir", H2))
    el += [Paragraph("• " + gras(m), N) for m in r.messages]
    for s in r.sections:
        el.append(Paragraph(_pdf_texte(s.titre), H2))
        el += [Paragraph(gras(x), N) for x in s.paragraphes]
        if s.tableau is not None and len(s.tableau.columns):
            n = len(s.tableau.columns)
            el += [Spacer(1, 3), table(list(s.tableau.columns), s.tableau.astype(str).values.tolist(), [larg * (0.30 if i == 0 else 0.70 / (n - 1)) for i in range(n)] if n > 1 else None)]
        if s.legende:
            el.append(Paragraph(gras(s.legende), petit))
    el.append(Paragraph("Plan d'action", H2))
    el.append(table(["Action", "Responsable", "Échéance", "Impact", "Priorité"], [[a.action, a.responsable, a.echeance, a.impact, a.priorite] for a in r.actions], [larg * x for x in (.40, .17, .13, .22, .08)]))
    if r.methode:
        el += [Paragraph("Méthode", H2), Paragraph(gras(r.methode), petit)]
    doc.build(el)
    return tampon.getvalue()
