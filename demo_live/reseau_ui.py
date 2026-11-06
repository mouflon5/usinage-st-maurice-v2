"""Onglet « Réseau de neurones » de la vue Raisonnement : les agents, les LLM, leurs garde-fous et les indicateurs reliés, dessinés comme un réseau.

Chaque neurone est un agent (grand cercle), un LLM (hexagone), un garde-fou (losange), un indicateur (carré), l'humain (étoile) ou une entrée. Une flèche est une synapse : son
épaisseur est le volume transmis, sa couleur le verdict. Cliquez un neurone (ou choisissez-le dans la liste) pour mettre en évidence son voisinage et lire son détail ; le curseur
« Étape du passage » rejoue le raisonnement : le réseau s'allume agent par agent. Le moteur du graphe est raisonnement_graphe.py (testé par test_reseau_raisonnement.py).
"""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import raisonnement_graphe as G

CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}
COULEUR_STATUT = {"ok": "#1baf7a", "att": "#d9930a", "crit": "#d03b3b", "inactif": "#8f9aa8"}
COULEUR_TYPE = {"entree": "#6b8fb5", "llm": "#8a63d2", "garde": "#d9930a", "humain": "#e0679c", "sortie": "#1f5f8b", "indicateur": "#17a2b8", "agent": "#2a78d6"}
SYMBOLE = {"entree": "circle", "agent": "circle", "llm": "hexagon", "garde": "diamond", "humain": "star", "sortie": "pentagon", "indicateur": "square"}
LIBELLE_TYPE = {"entree": "Entrées", "agent": "Agents", "llm": "LLM", "garde": "Garde-fous", "humain": "Humain", "sortie": "Sortie", "indicateur": "Indicateurs"}
STYLE_SYNAPSE = {"flux": ("#2a78d6", "solid"), "llm": ("#8a63d2", "solid"), "garde": ("#d9930a", "dash"), "supervision": ("#8f9aa8", "dot"), "indicateur": ("#17a2b8", "solid"), "relation": ("#17a2b8", "dash")}
LIBELLE_SYNAPSE = {"flux": "flux de données", "llm": "échange avec le LLM", "garde": "garde-fou", "supervision": "supervision", "indicateur": "mesure d'un indicateur", "relation": "relation entre indicateurs"}
LIBELLE_STATUT = {"ok": "conforme", "att": "à surveiller", "crit": "critique", "inactif": "inactif"}
COLONNES = [(0.0, "Entrées"), (1.0, "Acquisition"), (2.0, "Extraction"), (3.0, "Classement"), (4.0, "Prévision · Écarts"), (5.0, "Contrôle · Relecture"), (6.0, "Humain · Rapports"), (7.0, "Sortie"),
            (8.4, "Indicateurs du passage"), (10.0, "Trésorerie")]


def _rgba(hexa: str, a: float) -> str:
    h = hexa.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def _couleur_neurone(n: G.Neurone) -> str:
    if n.type in ("agent", "sortie", "garde"):
        return COULEUR_STATUT[n.statut] if n.statut != "inactif" or n.type != "garde" else COULEUR_TYPE["garde"]
    if n.type == "llm":
        return COULEUR_TYPE["llm"] if n.statut in ("ok", "inactif") else COULEUR_STATUT[n.statut]
    return COULEUR_TYPE[n.type]


def _survol(n: G.Neurone) -> str:
    L = [f"<b>{html.escape(n.label)}</b>", f"{LIBELLE_TYPE.get(n.type, n.type)} · {LIBELLE_STATUT[n.statut]}"]
    if n.valeur:
        L.append(f"Valeur : {html.escape(n.valeur)}")
    if n.delta is not None:
        L.append(f"Variation pendant le passage : {n.delta:+,.0f}".replace(",", " "))
    msg = n.details.get("message") or n.details.get("regle")
    if msg:
        L.append(html.escape(str(msg))[:170] + ("…" if len(str(msg)) > 170 else ""))
    return "<br>".join(L)


