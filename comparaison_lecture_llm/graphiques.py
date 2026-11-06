"""Graphiques et tableau de métriques à partir de resultats/*.json (voir banc_lecture_llm.py).

    py -3 graphiques.py        → comparaison.png, metriques.csv, RESULTATS.md
"""
import csv
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

ICI = os.path.dirname(os.path.abspath(__file__))
SURFACE, ENCRE, ENCRE2, MUET, GRILLE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
COULEURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]          # palette catégorielle de référence (bleu, orange, …)
plt.rcParams.update({"font.family": "Segoe UI", "axes.facecolor": SURFACE, "figure.facecolor": SURFACE, "text.color": ENCRE,
                     "axes.labelcolor": ENCRE2, "xtick.color": MUET, "ytick.color": MUET, "axes.edgecolor": GRILLE})


def charger():
    out = []
    for f in sorted(glob.glob(os.path.join(ICI, "resultats", "*.json"))):
        with open(f, encoding="utf-8-sig") as fh:
            out.append(json.load(fh))
    return out


def nom_court(m):
    return m.split(":")[0]


def epurer(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRILLE)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRILLE, linewidth=0.8)
    ax.set_axisbelow(True)


def main():
    res = charger()
    if not res:
        raise SystemExit("Aucun résultat dans resultats/")
    ok = [r for r in res if not r.get("timeout")]
    noms = [nom_court(r["modele"]) for r in res]
    coul = {r["modele"]: COULEURS[i % len(COULEURS)] for i, r in enumerate(res)}

    fig = plt.figure(figsize=(14, 9.5))
    fig.suptitle("Lecture d'un relevé Desjardins non reconnu : comparaison de modèles Ollama", fontsize=15, fontweight="bold", x=0.02, ha="left")
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.15], hspace=0.5, wspace=0.35, left=0.11, right=0.98, top=0.88, bottom=0.15)

    # 1. Qualité de la transcription
    ax = fig.add_subplot(gs[0, 0:2])
    mets = [("Rappel\n(lignes exactes)", "rappel"), ("Précision", "precision"),
            ("Acceptées\npar le garde-fou\n(strict)", None), ("Acceptées\n(dates tolérées)", None)]
    largeur = 0.8 / max(len(ok), 1)
    for i, r in enumerate(ok):
        n = r.get("n_attendues", 30) or 30
        xs = [k + (i - (len(ok) - 1) / 2) * largeur for k in range(4)]
        vals = [r["rappel"], r["precision"], r["strict"]["verifiees"] / n, r["tolerant"]["verifiees"] / n]
        ax.bar(xs, [v * 100 for v in vals], width=largeur * 0.92, color=coul[r["modele"]], label=nom_court(r["modele"]))
        for x, v in zip(xs, vals):
            ax.text(x, v * 100 + 1.5, f"{v * 100:.0f} %", ha="center", fontsize=9, color=ENCRE2)
    ax.set_xticks(range(4))
    ax.set_xticklabels([m[0] for m in mets], fontsize=9)
    ax.set_ylim(0, 125)
    ax.set_ylabel("% des lignes attendues")
    ax.set_title("Qualité de la transcription", loc="left", fontsize=11, color=ENCRE, pad=10)
    ax.legend(frameon=False, loc="upper left", fontsize=9, ncol=len(ok))
    absents = [nom_court(r["modele"]) for r in res if r.get("timeout")]
    if absents:
        ax.text(0.99, 0.97, " ; ".join(absents) + " : délai de 5 min dépassé, aucun résultat", transform=ax.transAxes, ha="right",
                va="top", fontsize=9, color=ENCRE2)
    epurer(ax)

    # 2. Durée
    ax = fig.add_subplot(gs[0, 2])
    durees = [r.get("duree_s", r.get("limite_s", 0)) for r in res]
    barres = ax.bar(noms, durees, color=[coul[r["modele"]] for r in res], width=0.55)
    for b, r in zip(barres, res):
        if r.get("timeout"):
            b.set_hatch("///")
            b.set_alpha(0.45)
    for i, (r, d) in enumerate(zip(res, durees)):
        ax.text(i, d + max(durees) * 0.02, ("> " if r.get("timeout") else "") + f"{d:.0f} s", ha="center", fontsize=10, color=ENCRE2)
    ax.axhline(300, color=MUET, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(0.5, 306, "limite\n5 min", ha="center", va="bottom", fontsize=8, color=MUET)
    ax.set_ylim(0, max(max(durees) * 1.18, 330))
    ax.set_ylabel("secondes")
    ax.set_title("Durée de la lecture", loc="left", fontsize=11, color=ENCRE, pad=10)
    epurer(ax)

    # 3. Carte des lignes
    ax = fig.add_subplot(gs[1, 0:2])
    n = max((r.get("n_attendues", 0) for r in ok), default=30)
    grille = [[-1] * n if r.get("timeout") else r.get("etat_lignes", [0] * n) for r in res]
    cmap = ListedColormap(["#efeee9", "#c3c2b7", "#eda100", "#1baf7a"])
    ax.imshow(grille, aspect="auto", cmap=cmap, vmin=-1, vmax=2, interpolation="nearest")
    ax.set_xticks(range(0, n, 2))
    ax.set_xticklabels([str(i + 1) for i in range(0, n, 2)], fontsize=8)
    ax.set_yticks(range(len(res)))
    ax.set_yticklabels(noms, fontsize=10)
    ax.set_xlabel("ligne du relevé (dans l'ordre, 1 = 8 avril)")
    ax.set_xticks([i - 0.5 for i in range(n + 1)], minor=True)
    ax.set_yticks([i - 0.5 for i in range(len(res) + 1)], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Sort de chaque ligne du relevé", loc="left", fontsize=11, color=ENCRE, pad=10)
    ax.legend(handles=[Patch(color="#1baf7a", label="exacte et acceptée"), Patch(color="#eda100", label="exacte mais refusée"),
                       Patch(color="#c3c2b7", label="fausse ou absente"),
                       Patch(facecolor="#efeee9", edgecolor=GRILLE, label="pas de résultat (délai de 5 min dépassé)")],
              frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=9)

    # 4. Motifs de refus (garde-fou strict)
    ax = fig.add_subplot(gs[1, 2])
    ax.axis("off")
    ax.set_title("Fiche de chaque modèle", loc="left", fontsize=11, color=ENCRE, pad=10)
    y = 0.95
    for r in res:
        ax.add_patch(plt.Rectangle((0, y - 0.025), 0.035, 0.05, color=coul[r["modele"]], transform=ax.transAxes))
        ax.text(0.07, y, r["modele"], transform=ax.transAxes, fontsize=11, fontweight="bold", va="center")
        if r.get("timeout"):
            lignes = ["Délai de 5 min dépassé", "aucun résultat à mesurer"]
        else:
            lignes = [f"Durée : {r['duree_s']:.0f} s",
                      f"Lignes lues : {r['n_llm']} sur {r['n_attendues']} attendues",
                      f"Lignes inventées : {r['inventees']}",
                      f"Refusées par le garde-fou : {r['strict']['rejetees']}",
                      "Section utilisable : " + ("oui" if r["strict"]["utilisable"] else "non")]
        for k, t in enumerate(lignes):
            ax.text(0.07, y - 0.075 * (k + 1), t, transform=ax.transAxes, fontsize=9.5, color=ENCRE2, va="center")
        y -= 0.075 * (len(lignes) + 1) + 0.06

    fig.savefig(os.path.join(ICI, "comparaison.png"), dpi=150)

    cols = ["modele", "duree_s", "erreur", "n_attendues", "n_sections", "n_llm", "exactes", "rappel", "precision", "inventees",
            "strict_verifiees", "strict_rejetees", "strict_utilisable", "tolerant_verifiees", "tolerant_rejetees", "tolerant_utilisable"]
    with open(os.path.join(ICI, "metriques.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in res:
            if r.get("timeout"):
                w.writerow([r["modele"], f">{r['limite_s']}", "timeout 5 min"] + [""] * (len(cols) - 3))
                continue
            w.writerow([r["modele"], r["duree_s"], r.get("erreur") or "", r["n_attendues"], r["n_sections"], r["n_llm"], r["exactes"],
                        r["rappel"], r["precision"], r["inventees"], r["strict"]["verifiees"], r["strict"]["rejetees"],
                        r["strict"]["utilisable"], r["tolerant"]["verifiees"], r["tolerant"]["rejetees"], r["tolerant"]["utilisable"]])
    print("ok")


if __name__ == "__main__":
    main()
