"""Vue « Achats et paiements » : le cycle achats-décaissements de bout en bout, avec la gestion des fournisseurs.

  Cycle complet         une commande suivie de l'idée au débit bancaire : neuf étapes cliquables, documents, rôles, contrôles, écritures,
                        et un simulateur d'appariement à trois voies (commande, réception, facture)
  Fournisseurs          fiches maîtres, intégration et suspension, évaluation, concentration des achats (politique des 40 %)
  Factures              entonnoir de traitement, file des écarts à trancher, approbation avec séparation des tâches
  Paiements             échéancier par ancienneté, décaissements prévus, lots à double approbation, escomptes de paiement rapide
  Contrôles, écritures  matrice des contrôles mesurés sur les données, règles de qualité du cycle, journal et balance des écritures

Les données sont celles de cycle_achats.py (tables gouvernées de la base de démonstration). Les actions écrivent dans cette base et respectent les contrôles.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import cycle_achats as A
from demo_live import moteur as M

CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
FAMILLES = {"matiere_premiere": "Matières premières", "transport": "Transport", "fournitures": "Fournitures", "service_public": "Services publics et télécom",
            "sous_traitance": "Sous-traitance", "services_professionnels": "Services professionnels"}
STATUTS_FACTURE = {"recue": "Reçue", "appariee": "Appariée", "ecart": "Écart à trancher", "approuvee": "Approuvée", "en_lot": "En lot de paiement", "payee": "Payée", "contestee": "Contestée"}
COULEUR_STATUT = {"recue": "#8f9aa8", "appariee": "#2a78d6", "ecart": "#eda100", "approuvee": "#1baf7a", "en_lot": "#6250d6", "payee": "#1f5f8b", "contestee": "#d03b3b"}
APPROBATEURS = list(A.ROLES.values())


def _conn() -> sqlite3.Connection:
    return A.connecter(M.BASE_DEMO)


def _df(sql: str, params=()) -> pd.DataFrame:
    c = _conn()
    try:
        return pd.read_sql_query(sql, c, params=params)
    finally:
        c.close()


def _m(cents) -> str:
    if cents is None or pd.isna(cents):
        return "—"
    return f"{cents / 100:,.0f} $".replace(",", " ")


def _m2(cents) -> str:
    if cents is None or pd.isna(cents):
        return "—"
    return f"{cents / 100:,.2f} $".replace(",", " ").replace(".", ",")


def _md(texte):
    """Échappe le signe $ : Streamlit le prendrait pour le début d'une formule et mangerait le texte entre deux montants."""
    return re.sub(r"(?<!\\)\$", r"\\$", texte) if isinstance(texte, str) else texte


def _info(t, **k):
    return st.info(_md(t), **k)


def _ok(t, **k):
    return st.success(_md(t), **k)


def _warn(t, **k):
    return st.warning(_md(t), **k)


def _err(t, **k):
    return st.error(_md(t), **k)


def _cap(t, **k):
    return st.caption(_md(t), **k)


def _mk(t, **k):
    return st.markdown(_md(t), **k)


def _wr(t, **k):
    return st.write(_md(t), **k)


def _z(v) -> float:
    """0 pour une valeur absente (NULL ou NaN) : les écarts non mesurés comptent pour zéro."""
    return 0.0 if v is None or pd.isna(v) else float(v)


def _fig(fig: go.Figure, hauteur: int = 340, cle: str | None = None) -> None:
    fig.update_layout(height=hauteur, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="")
    st.plotly_chart(fig, theme="streamlit", width="stretch", config=CONFIG, key=cle)


def _agir(action, *args, succes: str = "Fait.", **kw) -> None:
    """Exécute une action du cycle ; les règles de contrôle (ErreurCycle) s'affichent sans plantage."""
    try:
        action(M.BASE_DEMO, *args, **kw)
    except A.ErreurCycle as e:
        st.session_state["ach_msg"] = ("error", str(e))
    else:
        st.session_state["ach_msg"] = ("success", succes)


def _message() -> None:
    m = st.session_state.pop("ach_msg", None)
    if m:
        (_err if m[0] == "error" else _ok)(m[1], icon=":material/gpp_bad:" if m[0] == "error" else ":material/check_circle:")


# --------------------------------------------------------------------------- #
# Indicateurs
# --------------------------------------------------------------------------- #
def indicateurs(ref: date) -> dict:
    ouv = _df("SELECT total_cents, date_echeance, statut FROM core_facture_fournisseur WHERE statut NOT IN ('payee', 'contestee')")
    r = ref.isoformat()
    prochains = ref + timedelta(days=7)
    paye = _df("SELECT f.date_facture, l.date_paiement FROM core_paiement_fournisseur p JOIN core_facture_fournisseur f ON f.facture_id = p.facture_id "
               "JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE l.statut = 'execute'")
    dpo = None
    if not paye.empty:
        dpo = float((pd.to_datetime(paye["date_paiement"]) - pd.to_datetime(paye["date_facture"])).dt.days.mean())
    ap = _df("SELECT ecart_prix_pct, ecart_quantite_pct FROM core_facture_fournisseur WHERE commande_id IS NOT NULL AND statut <> 'contestee'")
    p = A.parametres(_conn())
    premiere = None
    if not ap.empty:
        hors = (ap["ecart_prix_pct"].abs().fillna(0) > p["tolerance_prix_pct"]) | (ap["ecart_quantite_pct"].abs().fillna(0) > p["tolerance_quantite_pct"])
        premiere = 100 * (1 - hors.mean())
    esc = _df("SELECT COALESCE(SUM(escompte_cents), 0) dispo FROM core_facture_fournisseur WHERE escompte_cents > 0 AND statut IN ('payee')")["dispo"][0]
    pris = _df("SELECT COALESCE(SUM(escompte_pris_cents), 0) v FROM core_paiement_fournisseur")["v"][0]
    return {"ouvert": int(ouv["total_cents"].sum()), "nb_ouvert": len(ouv), "echu": int(ouv[ouv["date_echeance"] < r]["total_cents"].sum()),
            "sous_7j": int(ouv[(ouv["date_echeance"] >= r) & (ouv["date_echeance"] <= prochains.isoformat())]["total_cents"].sum()),
            "dpo": dpo, "premiere": premiere, "esc_dispo": int(esc), "esc_pris": int(pris),
            "nb_ecart": int((ouv["statut"] == "ecart").sum())}


def bandeau(ref: date) -> None:
    k = indicateurs(ref)
    a, b, c, d, e = st.columns(5)
    a.metric("Comptes fournisseurs ouverts", _m(k["ouvert"]), f"{k['nb_ouvert']} facture(s)", delta_color="off", border=True)
    b.metric("Échu à ce jour", _m(k["echu"]), "à régler" if k["echu"] else "rien d'échu", delta_color="inverse" if k["echu"] else "off", border=True)
    c.metric("À payer sous 7 jours", _m(k["sous_7j"]), border=True)
    d.metric("Délai moyen de paiement", f"{k['dpo']:.0f} j" if k["dpo"] is not None else "—", help="Jours entre la date de facture et le paiement (DPO).", border=True)
    e.metric("Appariées du premier coup", f"{k['premiere']:.0f} %" if k["premiere"] is not None else "—", f"{k['nb_ecart']} écart(s) ouvert(s)", delta_color="off",
             help="Factures sur commande dans les tolérances de prix et de quantité.", border=True)


