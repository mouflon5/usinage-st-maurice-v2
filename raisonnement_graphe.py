"""Le raisonnement des agents et des LLM vu comme un réseau de neurones : qui active qui, avec quel poids, et quels indicateurs en dépendent.

Le réseau est construit à partir des mêmes sources que la vue « Raisonnement » (tables `evenements`, `llm_traces` et `llm_appels` d'un passage) :

  couche 0   Entrées        relevés bancaires, plan de classement (mots-clés), journal général, budget
  couches 1-6  Agents       A1 Acquisition → A2 Extraction → A3 Classement → A4 Prévision → A5 Écarts → A6 Contrôle → A8 Relecture → décision humaine → A7 Rapports
  autour des agents       un neurone LLM (modèle, échanges, décisions) et un garde-fou (la règle qui accepte ou rejette sa réponse) pour A3, A5, A8 et A7
  couche 7   Indicateurs    ce que le passage a mesuré ou fait bouger : soldes, creux, flux, écarts, contrôles, réserves ; reliés aux agents qui les produisent et entre eux

Une synapse porte un poids (le volume transmis : fichiers, transactions, lignes, contrôles) et un type : flux de données, échange avec le LLM (coloré par la décision de l'agent),
garde-fou, supervision, influence sur un indicateur, relation entre indicateurs. Sans passage, le réseau montre seulement sa structure ; avec un passage, chaque neurone
est coloré par le verdict de l'agent et le rejeu allume le réseau étape par étape. Fonctions pures, testées par test_reseau_raisonnement.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

AGENTS = {  # code → (libellé court, nom complet)
    "A1": ("A1 Acquisition", "Acquisition"), "A2": ("A2 Extraction", "Extraction"), "A3": ("A3 Classement", "Classement et chargement"), "A4": ("A4 Prévision", "Prévision"),
    "A5": ("A5 Écarts", "Écarts"), "A6": ("A6 Contrôle", "Contrôle"), "A8": ("A8 Relecture", "Relecture"), "A7": ("A7 Rapports", "Rapports"),
}
ORDRE_AGENTS = ["A1", "A2", "A3", "A4", "A5", "A6", "A8", "A7"]            # ordre d'exécution du pipeline
AVEC_LLM = ("A3", "A5", "A8", "A7")
STATUTS_OK = ("complet", "approuve", "ok", "approuvée", "termine")
STATUTS_ATT = ("a_arbitrer", "complet_avec_reserves", "reserve", "reserves", "approuve_avec_reserves", "attente", "arbitrage")
STATUTS_CRIT = ("bloque", "bloquee", "erreur", "rejete", "echec", "arret", "arrete")
GARDES = {
    "A3": ("Garde-fou de classement", "La catégorie proposée doit exister au plan de classement ET la confiance doit dépasser le seuil ; sinon la ligne est escaladée à l'humain (« À classer »)."),
    "A5": ("Vérificateur de nombres", "Tout nombre du commentaire absent du tableau des écarts fait rejeter le texte du modèle, remplacé par un gabarit."),
    "A8": ("Garde-fou de relecture", "Chaque constat doit citer une référence et des nombres qui existent ; un constat non sourcé est rejeté. La relecture ne peut jamais bloquer."),
    "A7": ("Vérificateur de nombres", "La synthèse rédigée par le LLM est vérifiée nombre par nombre contre les chiffres du rapport."),
}
REGLES = {
    "A1": "Compare les périodes attendues aux périodes couvertes par les noms de fichiers ; un trou arrête la chaîne.",
    "A2": "Lit chaque document ; toute ligne non reconnue est rejetée (jamais devinée) ; vérifie la continuité des soldes.",
    "A3": "Écarte les doublons, classe par mots-clés, puis soumet seulement le résidu au LLM.",
    "A4": "Modèle statistique SARIMAX sur l'historique du journal. Aucun LLM.",
    "A5": "Écarts calculés en SQL ; le LLM ne fait que rédiger le commentaire.",
    "A6": "Onze contrôles déterministes ; un contrôle bloquant arrête tout.",
    "A8": "Second avis qualitatif : peut ajouter des réserves, jamais bloquer ni modifier.",
    "A7": "Produit les rapports ; la synthèse du LLM est vérifiée nombre par nombre.",
}
ENTREES = {"in_releves": "Relevés bancaires", "in_regles": "Plan de classement (mots-clés)", "in_journal": "Journal général", "in_budget": "Budget et paramètres"}
# indicateur : (id, libellé, source, clé, agents qui le produisent, sens favorable : +1 hausse = bien, -1 hausse = mal, 0 neutre, format)
INDICATEURS = [
    ("k_transactions", "Transactions extraites", "sorties", ("A2", "transactions"), ("A2",), 0, "n"),
    ("k_classees", "Lignes classées", "sorties", ("A3", "classees_a3"), ("A3",), 1, "n"),
    ("k_a_classer", "Lignes à classer (résidu)", "sorties", ("A3", "residu_a3"), ("A3",), -1, "n"),
    ("k_flux_prevu", "Flux net prévu", "sorties", ("A4", "flux_net_prevu"), ("A4",), 0, "n"),
    ("k_ecarts", "Écarts significatifs", "sorties", ("A5", "ecarts_a5"), ("A5",), -1, "n"),
    ("k_controles", "Contrôles réussis", "controles", ("A6", None), ("A6",), 1, "ratio"),
    ("k_reserves", "Constats de relecture", "sorties", ("A8", "constats_a8"), ("A8",), -1, "n"),
    ("k_fichiers", "Rapports produits", "sorties", ("A7", "fichiers_a7"), ("A7",), 0, "n"),
    ("solde_actuel", "Solde actuel", "kpi", "solde_actuel", ("A3",), 1, "$"),
    ("creux", "Creux de trésorerie", "kpi", "creux", ("A3", "A4"), 1, "$"),
    ("semaines_sous_seuil", "Semaines sous le seuil", "kpi", "semaines_sous_seuil", ("A4",), -1, "n"),
    ("coussin_requis", "Coussin requis", "kpi", "coussin_requis", ("A4",), 0, "$"),
    ("flux_net_2026", "Flux net de l'exercice", "kpi", "flux_net_2026", ("A3",), 1, "$"),
    ("ecart_budget_annee", "Écart au budget", "kpi", "ecart_budget_annee", ("A5",), 0, "$"),
]
# relations entre indicateurs (cause → effet)
RELATIONS_INDICATEURS = [("k_classees", "flux_net_2026", "chaque ligne classée entre dans le flux"), ("k_a_classer", "k_classees", "complément : ce qui n'est pas classé reste à arbitrer"),
                         ("flux_net_2026", "solde_actuel", "le flux alimente le solde"), ("solde_actuel", "creux", "le creux se mesure à partir du solde"),
                         ("creux", "semaines_sous_seuil", "un creux bas ouvre des semaines sous le seuil"), ("creux", "coussin_requis", "le coussin couvre le creux"),
                         ("k_ecarts", "ecart_budget_annee", "les écarts significatifs composent l'écart au budget"), ("k_flux_prevu", "creux", "la prévision déplace le creux futur")]


@dataclass
class Neurone:
    id: str
    label: str
    type: str                       # entree | agent | llm | garde | humain | indicateur | sortie
    x: float
    y: float
    agent: str | None = None
    statut: str = "inactif"         # ok | att | crit | inactif
    ordre: int = 0                  # étape du passage à laquelle il s'allume (0 = dès le départ)
    taille: float = 20.0
    valeur: str | None = None
    delta: float | None = None
    delta_bon: bool | None = None
    details: dict = field(default_factory=dict)


@dataclass
class Synapse:
    source: str
    cible: str
    type: str                       # flux | llm | garde | supervision | indicateur | relation
    poids: float = 1.0
    etiquette: str = ""
    statut: str = "inactif"         # ok | att | crit | inactif (llm : couleur de la décision)


@dataclass
class Reseau:
    neurones: dict[str, Neurone]
    synapses: list[Synapse]
    etapes: list[str]               # agents exécutés, dans l'ordre
    avec_passage: bool = False
    titre: str = ""


# --- outils -----------------------------------------------------------------------------------------------------------------------------------------
def statut_agent(statut: str | None) -> str:
    s = (statut or "").lower()
    if s in STATUTS_OK:
        return "ok"
    if s in STATUTS_ATT:
        return "att"
    if s in STATUTS_CRIT:
        return "crit"
    return "ok" if s else "inactif"


def decision_statut(decision: str | None) -> str:
    d = (decision or "").lower()
    if d.startswith(("accept", "retenu", "valid")):
        return "ok"
    if d.startswith(("escalad", "remplac", "abst")):
        return "att"
    if d:
        return "crit"
    return "inactif"


def formater(v: float | None, fmt: str) -> str | None:
    if v is None:
        return None
    if fmt == "$":
        return f"{v:,.0f} $".replace(",", " ")
    return f"{v:,.0f}".replace(",", " ")


# --- structure --------------------------------------------------------------------------------------------------------------------------------------
COORD_AGENTS = {"A1": (1.0, 0.0), "A2": (2.0, 0.0), "A3": (3.0, 0.0), "A4": (4.0, 0.9), "A5": (4.0, -0.9), "A6": (5.0, 0.9), "A8": (5.0, -0.9), "A7": (6.0, 0.9)}
COORD_LLM = {"A3": (3.0, 2.3), "A5": (4.0, -3.1), "A8": (5.0, -3.1), "A7": (6.0, 3.1)}
COORD_GARDE = {"A3": (3.0, 1.2), "A5": (4.0, -2.0), "A8": (5.0, -2.0), "A7": (6.0, 2.0)}


def _structure() -> Reseau:
    n: dict[str, Neurone] = {}
    for i, (cle, lib) in enumerate(ENTREES.items()):
        n[cle] = Neurone(cle, lib, "entree", 0.0, 1.5 - i * 1.0, taille=15)
    for code in ORDRE_AGENTS:
        x, y = COORD_AGENTS[code]
        n[code] = Neurone(code, AGENTS[code][0], "agent", x, y, agent=code, taille=30, details={"regle": REGLES[code], "nom": AGENTS[code][1]})
    for code in AVEC_LLM:
        n["llm_" + code] = Neurone("llm_" + code, f"LLM · {code}", "llm", *COORD_LLM[code], agent=code, taille=22)
        n["gf_" + code] = Neurone("gf_" + code, GARDES[code][0], "garde", *COORD_GARDE[code], agent=code, taille=16, details={"regle": GARDES[code][1]})
    n["humain"] = Neurone("humain", "Décision humaine", "humain", 6.0, -0.9, taille=22, details={"regle": "L'humain arbitre les lignes « À classer » et approuve le passage."})
    n["sortie"] = Neurone("sortie", "Rapports et verdict", "sortie", 7.0, 0.0, taille=24)
    # indicateurs : deux colonnes à droite
    col_a = [i for i in INDICATEURS if i[0].startswith("k_")]
    col_b = [i for i in INDICATEURS if not i[0].startswith("k_")]
    for k, (cle, lib, *_rest) in enumerate(col_a):
        n[cle] = Neurone(cle, lib, "indicateur", 8.4, 3.2 - k * 0.9, taille=15)
    for k, (cle, lib, *_rest) in enumerate(col_b):
        n[cle] = Neurone(cle, lib, "indicateur", 10.0, 3.0 - k * 1.15, taille=15)
    s: list[Synapse] = []
    s += [Synapse("in_releves", "A1", "flux", 1, "fichiers"), Synapse("in_releves", "A2", "flux", 1, "documents"), Synapse("in_regles", "A3", "flux", 1, "règles"),
          Synapse("in_journal", "A3", "flux", 1, "journal"), Synapse("in_journal", "A4", "flux", 1, "historique"), Synapse("in_budget", "A5", "flux", 1, "budget"), Synapse("in_journal", "A5", "flux", 1, "réel")]
    s += [Synapse("A1", "A2", "flux", 1, "fichiers"), Synapse("A2", "A3", "flux", 1, "transactions"), Synapse("A3", "A4", "flux", 1, "lignes classées"), Synapse("A3", "humain", "flux", 1, "à classer"),
          Synapse("A4", "A5", "flux", 1, "prévisions"), Synapse("A5", "A6", "flux", 1, "écarts"), Synapse("A6", "A8", "flux", 1, "contrôles"), Synapse("A8", "humain", "flux", 1, "constats"),
          Synapse("A6", "A7", "supervision", 1, "autorise"), Synapse("humain", "A7", "flux", 1, "décision"), Synapse("A8", "A7", "supervision", 1, "réserves"), Synapse("A7", "sortie", "flux", 1, "fichiers")]
    for code in AVEC_LLM:
        s += [Synapse(code, "llm_" + code, "llm", 1, "prompt"), Synapse("llm_" + code, "gf_" + code, "llm", 1, "réponse"), Synapse("gf_" + code, code, "garde", 1, "accepte ou rejette")]
    for cle, lib, _src, _k, agents, _sens, _f in INDICATEURS:
        for a in agents:
            s.append(Synapse(a, cle, "indicateur", 1, "mesure"))
    for a, b, pourquoi in RELATIONS_INDICATEURS:
        s.append(Synapse(a, b, "relation", 1, pourquoi))
    return Reseau(n, s, [], False, "Structure du réseau (aucun passage)")


# --- passage ----------------------------------------------------------------------------------------------------------------------------------------
def _json_liste(v):
    return v if isinstance(v, list) else []


def _res(e: dict | None) -> dict:
    """Résumé d'un événement d'agent : le moteur l'écrit dans detail["resume"] (sorties, contrôles, relecture)."""
    d = (e or {}).get("detail") or {}
    r = d.get("resume")
    return r if isinstance(r, dict) else d


