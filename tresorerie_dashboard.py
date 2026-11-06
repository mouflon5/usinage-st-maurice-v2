"""
Tableau de bord de trésorerie CPA — V6 / moteur SARIMAX Python
================================================================

Cette version conserve le tableau de bord HTML R0 à R8, mais déplace le moteur
SARIMAX de R8 dans Python via statsmodels. Le navigateur appelle le serveur
local Python pour :
  * charger la série mensuelle depuis SQLite ;
  * estimer SARIMAX par maximum de vraisemblance ;
  * réaliser le backtest ;
  * calculer MAE, RMSE, biais, AIC et BIC ;
  * produire les prévisions et intervalles de confiance 80 % / 95 %.

Commandes :
    pip install -r requirements.txt
    python tresorerie_dashboard.py --check
    python tresorerie_dashboard.py --sarimax-test
    python tresorerie_dashboard.py
    python tresorerie_dashboard.py --build-db
    python tresorerie_dashboard.py --export-html copie.html

Important : pour utiliser le vrai SARIMAX Python dans R8, lancez simplement
`python tresorerie_dashboard.py`. Si le HTML est ouvert directement, le tableau conserve un
fallback local uniquement pour rester consultable hors serveur.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import warnings
import webbrowser
from dataclasses import dataclass
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from socketserver import ThreadingMixIn
from urllib.parse import unquote
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    STATSMODELS_AVAILABLE = True
except Exception:
    SARIMAX = None
    STATSMODELS_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("TRESORERIE_DB") or (BASE_DIR / "tresorerie.db")).resolve()
SORTIES_DIR = Path(os.environ.get("TRACES_DIR") or (BASE_DIR / "sorties")).resolve()   # traces écrites par le pipeline
AGENTS_HTML = BASE_DIR / "agents.html"
HTML_PATH = BASE_DIR / "tableau_de_bord_tresorerie_interactif.html"
SEED = 20260901
# En local (hors Docker) : 127.0.0.1. Dans le conteneur, le Dockerfile fixe
# DASHBOARD_HOST=0.0.0.0 pour que le port publié soit joignable depuis l'hôte.
HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")

EXPECTED_R8_CONTROLS = [
    "r8-serie", "r8-h", "r8-period", "r8-holdout", "r8-model", "r8-cycle",
    "r8-z", "r8-alpha", "r8-beta", "r8-gamma", "r8-sarp", "r8-sard",
    "r8-sarq", "r8-sarP", "r8-sarD", "r8-sarQ", "r8-sartrend",
    "r8-sarfourier", "r8-apply",
]
EXPECTED_MODELS = [
    "Auto", "Naïf saisonnier", "Holt-Winters additif",
    "Tendance + saisonnalité", "SARIMAX",
]

AGG_KEYS = {"Revenu", "Decaissements", "Fixe", "Variable", "Financement", "Flux"}


def _read_categories(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT categorie,nature FROM categories ORDER BY ordre", conn)


def _period_index(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT DISTINCT annee, mois,
                  printf('%04d-%02d', annee, mois) AS periode
           FROM journal_general
           ORDER BY annee, mois""", conn
    )


def load_monthly_series(series_key: str, db_path: Path = DB_PATH) -> tuple[list[str], np.ndarray, dict[str, Any]]:
    """Charge une série R8 directement depuis SQLite.

    Clés agrégées : Revenu, Decaissements, Fixe, Variable, Financement, Flux.
    Catégories détaillées : cat:<libellé exact>.
    Les dépenses sont retournées en valeur absolue, comme dans le dashboard.
    """
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path)
    try:
        periods_df = _period_index(conn)
        periods = periods_df["periode"].tolist()
        if len(periods) != 48:
            raise RuntimeError(f"48 mois attendus, {len(periods)} trouvés")

        base = pd.read_sql_query(
            """SELECT annee, mois, categorie, nature, montant
               FROM journal_general
               ORDER BY annee, mois""", conn
        )
        base["periode"] = base.apply(lambda r: f"{int(r.annee):04d}-{int(r.mois):02d}", axis=1)

        if series_key.startswith("cat:"):
            cat = series_key[4:]
            row = conn.execute("SELECT nature FROM categories WHERE categorie=?", (cat,)).fetchone()
            if not row:
                raise ValueError(f"Catégorie inconnue : {cat}")
            nature = str(row[0])
            s = base.loc[base.categorie == cat].groupby("periode")["montant"].sum()
            vals = np.array([float(s.get(p, 0.0)) for p in periods], dtype=float)
            nonnegative = nature != "Revenu" or True
            if nature != "Revenu":
                vals = np.abs(vals)
            meta = {"key": series_key, "label": cat, "nature": nature, "nonnegative": True}
            return periods, vals, meta

        if series_key not in AGG_KEYS:
            raise ValueError(f"Série inconnue : {series_key}")

        def summed(mask, absolute=False):
            g = base.loc[mask].groupby("periode")["montant"].sum()
            arr = np.array([float(g.get(p, 0.0)) for p in periods], dtype=float)
            return np.abs(arr) if absolute else arr

        if series_key == "Revenu":
            vals = summed(base.nature == "Revenu", False)
            label, nature, nonnegative = "Encaissements — total", "Revenu", True
        elif series_key == "Fixe":
            vals = summed(base.nature == "Fixe", True)
            label, nature, nonnegative = "Dépenses fixes — total", "Fixe", True
        elif series_key == "Variable":
            vals = summed(base.nature == "Variable", True)
            label, nature, nonnegative = "Dépenses variables — total", "Variable", True
        elif series_key == "Financement":
            vals = summed(base.nature == "Financement", True)
            label, nature, nonnegative = "Financement — total", "Financement", True
        elif series_key == "Decaissements":
            vals = summed(base.nature != "Revenu", True)
            label, nature, nonnegative = "Décaissements — total", "Dépense", True
        else:
            rev = summed(base.nature == "Revenu", False)
            dep = summed(base.nature != "Revenu", True)
            vals = rev - dep
            label, nature, nonnegative = "Flux net", "Flux net", False
        return periods, vals, {"key": series_key, "label": label, "nature": nature, "nonnegative": nonnegative}
    finally:
        conn.close()