# --------------------------------------------------------------------------- #
# 1. Cycle complet
# --------------------------------------------------------------------------- #
def _document(cid: int) -> dict:
    cmd = _df("SELECT c.*, f.nom_legal, f.condition_code, f.famille_achat FROM core_commande_achat c JOIN mdm_fournisseur f ON f.fournisseur_id = c.fournisseur_id WHERE c.commande_id = ?", (cid,)).iloc[0]
    lignes = _df("SELECT * FROM core_commande_achat_ligne WHERE commande_id = ? ORDER BY no_ligne", (cid,))
    rec = _df("SELECT r.*, l.produit, l.unite, l.quantite, l.prix_unitaire_cents FROM core_reception r JOIN core_commande_achat_ligne l ON l.ligne_id = r.ligne_id WHERE l.commande_id = ? ORDER BY r.reception_id", (cid,))
    fac = _df("SELECT * FROM core_facture_fournisseur WHERE commande_id = ? AND motif_ecart IS NOT 'Facture en double : même numéro déjà enregistré' ORDER BY facture_id LIMIT 1", (cid,))
    pai = _df("SELECT p.*, l.no_lot, l.date_paiement, l.statut statut_lot, l.mode_paiement, l.prepare_par, l.approbateur_1, l.approbateur_2 FROM core_paiement_fournisseur p JOIN core_lot_paiement l ON l.lot_id = p.lot_id "
              "WHERE p.facture_id = ?", (int(fac["facture_id"].iloc[0]),)) if not fac.empty else pd.DataFrame()
    return {"cmd": cmd, "lignes": lignes, "rec": rec, "fac": None if fac.empty else fac.iloc[0], "pai": None if pai.empty else pai.iloc[0]}


def _avancement(doc: dict) -> dict:
    """Statut de chacune des neuf étapes : fait, en cours ou à venir."""
    cmd, fac, pai, rec = doc["cmd"], doc["fac"], doc["pai"], doc["rec"]
    etat = {e[0]: "a_venir" for e in A.ETAPES}
    etat["besoin"] = etat["commande"] = "fait"
    etat["approbation_commande"] = "en_cours" if cmd["statut"] == "attente_approbation" else "fait"
    if cmd["statut"] != "attente_approbation":
        etat["reception"] = "fait" if not rec.empty else "en_cours"
    if fac is not None:
        etat["facture"] = "fait"
        etat["appariement"] = "fait" if fac["statut"] not in ("recue", "ecart") else "en_cours"
        etat["approbation_facture"] = "fait" if fac["statut"] in ("approuvee", "en_lot", "payee") else ("en_cours" if etat["appariement"] == "fait" or fac["statut"] == "ecart" else "a_venir")
        if fac["statut"] in ("approuvee", "en_lot", "payee"):
            etat["paiement"] = "fait" if fac["statut"] == "payee" else "en_cours"
        if fac["statut"] == "payee":
            etat["rapprochement"] = "fait" if pai is not None and pai["statut_rapprochement"] == "RAPPROCHE" else "en_cours"
    elif not rec.empty:
        etat["facture"] = "en_cours"
    return etat


def _ruban(etat: dict) -> None:
    pic = {"fait": "✅", "en_cours": "🟠", "a_venir": "⚪"}
    for debut in (0, 5):
        etapes = A.ETAPES[debut:debut + 5]
        for col, (cle, nom, _r, _d), n in zip(st.columns(5), etapes, range(debut + 1, debut + 6)):
            col.button(f"{pic[etat[cle]]} {n}. {nom}", key=f"ach_btn_{cle}", on_click=lambda c=cle: st.session_state.update(ach_etape=c), width="stretch",
                       type="primary" if st.session_state.get("ach_etape") == cle else "secondary")


