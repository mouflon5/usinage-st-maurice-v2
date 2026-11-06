"""
Générateur de scénarios aléatoires (reproductibles par graine) pour la démo.

Chaque scénario fabrique de vrais relevés PDF, déclare ce que le pipeline DOIT produire (« attendu »),
et le lanceur compare à ce qui est obtenu. Les montants et fournisseurs sont tirés de ta base
(historique de journal_general) pour rester réalistes ; les « attendus » sont fixés AVANT l'exécution,
indépendamment des agents.
"""

import os
import random
import re
import shutil
import sqlite3
from dataclasses import dataclass, field

from generer_scenario1 import creer_releve, lignes_en_cascade

COMPTE = "Desjardins EOP"


@dataclass
class Scenario:
    nom: str
    description: str
    periode: str                          # AAAA-MM analysé
    periode_debut: str
    dossier: str
    attendu: dict                         # statut_pipeline + indicateurs attendus
    rejeux: int = 1                       # nb d'exécutions successives du même relevé
    corruption_sql: str = ""              # SQL appliqué à la copie de démo avant l'exécution
    notes: list = field(default_factory=list)


def _mots_cles(conn):
    return [m.upper() for (m,) in conn.execute("SELECT mot_cle FROM mots_cles")]


def _modeles(conn, nature):
    """(motif de description, catégorie, montant médian) tirés de l'historique 2025-2026."""
    rows = conn.execute(
        "SELECT description, categorie, ABS(montant) FROM journal_general WHERE nature=? AND annee>=2025", (nature,)).fetchall()
    return rows


def _gabarit(description: str, rng: random.Random) -> str:
    return re.sub(r"FACT\s+\d+", f"FACT {rng.randint(60000, 99999)}", description)


def _jour(per, rng, bornes=(2, 27)):
    return f"{per}-{rng.randint(*bornes):02d}"


def _mouvements_normaux(conn, per, rng, n):
    dep = _modeles(conn, "Variable") + _modeles(conn, "Fixe")
    rev = _modeles(conn, "Revenu")
    mouv = []
    for _ in range(n):
        if rng.random() < 0.35:
            d, c, m = rng.choice(rev)
            mouv.append((_jour(per, rng), _gabarit(d, rng), round(m * rng.uniform(0.7, 1.2), 2), c))
        else:
            d, c, m = rng.choice(dep)
            mouv.append((_jour(per, rng), _gabarit(d, rng), -round(m * rng.uniform(0.7, 1.2), 2), c))
    return sorted(mouv)


def _candidat_residu_resolu(conn, per, rng):
    """Description sans mot-clé mais dont le fournisseur existe dans l'historique (→ précédent)."""
    mots = _mots_cles(conn)
    rows = conn.execute("SELECT DISTINCT description, categorie, nature, ABS(montant) FROM journal_general WHERE annee>=2025").fetchall()
    rng.shuffle(rows)
    for d, c, nat, m in rows:
        fournisseur = d.split(" - ", 1)[-1]
        if any(k in fournisseur.upper() for k in mots):
            continue
        return (_jour(per, rng), _gabarit(fournisseur, rng), (m if nat == "Revenu" else -m), c)
    return None