def _future_periods(last_period: str, h: int) -> list[str]:
    p = pd.Period(last_period, freq="M")
    return [str(p + i) for i in range(1, h + 1)]


def _exog_matrix(n: int, s: int, use_trend: bool, fourier_k: int, start_t: int = 0) -> pd.DataFrame | None:
    cols: dict[str, np.ndarray] = {}
    t = np.arange(start_t, start_t + n, dtype=float)
    if use_trend:
        scale = max(1.0, float(start_t + n - 1))
        cols["time_trend"] = t / scale
    for k in range(1, max(0, int(fourier_k)) + 1):
        cols[f"sin{k}"] = np.sin(2 * np.pi * k * t / max(2, int(s)))
        cols[f"cos{k}"] = np.cos(2 * np.pi * k * t / max(2, int(s)))
    return pd.DataFrame(cols) if cols else None


def _fit_sarimax(y: np.ndarray, p: int, d: int, q: int, P: int, D: int, Q: int,
                 s: int, use_trend: bool, fourier_k: int, maxiter: int = 250):
    if not STATSMODELS_AVAILABLE:
        raise RuntimeError("statsmodels n'est pas installé. Exécutez pip install -r requirements.txt")
    y = np.asarray(y, dtype=float)
    if len(y) < max(18, s + 6):
        raise ValueError("Historique insuffisant pour ce paramétrage SARIMAX")
    if not np.isfinite(y).all():
        raise ValueError("La série contient des valeurs non finies")
    exog = _exog_matrix(len(y), s, use_trend, fourier_k, 0)
    trend = "c" if (d == 0 and D == 0) else "n"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = SARIMAX(
            y,
            exog=exog,
            order=(int(p), int(d), int(q)),
            seasonal_order=(int(P), int(D), int(Q), int(s)),
            trend=trend,
            enforce_stationarity=False,
            enforce_invertibility=False,
            simple_differencing=False,
        )
        res = model.fit(disp=False, maxiter=int(maxiter), method="lbfgs")
    return res


def _metrics(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    err = pred - actual
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "bias": float(np.mean(err)),
    }


