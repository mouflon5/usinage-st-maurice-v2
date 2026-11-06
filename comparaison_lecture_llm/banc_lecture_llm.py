"""
Banc d'essai : un modèle Ollama lit un relevé que le lecteur déterministe ne reconnaît pas.

    py -3 banc_lecture_llm.py <relevé.pdf> <modèle> <sortie.json>

La « vérité terrain » est reconstruite par une analyse propre à ce relevé Desjardins (premier compte, lignes « D AVR … solde »),
uniquement pour NOTER le modèle : elle n'entre jamais dans le pipeline. Pour chaque modèle on mesure :
    rappel / précision   lignes transcrites exactement (date + solde) par rapport à la vérité terrain ;
    garde-fou strict     lignes acceptées par lecture_llm.verifier_section tel quel ;
    garde-fou tolérant   idem après conversion déterministe JJ-MM-AAAA / JJ/MM/AAAA → AAAA-MM-JJ ;
    inventées            lignes dont le solde n'existe nulle part dans le document.
"""
import json
import os
import re
import sys
import time
from datetime import date

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
os.chdir(RACINE)


def verite_terrain(lignes):
    debut = next(i for i, l in enumerate(lignes) if l.startswith("Date Code Description"))
    fin = next(i for i, l in enumerate(lignes) if i > debut and l.startswith("COMPTE D'EPARGNE"))
    rows = []
    for l in lignes[debut:fin]:
        m = re.match(r"^(\d{1,2}) AVR \S+ .*?(?<![\d.])(\d{1,3}(?: \d{3})*\.\d{2})$", l)
        if m:
            rows.append({"date": f"2021-04-{int(m.group(1)):02d}", "solde": float(m.group(2).replace(" ", "")), "ligne": l})
    return rows


def date_iso(s):
    s = (s or "").strip()
    for rx, ordre in ((r"^(\d{4})-(\d{2})-(\d{2})$", (0, 1, 2)), (r"^(\d{2})[-/](\d{2})[-/](\d{4})$", (2, 1, 0))):
        m = re.match(rx, s)
        if m:
            try:
                g = m.groups()
                return date(int(g[ordre[0]]), int(g[ordre[1]]), int(g[ordre[2]])).isoformat()
            except ValueError:
                return None
    return None


def categorie(raison):
    for cle, nom in (("date illisible", "date illisible"), ("introuvable", "ligne introuvable"), ("variation", "montant incohérent"),
                     ("pas de solde précédent", "sans solde précédent"), ("ne figure pas", "ouverture introuvable"),
                     ("jour", "date ≠ ligne"), ("mois", "date ≠ ligne")):
        if cle in raison:
            return nom
    return "autre"


def main():
    pdf, modele, sortie = sys.argv[1], sys.argv[2], sys.argv[3]
    os.environ["LLM_FOURNISSEUR"], os.environ["LLM_MODELE"] = "ollama", modele
    import llm_fournisseur as llm_f
    from lecture_llm import (_CONSIGNE, LectureLLM, LigneLue, SectionLue, _contient_nombre, _sans_accents, section_utilisable,
                             texte_integral, verifier_section)

    texte = texte_integral(pdf)
    lignes = [re.sub(r"\s+", " ", l).strip() for l in texte.splitlines() if l.strip()]
    norm = [_sans_accents(l) for l in lignes]
    verite = verite_terrain(lignes)
    res = {"modele": modele, "n_attendues": len(verite), "erreur": None}

    t0 = time.perf_counter()
    try:
        rep = llm_f.invoquer("A2", f"{_CONSIGNE}\n\nDocument :\n{texte}", schema=LectureLLM, max_tokens=6000, defaut="x")
        sections = rep.parse.sections
    except Exception as e:                                                       # noqa: BLE001
        sections = []
        res["erreur"] = f"{type(e).__name__}: {e}"[:300]
    res["duree_s"] = round(time.perf_counter() - t0, 1)
    res["n_sections"] = len(sections)

    def apparie(s):
        restants = [(r["date"], r["solde"]) for r in verite]
        exact = 0
        for lg in s.lignes:
            cle = (date_iso(lg.date), round(lg.solde, 2))
            if cle in restants:
                restants.remove(cle)
                exact += 1
        return exact

    if sections:
        s = max(sections, key=apparie)
        exact = apparie(s)
        res.update({"section": s.nom, "n_llm": len(s.lignes), "exactes": exact,
                    "rappel": round(exact / len(verite), 3), "precision": round(exact / len(s.lignes), 3) if s.lignes else 0.0,
                    "inventees": sum(not any(_contient_nombre(l, lg.solde) for l in norm) for lg in s.lignes)})
        tol = SectionLue(nom=s.nom, solde_ouverture=s.solde_ouverture,
                         lignes=[LigneLue(date=date_iso(lg.date) or lg.date, description=lg.description, solde=lg.solde) for lg in s.lignes])
        for nom, sec in (("strict", s), ("tolerant", tol)):
            v = verifier_section(sec, lignes)
            rejets = {}
            for r in v["rejetees"]:
                rejets[categorie(r["raison"])] = rejets.get(categorie(r["raison"]), 0) + 1
            res[nom] = {"verifiees": len(v["transactions"]), "rejetees": len(v["rejetees"]), "rejets": rejets,
                        "utilisable": section_utilisable(v), "soldes_verifies": sorted(t["solde"] for t in v["transactions"])}
        # état de chaque ligne attendue : 2 = exacte et acceptée (tolérant) ; 1 = exacte mais refusée ; 0 = fausse ou absente
        acceptes = list(res["tolerant"]["soldes_verifies"])
        etat, dispo = [], [(date_iso(lg.date), round(lg.solde, 2)) for lg in s.lignes]
        for r in verite:
            cle = (r["date"], r["solde"])
            if cle in dispo:
                dispo.remove(cle)
                if r["solde"] in acceptes:
                    acceptes.remove(r["solde"])
                    etat.append(2)
                else:
                    etat.append(1)
            else:
                etat.append(0)
        res["etat_lignes"] = etat
    else:
        res.update({"n_llm": 0, "exactes": 0, "rappel": 0.0, "precision": 0.0, "inventees": 0, "etat_lignes": [0] * len(verite),
                    "strict": {"verifiees": 0, "rejetees": 0, "rejets": {}, "utilisable": False},
                    "tolerant": {"verifiees": 0, "rejetees": 0, "rejets": {}, "utilisable": False}})
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ("etat_lignes",)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