def _kpi(e: dict) -> dict | None:
    """Indicateurs de trésorerie d'un événement (JSON dans la base)."""
    import json
    v = e.get("kpi")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    return v if isinstance(v, dict) else None


def _categorie_decision(decision: str | None) -> str:
    """accepte | escalade | rejet | aucune : une trace sans décision enregistrée est une réponse utilisée telle quelle (règle, gabarit ou simulation)."""
    d = (decision or "").lower()
    if not d or d.startswith(("accept", "retenu", "valid")):
        return "accepte"
    if d.startswith(("rejet", "erreur", "refus")):
        return "rejet"
    return "escalade"


def construire(evts: list[dict] | None = None, traces: list[dict] | None = None, appels=None, titre: str = "") -> Reseau:
    """Réseau d'un passage. `evts` : lignes de la table evenements (detail déjà décodé), `traces` : llm_traces (meta décodé), `appels` : liste de dict de llm_appels
    (ou DataFrame). Sans événements, retourne la structure seule."""
    r = _structure()
    evts, traces = evts or [], traces or []
    ag = [e for e in evts if e.get("type") == "agent" and e.get("agent") in AGENTS]
    if not ag and not evts:
        return r
    r.avec_passage, r.titre = True, titre or "Passage"
    par_agent = {e["agent"]: e for e in ag}
    r.etapes = [e["agent"] for e in ag]
    ordre = {code: i + 1 for i, code in enumerate(r.etapes)}
    durees = [float(e.get("duree") or 0) for e in ag] or [0.0]
    dmax = max(durees) or 1.0
    # agents
    for code in ORDRE_AGENTS:
        nr = r.neurones[code]
        e = par_agent.get(code)
        if not e:
            nr.statut, nr.taille = "inactif", 24
            nr.details.update(message="Non exécuté dans ce passage (le pipeline s'est arrêté avant ou a pris un autre chemin).")
            continue
        d = _res(e)
        nr.statut = statut_agent(e.get("statut"))
        nr.ordre = ordre[code]
        nr.taille = 28 + 16 * float(e.get("duree") or 0) / dmax
        nr.details.update(message=e.get("message"), duree=float(e.get("duree") or 0), statut_brut=e.get("statut"), sorties=d.get("sorties") or {}, detail=d)
    # entrées : allumées dès l'étape 0
    for cle in ENTREES:
        r.neurones[cle].statut, r.neurones[cle].ordre = "ok", 0
    # décision humaine : allumée si le passage l'a demandée (arbitrage) ou si A7 s'est exécuté après A8
    fin = next((e for e in reversed(evts) if e.get("type") == "fin"), None)
    verdict = ((fin or {}).get("detail") or {}).get("statut_pipeline") or (fin or {}).get("statut")
    humain_ev = next((e for e in evts if e.get("type") == "agent" and not e.get("agent") and "decision_humaine" in (_res(e).get("sorties") or {})), None)
    arbitrage = bool(verdict and "arbitrage" in str(verdict))
    if arbitrage or humain_ev or "A7" in par_agent:
        hum = r.neurones["humain"]
        hum.statut = "att" if arbitrage else "ok"
        hum.ordre = ordre.get("A8") or ordre.get("A3") or len(r.etapes)                     # l'humain intervient après la relecture, avant les rapports
        hum.details.update(message="Arbitrage humain demandé : des lignes restent « À classer »." if arbitrage else "Passage approuvé : le pipeline a poursuivi jusqu'aux rapports.", verdict=verdict)
    sortie = r.neurones["sortie"]
    sortie.statut = statut_agent(verdict) if verdict else "inactif"
    sortie.ordre = len(r.etapes) + 1
    sortie.details.update(message=(fin or {}).get("message"), verdict=verdict, fichiers=((fin or {}).get("detail") or {}).get("fichiers"))
    # neurones LLM et garde-fous
    appels_l = appels.to_dict("records") if hasattr(appels, "to_dict") else list(appels or [])
    for code in AVEC_LLM:
        mes = [t for t in traces if t.get("agent") == code]
        llm, gf = r.neurones["llm_" + code], r.neurones["gf_" + code]
        base = ordre.get(code, 0)
        llm.ordre = gf.ordre = base
        decisions: dict[str, int] = {}
        for t in mes:
            decisions[t.get("decision") or "réponse utilisée"] = decisions.get(t.get("decision") or "réponse utilisée", 0) + 1
        cats = [_categorie_decision(t.get("decision")) for t in mes]
        reels = [t for t in mes if t.get("fournisseur") not in (None, "simule")]
        fourn = sorted({f"{t.get('fournisseur')} · {t.get('modele')}" for t in mes}) or ["aucun échange"]
        ap = [a for a in appels_l if a.get("agent") == code and a.get("type", "appel") == "appel"]
        rejets = sum(1 for c in cats if c != "accepte")
        llm.details.update(echanges=len(mes), reels=len(reels), decisions=decisions, modeles=fourn, tokens_in=int(sum(a.get("tok_in") or 0 for a in ap)), tokens_out=int(sum(a.get("tok_out") or 0 for a in ap)),
                           traces=[{"id": t.get("id"), "decision": t.get("decision"), "detail": t.get("decision_detail"), "modele": t.get("modele")} for t in mes[:30]])
        gf.details.update(rejets=rejets, acceptees=len(mes) - rejets, rejets_durs=sum(1 for c in cats if c == "rejet"),
                          raisons=sorted({t.get("decision_detail") for t, c in zip(mes, cats) if t.get("decision_detail") and c != "accepte"})[:5])
        if mes:
            statut = "crit" if "rejet" in cats else ("att" if "escalade" in cats else "ok")
            llm.statut, gf.statut = statut, statut
            llm.taille = 18 + min(14, len(mes) * 1.5)
            llm.valeur = f"{len(mes)} échange(s)" + ("" if reels else " · simulé")
            gf.valeur = f"{rejets} écartée(s)" if rejets else "tout accepté"
        else:
            llm.statut = gf.statut = "inactif" if code not in par_agent else "ok"
            llm.valeur = "non sollicité" if code in par_agent else None
        llm.details["regle"] = "Le modèle propose ; l'agent décide. Sa réponse n'est utilisée que si le garde-fou l'accepte."
    # synapses : poids et état
    sorties = {code: _res(par_agent[code]).get("sorties") or {} for code in par_agent}
    poids = {("A1", "A2"): sorties.get("A1", {}).get("fichiers_trouves"), ("A2", "A3"): sorties.get("A2", {}).get("transactions"), ("A3", "A4"): sorties.get("A3", {}).get("classees_a3"),
             ("A3", "humain"): sorties.get("A3", {}).get("residu_a3"), ("A4", "A5"): sorties.get("A4", {}).get("previsions"), ("A5", "A6"): sorties.get("A5", {}).get("ecarts_a5"),
             ("A6", "A8"): sorties.get("A6", {}).get("controles_a6"), ("A8", "humain"): sorties.get("A8", {}).get("constats_a8"), ("A7", "sortie"): sorties.get("A7", {}).get("fichiers_a7"),
             ("humain", "A7"): (_res(humain_ev).get("sorties") or {}).get("decision_humaine") if humain_ev else None}
    for syn in r.synapses:
        a, b = r.neurones[syn.source], r.neurones[syn.cible]
        if syn.type in ("flux", "supervision"):
            w = poids.get((syn.source, syn.cible))
            actif = a.statut != "inactif" and b.statut != "inactif"
            if w is not None and w != 0:
                syn.poids = float(w)
            elif w == 0 and syn.source in par_agent:
                syn.poids = 0.0
            syn.statut = (a.statut if a.statut in ("att", "crit") else "ok") if actif else "inactif"
            if syn.poids:
                syn.etiquette = f"{syn.etiquette} · {syn.poids:g}" if syn.etiquette and syn.type == "flux" else syn.etiquette
        elif syn.type == "llm":
            llm_id = syn.cible if syn.cible.startswith("llm_") else syn.source
            code = llm_id.split("_", 1)[1]
            dec = r.neurones[llm_id].details.get("decisions") or {}
            syn.poids = float(sum(dec.values())) or 0.0
            syn.statut = r.neurones[llm_id].statut if syn.poids else "inactif"
        elif syn.type == "garde":
            code = syn.source.split("_", 1)[1]
            gf = r.neurones[syn.source]
            syn.poids = float(gf.details.get("rejets", 0) + gf.details.get("acceptees", 0))
            syn.statut = gf.statut
        elif syn.type == "indicateur":
            syn.statut = "ok" if a.statut != "inactif" and b.statut != "inactif" else "inactif"
        else:
            syn.statut = "ok" if a.statut != "inactif" and b.statut != "inactif" else "inactif"
    # indicateurs
    kpis = [k for k in (_kpi(e) for e in evts) if k]
    kpi_avant = next((_kpi(e) for e in evts if e.get("type") == "instantane" and _kpi(e)), None)
    kpi_apres = kpis[-1] if kpis else None
    for cle, lib, source, k, agents, sens, fmt in INDICATEURS:
        nr = r.neurones[cle]
        nr.ordre = min((ordre.get(a, 99) for a in agents if a in ordre), default=0)
        val, avant = None, None
        if source == "sorties":
            val = (sorties.get(k[0]) or {}).get(k[1])
        elif source == "controles":
            c = _json_liste(_res(par_agent.get("A6")).get("controles"))
            if c:
                val = float(sum(1 for x in c if x.get("ok")))
                nr.valeur = f"{int(val)} / {len(c)}"
                nr.details["total"] = len(c)
        elif source == "kpi" and kpi_apres:
            val = kpi_apres.get(k)
            avant = (kpi_avant or {}).get(k)
        if val is None or not any(a in ordre for a in agents):
            nr.statut = "inactif"
            continue
        nr.statut = "ok"
        if nr.valeur is None:
            nr.valeur = formater(float(val), fmt)
        if source == "controles":
            nr.statut = "ok" if val == nr.details.get("total") else "crit"
        if avant is not None and float(val) != float(avant):
            nr.delta = float(val) - float(avant)
            nr.delta_bon = None if sens == 0 else ((nr.delta > 0) == (sens > 0))
        nr.details.update(valeur_brute=float(val), avant=None if avant is None else float(avant), sens=sens, agents=list(agents))
        if source == "sorties" and val and cle in ("k_a_classer", "k_reserves", "k_ecarts") and float(val) > 0:
            nr.statut = "att"
        nr.taille = 15 + (3 if nr.delta else 0)
    return r


