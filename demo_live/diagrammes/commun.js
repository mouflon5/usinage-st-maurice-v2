/* Outils communs aux trois diagrammes : SVG, infobulle, rejeu des événements, métadonnées des agents. */
const NS = 'http://www.w3.org/2000/svg';
const $ = (s, r = document) => r.querySelector(s);
function S(tag, attrs = {}, ...enfants) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) e.setAttribute(k, v);
  for (const c of enfants.flat()) if (c !== null && c !== undefined) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
function H(tag, attrs = {}, ...enfants) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (v !== null && v !== undefined) e.setAttribute(k, v); }
  for (const c of enfants.flat()) if (c !== null && c !== undefined) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
const esp = n => String(Math.round(Math.abs(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
const $$ = (v, signe) => v == null ? '—' : (v < 0 ? '−' : (signe && v > 0 ? '+' : '')) + esp(v) + ' $';
const nb = v => v == null ? '—' : esp(v);
const sec = v => v == null ? '—' : (v < 1 ? Math.round(v * 1000) + ' ms' : v.toFixed(2).replace('.', ',') + ' s');
const sup = (t, n) => (t && t.length > n) ? t.slice(0, n - 1) + '…' : (t || '');
async function api(url, corps) {
  const r = await fetch(url, corps ? { method: 'POST', body: JSON.stringify(corps) } : { cache: 'no-store' });
  return r.json();
}

/* ---------- infobulle ---------- */
const tip = H('div', { class: 'tip' });
document.addEventListener('DOMContentLoaded', () => document.body.append(tip));
function bulle(el, html) {
  el.addEventListener('mousemove', e => { tip.innerHTML = typeof html === 'function' ? html() : html; tip.style.display = 'block'; tip.style.left = Math.min(e.clientX + 14, innerWidth - 350) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
  el.addEventListener('mouseleave', () => tip.style.display = 'none');
}

/* ---------- statuts ---------- */
function classe(statut) {
  if (!statut) return 'ok';
  if (['complet', 'approuve', 'ok', 'approuver'].includes(statut)) return 'ok';
  if (['reserves', 'a_arbitrer', 'degrade', 'indisponible', 'complet_avec_reserves'].includes(statut)) return 'res';
  return 'stop';
}
const LIB = { ok: '✓ terminé', res: '⚠ réserve', stop: '✕ arrêt', cours: '● en cours', att: '· en attente', non: '– non exécuté' };
const VIVANT = ['en_cours', 'en_attente', 'en_pause', 'approbation'];

/* ---------- métadonnées (ce que fait chaque agent, ce qui est LLM, quels rapports) ---------- */
const META = {
  SOURCE: { nom: 'Relevés bancaires (PDF)', role: 'Entrée du système : un ou plusieurs relevés mensuels, quatre mises en page différentes.', llm: 'non', rapports: [] },
  A1: { nom: 'Acquisition', role: 'Trouve les relevés du compte et détecte les mois manquants.', llm: 'non', outil: 'Lecture du dossier, calendrier des périodes', entrees: 'Dossier de relevés, période', sorties: 'Liste de fichiers, trous éventuels', rapports: [], arret: 'Trou de période → arrêt A1, rien n’est écrit.' },
  A2: { nom: 'Extraction', role: 'Lit les PDF (pdfplumber) et rejoue la continuité des soldes ligne par ligne.', llm: 'non', outil: 'pdfplumber, rejeu des soldes', entrees: 'Fichiers PDF', sorties: 'Transactions normalisées', rapports: ['R6 · saisie'], arret: 'Solde incohérent, ligne illisible → arrêt A2.' },
  A3: { nom: 'Classement', role: 'Écarte les doublons, classe par règles de mots-clés, puis demande au LLM de classer le résidu (liste fermée, seuil 0,8). Charge de façon atomique dans SQLite.', llm: 'résidu seulement', outil: 'Règles mots_cles, SQLite (transaction)', entrees: 'Transactions', sorties: 'Écritures au journal, lignes « À classer », doublons', rapports: ['R6 · Contrôles', 'R4 · Structure annuelle'], arret: 'Lignes « À classer » → arbitrage humain.' },
  A4: { nom: 'Prévision', role: 'SARIMAX (même moteur que R8), repli saisonnier naïf, alertes de backtest.', llm: 'non', outil: 'statsmodels SARIMAX', entrees: 'Historique mensuel (48 mois)', sorties: 'Prévisions à 6 mois, flux net prévu', rapports: ['R2 · Rolling forecast', 'R3 · Stress', 'R7 · Risque', 'R8 · Séries temporelles'], arret: 'Historique inutilisable → arrêt A4.' },
  A5: { nom: 'Écarts', role: 'Réel contre budget contre prévision, sans fuite de données ; causes calculées en SQL ; le LLM ne fait que rédiger.', llm: 'rédaction seulement', outil: 'SQL, seuils de matérialité', entrees: 'Journal, budget, prévisions', sorties: 'Lignes d’écart, commentaire', rapports: ['R5 · Écarts', 'R0 · Synthèse'], arret: 'Écarts non calculables → arrêt A5.' },
  A6: { nom: 'Contrôle', role: 'Refait 11 contrôles de façon indépendante. Seul point de sortie vers un humain : il approuve, approuve avec réserves ou bloque.', llm: 'non', outil: '11 contrôles déterministes (C1–C11)', entrees: 'Tout le dossier + la base', sorties: 'Verdict, empreinte', rapports: ['R6 · Contrôles'], arret: 'Contrôle bloquant → rien ne sort.' },
  A8: { nom: 'Relecture', role: 'Second avis qualitatif (LLM). Ne peut qu’ajouter des réserves : il ne bloque, ne débloque ni ne modifie rien. Toute réserve doit citer une ligne existante et aucun chiffre inventé.', llm: 'oui (règles en mode simulé)', outil: 'Garde-fous : références, gravité, nombres', entrees: 'Dossier complet', sorties: 'Réserves (L#, D#, A6:Cn)', rapports: ['R0 · Réserves'], arret: 'Jamais : en cas de panne, réserve « relecture non effectuée ».' },
  APPRO: { nom: 'Approbation humaine', role: 'Le contrôleur voit le verdict A6, les réserves A8 et les écarts, puis approuve ou rejette. Optionnelle dans la démo.', llm: 'non', rapports: [], arret: 'Rejet → rapport non produit.' },
  A7: { nom: 'Reporting', role: 'Produit le classeur Excel (R0–R5 + contrôles) et le brouillon R0 ; le LLM ne fait que la synthèse, chaque chiffre est vérifié.', llm: 'synthèse seulement', outil: 'openpyxl, gabarit R0', entrees: 'Dossier approuvé', sorties: 'Classeur Excel, R0 (.md)', rapports: ['Classeur Excel', 'R0 (texte)'] },
  SORTIES: { nom: 'Rapports', role: 'Fichiers remis au contrôleur : R0 en texte et classeur Excel.', llm: 'non', rapports: ['Classeur Excel', 'R0 (texte)'] },
  TABLEAU: { nom: 'Tableau de trésorerie', role: 'Ton tableau HTML (R0–R8), recalculé depuis la base à chaque étape.', llm: 'non', rapports: ['R0 à R8'] },
};

/* ---------- état des agents à partir des événements ---------- */
function etatAgents(evts, run) {
  const ag = {}, o = { ag, fin: null, appro: null, kpis: [], demarrage: null, enAttenteAppro: false };
  evts.forEach((e, i) => {
    if (e.type === 'demarrage') o.demarrage = e;
    if (e.type === 'agent' && e.noeud && e.noeud.startsWith('executer_')) ag[e.noeud.slice(-2).toUpperCase()] = { ...e, classe: classe(e.statut), i };
    if (e.type === 'agent' && e.noeud === 'approbation_humaine') ag.APPRO = { ...e, classe: 'ok', i };
    if (e.type === 'approbation') o.enAttenteAppro = true;
    if (e.type === 'decision') { o.appro = e.statut; o.enAttenteAppro = false; }
    if (e.type === 'fin') o.fin = e;
    if (e.kpi) o.kpis.push(e.kpi);
  });
  o.vivant = !!run && VIVANT.includes(run.statut) && !o.fin;
  return o;
}

/* ---------- barre de rejeu : passage, curseur, lecture, direct ---------- */
function barreRejeu(conteneur, titre, surChangement) {
  const st = { runs: [], run: null, evts: [], k: 0, direct: true, joue: false, vitesse: 1, moyennes: {}, issues: {}, runId: null };
  const sel = H('select', { onchange: () => { st.runId = sel.value; st.direct = false; chk.checked = false; charger(true); } });
  const chk = H('input', { type: 'checkbox', checked: '', onchange: () => { st.direct = chk.checked; if (st.direct) { st.runId = null; charger(true); } } });
  const cur = H('input', { type: 'range', min: 0, max: 0, value: 0, oninput: () => { st.k = +cur.value; st.direct = false; chk.checked = false; st.joue = false; bp.textContent = '▶'; rendre(); } });
  const lbl = H('span', { class: 'att' }, '');
  const bp = H('button', { title: 'Rejouer le passage étape par étape', onclick: () => { st.joue = !st.joue; bp.textContent = st.joue ? '⏸' : '▶'; if (st.joue) { st.direct = false; chk.checked = false; if (st.k >= st.evts.length) st.k = 0; } } }, '▶');
  const vit = H('select', { onchange: () => st.vitesse = +vit.value }, ...[0.5, 1, 2, 4].map(v => H('option', { value: v, selected: v === 1 ? '' : null }, v + '×')));
  conteneur.append(H('h1', {}, titre), H('label', {}, 'Passage ', sel), bp, H('label', {}, 'Étape ', cur, ' ', lbl), H('label', {}, 'Vitesse ', vit), H('label', {}, chk, ' Suivre le direct'));
  function rendre() {
    cur.max = st.evts.length; cur.value = st.k;
    lbl.textContent = st.k + ' / ' + st.evts.length;
    surChangement({ ...st, evtsVus: st.evts.slice(0, st.k), etat: etatAgents(st.evts.slice(0, st.k), st.run) });
  }
  async function charger(force) {
    const d = await api('/api/diag/etat' + (st.runId ? '?run=' + encodeURIComponent(st.runId) : ''));
    st.runs = d.runs; st.run = d.run; st.llm = d.llm_run || {}; st.moyennes = d.moyennes; st.issues = d.issues || {};
    const ancien = st.evts.length;
    st.evts = d.evenements;
    if (st.run) st.runId = st.run.run_id;
    sel.replaceChildren(...st.runs.map(r => H('option', { value: r.run_id, selected: r.run_id === st.runId ? '' : null }, `${sup(r.titre, 34)} — ${r.statut} — ${(r.debut || '').slice(11, 19)}`)));
    if (st.direct) st.k = st.evts.length; else if (force) st.k = Math.min(st.k, st.evts.length);
    if (force || st.direct || ancien !== st.evts.length) rendre();
  }
  setInterval(charger, 1500);
  setInterval(() => { if (st.joue) { if (st.k < st.evts.length) { st.k++; rendre(); } else { st.joue = false; bp.textContent = '▶'; } } }, 700);
  charger(true);
  return st;
}