def _ecrire(dossier, per, mouvements, solde_depart=1_000_000.0, casse=False, ligne_illisible=False):
    os.makedirs(dossier, exist_ok=True)
    lignes = lignes_en_cascade(solde_depart, [(d, desc, m) for d, desc, m, *_ in mouvements])
    if casse:
        d, desc, m = lignes[-1][:10], lignes[-1][12:60].strip(), None
        v = lignes[-1].split()
        v[-1] = f"{float(v[-1]) + 500.00:.2f}"
        lignes[-1] = lignes[-1][:-12] + f"{float(v[-1]):>12.2f}"
    if ligne_illisible:
        lignes.insert(len(lignes) // 2, "VIREMENT ??? montant illisible")
    creer_releve(os.path.join(dossier, f"{COMPTE}_{per}.pdf"), COMPTE, lignes)


def generer(seed: int, n: int, source_db: str, racine: str = "releves_demo") -> list:
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    types = ["normal", "normal", "doublon", "residu_resolu", "residu_inconnu", "solde_casse",
             "ligne_illisible", "mois_manquant", "base_corrompue", "gros_ecart"]
    ordre = [types[i % len(types)] for i in range(n)]
    rng.shuffle(ordre)
    if n >= len(types):
        ordre[:len(types)] = rng.sample(types, len(types))   # tous les types au moins une fois
    scenarios = []
    for i, t in enumerate(ordre, 1):
        per = f"2026-{rng.randint(2, 11):02d}"
        dossier = os.path.join(racine, f"s{i:02d}_{t}")
        if os.path.isdir(dossier):
            shutil.rmtree(dossier)
        nb = rng.randint(4, 8)
        mouv = _mouvements_normaux(conn, per, rng, nb)
        debut = per
        corr, rejeux, notes = "", 1, []
        attendu = {"statut_pipeline": "complet", "promus": nb, "a_classer": 0, "doublons": 0}

        if t == "doublon":
            rejeux = 2
            attendu.update({"doublons": nb, "promus": 0, "derniere_execution": True})
            desc = "Même relevé soumis deux fois : la 2e exécution doit tout reconnaître comme doublon."
        elif t == "residu_resolu":
            c = _candidat_residu_resolu(conn, per, rng)
            mouv = sorted(mouv + [c])
            attendu.update({"promus": nb + 1, "categorie_ligne_resolue": c[3]})
            notes.append(f"ligne sans mot-clé : « {c[1]} » (catégorie attendue : {c[3]})")
            desc = "Une ligne sans mot-clé, résolue par les précédents (A3, LLM/simulé), puis pipeline complet."
        elif t == "residu_inconnu":
            mouv = sorted(mouv + [(_jour(per, rng), f"ZXQ INCONNU {rng.randint(100, 999)} VIREMENT DIVERS", -round(rng.uniform(5_000, 60_000), 2), None)])
            attendu.update({"statut_pipeline": "a_arbitrer", "promus": nb, "a_classer": 1})
            desc = "Une ligne inconnue : A3 doit l'escalader au contrôleur (arbitrage) et A4 à A7 ne doivent pas tourner."
        elif t == "solde_casse":
            attendu = {"statut_pipeline": "arrete_a2"}
            desc = "Rupture de continuité de solde dans le relevé : A2 doit arrêter le pipeline."
        elif t == "ligne_illisible":
            attendu = {"statut_pipeline": "arrete_a2"}
            desc = "Ligne non reconnue dans le PDF : A2 doit arrêter le pipeline."
        elif t == "mois_manquant":
            prev = f"2026-{int(per[5:]) - 1:02d}"
            debut = prev
            attendu = {"statut_pipeline": "arrete_a1"}
            desc = f"Relevé de {prev} absent : A1 doit détecter le trou et arrêter."
        elif t == "base_corrompue":
            # Corruption silencieuse du grand livre : A6 doit bloquer même si A1-A5 réussissent.
            corr = "UPDATE journal_general SET nature='Variable' WHERE no_ecriture=(SELECT no_ecriture FROM journal_general WHERE nature='Revenu' LIMIT 1)"
            attendu = {"statut_pipeline": "bloque_a6", "promus": nb}
            desc = "Une écriture du grand livre a une nature incohérente avec `categories` : A6 doit BLOQUER."
        elif t == "gros_ecart":
            d, c, m = rng.choice(_modeles(conn, "Variable"))
            mouv = sorted(mouv + [(_jour(per, rng), _gabarit(d, rng), -round(m * 6, 2), c)])
            attendu.update({"promus": nb + 1, "ecart_significatif": True})
            desc = "Une dépense 6× la normale : A5 doit signaler un écart défavorable significatif."
        else:
            desc = "Relevé normal : tout doit passer (A1→A7) et produire le rapport."

        if t == "mois_manquant":
            pass   # on écrit seulement le relevé du mois courant
        _ecrire(dossier, per, mouv, casse=(t == "solde_casse"), ligne_illisible=(t == "ligne_illisible"))
        scenarios.append(Scenario(f"s{i:02d}_{t}", desc, per, debut, dossier, attendu, rejeux, corr, notes))
    conn.close()
    return scenarios