def sarimax_analysis(payload: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    series_key = str(payload.get("series", "Revenu"))
    h = int(payload.get("horizon", 6))
    holdout = int(payload.get("holdout", 6))
    p = int(payload.get("p", 1)); d = int(payload.get("d", 0)); q = int(payload.get("q", 0))
    P = int(payload.get("P", 1)); D = int(payload.get("D", 0)); Q = int(payload.get("Q", 1))
    s = int(payload.get("s", 12))
    use_trend = bool(payload.get("trend", True))
    fourier_k = int(payload.get("fourier", 1))

    # Gardes-fous cohérents avec les contrôles HTML.
    if not (0 <= p <= 3 and 0 <= q <= 3 and 0 <= d <= 2): raise ValueError("p,d,q hors limites")
    if not (0 <= P <= 2 and 0 <= Q <= 2 and 0 <= D <= 1): raise ValueError("P,D,Q hors limites")
    if s not in (3, 6, 12): raise ValueError("s doit être 3, 6 ou 12")
    if not (0 <= fourier_k <= 2): raise ValueError("Fourier K hors limites")
    if not (3 <= h <= 12): raise ValueError("Horizon hors limites")
    if holdout not in (3, 4, 6, 8): raise ValueError("Fenêtre de backtest invalide")

    periods, y, meta = load_monthly_series(series_key, db_path)
    nonnegative = bool(meta["nonnegative"])
    if len(y) <= holdout + max(10, s):
        raise ValueError("Pas assez d'observations après retrait du backtest")

    train, actual = y[:-holdout], y[-holdout:]
    bt_res = _fit_sarimax(train, p,d,q,P,D,Q,s,use_trend,fourier_k)
    bt_exog = _exog_matrix(holdout, s, use_trend, fourier_k, len(train))
    bt_fc = bt_res.get_forecast(steps=holdout, exog=bt_exog)
    bt_pred = np.asarray(bt_fc.predicted_mean, float)
    if nonnegative: bt_pred = np.maximum(0, bt_pred)
    metrics = _metrics(actual, bt_pred)

    res = _fit_sarimax(y, p,d,q,P,D,Q,s,use_trend,fourier_k)
    fut_exog = _exog_matrix(h, s, use_trend, fourier_k, len(y))
    fc = res.get_forecast(steps=h, exog=fut_exog)
    pred = np.array(fc.predicted_mean, float)
    ci80 = np.array(fc.conf_int(alpha=0.20), float)
    ci95 = np.array(fc.conf_int(alpha=0.05), float)
    if nonnegative:
        pred = np.maximum(0, pred)
        ci80[:,0] = np.maximum(0, ci80[:,0]); ci80[:,1] = np.maximum(0, ci80[:,1])
        ci95[:,0] = np.maximum(0, ci95[:,0]); ci95[:,1] = np.maximum(0, ci95[:,1])

    converged = bool(getattr(res, "mle_retvals", {}).get("converged", True))
    return {
        "ok": True,
        "engine": "Python statsmodels SARIMAX",
        "statsmodels": True,
        "series": series_key,
        "label": meta["label"],
        "nature": meta["nature"],
        "periods": periods,
        "values": [float(x) for x in y],
        "future_periods": _future_periods(periods[-1], h),
        "forecast": [float(x) for x in pred],
        "ci80_low": [float(x) for x in ci80[:,0]],
        "ci80_high": [float(x) for x in ci80[:,1]],
        "ci95_low": [float(x) for x in ci95[:,0]],
        "ci95_high": [float(x) for x in ci95[:,1]],
        "backtest": {
            **metrics,
            "actual": [float(x) for x in actual],
            "pred": [float(x) for x in bt_pred],
            "holdout": holdout,
        },
        "diagnostics": {
            "aic": float(res.aic) if np.isfinite(res.aic) else None,
            "bic": float(res.bic) if np.isfinite(res.bic) else None,
            "llf": float(res.llf) if np.isfinite(res.llf) else None,
            "converged": converged,
            "nobs": int(res.nobs),
        },
        "params": {
            "order": [p,d,q], "seasonal_order": [P,D,Q,s],
            "trend_exog": use_trend, "fourier_k": fourier_k,
        },
        "warning": "" if converged else "L'optimiseur n'a pas déclaré une convergence complète; interpréter avec prudence.",
    }


def rebuild_synthetic_history(db_path: Path = DB_PATH) -> None:
    if not db_path.exists(): raise FileNotFoundError(db_path)
    rng = np.random.default_rng(SEED)
    conn = sqlite3.connect(db_path); conn.execute("PRAGMA foreign_keys=ON")
    try:
        base = pd.read_sql_query("SELECT * FROM journal_general WHERE annee IN (2025,2026)", conn)
        if base.empty: raise RuntimeError("La base ne contient pas les données de référence 2025-2026.")
        agg=(base.assign(abs_montant=base.montant.abs()).groupby(["annee","mois","categorie","nature"],as_index=False)["abs_montant"].sum())
        cats=_read_categories(conn)
        pivot=agg.pivot_table(index=["categorie","nature","mois"],columns="annee",values="abs_montant",aggfunc="sum")
        pivot["ref"]=pivot.mean(axis=1); ref=pivot["ref"].to_dict()
        templates={}
        for (month,cat),g in base[base.annee==2025].groupby(["mois","categorie"]): templates[(int(month),str(cat))]=g.sort_values("date_ecriture").copy()
        for (month,cat),g in base[base.annee==2026].groupby(["mois","categorie"]): templates.setdefault((int(month),str(cat)),g.sort_values("date_ecriture").copy())
        cat_offsets={c:float(rng.normal(0,.018)) for c in cats.categorie}; cat_phase={c:float(rng.uniform(0,2*math.pi)) for c in cats.categorie}
        year_scale={2023:.885,2024:.945}; noise={"Fixe":.018,"Variable":.045,"Financement":.030,"Revenu":.038}
        rows=[]
        for year in (2023,2024):
            for month in range(1,13):
                for cat,nature in cats.itertuples(index=False):
                    ref_amt=float(ref.get((cat,nature,month),0) or 0); tmpl=templates.get((month,cat))
                    if ref_amt<=0 or tmpl is None or len(tmpl)==0: continue
                    macro=1+.025*math.sin(2*math.pi*((year-2023)*12+month)/17+cat_phase[cat]); eps=float(rng.normal(0,noise.get(nature,.03)))
                    target=max(0,ref_amt*year_scale[year]*(1+cat_offsets[cat])*macro*(1+eps))
                    if cat in {"Location d'équipement (crédit-bail CNC)","Remboursement emprunt équipement (BDC)"}: target=max(0,ref_amt*year_scale[year]*(1+.003*math.sin(month)))
                    if "Subventions et crédits" in cat and month not in (3,9): continue
                    weights=tmpl.montant.abs().to_numpy(float); weights*=np.clip(rng.lognormal(0,.07,len(weights)),.75,1.35); weights/=weights.sum()
                    amounts=np.round(target*weights,2)
                    if len(amounts): amounts[-1]=round(target-float(amounts[:-1].sum()),2)
                    for (_,tr),amt in zip(tmpl.iterrows(),amounts):
                        dt=pd.Timestamp(tr["date_ecriture"]); last=calendar.monthrange(year,month)[1]; day=max(1,min(last,int(dt.day)+int(rng.integers(-2,3))))
                        desc=str(tr["description"]); desc=re.sub(r"FACT\s+\d+",lambda _m:f"FACT {int(rng.integers(10000,99999))}",desc); desc=re.sub(r"FACTURE\s+\d+",lambda _m:f"FACTURE {int(rng.integers(10000,99999))}",desc)
                        sign=1 if nature=="Revenu" else -1
                        rows.append((year,month,day,desc,round(sign*float(amt),2),cat,nature,tr["compte_source"]))
        rows.sort(key=lambda r:(r[0],r[1],r[2],r[5],r[3])); counters={2023:0,2024:0}; insert=[]
        for year,month,day,desc,amt,cat,nature,compte in rows:
            counters[year]+=1; insert.append((f"JG-{year}-{counters[year]:05d}",f"{year:04d}-{month:02d}-{day:02d}",desc,amt,cat,nature,month,year,compte,f"FY{year}"))
        with conn:
            conn.execute("DELETE FROM journal_general WHERE annee IN (2023,2024)")
            conn.executemany("""INSERT INTO journal_general(no_ecriture,date_ecriture,description,montant,categorie,nature,mois,annee,compte_source,exercice) VALUES (?,?,?,?,?,?,?,?,?,?)""",insert)
            params=[
              ("general","historique_debut","2023-01","str","Début de l’historique mensuel"),("general","historique_nb_mois","48","int","Nombre de mois d’historique"),("general","annees_synthetiques",json.dumps([2023,2024]),"json","Années synthétiques ajoutées"),("general","graine_historique_synthetique",str(SEED),"int","Graine des données synthétiques"),
              ("r8_sarimax","p","1","int","Ordre AR"),("r8_sarimax","d","0","int","Différenciation"),("r8_sarimax","q","0","int","Ordre MA"),("r8_sarimax","P","1","int","Ordre AR saisonnier"),("r8_sarimax","D","0","int","Différenciation saisonnière"),("r8_sarimax","Q","1","int","Ordre MA saisonnier"),("r8_sarimax","s","12","int","Période saisonnière"),("r8_sarimax","trend_exog","true","bool","Tendance temporelle exogène"),("r8_sarimax","fourier_k","1","int","Nombre de paires Fourier")]
            conn.executemany("INSERT OR REPLACE INTO parametres(domaine,cle,valeur,type_valeur,libelle) VALUES (?,?,?,?,?)",params)
        print(f"Historique synthétique reconstruit : {len(insert)} écritures 2023-2024.")
    finally: conn.close()


def ensure_sarimax_params(db_path: Path = DB_PATH) -> None:
    conn=sqlite3.connect(db_path)
    try:
        params=[("r8_sarimax","p","1","int","Ordre AR"),("r8_sarimax","d","0","int","Différenciation"),("r8_sarimax","q","0","int","Ordre MA"),("r8_sarimax","P","1","int","Ordre AR saisonnier"),("r8_sarimax","D","0","int","Différenciation saisonnière"),("r8_sarimax","Q","1","int","Ordre MA saisonnier"),("r8_sarimax","s","12","int","Période saisonnière"),("r8_sarimax","trend_exog","true","bool","Tendance temporelle exogène"),("r8_sarimax","fourier_k","1","int","Paires Fourier")]
        with conn: conn.executemany("INSERT OR REPLACE INTO parametres(domaine,cle,valeur,type_valeur,libelle) VALUES (?,?,?,?,?)",params)
    finally: conn.close()


def run_sarimax_tests(db_path: Path = DB_PATH, verbose: bool = True) -> bool:
    tests=[]
    def check(name, fn):
        try:
            val=fn(); tests.append((name,True,str(val)[:110]))
        except Exception as exc: tests.append((name,False,f"{type(exc).__name__}: {exc}"))
    check("statsmodels disponible", lambda: STATSMODELS_AVAILABLE or (_ for _ in ()).throw(RuntimeError("absent")))
    for key in ["Revenu","Decaissements","Fixe","Variable","Financement","Flux"]:
        check(f"Série {key}", lambda k=key: len(load_monthly_series(k,db_path)[1])==48 or (_ for _ in ()).throw(RuntimeError("taille")))
    conn=sqlite3.connect(db_path); cats=[r[0] for r in conn.execute("select categorie from categories order by ordre")]; conn.close()
    for cat in cats:
        check(f"Catégorie {cat[:35]}", lambda c=cat: len(load_monthly_series('cat:'+c,db_path)[1])==48 or (_ for _ in ()).throw(RuntimeError("taille")))
    default={"series":"Revenu","horizon":6,"holdout":6,"p":1,"d":0,"q":0,"P":1,"D":0,"Q":1,"s":12,"trend":True,"fourier":1}
    check("SARIMAX défaut", lambda: len(sarimax_analysis(default,db_path)["forecast"])==6 or (_ for _ in ()).throw(RuntimeError("forecast")))
    variations=[("p",0),("p",2),("d",1),("q",1),("P",0),("P",2),("D",1),("Q",0),("Q",2),("s",6),("s",3),("trend",False),("fourier",0),("fourier",2),("horizon",12),("holdout",3),("holdout",8)]
    for key,val in variations:
        pp=dict(default); pp[key]=val
        check(f"Paramètre {key}={val}", lambda p=pp: sarimax_analysis(p,db_path)["ok"])
    # Catégories contrastées
    for cat in [cats[0], cats[1], cats[-1]]:
        pp=dict(default); pp["series"]='cat:'+cat
        check(f"SARIMAX catégorie {cat[:30]}", lambda p=pp: sarimax_analysis(p,db_path)["ok"])
    ok=sum(1 for _,x,_ in tests if x)
    if verbose:
        print(f"\nTests SARIMAX Python : {ok}/{len(tests)} réussis\n")
        for name,good,detail in tests: print(("OK " if good else "ERR")+"  "+name+(" — "+detail if detail else ""))
    return ok==len(tests)


def check_package(db_path: Path = DB_PATH, html_path: Path = HTML_PATH) -> bool:
    checks=[]
    def add(name,ok,detail=""): checks.append((name,bool(ok),detail))
    add("Fichier HTML présent",html_path.exists(),html_path.name); add("Base SQLite présente",db_path.exists(),db_path.name); add("statsmodels disponible",STATSMODELS_AVAILABLE)
    if db_path.exists():
        conn=sqlite3.connect(db_path)
        try:
            quick=conn.execute("PRAGMA quick_check").fetchone()[0]; add("SQLite quick_check",quick=="ok",str(quick))
            row=conn.execute("SELECT min(date_ecriture),max(date_ecriture),count(*) FROM journal_general").fetchone(); add("Historique commence en 2023",str(row[0]).startswith("2023-"),str(row[0])); add("Historique se termine en 2026",str(row[1]).startswith("2026-"),str(row[1])); add("1 824 écritures",int(row[2])==1824,str(row[2]))
            months=conn.execute("SELECT count(DISTINCT printf('%04d-%02d',annee,mois)) FROM journal_general").fetchone()[0]; add("48 mois distincts",int(months)==48,str(months))
            originals=conn.execute("SELECT count(*) FROM journal_general WHERE annee IN (2025,2026)").fetchone()[0]; add("2025-2026 conservés",int(originals)==912,str(originals)); cats=conn.execute("SELECT count(*) FROM categories").fetchone()[0]; add("25 catégories",int(cats)>=25,str(cats)); sarpars=conn.execute("SELECT count(*) FROM parametres WHERE domaine='r8_sarimax'").fetchone()[0]; add("Paramètres SARIMAX en base",int(sarpars)>=9,str(sarpars))
        finally: conn.close()
    if html_path.exists():
        html=html_path.read_text(encoding="utf-8",errors="replace"); add("R8 présent","R8" in html and "Analyse temporelle" in html); add("API Python SARIMAX référencée","/api/r8/sarimax" in html); add("Moteur Python affiché","Python statsmodels" in html)
        for cid in EXPECTED_R8_CONTROLS: add(f"Contrôle {cid}",f'id="{cid}"' in html or f"'{cid}'" in html or f'"{cid}"' in html)
        node=shutil.which("node")
        if node:
            scripts=re.findall(r"<script(?:\\s[^>]*)?>([\\s\\S]*?)</script>",html,flags=re.I); tmp=BASE_DIR/".jscheck.js"; tmp.write_text("\n".join(scripts),encoding="utf-8"); proc=subprocess.run([node,"--check",str(tmp)],capture_output=True,text=True); tmp.unlink(missing_ok=True); add("Syntaxe JavaScript",proc.returncode==0,proc.stderr.strip()[:120])
    passed=sum(x for _,x,_ in checks); print(f"\nContrôles du package : {passed}/{len(checks)} réussis\n")
    for name,ok,detail in checks: print(("OK " if ok else "ERR")+"  "+name+(" — "+detail if detail else ""))
    return passed==len(checks)


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Petit serveur local robuste, sans dépendance web externe.

    On évite ici SimpleHTTPRequestHandler, qui pouvait accepter la connexion
    sous Windows puis la fermer avant d'envoyer la page (NS_ERROR_NET_EMPTY_RESPONSE).
    """
    daemon_threads = True
    allow_reuse_address = True


def _wsgi_json(start_response, status: str, obj: dict[str, Any]):
    raw = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(raw))),
        ("Cache-Control", "no-store"),
    ])
    return [raw]


LIEN_AGENTS = (b'<a href="/agents" style="position:fixed;right:16px;bottom:16px;z-index:99999;padding:10px 16px;'
               b'border-radius:999px;background:#2a78d6;color:#fff;font:600 14px system-ui,sans-serif;text-decoration:none;'
               b'box-shadow:0 2px 8px rgba(0,0,0,.25)">Agents \xe2\x96\xb8</a>')


LIVE = os.environ.get("TRESORERIE_LIVE") == "1"          # mode démo : R0–R7 recalculés depuis la base
REF_DB = os.environ.get("TRESORERIE_REF")                 # base de référence (effet de trésorerie des écritures ajoutées)
DEMO_DB = os.environ.get("DEMO_DB")                       # base d'événements de la démo (version « temps réel »)

# Script injecté en mode démo (aucun changement de mise en page) : mémorise l'onglet et le défilement,
# et recharge la page quand la base a changé (sondage toutes les 2 s).
SCRIPT_LIVE = """<script>
(function(){
  var K='tdb_live_';
  function lire(k){try{return sessionStorage.getItem(K+k)}catch(e){return null}}
  function ecrire(k,v){try{sessionStorage.setItem(K+k,v)}catch(e){}}
  window.addEventListener('load',function(){
    setTimeout(function(){
      var cible=lire('tab'); if(cible){var b=document.querySelector('button[role=tab][data-cible="'+cible+'"]'); if(b) b.click();}
      var y=parseInt(lire('y')||'0',10); if(y) window.scrollTo(0,y);
    },350);
    document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button[role=tab]'); if(b&&b.dataset.cible) ecrire('tab',b.dataset.cible);});
    window.addEventListener('scroll',function(){ecrire('y',String(window.scrollY))},{passive:true});
  });
  /* Rafraîchissement À LA DEMANDE : la page signale qu'il y a du nouveau (bouton orange) mais ne se recharge que sur clic.
     La case « auto » (désactivée par défaut, mémorisée) rétablit l'ancien rechargement automatique. */
  function lireL(k){try{return localStorage.getItem(K+k)}catch(e){return null}}
  function ecrireL(k,v){try{localStorage.setItem(K+k,v)}catch(e){}}
  function recharger(){ecrire('y',String(window.scrollY));location.reload();}
  var v0=null, nouveau=false, btn=null, cb=null;
  function monter(){
    var barre=document.getElementById('hne-barre');
    if(!barre){return setTimeout(monter,100);}
    btn=document.createElement('button'); btn.id='hne-rafraichir'; btn.type='button';
    btn.textContent='\\u21bb Rafra\\u00eechir'; btn.title='Recharger les donn\\u00e9es depuis la base';
    btn.onclick=recharger;
    var lab=document.createElement('label'); lab.className='hne-auto'; lab.title='Recharger automatiquement d\\u00e8s que la base change';
    cb=document.createElement('input'); cb.type='checkbox'; cb.checked=(lireL('auto')==='1');
    cb.onchange=function(){ecrireL('auto',cb.checked?'1':'0'); if(cb.checked&&nouveau){recharger();}};
    lab.appendChild(cb); lab.appendChild(document.createTextNode(' auto'));
    barre.insertBefore(lab,barre.firstChild); barre.insertBefore(btn,barre.firstChild);
  }
  function sonder(){
    fetch('/api/live/version',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
      if(v0===null){v0=j.version;return;}
      if(j.version!==v0){
        nouveau=true;
        if(btn){btn.classList.add('neuf'); btn.textContent='\\u21bb Rafra\\u00eechir \\u25cf'; btn.title='Nouvelles donn\\u00e9es disponibles';}
        if(cb&&cb.checked){recharger();}
      }
    }).catch(function(){});
  }
  monter(); setInterval(sonder,2000); sonder();
})();
</script>"""

# Thème clair / sombre (choix mémorisé dans le navigateur ; « auto » suit le système). La mise en page d'origine n'est pas modifiée :
# on surcharge seulement les variables CSS, puis on recolore les graphiques Plotly déjà tracés.
THEME_TETE = """<style id="hne-theme">
:root[data-theme="dark"]{color-scheme:dark;
  --fond:#1b1713;--surface:#25201a;--surface2:#2e2720;--grille:#3b3228;--texte:#efe6d8;--attenue:#aa9c8a;
  --laiton:#d9a04e;--sarcelle:#8fa086;--rouge:#e07a57;--bleu:#b89678;--violet:#c19c7c;--vert:#a3a977;--orange:#e0aa5f}
:root[data-theme="dark"] .barre-onglets{background:rgba(27,23,19,.95)}
:root[data-theme="dark"] .kpi,:root[data-theme="dark"] .graphe,:root[data-theme="dark"] .sim-panel{box-shadow:0 2px 10px rgba(0,0,0,.35)}
#hne-barre{position:fixed;top:10px;right:14px;z-index:99998;display:flex;gap:8px;align-items:center;padding:5px 8px;
  border:1px solid var(--grille);border-radius:999px;background:var(--surface);color:var(--texte);
  font:500 13px 'IBM Plex Sans',system-ui,sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.18)}