# --- interrogation du réseau -----------------------------------------------------------------------------------------------------------------------
def voisins(r: Reseau, cle: str, profondeur: int = 1) -> set[str]:
    """Le neurone, ses prédécesseurs et ses successeurs jusqu'à la profondeur donnée."""
    vus, front = {cle}, {cle}
    for _ in range(max(profondeur, 0)):
        nxt = set()
        for s in r.synapses:
            if s.source in front:
                nxt.add(s.cible)
            if s.cible in front:
                nxt.add(s.source)
        front = nxt - vus
        vus |= nxt
    return vus


def amont_aval(r: Reseau, cle: str) -> tuple[list[Synapse], list[Synapse]]:
    return [s for s in r.synapses if s.cible == cle], [s for s in r.synapses if s.source == cle]


def allume(r: Reseau, etape: int) -> set[str]:
    """Neurones allumés au rejeu à l'étape donnée (0 = entrées seulement). Sans passage, tout est allumé."""
    if not r.avec_passage:
        return set(r.neurones)
    return {k for k, n in r.neurones.items() if n.statut != "inactif" and n.ordre <= etape}


def nb_etapes(r: Reseau) -> int:
    return len(r.etapes) + 1 if r.avec_passage else 0


def resume(r: Reseau) -> dict:
    ag = [n for n in r.neurones.values() if n.type == "agent"]
    llm = [n for n in r.neurones.values() if n.type == "llm"]
    return {"agents_actifs": sum(1 for n in ag if n.statut != "inactif"), "agents": len(ag), "echanges_llm": sum(n.details.get("echanges", 0) for n in llm),
            "rejets": sum(n.details.get("rejets", 0) for n in r.neurones.values() if n.type == "garde"), "synapses": len(r.synapses),
            "indicateurs": sum(1 for n in r.neurones.values() if n.type == "indicateur" and n.statut != "inactif")}