def _chronologie(doc: dict) -> None:
    cmd, fac, pai, rec = doc["cmd"], doc["fac"], doc["pai"], doc["rec"]
    pts = [("Commande", cmd["date_commande"], "#6250d6"), ("Livraison prévue", cmd["date_livraison_prevue"], "#8f9aa8")]
    if not rec.empty:
        pts.append(("Réception", rec["date_reception"].iloc[0], "#1baf7a"))
    if fac is not None:
        pts += [("Facture", fac["date_facture"], "#2a78d6"), ("Échéance", fac["date_echeance"], "#d03b3b")]
        if fac["date_limite_escompte"]:
            pts.append(("Limite d'escompte", fac["date_limite_escompte"], "#eda100"))
    if pai is not None:
        pts.append(("Paiement", pai["date_paiement"], "#1f5f8b"))
    pts.sort(key=lambda p: p[1])
    # étiquettes en escalier au-dessus et au-dessous de la ligne pour que des dates voisines ne se chevauchent pas
    ys = [(0.35 + 0.28 * (i // 2)) * (1 if i % 2 == 0 else -1) for i in range(len(pts))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[pts[0][1], pts[-1][1]], y=[0, 0], mode="lines", line=dict(color="rgba(137,135,129,0.6)", width=2), hoverinfo="skip", showlegend=False))
    for (nom, jour, col), y in zip(pts, ys):
        fig.add_trace(go.Scatter(x=[jour, jour], y=[0, y], mode="lines", line=dict(color=col, width=1.5), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=[p[1] for p in pts], y=ys, mode="markers+text", text=[f"{p[0]}<br>{p[1][5:]}" for p in pts], textposition=["top center" if y > 0 else "bottom center" for y in ys],
                             textfont=dict(size=10), marker=dict(size=13, color=[p[2] for p in pts]), hovertext=[f"{p[0]} : {p[1]}" for p in pts], hoverinfo="text", showlegend=False))
    fig.update_yaxes(visible=False, range=[-1.5, 1.5])
    fig.update_xaxes(showgrid=False, visible=False)
    _fig(fig, 250, "ach_chrono")


def _etape(cle: str, doc: dict, ref: date) -> None:
    cmd, lignes, rec, fac, pai = doc["cmd"], doc["lignes"], doc["rec"], doc["fac"], doc["pai"]
    p = A.parametres(_conn())
    info = next(e for e in A.ETAPES if e[0] == cle)
    _mk(f"##### {info[1]}")
    _cap(f"Rôle : **{info[2]}** · {info[3]}")
    if cle == "besoin":
        _wr(f"Le **{cmd['demandeur']}** constate que le stock de barres de **{cmd['site_livraison']}** descend sous le seuil de réapprovisionnement. "
                 "Le besoin devient une demande d'achat, adressée au chef des approvisionnements.")
        _info("Contrôle : le demandeur n'a aucun droit de payer ni de créer la fiche fournisseur.", icon=":material/rule:")
    elif cle == "commande":
        a, b, c = st.columns(3)
        a.metric("Commande", cmd["no_commande"], border=True)
        b.metric("Fournisseur", cmd["nom_legal"], border=True)
        c.metric("Total avant taxes", _m(cmd["montant_ht_cents"]), border=True)
        st.dataframe(lignes.assign(**{"Prix": lignes["prix_unitaire_cents"].map(lambda v: f"{v / 100:,.4f} $/{lignes['unite'].iloc[0]}".replace(",", " ")),
                                      "Montant": lignes["montant_cents"].map(_m)})[["no_ligne", "produit", "quantite", "unite", "Prix", "Montant", "compte_code"]]
                     .rename(columns={"no_ligne": "Ligne", "produit": "Produit", "quantite": "Quantité", "unite": "Unité", "compte_code": "Compte"}), hide_index=True, width="stretch")
        _cap(f"Date de commande {cmd['date_commande']} · livraison prévue {cmd['date_livraison_prevue']} · condition de paiement **{cmd['condition_code']}**.")
    elif cle == "approbation_commande":
        niv = int(cmd["niveau_approbation"])
        st.dataframe(pd.DataFrame([{"Niveau": n, "Approbateur": A.ROLES[n], "Jusqu'à": {1: f"{p['seuil_niveau_1']:,.0f} $", 2: f"{p['seuil_niveau_2']:,.0f} $", 3: "au-delà"}[n].replace(",", " "),
                                    "Cette commande": "◀ requis" if n == niv else ""} for n in (1, 2, 3)]), hide_index=True, width="stretch")
        if cmd["statut"] == "attente_approbation":
            _warn(f"Commande de {_m(cmd['montant_ht_cents'])} en attente : approbation du niveau {niv} ({A.ROLES[niv]}) requise avant l'envoi au fournisseur.", icon=":material/hourglass_top:")
        else:
            _ok(f"Approuvée par **{cmd['approuve_par']}** le {cmd['approuve_le']} (niveau {niv}).", icon=":material/verified:")
    elif cle == "reception":
        if rec.empty:
            _info("Rien n'est encore reçu. La livraison est attendue le " + cmd["date_livraison_prevue"] + ".")
        else:
            d = rec.assign(Commandée=rec["quantite"], Reçue=rec["quantite_recue"], Écart=(rec["quantite_recue"] - rec["quantite"]))
            fig = go.Figure([go.Bar(name="Commandée", x=d["produit"], y=d["Commandée"], marker_color="#8f9aa8"), go.Bar(name="Reçue (pesée)", x=d["produit"], y=d["Reçue"], marker_color="#1baf7a")])
            fig.update_layout(barmode="group")
            _fig(fig, 260, "ach_rec")
            st.dataframe(d[["no_bon_livraison", "date_reception", "produit", "Commandée", "Reçue", "Écart", "conforme", "recu_par", "commentaire"]].rename(
                columns={"no_bon_livraison": "Bon de livraison", "date_reception": "Date", "produit": "Produit", "conforme": "Conforme", "recu_par": "Reçu par", "commentaire": "Commentaire"}),
                hide_index=True, width="stretch")
            _info("Contrôle : la réception est faite par une autre personne que celle qui commande et que celle qui paie. Elle crée l'écriture « achats reçus non facturés » (compte 2105).", icon=":material/rule:")
    elif cle == "facture":
        if fac is None:
            _info("Aucune facture reçue pour cette commande : la valeur reçue reste au compte 2105 (achats reçus non facturés).")
        else:
            a, b, c, d = st.columns(4)
            a.metric("Facture", fac["no_facture"], border=True)
            b.metric("Avant taxes", _m2(fac["montant_ht_cents"]), border=True)
            c.metric("TPS 5 % + TVQ 9,975 %", _m2(fac["tps_cents"] + fac["tvq_cents"]), border=True)
            d.metric("Total à payer", _m2(fac["total_cents"]), border=True)
            _wr(f"Date de facture **{fac['date_facture']}** · reçue le {fac['date_reception_facture']} · échéance **{fac['date_echeance']}** ({cmd['condition_code']}).")
            if fac["date_limite_escompte"]:
                cond = _df("SELECT jours_net, jours_escompte, escompte_pct FROM ref_condition_paiement WHERE code = ?", (cmd["condition_code"],)).iloc[0]
                rend = A.escompte_annualise_pct(cond["escompte_pct"], int(cond["jours_escompte"]), int(cond["jours_net"]))
                _ok(f"Escompte de {cond['escompte_pct']:g} % ({_m2(fac['escompte_cents'])}) si payé avant le **{fac['date_limite_escompte']}** : "
                           f"rendement annualisé d'environ **{rend:.0f} %**, bien au-dessus du coût de la marge de crédit. Il vaut presque toujours la peine de le prendre.", icon=":material/savings:")
    elif cle == "appariement":
        _appariement(cmd, lignes, rec, fac, p)
    elif cle == "approbation_facture":
        if fac is None:
            _info("En attente de la facture.")
        elif fac["statut"] in ("approuvee", "en_lot", "payee"):
            _ok(f"Facture approuvée par **{fac['approuve_par']}** le {fac['approuve_le']}." + (f" Motif de l'écart : {fac['motif_ecart']}." if fac["motif_ecart"] else " Dans les tolérances."),
                       icon=":material/verified:")
            _cap("La facture entre à l'échéancier des comptes fournisseurs (compte 2100). Aucun paiement n'est possible avant ce point.")
        elif fac["statut"] == "ecart":
            _warn("Facture retenue : écart hors tolérance à trancher dans l'onglet « Factures ».", icon=":material/pause_circle:")
        else:
            _info(f"Statut de la facture : {STATUTS_FACTURE.get(fac['statut'], fac['statut'])}.")
    elif cle == "paiement":
        if pai is None:
            _info("Pas encore payée." + (" La facture est approuvée et sera payée au prochain lot." if fac is not None and fac["statut"] in ("approuvee", "en_lot") else ""))
        else:
            a, b, c, d = st.columns(4)
            a.metric("Lot", pai["no_lot"], border=True)
            b.metric("Date de paiement", pai["date_paiement"], border=True)
            c.metric("Montant décaissé", _m2(pai["montant_cents"]), border=True)
            d.metric("Escompte pris", _m2(pai["escompte_pris_cents"]), border=True)
            _wr(f"Mode **{pai['mode_paiement']}** · préparé par {pai['prepare_par']} · approuvé par **{pai['approbateur_1'] or '—'}**" + (f" et **{pai['approbateur_2']}**" if pai["approbateur_2"] else "")
                     + f" · statut du lot : {pai['statut_lot']}.")
            _info("Contrôle : le préparateur n'approuve pas son propre lot ; au-delà de 50 000 $, deux approbateurs distincts.", icon=":material/rule:")
    elif cle == "rapprochement":
        if pai is None:
            _info("En attente du paiement.")
        else:
            ok = pai["statut_rapprochement"] == "RAPPROCHE"
            (_ok if ok else _warn)(f"Paiement {'retrouvé au relevé bancaire : rapproché' if ok else 'pas encore retrouvé au relevé : non rapproché'}.", icon=":material/account_balance:")
            _cap("L'agent A6 de l'orchestrateur rapproche les débits du relevé avec les paiements du lot ; core_paiement_fournisseur.mouvement_id garde le lien.")
        _ecritures_doc(cmd, fac)


def _ecritures_doc(cmd, fac) -> None:
    refs = [cmd["no_commande"]] + ([fac["no_facture"]] if fac is not None else [])
    if fac is not None:
        lots = _df("SELECT l.no_lot FROM core_paiement_fournisseur p JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE p.facture_id = ?", (int(fac["facture_id"]),))
        refs += list(lots["no_lot"])
    e = _df(f"SELECT e.no_ecriture, e.date_ecriture, e.evenement, e.compte_code, c.libelle_fr, e.debit_cents, e.credit_cents FROM core_ecriture_achat e JOIN ref_compte_comptable c ON c.code = e.compte_code "
            f"WHERE e.document_ref IN ({','.join('?' * len(refs))}) ORDER BY e.date_ecriture, e.ligne_ecriture_id", tuple(refs))
    if e.empty:
        return
    _mk("**Écritures comptables générées par ce dossier**")
    aff = e.assign(Débit=e["debit_cents"].map(lambda v: _m2(v) if v else ""), Crédit=e["credit_cents"].map(lambda v: _m2(v) if v else ""))
    st.dataframe(aff[["date_ecriture", "evenement", "no_ecriture", "compte_code", "libelle_fr", "Débit", "Crédit"]].rename(
        columns={"date_ecriture": "Date", "evenement": "Événement", "no_ecriture": "Écriture", "compte_code": "Compte", "libelle_fr": "Libellé du compte"}), hide_index=True, width="stretch")
    _cap(f"Total des débits {_m2(e['debit_cents'].sum())} · total des crédits {_m2(e['credit_cents'].sum())} — "
               + ("équilibré." if e["debit_cents"].sum() == e["credit_cents"].sum() else "déséquilibre : voir les écritures non encore soldées."))


def _appariement(cmd, lignes, rec, fac, p) -> None:
    ligne = lignes.iloc[0]
    qr0 = float(rec[rec["ligne_id"] == ligne["ligne_id"]]["quantite_recue"].sum()) if not rec.empty else float(ligne["quantite"])
    qf0 = qr0
    pf0 = float(ligne["prix_unitaire_cents"])
    if fac is not None and len(lignes) == 1:
        qf0 = float(ligne["quantite"]) if _z(fac["ecart_quantite_pct"]) > p["tolerance_quantite_pct"] else qr0
        pf0 = float(ligne["prix_unitaire_cents"]) * (1 + _z(fac["ecart_prix_pct"]) / 100)
    _cap("Règle : on ne paie que ce qui est entré au magasin, au prix convenu. Le prix facturé doit rester à ±"
               f"{p['tolerance_prix_pct']:g} % du prix commandé et la quantité facturée à ±{p['tolerance_quantite_pct']:g} % de la quantité reçue. "
               "Déplacez les curseurs pour tester ce que le système déciderait (le simulateur travaille sur la première ligne de la commande).")
    c1, c2, c3 = st.columns(3)
    qr = c1.slider("Quantité reçue", 0.0, float(ligne["quantite"]) * 1.1, float(qr0), step=max(float(ligne["quantite"]) / 400, 0.01), key=f"ach_sim_qr_{cmd['commande_id']}")
    qf = c2.slider("Quantité facturée", 0.0, float(ligne["quantite"]) * 1.1, float(min(qf0, ligne["quantite"] * 1.1)), step=max(float(ligne["quantite"]) / 400, 0.01), key=f"ach_sim_qf_{cmd['commande_id']}")
    prix0 = float(ligne["prix_unitaire_cents"]) / 100                       # en dollars par unité (1,38 $/L plutôt que 138 ¢/L)
    pf = c3.slider(f"Prix facturé ($ par {ligne['unite']})", prix0 * 0.9, prix0 * 1.1, float(pf0) / 100, step=max(prix0 / 1000, 0.0001), format="%.4f",
                   key=f"ach_sim_pf_{cmd['commande_id']}")
    r = A.simuler_appariement(float(ligne["quantite"]), float(ligne["prix_unitaire_cents"]), qr, qf, pf * 100, p["tolerance_prix_pct"], p["tolerance_quantite_pct"])
    fig = go.Figure(go.Bar(x=["Commandé", "Reçu (au prix commandé)", "Facturé"], y=[r["commande_cents"] / 100, r["recu_cents"] / 100, r["facture_cents"] / 100],
                           marker_color=["#8f9aa8", "#1baf7a", "#2a78d6" if r["conforme"] else "#d03b3b"], text=[_m(r["commande_cents"]), _m(r["recu_cents"]), _m(r["facture_cents"])], textposition="outside"))
    fig.update_yaxes(title="$", rangemode="tozero")
    a, b = st.columns([3, 2])
    with a:
        _fig(fig, 300, f"ach_sim_{cmd['commande_id']}")
    with b:
        st.metric("Écart de prix", f"{r['ecart_prix_pct']:+.2f} %", border=True)
        st.metric("Écart de quantité", f"{r['ecart_quantite_pct']:+.2f} %", border=True)
        (_ok if r["conforme"] else _warn)(r["decision"].capitalize() + ("." if r["conforme"] else " : " + " ; ".join(r["motifs"]) + f". Surcoût à justifier : {_m(r['ecart_cents'])}."))
    if fac is not None:
        _cap(f"Dans l'exemple : facture {fac['no_facture']}, statut « {STATUTS_FACTURE.get(fac['statut'], fac['statut'])} »"
                   + (f", motif : {fac['motif_ecart']}" if fac["motif_ecart"] else "") + ".")


def onglet_cycle(ref: date) -> None:
    c = _conn()
    phare = A.exemple_phare(c)
    cmds = _df("SELECT c.commande_id, c.no_commande, f.nom_legal, c.montant_ht_cents, c.statut FROM core_commande_achat c JOIN mdm_fournisseur f ON f.fournisseur_id = c.fournisseur_id ORDER BY c.date_commande DESC")
    c.close()
    if cmds.empty:
        _info("Aucune commande.")
        return
    libelles = {int(r.commande_id): f"{r.no_commande} · {r.nom_legal} · {_m(r.montant_ht_cents)} · {r.statut.replace('_', ' ')}" for r in cmds.itertuples()}
    ids = list(libelles)
    if st.session_state.get("ach_cmd") not in ids:
        st.session_state["ach_cmd"] = phare if phare in ids else ids[0]
    _cap("Suivez une commande de l'idée au débit bancaire. L'exemple de départ est une livraison d'aluminium au 2/10 net 30 dont le prix facturé dépassait la tolérance : "
               "l'écart a été tranché avec motif, la facture payée avec escompte et le paiement rapproché. Choisissez-en une autre pour voir une commande en attente, un écart ouvert ou un paiement à venir.")
    cmd_id = st.selectbox("Commande", ids, format_func=lambda i: libelles[i], key="ach_cmd")
    doc = _document(int(cmd_id))
    etat = _avancement(doc)
    cles = [e[0] for e in A.ETAPES]
    if st.session_state.get("ach_etape") not in cles:
        st.session_state["ach_etape"] = "appariement" if doc["fac"] is not None else "commande"
    _ruban(etat)
    _chronologie(doc)
    with st.container(border=True):
        _etape(st.session_state["ach_etape"], doc, ref)
    col1, col2 = st.columns(2)
    k = cles.index(st.session_state["ach_etape"])
    col1.button("← Étape précédente", disabled=k == 0, on_click=lambda: st.session_state.update(ach_etape=cles[k - 1]), key="ach_prec", width="stretch")
    col2.button("Étape suivante →", disabled=k == len(cles) - 1, on_click=lambda: st.session_state.update(ach_etape=cles[k + 1]), key="ach_suiv", width="stretch")


# --------------------------------------------------------------------------- #
# 2. Fournisseurs
# --------------------------------------------------------------------------- #
def onglet_fournisseurs(ref: date) -> None:
    f = _df("SELECT f.*, c.jours_net, c.libelle_fr condition_libelle, "
            "(SELECT COUNT(*) FROM core_facture_fournisseur x WHERE x.fournisseur_id = f.fournisseur_id AND x.statut NOT IN ('payee', 'contestee')) factures_ouvertes, "
            "(SELECT COALESCE(SUM(x.total_cents), 0) FROM core_facture_fournisseur x WHERE x.fournisseur_id = f.fournisseur_id AND x.statut NOT IN ('payee', 'contestee')) solde_cents, "
            "(SELECT COALESCE(SUM(x.montant_ht_cents), 0) FROM core_facture_fournisseur x WHERE x.fournisseur_id = f.fournisseur_id AND x.statut <> 'contestee') achats_cents "
            "FROM mdm_fournisseur f JOIN ref_condition_paiement c ON c.code = f.condition_code ORDER BY achats_cents DESC")
    a, b, c, d = st.columns(4)
    a.metric("Fournisseurs", len(f), border=True)
    b.metric("Actifs", int((f["statut"] == "actif").sum()), border=True)
    c.metric("En intégration", int((f["statut"] == "a_valider").sum()), help="Non payables tant que la fiche n'est pas validée.", border=True)
    d.metric("Suspendus", int((f["statut"] == "suspendu").sum()), help="Changement de coordonnées bancaires non confirmé par rappel.", border=True)

    g1, g2 = st.columns([3, 2])
    with g1, st.container(border=True):
        _mk("**Concentration des achats de matières premières** (politique : aucune source au-delà de 40 %)")
        pp = f[f["famille_achat"] == "matiere_premiere"]
        tot = pp["achats_cents"].sum()
        if tot:
            pp = pp.assign(part=100 * pp["achats_cents"] / tot).sort_values("part")
            fig = go.Figure(go.Bar(x=pp["part"], y=pp["nom_legal"], orientation="h", marker_color=["#d03b3b" if v > 40 else "#2a78d6" for v in pp["part"]],
                                   text=[f"{v:.0f} %" for v in pp["part"]], textposition="outside"))
            fig.add_vline(x=40, line_dash="dash", line_color="#d03b3b", annotation_text="plafond 40 %")
            fig.update_xaxes(range=[0, 100], title="Part des achats avant taxes (%)")
            _fig(fig, 250, "ach_conc")
            if (pp["part"] > 40).any():
                _warn("Au moins une source dépasse le plafond de 40 % : diversifier les approvisionnements ou documenter l'exception.", icon=":material/warning:")
    with g2, st.container(border=True):
        _mk("**Intégration d'un fournisseur**")
        _mk("1. Demande de création (demandeur d'achat)\n2. Vérification : numéros de TPS et de TVQ, existence légale, courriel de facturation\n"
                    "3. Coordonnées bancaires confirmées par **rappel** à un numéro connu\n4. Approbation par une personne autre que le demandeur\n5. Fiche **active** : payable")

    fil1, fil2 = st.columns(2)
    fam = fil1.multiselect("Famille d'achat", list(FAMILLES), default=list(FAMILLES), format_func=lambda k: FAMILLES[k], key="ach_fam")
    sta = fil2.multiselect("Statut", ["actif", "a_valider", "suspendu", "inactif"], default=["actif", "a_valider", "suspendu", "inactif"], key="ach_sta_f")
    v = f[f["famille_achat"].isin(fam) & f["statut"].isin(sta)]
    st.dataframe(v.assign(Famille=v["famille_achat"].map(FAMILLES), Achats=v["achats_cents"].map(_m), Solde=v["solde_cents"].map(_m))[["nom_legal", "Famille", "condition_libelle", "statut", "note_globale", "Achats", "Solde", "factures_ouvertes"]]
                 .rename(columns={"nom_legal": "Fournisseur", "condition_libelle": "Condition", "statut": "Statut", "note_globale": "Note /5", "factures_ouvertes": "Factures ouvertes"}),
                 hide_index=True, width="stretch")

    if v.empty:
        return
    choix = st.selectbox("Fiche du fournisseur", list(v["fournisseur_id"]), format_func=lambda i: v[v["fournisseur_id"] == i]["nom_legal"].iloc[0], key="ach_fou")
    r = f[f["fournisseur_id"] == choix].iloc[0]
    with st.container(border=True):
        _mk(f"#### {r['nom_legal']}")
        _cap(f"{FAMILLES[r['famille_achat']]} · condition {r['condition_libelle']} · statut **{r['statut']}**")
        _message()
        if r["statut"] == "suspendu":
            _err(f"Paiement bloqué : les coordonnées bancaires ont changé le {r['coordonnees_modifiees_le']} et ne sont pas confirmées par rappel. C'est le scénario classique de la fraude au faux changement de coordonnées.",
                     icon=":material/gpp_bad:")
            qui = st.selectbox("Personne qui a fait le rappel", APPROBATEURS, key="ach_qui_susp")
            st.button("J'ai rappelé le fournisseur : lever la suspension", key="ach_lever",
                      on_click=lambda: _agir(A.lever_suspension, int(choix), st.session_state["ach_qui_susp"], succes="Suspension levée : le fournisseur est payable."))
        elif r["statut"] == "a_valider":
            _warn("Fiche en intégration : aucune commande ni paiement possible tant qu'elle n'est pas validée.", icon=":material/hourglass_top:")
            qui = st.selectbox("Approbateur", APPROBATEURS, key="ach_qui_val")
            st.button("Valider la fiche (vérifications faites)", key="ach_valider",
                      on_click=lambda: _agir(A.valider_fournisseur, int(choix), st.session_state["ach_qui_val"], succes="Fiche validée : le fournisseur est actif."))
        a, b, c, d = st.columns(4)
        a.metric("Achats avant taxes", _m(r["achats_cents"]), border=True)
        b.metric("Solde à payer", _m(r["solde_cents"]), border=True)
        c.metric("Factures ouvertes", int(r["factures_ouvertes"]), border=True)
        d.metric("Note globale", f"{r['note_globale']:.1f} / 5" if pd.notna(r["note_globale"]) else "—", border=True)
        x, y = st.columns(2)
        with x:
            ev = _df("SELECT * FROM mdm_fournisseur_evaluation WHERE fournisseur_id = ? ORDER BY trimestre", (int(choix),))
            if not ev.empty:
                axes = ["note_qualite", "note_delai", "note_prix", "note_conformite"]
                noms = ["Qualité", "Délais", "Prix", "Conformité"]
                fig = go.Figure()
                for _, e in ev.iterrows():
                    fig.add_trace(go.Scatterpolar(r=[e[k] for k in axes] + [e[axes[0]]], theta=noms + [noms[0]], name=e["trimestre"], fill="toself" if e["trimestre"] == ev["trimestre"].max() else "none", opacity=0.8))
                fig.update_layout(polar=dict(radialaxis=dict(range=[0, 5])))
                _mk("**Évaluation trimestrielle**")
                _fig(fig, 300, "ach_radar")
            else:
                _cap("Aucune évaluation (fournisseur en intégration).")
        with y:
            m = _df("SELECT substr(date_facture, 1, 7) mois, SUM(montant_ht_cents) / 100.0 ht FROM core_facture_fournisseur WHERE fournisseur_id = ? AND statut <> 'contestee' GROUP BY 1 ORDER BY 1", (int(choix),))
            _mk("**Factures par mois (avant taxes)**")
            if m.empty:
                _cap("Aucune facture.")
            else:
                _fig(go.Figure(go.Bar(x=m["mois"], y=m["ht"], marker_color="#2a78d6")), 300, "ach_mois")
        _cap(f"TPS : {r['no_tps']} · TVQ : {r['no_tvq']} · compte bancaire {r['compte_bancaire_masque']} · courriel de facturation {r['courriel_facturation']} · "
                   f"fiche approuvée par {r['approuve_par'] or '—'} le {r['approuve_le'] or '—'}.")


# --------------------------------------------------------------------------- #
# 3. Factures et appariement
# --------------------------------------------------------------------------- #
def onglet_factures(ref: date) -> None:
    f = _df("SELECT f.*, o.nom_legal, o.famille_achat, c.no_commande FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id "
            "LEFT JOIN core_commande_achat c ON c.commande_id = f.commande_id ORDER BY f.date_facture DESC, f.facture_id DESC")
    cnt = f["statut"].value_counts()
    fig = go.Figure(go.Bar(x=[STATUTS_FACTURE[s] for s in STATUTS_FACTURE], y=[int(cnt.get(s, 0)) for s in STATUTS_FACTURE], marker_color=[COULEUR_STATUT[s] for s in STATUTS_FACTURE],
                           text=[int(cnt.get(s, 0)) for s in STATUTS_FACTURE], textposition="outside"))
    _mk("**Entonnoir de traitement des factures** (cliquez un statut dans le filtre pour détailler)")
    _fig(fig, 260, "ach_entonnoir")
    sel = st.multiselect("Statuts affichés", list(STATUTS_FACTURE), default=["ecart", "appariee", "recue", "approuvee"], format_func=lambda s: STATUTS_FACTURE[s], key="ach_sta_fac")
    v = f[f["statut"].isin(sel)]
    st.dataframe(v.assign(Statut=v["statut"].map(STATUTS_FACTURE), Total=v["total_cents"].map(_m2))[["no_facture", "nom_legal", "no_commande", "date_facture", "date_echeance", "Total", "ecart_prix_pct", "ecart_quantite_pct", "Statut", "motif_ecart"]]
                 .rename(columns={"no_facture": "Facture", "nom_legal": "Fournisseur", "no_commande": "Commande", "date_facture": "Date", "date_echeance": "Échéance", "ecart_prix_pct": "Écart prix %",
                                  "ecart_quantite_pct": "Écart qté %", "motif_ecart": "Motif"}), hide_index=True, width="stretch", height=300)

    _mk("##### File des écarts et des factures à approuver")
    _message()
    att = f[f["statut"].isin(["ecart", "appariee", "recue"])]
    if att.empty:
        _ok("Aucune facture en attente : tout est tranché.", icon=":material/check_circle:")
        return
    choix = st.selectbox("Facture à traiter", list(att["facture_id"]), key="ach_fac_sel",
                         format_func=lambda i: (lambda r: f"{r.no_facture} · {r.nom_legal} · {_m(r.total_cents)} · {STATUTS_FACTURE[r.statut]}")(att[att['facture_id'] == i].iloc[0]))
    r = att[att["facture_id"] == choix].iloc[0]
    with st.container(border=True):
        a, b, c, d = st.columns(4)
        a.metric("Facture", r["no_facture"], border=True)
        b.metric("Total", _m2(r["total_cents"]), border=True)
        c.metric("Écart de prix", f"{_z(r['ecart_prix_pct']):+.2f} %", border=True)
        d.metric("Écart de quantité", f"{_z(r['ecart_quantite_pct']):+.2f} %", border=True)
        if pd.isna(r["commande_id"]):
            _warn(f"Aucune commande rattachée : un achat hors famille préautorisée ({FAMILLES[r['famille_achat']]}) doit avoir un bon de commande. Motif consigné : {r['motif_ecart']}.", icon=":material/rule:")
        elif r["motif_ecart"]:
            _warn(f"Écart hors tolérance — {r['motif_ecart']}. Le contrôleur tranche : accepter avec motif, ou contester auprès du fournisseur (note de crédit).", icon=":material/rule:")
        else:
            _info("Dans les tolérances : approbation courante.")
        who = st.selectbox("Approbateur", APPROBATEURS, index=1, key="ach_who_fac")
        mot = st.text_input("Motif (obligatoire pour un écart)", value="", key="ach_mot_fac", placeholder="ex. prix du jour confirmé par le fournisseur, note de crédit demandée")
        x, y = st.columns(2)
        x.button("✅ Approuver la facture", key="ach_appr_fac", width="stretch",
                 on_click=lambda: _agir(A.approuver_facture, int(choix), st.session_state["ach_who_fac"], st.session_state["ach_mot_fac"], succes="Facture approuvée : elle entre à l'échéancier."))
        y.button("⛔ Contester auprès du fournisseur", key="ach_cont_fac", width="stretch",
                 on_click=lambda: _agir(A.contester_facture, int(choix), st.session_state["ach_mot_fac"], succes="Facture contestée : elle sort de l'échéancier."))


# --------------------------------------------------------------------------- #
# 4. Paiements et échéancier
# --------------------------------------------------------------------------- #
def _tranche(jours: int) -> str:
    if jours > 60:
        return "Échu > 60 j"
    if jours > 30:
        return "Échu 31-60 j"
    if jours > 0:
        return "Échu 1-30 j"
    if jours >= -7:
        return "À venir 0-7 j"
    if jours >= -30:
        return "À venir 8-30 j"
    return "À venir > 30 j"


TRANCHES = ["Échu > 60 j", "Échu 31-60 j", "Échu 1-30 j", "À venir 0-7 j", "À venir 8-30 j", "À venir > 30 j"]
COULEUR_TRANCHE = ["#a82c2c", "#d03b3b", "#ee8a3a", "#a8cf5a", "#3aa65a", "#1a7a46"]


def onglet_paiements(ref: date) -> None:
    ouv = _df("SELECT f.*, o.nom_legal, o.famille_achat, o.statut statut_fournisseur FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id "
              "WHERE f.statut NOT IN ('payee', 'contestee')")
    ouv["jours"] = (pd.Timestamp(ref) - pd.to_datetime(ouv["date_echeance"])).dt.days
    ouv["tranche"] = ouv["jours"].map(_tranche)
    g1, g2 = st.columns(2)
    with g1, st.container(border=True):
        _mk("**Échéancier par ancienneté** (par famille d'achat)")
        d = ouv.assign(famille=ouv["famille_achat"].map(FAMILLES)).groupby(["tranche", "famille"], as_index=False)["total_cents"].sum()
        d["total"] = d["total_cents"] / 100
        fig = px.bar(d, x="tranche", y="total", color="famille", category_orders={"tranche": TRANCHES}, color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_xaxes(title=None)
        fig.update_yaxes(title="$")
        _fig(fig, 330, "ach_age")
    with g2, st.container(border=True):
        _mk("**Décaissements prévus, semaine par semaine** (selon l'échéance)")
        futur = ouv.assign(sem=pd.to_datetime(ouv["date_echeance"]).dt.to_period("W-SUN").dt.start_time)
        futur["sem"] = futur["sem"].where(pd.to_datetime(ouv["date_echeance"]) >= pd.Timestamp(ref), pd.Timestamp(ref - timedelta(days=ref.weekday())))
        d = futur[futur["sem"] <= pd.Timestamp(ref + timedelta(days=56))].groupby("sem", as_index=False)["total_cents"].sum()
        d["total"] = d["total_cents"] / 100
        if d.empty:
            _cap("Rien à décaisser dans les 8 prochaines semaines.")
        else:
            fig = go.Figure(go.Bar(x=d["sem"], y=d["total"], marker_color=["#d03b3b" if s <= pd.Timestamp(ref) else "#2a78d6" for s in d["sem"]]))
            fig.update_yaxes(title="$")
            fig.update_xaxes(title="Semaine commençant le")
            _fig(fig, 330, "ach_sem")
            p = _df("SELECT valeur FROM parametres WHERE domaine = 'general' AND cle = 'seuil_securite'")
            if not p.empty:
                _cap(f"Comparer avec le seuil de sécurité de trésorerie de {float(p['valeur'][0]):,.0f} $ : ces décaissements s'ajoutent aux autres charges du plan de trésorerie.".replace(",", " "))

    _mk("##### Lots de paiement")
    _message()
    lots = _df("SELECT l.*, (SELECT COUNT(*) FROM core_paiement_fournisseur p WHERE p.lot_id = l.lot_id) nb, "
               "(SELECT COALESCE(SUM(p.montant_cents), 0) FROM core_paiement_fournisseur p WHERE p.lot_id = l.lot_id) total, "
               "(SELECT COALESCE(SUM(p.escompte_pris_cents), 0) FROM core_paiement_fournisseur p WHERE p.lot_id = l.lot_id) escompte FROM core_lot_paiement l ORDER BY l.date_paiement DESC, l.lot_id DESC")
    ouverts = lots[lots["statut"].isin(["prepare", "approuve_1", "approuve"])]
    seuil = A.parametres(_conn())["seuil_double_approbation"] * 100
    if ouverts.empty:
        _info("Aucun lot en cours : préparez-en un ci-dessous.")
    for r in ouverts.itertuples():
        with st.container(border=True):
            double = r.total > seuil
            _mk(f"**{r.no_lot}** · {r.mode_paiement} · {r.nb} paiement(s) · {_m(r.total)} · date {r.date_paiement} · statut **{r.statut.replace('_', ' ')}**")
            _cap(f"Préparé par {r.prepare_par} · approbateur 1 : {r.approbateur_1 or '—'} · approbateur 2 : {r.approbateur_2 or ('—' if double else 'non requis')} · "
                       + ("double approbation exigée (total au-dessus de " + _m(seuil) + ")" if double else "une approbation suffit"))
            who = st.selectbox("Approuver comme", APPROBATEURS + [A.PREPARATEUR], index=1, key=f"ach_who_lot_{r.lot_id}")
            x, y = st.columns(2)
            x.button("Approuver le lot", key=f"ach_ap_lot_{r.lot_id}", disabled=r.statut not in ("prepare", "approuve_1"), width="stretch",
                     on_click=lambda i=r.lot_id: _agir(A.approuver_lot, int(i), st.session_state[f"ach_who_lot_{i}"], succes="Approbation enregistrée."))
            y.button("Exécuter le lot (paiement EFT)", key=f"ach_ex_lot_{r.lot_id}", disabled=r.statut != "approuve", width="stretch",
                     on_click=lambda i=r.lot_id: _agir(A.executer_lot, int(i), succes="Lot exécuté : factures payées et écritures générées."))
    _mk("##### Préparer un nouveau lot")
    elig = ouv[ouv["statut"] == "approuvee"].copy()
    if elig.empty:
        _cap("Aucune facture approuvée à payer.")
    else:
        strat = st.radio("Stratégie", ["Selon l'échéance", "Capter les escomptes", "Tout ce qui est approuvé"], horizontal=True, key="ach_strat")
        jp = st.date_input("Date de paiement", value=A._jeudi_suivant(ref + timedelta(days=1)), key="ach_date_pay")
        horizon = jp + timedelta(days=7)
        if strat == "Selon l'échéance":
            defaut = elig[pd.to_datetime(elig["date_echeance"]) <= pd.Timestamp(horizon)]
        elif strat == "Capter les escomptes":
            defaut = elig[(elig["date_limite_escompte"].notna() & (elig["date_limite_escompte"] >= jp.isoformat())) | (pd.to_datetime(elig["date_echeance"]) <= pd.Timestamp(jp))]
        else:
            defaut = elig
        bloques = elig[elig["statut_fournisseur"] != "actif"]
        libelle = {int(r.facture_id): f"{r.no_facture} · {r.nom_legal} · {_m(r.total_cents)} · éch. {r.date_echeance}" + (" · ⛔ fournisseur bloqué" if r.statut_fournisseur != "actif" else "")
                   + (f" · escompte {_m(r.escompte_cents)} avant le {r.date_limite_escompte}" if r.date_limite_escompte and r.escompte_cents else "") for r in elig.itertuples()}
        choisies = st.multiselect("Factures du lot", list(libelle), default=[int(i) for i in defaut["facture_id"] if int(i) in libelle and i not in set(bloques["facture_id"])], format_func=lambda i: libelle[i], key=f"ach_choix_{strat}")
        sel = elig[elig["facture_id"].isin(choisies)]
        prise = int(sel[(sel["date_limite_escompte"].notna()) & (sel["date_limite_escompte"] >= jp.isoformat())]["escompte_cents"].sum())
        a, b, c = st.columns(3)
        a.metric("Total du lot", _m(sel["total_cents"].sum() - prise), border=True)
        b.metric("Escomptes pris", _m(prise), border=True)
        c.metric("Doubles approbations ?", "oui" if (sel["total_cents"].sum() - prise) > seuil else "non", border=True)
        if not bloques.empty:
            _cap("Bloqués : " + ", ".join(sorted(set(bloques["nom_legal"]))) + " (fiche non payable : voir l'onglet Fournisseurs).")
        st.button("Préparer le lot", key="ach_creer", disabled=not choisies,
                  on_click=lambda: _agir(A.creer_lot, [int(i) for i in st.session_state[f"ach_choix_{strat}"]], st.session_state["ach_date_pay"], "EFT",
                                         succes="Lot préparé : il attend maintenant ses approbations."))
    # escomptes
    esc = _df("SELECT o.nom_legal, f.no_facture, f.total_cents, f.escompte_cents, f.date_limite_escompte, l.date_paiement, p.escompte_pris_cents FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id "
              "LEFT JOIN core_paiement_fournisseur p ON p.facture_id = f.facture_id LEFT JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE f.escompte_cents > 0 ORDER BY f.date_facture DESC")
    if not esc.empty:
        _mk("##### Escomptes de paiement rapide (2/10 net 30)")
        esc["pris"] = esc["escompte_pris_cents"].fillna(0)
        esc["manque"] = (esc["escompte_cents"] - esc["pris"]).where(esc["date_paiement"].notna(), 0)
        a, b, c = st.columns(3)
        a.metric("Escomptes pris", _m(esc["pris"].sum()), border=True)
        b.metric("Escomptes manqués", _m(esc["manque"].sum()), help="Facture payée après la date limite d'escompte.", border=True)
        c.metric("Rendement annualisé du 2/10 net 30", f"{A.escompte_annualise_pct(2, 10, 30):.0f} %", help="À comparer au taux de la marge de crédit.", border=True)
        st.dataframe(esc.assign(Disponible=esc["escompte_cents"].map(_m2), Pris=esc["pris"].map(_m2))[["nom_legal", "no_facture", "date_limite_escompte", "date_paiement", "Disponible", "Pris"]]
                     .rename(columns={"nom_legal": "Fournisseur", "no_facture": "Facture", "date_limite_escompte": "Limite d'escompte", "date_paiement": "Payée le"}), hide_index=True, width="stretch")


# --------------------------------------------------------------------------- #
# 5. Contrôles et écritures
# --------------------------------------------------------------------------- #
def _controles(ref: date) -> pd.DataFrame:
    p = A.parametres(_conn())
    seuil = p["seuil_double_approbation"] * 100
    n = lambda sql, par=(): int(_df(sql, par).iloc[0, 0])
    lignes = [
        ("Séparation des tâches : le demandeur n'approuve pas sa commande", "Fraude et erreur de saisie", "Chaque commande",
         n("SELECT COUNT(*) FROM core_commande_achat WHERE demandeur = approuve_par"), "commandes où demandeur = approbateur"),
        ("Délégation d'autorité : le niveau d'approbation correspond au montant", "Engagement au-delà de l'autorité", "Chaque commande",
         n("SELECT COUNT(*) FROM core_commande_achat WHERE statut <> 'attente_approbation' AND ((niveau_approbation = 3 AND approuve_par <> 'Direction générale') OR (niveau_approbation = 2 AND approuve_par = 'Chef des approvisionnements'))"),
         "commandes approuvées par un niveau insuffisant"),
        ("Appariement à trois voies avant approbation", "Payer ce qui n'a pas été reçu ou au mauvais prix", "Chaque facture",
         n("SELECT COUNT(*) FROM core_facture_fournisseur WHERE statut IN ('approuvee', 'en_lot', 'payee') AND commande_id IS NOT NULL AND (ABS(COALESCE(ecart_prix_pct, 0)) > ? OR ABS(COALESCE(ecart_quantite_pct, 0)) > ?) "
           "AND (approuve_par IS NULL OR motif_ecart IS NULL)", (p["tolerance_prix_pct"], p["tolerance_quantite_pct"])), "factures hors tolérance acceptées sans motif"),
        ("Détection des factures en double", "Double paiement", "Chaque facture",
         n("SELECT COUNT(*) FROM core_facture_fournisseur f WHERE EXISTS (SELECT 1 FROM core_facture_fournisseur g WHERE g.fournisseur_id = f.fournisseur_id AND g.no_facture = f.no_facture AND g.facture_id < f.facture_id AND f.statut <> 'contestee')"),
         "doublons non contestés"),
        ("Bon de commande exigé hors achats préautorisés", "Achats non autorisés", "Chaque facture",
         n("SELECT COUNT(*) FROM core_facture_fournisseur f JOIN mdm_fournisseur o ON o.fournisseur_id = f.fournisseur_id WHERE f.commande_id IS NULL AND o.famille_achat NOT IN ('service_public', 'services_professionnels') AND f.statut NOT IN ('ecart', 'contestee')"),
         "factures sans commande acceptées"),
        ("Fiche fournisseur validée, coordonnées bancaires confirmées par rappel", "Fraude au faux changement de coordonnées", "Chaque paiement",
         n("SELECT COUNT(*) FROM core_paiement_fournisseur p JOIN mdm_fournisseur o ON o.fournisseur_id = p.fournisseur_id WHERE o.statut <> 'actif'"), "paiements à un fournisseur non actif"),
        ("Double approbation des lots importants", "Paiement frauduleux ou erroné de grande valeur", "Chaque lot",
         n("SELECT COUNT(*) FROM core_lot_paiement l WHERE l.statut = 'execute' AND (SELECT COALESCE(SUM(montant_cents), 0) FROM core_paiement_fournisseur p WHERE p.lot_id = l.lot_id) > ? AND (l.approbateur_2 IS NULL OR l.approbateur_2 = l.approbateur_1)", (seuil,)),
         "lots exécutés sans double approbation"),
        ("Le préparateur du lot ne l'approuve pas", "Auto-approbation", "Chaque lot", n("SELECT COUNT(*) FROM core_lot_paiement WHERE prepare_par IN (approbateur_1, approbateur_2)"), "lots auto-approuvés"),
        ("Paiement dans les délais", "Pénalités, relations fournisseurs", "Chaque semaine",
         n("SELECT COUNT(*) FROM core_paiement_fournisseur p JOIN core_facture_fournisseur f ON f.facture_id = p.facture_id JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE l.date_paiement > f.date_echeance"), "paiements après l'échéance"),
        ("Rapprochement bancaire des paiements", "Débit inconnu ou absent", "Chaque mois",
         n("SELECT COUNT(*) FROM core_paiement_fournisseur p JOIN core_lot_paiement l ON l.lot_id = p.lot_id WHERE p.statut_rapprochement <> 'RAPPROCHE' AND l.statut = 'execute' AND l.date_paiement < date(?, '-2 day')", (ref.isoformat(),)),
         "paiements exécutés depuis plus de 2 jours, non rapprochés"),
        ("Écritures équilibrées", "Erreur comptable", "Chaque écriture",
         n("SELECT COUNT(*) FROM (SELECT no_ecriture FROM core_ecriture_achat GROUP BY no_ecriture HAVING SUM(debit_cents) <> SUM(credit_cents))"), "écritures déséquilibrées"),
    ]
    df = pd.DataFrame(lignes, columns=["Contrôle", "Risque couvert", "Fréquence", "Exceptions", "Mesure"])
    df["Résultat"] = df["Exceptions"].map(lambda v: "✅ conforme" if v == 0 else "⚠ à traiter")
    df["Mesure"] = df["Exceptions"].astype(str) + " " + df["Mesure"]
    return df


def onglet_controles(ref: date) -> None:
    df = _controles(ref)
    a, b, c = st.columns(3)
    a.metric("Contrôles", len(df), border=True)
    b.metric("Conformes", int((df["Exceptions"] == 0).sum()), border=True)
    c.metric("Avec exceptions", int((df["Exceptions"] > 0).sum()), border=True)
    _mk("**Matrice des contrôles**, mesurée sur les données du cycle")
    st.dataframe(df[["Résultat", "Contrôle", "Risque couvert", "Fréquence", "Mesure"]], hide_index=True, width="stretch")

    _mk("**Règles de qualité du cycle** (moteur de qualité des données)")
    c = _conn()
    try:
        regles = c.execute("SELECT regle_id, nom, dimension, severite, sql_violations, sql_total, seuil_pct FROM dq_regle WHERE regle_id IN ('DQ-UNI-010', 'DQ-COH-010', 'DQ-COH-011', 'DQ-EXA-010', 'DQ-INT-010', 'DQ-VAL-010') ORDER BY regle_id").fetchall()
        rows = []
        for rid, nom, dim, sev, sv, stt, seuil in regles:
            tot = c.execute(stt, {"run_id": None}).fetchone()[0]
            viol = len({r[0] for r in c.execute(sv, {"run_id": None})})
            score = 100.0 if tot == 0 else round(100 * (1 - viol / tot), 1)
            rows.append({"Règle": rid, "Nom": nom, "Dimension": dim, "Évalués": tot, "Violations": viol, "Score %": score, "Statut": "✅ pass" if score >= seuil else "⚠ fail"})
    finally:
        c.close()
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    _mk("##### Journal et balance des écritures du cycle")
    ev = st.segmented_control("Événement", ["Tous", "reception", "facture", "paiement"], default="Tous", key="ach_ev") or "Tous"
    e = _df("SELECT e.*, c.libelle_fr FROM core_ecriture_achat e JOIN ref_compte_comptable c ON c.code = e.compte_code ORDER BY e.date_ecriture DESC, e.ligne_ecriture_id DESC")
    if ev != "Tous":
        e = e[e["evenement"] == ev]
    bal = e.groupby(["compte_code", "libelle_fr"], as_index=False)[["debit_cents", "credit_cents"]].sum()
    bal["solde_cents"] = bal["debit_cents"] - bal["credit_cents"]
    x, y = st.columns([3, 2])
    with x:
        st.dataframe(bal.assign(Débit=bal["debit_cents"].map(_m), Crédit=bal["credit_cents"].map(_m), Solde=bal["solde_cents"].map(_m))[["compte_code", "libelle_fr", "Débit", "Crédit", "Solde"]]
                     .rename(columns={"compte_code": "Compte", "libelle_fr": "Libellé"}), hide_index=True, width="stretch")
        _cap(f"Total des débits {_m(bal['debit_cents'].sum())} · total des crédits {_m(bal['credit_cents'].sum())} · " + ("balance équilibrée." if bal["debit_cents"].sum() == bal["credit_cents"].sum() else "balance déséquilibrée."))
    with y:
        fig = px.bar(bal.sort_values("solde_cents"), x="solde_cents", y="compte_code", orientation="h", color_discrete_sequence=["#2a78d6"])
        fig.update_xaxes(title="Solde (cents)")
        fig.update_yaxes(title=None, type="category")
        _fig(fig, 320, "ach_bal")
    grni = bal[bal["compte_code"] == "2105"]["solde_cents"].sum()
    _info(f"Achats reçus non facturés (compte 2105) : **{_m(-grni)}** — produits entrés au magasin dont la facture n'est pas arrivée. À provisionner en fin de période. "
            f"Comptes fournisseurs (2100) : **{_m(-bal[bal['compte_code'] == '2100']['solde_cents'].sum())}** dus aux fournisseurs.", icon=":material/account_balance:")
    with st.expander("Dernières écritures"):
        st.dataframe(e.head(60).assign(Débit=e.head(60)["debit_cents"].map(lambda v: _m2(v) if v else ""), Crédit=e.head(60)["credit_cents"].map(lambda v: _m2(v) if v else ""))[
            ["date_ecriture", "evenement", "no_ecriture", "document_ref", "compte_code", "libelle_fr", "Débit", "Crédit"]], hide_index=True, width="stretch")


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #
def afficher() -> None:
    _cap("Le cycle achats-décaissements de Groupe Usinage Saint-Maurice : de la commande au débit bancaire, avec la gestion des fournisseurs, les contrôles et les écritures. "
               "L'exemple est complet et vit dans la base de démonstration ; les actions (approuver, préparer et exécuter un lot) écrivent dans cette base et respectent les contrôles.")
    if not A.assurer(M.BASE_DEMO):
        _warn("Le socle de gouvernance n'est pas initialisé sur la base de démonstration : l'exemple du cycle ne peut pas être créé.")
        return
    ref = A.date_reference(_conn())
    top1, top2 = st.columns([5, 1])
    top1.caption(f"Date de référence de l'exemple : **{ref.isoformat()}**. Les échéances, retards et décaissements sont calculés à cette date.")
    if top2.button("Régénérer l'exemple", key="ach_regen", width="stretch", help="Efface les données du cycle et recrée l'exemple à la date d'aujourd'hui."):
        A.reinitialiser(M.BASE_DEMO)
        for k in ("ach_cmd", "ach_etape"):
            st.session_state.pop(k, None)
        st.rerun()
    bandeau(ref)
    onglets = st.tabs(["🔄 Cycle complet", "🏭 Fournisseurs", "🧾 Factures et appariement", "💸 Paiements et échéancier", "🛡 Contrôles et écritures"])
    with onglets[0]:
        onglet_cycle(ref)
    with onglets[1]:
        onglet_fournisseurs(ref)
    with onglets[2]:
        onglet_factures(ref)
    with onglets[3]:
        onglet_paiements(ref)
    with onglets[4]:
        onglet_controles(ref)