#hne-barre button,#hne-barre select{font:inherit;color:var(--texte);background:var(--surface2);border:1px solid var(--grille);
  border-radius:999px;padding:4px 11px;cursor:pointer}
#hne-barre button:hover,#hne-barre select:hover{border-color:var(--laiton)}
#hne-barre button.neuf{background:var(--laiton);color:#1b1713;border-color:var(--laiton);font-weight:600}
#hne-barre .hne-auto{display:flex;align-items:center;gap:2px;color:var(--attenue);cursor:pointer}
</style>
<script>
(function(){
  var cle='tdb_theme';
  /* ?theme=dark|light|auto : imposé par l'application (sélecteur de la barre latérale) ; mémorisé pour les pages suivantes */
  var m=(location.search||'').match(/[?&]theme=(dark|light|auto)/), force=m?m[1]:null;
  try{if(force)localStorage.setItem(cle,force);}catch(e){}
  function lire(){try{return localStorage.getItem(cle)||'auto'}catch(e){return 'auto'}}
  function effectif(c){return c==='auto'?(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):c;}
  document.documentElement.setAttribute('data-theme',effectif(lire()));
  window.hneTheme={lire:lire,effectif:effectif,cle:cle,force:!!force};
})();
</script>"""

# Pages annexes servies par le même serveur (agents, diagrammes) : elles ont déjà leurs couleurs claires et sombres ; on leur transmet le thème.
THEME_PAGES = """<script>(function(){var cle='tdb_theme',m=(location.search||'').match(/[?&]theme=(dark|light|auto)/),t=m?m[1]:null;
try{if(t)localStorage.setItem(cle,t);else t=localStorage.getItem(cle);}catch(e){}
if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);
else document.documentElement.removeAttribute('data-theme');})();</script>"""


def _avec_theme(raw: bytes) -> bytes:
    return raw.replace(b"</head>", THEME_PAGES.encode("utf-8") + b"</head>", 1) if b"</head>" in raw else THEME_PAGES.encode("utf-8") + raw


THEME_BARRE = """<div id="hne-barre"><select id="hne-theme" aria-label="Thème"><option value="auto">Thème : auto</option><option value="light">☀ Clair</option><option value="dark">☾ Sombre</option></select></div>
<script>
(function(){
  var T=window.hneTheme, sel=document.getElementById('hne-theme');
  var PAL={light:{surface:'#FFFEFB',grille:'#E4D8C8',texte:'#302820',attenue:'#756658'},
           dark:{surface:'#25201a',grille:'#3b3228',texte:'#efe6d8',attenue:'#aa9c8a'}};
  function appliquer(choix){
    var eff=T.effectif(choix), p=PAL[eff];
    document.documentElement.setAttribute('data-theme',eff);
    try{Object.assign(C,p);}catch(e){}                       /* les graphiques tracés ensuite reprennent la palette */
    if(window.Plotly){
      document.querySelectorAll('.js-plotly-plot').forEach(function(el){
        try{Plotly.relayout(el,{plot_bgcolor:p.surface,'font.color':p.texte,'title.font.color':p.texte,
          'xaxis.linecolor':p.grille,'xaxis.tickfont.color':p.attenue,'yaxis.gridcolor':p.grille,'yaxis.tickfont.color':p.attenue,
          'hoverlabel.bgcolor':p.surface,'hoverlabel.bordercolor':p.grille,'hoverlabel.font.color':p.texte});}catch(e){}
      });
    }
  }
  sel.value=T.lire();
  if(T.force){sel.style.display='none';}                       /* thème imposé par l'application : un seul sélecteur pour tout le projet */
  sel.onchange=function(){try{localStorage.setItem(T.cle,sel.value)}catch(e){} appliquer(sel.value);};
  if(window.matchMedia){matchMedia('(prefers-color-scheme: dark)').addEventListener('change',function(){if(T.lire()==='auto')appliquer('auto');});}
  appliquer(T.lire());
})();
</script>"""


def _version_live() -> str:
    """Change dès que la base de données ou le journal d'événements de la démo change."""
    parts = []
    for p in (str(DB_PATH), str(DB_PATH) + "-wal", DEMO_DB, (DEMO_DB + "-wal") if DEMO_DB else None):
        try:
            if p and os.path.exists(p):
                st = os.stat(p)
                parts.append(f"{int(st.st_mtime * 1000)}:{st.st_size}")
        except OSError:
            pass
    return "|".join(parts)