def figure(r: G.Reseau, etape: int, selection: str | None = None, profondeur: int = 1, montrer_llm: bool = True, montrer_ind: bool = True) -> go.Figure:
    """Réseau dessiné pour une étape du rejeu et un neurone sélectionné."""
    allumes = G.allume(r, etape)
    visibles = {k for k, n in r.neurones.items() if (montrer_llm or n.type not in ("llm", "garde")) and (montrer_ind or n.type != "indicateur")}
    voisinage = G.voisins(r, selection, profondeur) if selection and selection in r.neurones and profondeur > 0 else None
    fig = go.Figure()
    for x, titre in COLONNES:
        if x >= 8 and not montrer_ind:
            continue
        fig.add_shape(type="rect", x0=x - 0.42, x1=x + 0.42, y0=-4.0, y1=4.2, fillcolor="rgba(128,128,128,.06)", line=dict(width=0), layer="below")
        fig.add_annotation(x=x, y=4.45, text=f"<b>{titre}</b>", showarrow=False, font=dict(size=11, color="rgba(128,128,128,.95)"))
    pmax = max([s.poids for s in r.synapses if s.type == "flux"] + [1.0])
    for s in r.synapses:
        if s.source not in visibles or s.cible not in visibles:
            continue
        a, b = r.neurones[s.source], r.neurones[s.cible]
        actif = s.source in allumes and s.cible in allumes and s.statut != "inactif"
        couleur, dash = STYLE_SYNAPSE[s.type]
        if s.type in ("llm", "garde") and s.statut in ("att", "crit"):
            couleur = COULEUR_STATUT[s.statut]
        if s.type == "flux" and s.statut in ("att", "crit"):
            couleur = COULEUR_STATUT[s.statut]
        dim = voisinage is not None and not (s.source in voisinage and s.cible in voisinage and (s.source == selection or s.cible == selection))
        if not actif:
            alpha, couleur = 0.14, "#8f9aa8"
        else:
            alpha = 0.9 if s.type in ("flux", "llm", "garde") else 0.55
        if dim:
            alpha *= 0.18
        if s.type == "flux":
            largeur = 1.4 + 4.2 * (min(s.poids, pmax) / pmax) ** 0.5 if s.poids else 1.0
        elif s.type in ("llm", "garde"):
            largeur = 1.4 + min(3.0, s.poids * 0.4)
        else:
            largeur = 1.2
        fig.add_annotation(x=b.x, y=b.y, ax=a.x, ay=a.y, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.0, arrowwidth=largeur,
                           arrowcolor=_rgba(couleur, alpha), standoff=b.taille / 2 + 3, startstandoff=a.taille / 2 + 3, text="")
        if s.type == "flux" and actif and s.poids and not dim:
            fig.add_annotation(x=(a.x + b.x) / 2, y=(a.y + b.y) / 2, text=f"{s.poids:g}", showarrow=False, font=dict(size=10, color=_rgba(couleur, 1)), bgcolor="rgba(255,255,255,.0)", yshift=7)
    # points invisibles au milieu des synapses : survol
    mx, my, mt = [], [], []
    for s in r.synapses:
        if s.source in visibles and s.cible in visibles:
            a, b = r.neurones[s.source], r.neurones[s.cible]
            mx.append((a.x + b.x) / 2)
            my.append((a.y + b.y) / 2)
            mt.append(f"<b>{html.escape(a.label)} → {html.escape(b.label)}</b><br>{LIBELLE_SYNAPSE[s.type]}" + (f" · poids {s.poids:g}" if s.poids else "") + (f"<br>{html.escape(s.etiquette)}" if s.etiquette else ""))
    fig.add_scatter(x=mx, y=my, mode="markers", marker=dict(size=9, color="rgba(0,0,0,0)"), hovertext=mt, hoverinfo="text", showlegend=False, name="synapses")
    for typ in ("entree", "agent", "llm", "garde", "humain", "sortie", "indicateur"):
        ns = [n for k, n in r.neurones.items() if n.type == typ and k in visibles]
        if not ns:
            continue
        couleurs, bords, textes, tailles = [], [], [], []
        for n in ns:
            lumiere = n.id in allumes
            dim = voisinage is not None and n.id not in voisinage
            a = (1.0 if lumiere else 0.35) * (0.2 if dim else 1.0)
            base = _couleur_neurone(n) if lumiere else "#8f9aa8"
            couleurs.append(_rgba(base, a) if (typ not in ("llm", "garde") or lumiere) else "rgba(143,154,168,.18)")
            bord = "#1b2430" if n.id == selection else ("#1baf7a" if n.delta_bon is True else "#d03b3b" if n.delta_bon is False else "#ffffff")
            bords.append(_rgba(bord, 1.0 if n.id == selection else (0.0 if dim else 0.9)))
            textes.append(n.label + (f"<br><b>{n.valeur}</b>" if n.valeur and lumiere else ""))
            tailles.append(n.taille * (1.18 if (r.avec_passage and etape and n.ordre == etape and n.type == "agent") else 1.0))
        fig.add_scatter(x=[n.x for n in ns], y=[n.y for n in ns], mode="markers+text", name=LIBELLE_TYPE[typ], text=textes, textposition="bottom center",
                        textfont=dict(size=10.5, color=["rgba(128,128,128,.95)" if (voisinage is None or n.id in voisinage) else "rgba(128,128,128,.25)" for n in ns]),
                        marker=dict(size=tailles, color=couleurs, symbol=[SYMBOLE[typ] if (n.id in allumes or n.type != "llm") else "hexagon-open" for n in ns], line=dict(color=bords, width=[3 if n.id == selection else 1.6 for n in ns])),
                        customdata=[n.id for n in ns], hovertext=[_survol(n) for n in ns], hoverinfo="text", selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))
    fig.update_xaxes(visible=False, range=[-0.7, 10.7], fixedrange=True)
    fig.update_yaxes(visible=False, range=[-4.3, 4.9], fixedrange=True, scaleanchor=None)
    fig.update_layout(height=680, margin=dict(l=0, r=0, t=6, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=True, clickmode="event+select", dragmode=False,
                      legend=dict(orientation="h", y=-0.02, x=0, font=dict(size=11)), hoverlabel=dict(font_size=12, align="left"))
    return fig


def _pastille(statut: str) -> str:
    return f'<span style="background:{COULEUR_STATUT[statut]};color:#fff;border-radius:999px;padding:1px 9px;font-size:.78rem;font-weight:700">{LIBELLE_STATUT[statut]}</span>'


def _panneau(r: G.Reseau, cle: str, traces: list[dict]) -> None:
    n = r.neurones[cle]
    amont, aval = G.amont_aval(r, cle)
    st.html(f'<div style="border:1px solid rgba(128,128,128,.3);border-left:6px solid {_couleur_neurone(n)};border-radius:10px;padding:10px 14px;margin-bottom:8px">'
            f'<div style="font-size:.72rem;opacity:.7;text-transform:uppercase;letter-spacing:.05em">{LIBELLE_TYPE.get(n.type, n.type)}</div>'
            f'<div style="font-size:1.15rem;font-weight:700">{html.escape(n.label)}</div><div style="margin-top:4px">{_pastille(n.statut)}'
            f'{(" &nbsp; <b>" + html.escape(n.valeur) + "</b>") if n.valeur else ""}</div></div>')
    d = n.details
    if d.get("regle"):
        st.markdown(f"**Sa règle.** {d['regle'].replace('$', chr(92) + '$')}")
    if d.get("message"):
        st.markdown(f"**Sa décision.** {str(d['message']).replace('$', chr(92) + '$')}")
    if n.type == "agent" and d.get("duree") is not None:
        st.caption(f"Durée : {d['duree']:.2f} s · statut brut : {d.get('statut_brut')}")
        if d.get("sorties"):
            st.markdown("**A transmis** : " + ", ".join(f"{v} {k}" for k, v in d["sorties"].items()))
    if n.type == "llm":
        st.markdown(f"**Échanges** : {d.get('echanges', 0)} · **modèle** : {', '.join(d.get('modeles', []))}")
        if d.get("decisions"):
            st.markdown("**Décisions de l'agent** : " + ", ".join(f"{k} ({v})" for k, v in d["decisions"].items()))
        if d.get("tokens_in") or d.get("tokens_out"):
            st.caption(f"Jetons : {d.get('tokens_in', 0)} entrés, {d.get('tokens_out', 0)} sortis")
        mes = [t for t in traces if t.get("agent") == n.agent]
        if mes:
            from demo_live import raisonnement_ui as RS
            t = st.selectbox("Voir un échange", mes, key=f"rn_ech_{cle}", format_func=lambda x: f"#{x['id']} · {x.get('decision') or 'réponse utilisée'}")
            RS._echange(t)
    if n.type == "garde":
        st.markdown(f"**Réponses acceptées** : {d.get('acceptees', 0)} · **écartées** : {d.get('rejets', 0)}")
        for rs in d.get("raisons", []):
            st.markdown(f"- {str(rs).replace('$', chr(92) + '$')}")
    if n.type == "indicateur":
        if d.get("avant") is not None:
            st.markdown(f"**Avant** : {G.formater(d['avant'], '$' if '$' in (n.valeur or '') else 'n')} → **après** : {n.valeur}")
        if n.delta is not None:
            bon = {True: "dans le bon sens", False: "dans le mauvais sens", None: "sans sens favorable défini"}[n.delta_bon]
            st.markdown(f"**Variation** : {n.delta:+,.0f}".replace(",", " ") + f" ({bon})")
        if d.get("agents"):
            st.markdown("**Produit par** : " + ", ".join(d["agents"]))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Reçoit de**")
        for s in amont:
            st.caption(f"← {r.neurones[s.source].label} · {LIBELLE_SYNAPSE[s.type]}" + (f" · {s.poids:g}" if s.poids else ""))
        if not amont:
            st.caption("—")
    with c2:
        st.markdown("**Transmet à**")
        for s in aval:
            st.caption(f"→ {r.neurones[s.cible].label} · {LIBELLE_SYNAPSE[s.type]}" + (f" · {s.poids:g}" if s.poids else ""))
        if not aval:
            st.caption("—")


def _tableau_indicateurs(r: G.Reseau) -> None:
    lignes = []
    for cle, lib, source, k, agents, sens, fmt in G.INDICATEURS:
        n = r.neurones[cle]
        lies = [s.source if s.cible == cle else s.cible for s in r.synapses if s.type == "relation" and cle in (s.source, s.cible)]
        lignes.append({"Indicateur": lib, "Valeur": n.valeur or "—", "Variation": "—" if n.delta is None else f"{n.delta:+,.0f}".replace(",", " "),
                       "Sens": {True: "favorable", False: "défavorable", None: "—"}[n.delta_bon] if n.delta is not None else "—", "Produit par": ", ".join(agents),
                       "Lié à": ", ".join(r.neurones[x].label for x in lies) or "—", "État": LIBELLE_STATUT[n.statut]})
    st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")


def _legende() -> None:
    st.html('<div style="display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.8rem;opacity:.85;margin:2px 0 6px">'
            '<span>● agent (taille = durée)</span><span style="color:#8a63d2">⬢ LLM</span><span style="color:#d9930a">◆ garde-fou</span><span style="color:#17a2b8">■ indicateur</span>'
            '<span style="color:#e0679c">★ humain</span><span>→ flux : épaisseur = volume transmis</span><span style="color:#d9930a">⇢ garde-fou</span>'
            '<span style="color:#17a2b8">⇢ relation entre indicateurs</span><span>contour vert/rouge = indicateur qui a bougé dans le bon/mauvais sens</span></div>')


def afficher_reseau(evts: list[dict], traces: list[dict], appels, titre: str = "") -> None:
    r = G.construire(evts, traces, appels, titre)
    if not r.avec_passage:
        st.info("Aucun passage choisi : voici la structure du réseau. Lancez une démonstration pour voir chaque neurone s'allumer.")
    m = G.resume(r)
    c = st.columns(5)
    c[0].metric("Agents actifs", f"{m['agents_actifs']} / {m['agents']}")
    c[1].metric("Échanges avec un LLM", m["echanges_llm"])
    c[2].metric("Réponses écartées", m["rejets"], help="Escaladées à l'humain, rejetées ou remplacées par un garde-fou.")
    c[3].metric("Indicateurs reliés", m["indicateurs"] if r.avec_passage else len(G.INDICATEURS))
    c[4].metric("Synapses", m["synapses"])
    n_et = G.nb_etapes(r)
    a, b, cc, d = st.columns([3, 1.4, 1.2, 1.2])
    etape = a.slider("Étape du passage (rejeu)", 0, max(n_et, 1), n_et, key="rn_etape", disabled=not r.avec_passage,
                     help="0 : seules les entrées sont allumées ; chaque cran allume l'agent suivant, ses LLM, ses garde-fous et ses indicateurs.") if r.avec_passage else 0
    prof = b.radio("Voisinage mis en évidence", [0, 1, 2], index=1, horizontal=True, key="rn_prof", format_func=lambda v: {0: "tout", 1: "direct", 2: "2 niveaux"}[v])
    montrer_llm = cc.toggle("LLM et garde-fous", True, key="rn_llm")
    montrer_ind = d.toggle("Indicateurs", True, key="rn_ind")
    ids = list(r.neurones)
    if "rn_choix" not in st.session_state or st.session_state["rn_choix"] not in ids:
        st.session_state["rn_choix"] = "A3"
    ev = st.session_state.get("rn_graph")
    pts = (ev or {}).get("selection", {}).get("points", []) if ev else []
    if pts:
        cd = pts[0].get("customdata")
        cd = cd[0] if isinstance(cd, (list, tuple)) and cd else cd
        signature = (cd, pts[0].get("x"), pts[0].get("y"))
        if cd in r.neurones and st.session_state.get("rn_dernier_clic") != signature:
            st.session_state["rn_choix"] = cd
            st.session_state["rn_dernier_clic"] = signature
    _legende()
    g, p = st.columns([7, 3])
    with p:
        cle = st.selectbox("Neurone", ids, key="rn_choix", format_func=lambda k: f"{G.AGENTS[k][0]}" if k in G.AGENTS else r.neurones[k].label)
    with g:
        st.plotly_chart(figure(r, etape, cle, prof, montrer_llm, montrer_ind), theme="streamlit", width="stretch", config=CONFIG, key="rn_graph", on_select="rerun", selection_mode="points")
    with p:
        _panneau(r, cle, traces)
    if r.avec_passage and etape:
        agent = next((code for code in r.etapes if r.neurones[code].ordre == etape), None)
        if agent:
            from demo_live import raisonnement_ui as RS
            nom, regle = RS.ROLES.get(agent, (agent, ""))
            st.info(f"**Étape {etape} — {agent} · {nom}.** {regle}  \n**Décision :** {r.neurones[agent].details.get('message') or '—'}".replace("$", "\\$"))
    with st.expander("Indicateurs reliés : valeurs, variations et relations", expanded=False):
        st.caption("Chaque indicateur est produit par un ou plusieurs agents et dépend d'autres indicateurs : le solde dépend du flux, le creux du solde, le coussin et les semaines sous le seuil du creux.")
        _tableau_indicateurs(r)
    with st.expander("Toutes les synapses du réseau"):
        st.dataframe(pd.DataFrame([{"De": r.neurones[s.source].label, "Vers": r.neurones[s.cible].label, "Type": LIBELLE_SYNAPSE[s.type], "Poids": s.poids, "Note": s.etiquette, "État": LIBELLE_STATUT[s.statut]}
                                   for s in r.synapses]), hide_index=True, width="stretch")
    st.caption("Lecture : un agent s'active quand ses entrées sont prêtes ; son LLM propose, son garde-fou accepte ou écarte, l'agent décide et transmet ; les indicateurs reflètent ce que le passage a changé. "
               "Le LLM ne décide jamais seul : toute réponse écartée reste visible ici.")