def _wsgi_html(start_response):
    if LIVE:
        import donnees_tableau as dt
        try:
            texte = dt.html_vivant(DB_PATH, HTML_PATH, REF_DB)
        except Exception as exc:                      # ne jamais laisser l'écran vide pendant une démo
            texte = HTML_PATH.read_text(encoding="utf-8")
            print("[live] reconstruction impossible :", type(exc).__name__, exc)
        if dt.plotly_local():
            texte = dt.html_hors_ligne(texte)
        raw = texte.encode("utf-8")
        raw = raw.replace(b"</body>", THEME_BARRE.encode("utf-8") + SCRIPT_LIVE.encode("utf-8") + b"</body>", 1)
    else:
        raw = HTML_PATH.read_bytes()
        raw = raw.replace(b"</body>", THEME_BARRE.encode("utf-8") + LIEN_AGENTS + b"</body>", 1) if b"</body>" in raw else raw + LIEN_AGENTS
    raw = raw.replace(b"</head>", THEME_TETE.encode("utf-8") + b"</head>", 1)
    start_response("200 OK", [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(raw))),
        ("Cache-Control", "no-store"),
    ])
    return [raw]


def _agents_api(environ, start_response, path: str):
    from urllib.parse import parse_qs
    ok = lambda obj: _wsgi_json(start_response, "200 OK", obj)
    if path == "/api/agents/dernier":
        f = SORTIES_DIR / "dernier_run.json"
        if not f.exists():
            return ok({"ok": False, "error": "Aucun passage du pipeline trouvé dans " + str(SORTIES_DIR)})
        return ok({"ok": True, "run": json.loads(f.read_text(encoding="utf-8"))})
    if path == "/api/agents/historique":
        f = SORTIES_DIR / "historique_runs.jsonl"
        lignes = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
        return ok({"ok": True, "runs": lignes[-30:][::-1]})
    if path == "/api/agents/run":
        ident = (parse_qs(environ.get("QUERY_STRING") or "").get("id") or [""])[0]
        if not re.fullmatch(r"[0-9T]{10,30}", ident):
            return _wsgi_json(start_response, "400 Bad Request", {"ok": False, "error": "id invalide"})
        f = SORTIES_DIR / "runs" / f"{ident}.json"
        if not f.exists():
            return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "passage introuvable"})
        return ok({"ok": True, "run": json.loads(f.read_text(encoding="utf-8"))})
    if path == "/api/agents/series":
        out = {}
        for cle in ("Revenu", "Decaissements", "Flux"):
            periodes, vals, meta = load_monthly_series(cle, DB_PATH)
            out[cle] = [float(v) for v in vals]
        return ok({"ok": True, "periodes": periodes, "series": out, "base": DB_PATH.name})
    return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "Ressource inconnue"})


def dashboard_wsgi_app(environ, start_response):
    """Application WSGI minimale : page HTML + API SARIMAX."""
    try:
        method = (environ.get("REQUEST_METHOD") or "GET").upper()
        path = unquote(environ.get("PATH_INFO") or "/")

        if method == "GET" and path == "/api/health":
            return _wsgi_json(start_response, "200 OK", {
                "ok": True,
                "engine": "Python statsmodels SARIMAX",
                "statsmodels": STATSMODELS_AVAILABLE,
            })

        if method == "GET" and path == "/api/live/version":
            return _wsgi_json(start_response, "200 OK", {"ok": True, "version": _version_live()})
        if method == "GET" and path == "/static/plotly.min.js":
            import donnees_tableau as dt
            f = dt.plotly_local()
            if not f:
                return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "plotly local absent"})
            raw = f.read_bytes()
            start_response("200 OK", [("Content-Type", "application/javascript; charset=utf-8"),
                                      ("Content-Length", str(len(raw))), ("Cache-Control", "max-age=86400")])
            return [raw]

        # ---- Diagrammes interactifs de la démo (pages + données en direct) ----
        if path.startswith("/diagrammes/") or path.startswith("/api/diag/"):
            import demo_live.api_diagrammes as dg
            from urllib.parse import parse_qs
            if method == "GET" and path.startswith("/diagrammes/"):
                raw = dg.page(path[len("/diagrammes/"):])
                if raw is None:
                    return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "page inconnue"})
                tipo = "text/html" if path.endswith(".html") else ("text/css" if path.endswith(".css") else "application/javascript")
                if tipo == "text/html":
                    raw = _avec_theme(raw)
                start_response("200 OK", [("Content-Type", tipo + "; charset=utf-8"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store")])
                return [raw]
            if method == "GET" and path == "/api/diag/etat":
                run = (parse_qs(environ.get("QUERY_STRING") or "").get("run") or [None])[0]
                return _wsgi_json(start_response, "200 OK", json.loads(json.dumps(dg.etat(run), default=str)))
            if method == "GET" and path == "/api/diag/perf":
                return _wsgi_json(start_response, "200 OK", json.loads(json.dumps(dg.perf(), default=str)))
            if method == "GET" and path == "/api/diag/rag":
                return _wsgi_json(start_response, "200 OK", json.loads(json.dumps(dg.rag_etat(), default=str)))
            if method == "POST":
                try:
                    n = int(environ.get("CONTENT_LENGTH") or "0")
                except ValueError:
                    n = 0
                corps = json.loads(environ["wsgi.input"].read(n).decode("utf-8") or "{}") if n else {}
                return _wsgi_json(start_response, "200 OK", dg.post(path, corps))
            return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "inconnu"})

        # ---- Onglet « Agents » : lit les traces écrites par le pipeline (sorties/) et la base ----
        if method == "GET" and path == "/agents":
            if not AGENTS_HTML.exists():
                return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "agents.html absent"})
            raw = _avec_theme(AGENTS_HTML.read_bytes())
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                      ("Content-Length", str(len(raw))), ("Cache-Control", "no-store")])
            return [raw]
        if method == "GET" and path.startswith("/api/agents/"):
            return _agents_api(environ, start_response, path)

        if method == "POST" and path == "/api/r8/sarimax":
            try:
                n = int(environ.get("CONTENT_LENGTH") or "0")
            except ValueError:
                n = 0
            try:
                raw = environ["wsgi.input"].read(n) if n else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
                result = sarimax_analysis(payload, DB_PATH)
                return _wsgi_json(start_response, "200 OK", result)
            except Exception as exc:
                return _wsgi_json(start_response, "422 Unprocessable Entity", {
                    "ok": False,
                    "engine": "Python statsmodels SARIMAX",
                    "error": str(exc),
                    "type": type(exc).__name__,
                })

        # Le navigateur peut demander la racine, la page elle-même ou favicon.ico.
        if method == "GET" and path in ("/", f"/{HTML_PATH.name}"):
            return _wsgi_html(start_response)
        if method == "GET" and path == "/favicon.ico":
            start_response("204 No Content", [("Content-Length", "0")])
            return [b""]

        return _wsgi_json(start_response, "404 Not Found", {"ok": False, "error": "Ressource inconnue"})
    except Exception as exc:
        # Dernier filet de sécurité : ne jamais fermer la connexion sans réponse.
        return _wsgi_json(start_response, "500 Internal Server Error", {
            "ok": False,
            "error": str(exc),
            "type": type(exc).__name__,
        })


def serve(port: int = 8765, open_browser: bool = True):
    """Lance le tableau de bord local.

    `python tresorerie_dashboard.py` suffit. Le serveur essaie le port demandé
    puis les 9 ports suivants si nécessaire.
    """
    if not HTML_PATH.exists():
        raise FileNotFoundError(HTML_PATH)
    ensure_sarimax_params()

    server = None
    selected_port = None
    last_error = None
    for candidate in range(int(port), int(port) + 10):
        try:
            server = make_server(
                HOST,
                candidate,
                dashboard_wsgi_app,
                server_class=ThreadingWSGIServer,
                handler_class=WSGIRequestHandler,
            )
            selected_port = candidate
            break
        except OSError as exc:
            last_error = exc

    if server is None or selected_port is None:
        raise RuntimeError(
            f"Impossible d'ouvrir un port local entre {port} et {int(port)+9}. "
            f"Dernière erreur : {last_error}"
        )

    display_host = "127.0.0.1" if HOST == "0.0.0.0" else HOST
    url = f"http://{display_host}:{selected_port}/"
    if selected_port != int(port):
        print(f"Port {port} occupé : utilisation automatique du port {selected_port}.")
    print(f"Tableau de bord : {url}")
    print("R8 SARIMAX : moteur Python statsmodels actif")
    print(f"Base utilisée : {DB_PATH}  |  Traces des agents : {SORTIES_DIR}  |  Onglet Agents : {url}agents")
    print("Gardez cette fenêtre ouverte. Ctrl+C pour arrêter.")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServeur arrêté.")
    finally:
        server.server_close()

def main():
    parser=argparse.ArgumentParser(description="Tableau de bord de trésorerie CPA — V6")
    parser.add_argument("--check",action="store_true"); parser.add_argument("--sarimax-test",action="store_true",help="Tester le moteur SARIMAX Python"); parser.add_argument("--build-db",action="store_true"); parser.add_argument("--serve",action="store_true"); parser.add_argument("--port",type=int,default=8765); parser.add_argument("--no-browser",action="store_true"); parser.add_argument("--export-html",type=Path,metavar="DEST")
    args=parser.parse_args(); did=False
    if args.build_db: rebuild_synthetic_history(); ensure_sarimax_params(); did=True
    if args.sarimax_test: did=True; assert run_sarimax_tests()
    if args.check: did=True; ensure_sarimax_params(); ok=check_package(); ok2=run_sarimax_tests(verbose=False); print("SARIMAX smoke tests :", "OK" if ok2 else "ERREUR");
    if args.check and not (ok and ok2): raise SystemExit(1)
    if args.export_html: shutil.copy2(HTML_PATH,args.export_html); print(f"HTML exporté : {args.export_html}"); did=True
    if args.serve or not did: serve(args.port,not args.no_browser)

if __name__=="__main__": main()
