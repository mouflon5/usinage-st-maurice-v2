"use strict";
/* Moteur de graphe « neuronal » : physique en continu, nœuds déplaçables dont les voisins suivent (ressorts),
   impulsions lumineuses le long des liens, zoom à la molette, déplacement du fond, épinglage par double-clic.
   liveGraph({nodes, links, ...}) -> { svg, api } */
function liveGraph(o) {
  const W = o.width || 1000, H = o.height || 640;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", style: `background:var(--surface);border:1px solid var(--line);border-radius:10px;touch-action:none;user-select:none;max-height:${o.maxHeight || "78vh"}` });
  const mk = s("marker", { id: "lg" + (o.key || "x"), viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 6, markerHeight: 6, orient: "auto" }, s("path", { d: "M0,0 L8,4 L0,8 z", fill: "var(--muted)" }));
  svg.append(s("defs", {}, mk));
  const world = s("g"); svg.append(world);
  if (o.background) o.background(world);
  const gLinks = s("g"), gPulses = s("g"), gNodes = s("g"), gLabels = s("g");
  world.append(gLinks, gPulses, gNodes, gLabels);

  const P = { charge: o.charge ?? 3200, len: o.linkLen ?? 80, home: o.homeK ?? 0, gravity: o.gravity ?? 0.01, pulses: o.pulses !== false };
  const known = !!o.store && o.nodes.length > 0 && o.nodes.every(n => o.store.has(n.id)); // positions déjà connues : on repart calmement
  const nodes = o.nodes.map((n) => {
    const st = o.store && o.store.get(n.id);
    const a = Math.random() * Math.PI * 2, rr = 120 + Math.random() * 180;
    const m = Object.assign({ vx: 0, vy: 0, pinned: false, r: 7 }, n);
    m.x = st ? st.x : (n.x !== undefined ? n.x : W / 2 + Math.cos(a) * rr);
    m.y = st ? st.y : (n.y !== undefined ? n.y : H / 2 + Math.sin(a) * rr * 0.7);
    if (n.hx !== undefined) { m.hx = n.hx; m.hy = n.hy; }
    return m;
  });
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = o.links.filter(l => byId.has(l.a) && byId.has(l.b)).map(l => Object.assign({}, l, { A: byId.get(l.a), B: byId.get(l.b) }));
  const adj = new Map(nodes.map(n => [n.id, new Set()]));
  links.forEach(l => { adj.get(l.a).add(l.b); adj.get(l.b).add(l.a); });

  /* éléments SVG */
  links.forEach(l => {
    l.el = s("line", { stroke: l.color || "var(--line)", "stroke-width": l.width || 1, "stroke-dasharray": l.dash || null, "marker-end": o.arrows ? `url(#lg${o.key || "x"})` : null, style: "transition:opacity .15s" });
    gLinks.append(l.el);
    l.txt = s("text", { "text-anchor": "middle", "font-size": 10.5, fill: "var(--accent)", style: "paint-order:stroke;stroke:var(--surface);stroke-width:3px;pointer-events:none", display: o.linkLabels === "always" ? null : "none" }, l.label || "");
    gLabels.append(l.txt);
  });
  nodes.forEach(n => {
    const g = s("g", { class: "node", style: "cursor:grab;transition:opacity .15s" });
    n.g = g;
    if (o.renderNode) o.renderNode(n, g);
    else if (n.w) {
      g.append(s("rect", { x: -n.w / 2, y: -n.h / 2, width: n.w, height: n.h, rx: 9, fill: n.color, stroke: "var(--surface)", "stroke-width": 1.5 }),
        s("text", { y: 4, "text-anchor": "middle", fill: "#fff", "font-size": 12, "font-weight": 600, style: "pointer-events:none" }, n.label));
    } else {
      n.circ = s("circle", { r: n.r, fill: n.color, stroke: "var(--surface)", "stroke-width": 1.5, style: `filter:drop-shadow(0 0 5px ${n.color})` });
      g.append(n.circ);
      n.txt = s("text", { y: n.r + 11, "text-anchor": "middle", "font-size": 10, fill: "var(--ink)", style: "paint-order:stroke;stroke:var(--surface);stroke-width:3px;pointer-events:none", display: o.labels === "always" ? null : "none" }, n.label || "");
      g.append(n.txt);
    }
    n.pin = s("circle", { r: (n.w ? 5 : n.r + 4), cx: n.w ? n.w / 2 : 0, cy: n.w ? -n.h / 2 : 0, fill: "none", stroke: "var(--ink)", "stroke-width": 1.5, "stroke-dasharray": "3 2", display: "none", style: "pointer-events:none" });
    g.append(n.pin, s("title", {}, n.title || n.label || ""));
    gNodes.append(g);
  });

  /* mise en évidence */
  let hover = null, alpha = known ? 0.05 : 1, frozen = false, running = true, frames = 0;
  const focusId = () => hover || o.selected || null;
  function applyHighlight() {
    const f = focusId(); const hi = f && adj.has(f) ? new Set([f, ...adj.get(f)]) : null;
    nodes.forEach(n => {
      n.g.setAttribute("opacity", hi && !hi.has(n.id) ? 0.2 : 1);
      if (n.txt && o.labels !== "always") n.txt.setAttribute("display", hi && hi.has(n.id) || n.big ? null : "none");
      if (n.pin) n.pin.setAttribute("display", n.pinned ? null : "none");
    });
    links.forEach(l => {
      const on = !!f && (l.a === f || l.b === f);
      l.on = on;
      l.el.setAttribute("opacity", f && !on ? 0.12 : 1);
      l.el.setAttribute("stroke", on ? "var(--accent)" : (l.color || "var(--line)"));
      l.el.setAttribute("stroke-width", on ? 2.2 : (l.width || 1));
      if (o.linkLabels !== "always") l.txt.setAttribute("display", on ? null : "none");
    });
    buildPulses();
  }

  /* impulsions */
  let pulses = [];
  function buildPulses() {
    gPulses.innerHTML = ""; pulses = [];
    if (!P.pulses || !links.length) return;
    const act = links.filter(l => l.on);
    const pool = act.length ? act : links;
    const count = act.length ? act.length : Math.min(9, links.length);
    for (let i = 0; i < count; i++) {
      const l = act.length ? act[i] : pool[Math.floor(Math.random() * pool.length)];
      const dot = s("circle", { r: act.length ? 3.6 : 2.8, fill: act.length ? "var(--accent)" : "#ffd447", style: "filter:drop-shadow(0 0 4px #ffd447);pointer-events:none" });
      gPulses.append(dot);
      pulses.push({ l, t: Math.random(), v: 0.5 + Math.random() * 0.5, dot, act: !!act.length });
    }
  }

  /* interactions */
  const view = o.viewStore || { k: 1, x: 0, y: 0 };
  const applyView = () => world.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
  const toSvg = (ev) => { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; return pt.matrixTransform(svg.getScreenCTM().inverse()); };
  const toWorld = (ev) => { const q = toSvg(ev); return { x: (q.x - view.x) / view.k, y: (q.y - view.y) / view.k, sx: q.x, sy: q.y }; };
  let drag = null, pan = null;
  nodes.forEach(n => {
    n.g.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); svg.setPointerCapture(ev.pointerId); drag = { n, moved: false, sx: ev.clientX, sy: ev.clientY }; n.g.style.cursor = "grabbing"; alpha = Math.max(alpha, 0.5); });
    n.g.addEventListener("pointerenter", () => { if (!drag && !pan) { hover = n.id; applyHighlight(); } });
    n.g.addEventListener("pointerleave", () => { if (hover === n.id) { hover = null; applyHighlight(); } });
    n.g.addEventListener("dblclick", (ev) => { ev.stopPropagation(); n.pinned = !n.pinned; applyHighlight(); });
  });
  svg.addEventListener("pointerdown", (ev) => { if (drag) return; pan = { x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y }; svg.style.cursor = "grabbing"; svg.setPointerCapture(ev.pointerId); });
  svg.addEventListener("pointermove", (ev) => {
    if (drag) {
      if (Math.abs(ev.clientX - drag.sx) + Math.abs(ev.clientY - drag.sy) > 4) drag.moved = true;
      if (drag.moved) { const p = toWorld(ev); drag.n.x = p.x; drag.n.y = p.y; drag.n.vx = drag.n.vy = 0; alpha = Math.max(alpha, 0.45); if (frozen) draw(); }
    } else if (pan) {
      const sc = svg.getScreenCTM(); view.x = pan.vx + (ev.clientX - pan.x) / sc.a; view.y = pan.vy + (ev.clientY - pan.y) / sc.d; applyView();
    }
  });
  const endDrag = () => {
    if (drag) { const was = drag; drag = null; was.n.g.style.cursor = "grab"; if (!was.moved && o.onClick) o.onClick(was.n.id); }
    pan = null; svg.style.cursor = "";
  };
  svg.addEventListener("pointerup", endDrag); svg.addEventListener("pointercancel", endDrag);
  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault(); const q = toSvg(ev), k2 = clamp(view.k * Math.exp(-ev.deltaY * 0.0015), 0.35, 4);
    view.x = q.x - (q.x - view.x) * (k2 / view.k); view.y = q.y - (q.y - view.y) * (k2 / view.k); view.k = k2; applyView();
  }, { passive: false });

  /* physique */
  function physics() {
    const a = alpha, N = nodes.length;
    for (let i = 0; i < N; i++) {
      const A = nodes[i];
      for (let j = i + 1; j < N; j++) {
        const B = nodes[j]; let dx = A.x - B.x, dy = A.y - B.y, d2 = dx * dx + dy * dy;
        if (d2 > 160000) continue; if (d2 < 30) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 30; }
        const d = Math.sqrt(d2), f = (P.charge * a) / d2; dx /= d; dy /= d;
        A.vx += dx * f; A.vy += dy * f; B.vx -= dx * f; B.vy -= dy * f;
      }
    }
    for (const l of links) {
      let dx = l.B.x - l.A.x, dy = l.B.y - l.A.y; const d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = (d - (l.len || P.len)) * 0.03 * a;
      dx /= d; dy /= d; l.A.vx += dx * f; l.A.vy += dy * f; l.B.vx -= dx * f; l.B.vy -= dy * f;
    }
    for (const n of nodes) {
      if (n.hx !== undefined && P.home > 0) { n.vx += (n.hx - n.x) * P.home * (0.4 + a); n.vy += (n.hy - n.y) * P.home * (0.4 + a); }
      else { n.vx += (W / 2 - n.x) * P.gravity * a; n.vy += (H / 2 - n.y) * P.gravity * a; }
      if (drag && drag.n === n || n.pinned) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.78; n.vy *= 0.78;
      n.x = clamp(n.x + clamp(n.vx, -14, 14), -300, W + 300); n.y = clamp(n.y + clamp(n.vy, -14, 14), -300, H + 300);
    }
    alpha = Math.max(alpha * 0.992, 0.002);
  }
  const trim = (n, ux, uy) => n.w ? 1 / Math.max(Math.abs(ux) / (n.w / 2), Math.abs(uy) / (n.h / 2), 1e-6) : n.r + (o.arrows ? 3 : 0);
  function draw() {
    for (const n of nodes) { n.g.setAttribute("transform", `translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`); if (o.store) o.store.set(n.id, { x: n.x, y: n.y }); }
    for (const l of links) {
      let dx = l.B.x - l.A.x, dy = l.B.y - l.A.y; const d = Math.sqrt(dx * dx + dy * dy) + 0.01, ux = dx / d, uy = dy / d;
      const t1 = trim(l.A, ux, uy), t2 = trim(l.B, ux, uy);
      l.el.setAttribute("x1", (l.A.x + ux * t1).toFixed(1)); l.el.setAttribute("y1", (l.A.y + uy * t1).toFixed(1));
      l.el.setAttribute("x2", (l.B.x - ux * t2).toFixed(1)); l.el.setAttribute("y2", (l.B.y - uy * t2).toFixed(1));
      if (l.on || o.linkLabels === "always") { l.txt.setAttribute("x", ((l.A.x + l.B.x) / 2).toFixed(1)); l.txt.setAttribute("y", ((l.A.y + l.B.y) / 2 - 4).toFixed(1)); }
    }
  }
  let last = performance.now();
  function frame(now) {
    frames++;
    if (!svg.isConnected && frames > 5) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    if (running && !frozen && alpha > 0.003) { physics(); physics(); draw(); }
    else if (frames < 3) draw();
    for (const p of pulses) {
      p.t += p.v * dt * 0.8;
      if (p.t >= 1) { p.t = 0; if (!p.act) p.l = links[Math.floor(Math.random() * links.length)]; }
      const A = p.l.A, B = p.l.B;
      p.dot.setAttribute("cx", (A.x + (B.x - A.x) * p.t).toFixed(1)); p.dot.setAttribute("cy", (A.y + (B.y - A.y) * p.t).toFixed(1));
      p.dot.setAttribute("opacity", Math.sin(p.t * Math.PI).toFixed(2));
    }
    requestAnimationFrame(frame);
  }
  draw(); applyHighlight(); applyView();
  requestAnimationFrame(frame);

  const api = {
    reheat: (a) => { alpha = a ?? 0.8; frozen = false; },
    setCharge: (v) => { P.charge = v; alpha = Math.max(alpha, 0.5); },
    setLen: (v) => { P.len = v; alpha = Math.max(alpha, 0.5); },
    setPulses: (b) => { P.pulses = b; buildPulses(); },
    toggleFreeze: () => { frozen = !frozen; if (!frozen) alpha = Math.max(alpha, 0.4); return frozen; },
    shuffle: () => { nodes.forEach(n => { n.x = W / 2 + (Math.random() - 0.5) * W * 0.8; n.y = H / 2 + (Math.random() - 0.5) * H * 0.8; n.vx = n.vy = 0; n.pinned = false; }); frozen = false; alpha = 1; applyHighlight(); },
    recenter: () => { view.k = 1; view.x = 0; view.y = 0; applyView(); },
    unpin: () => { nodes.forEach(n => { n.pinned = false; }); applyHighlight(); alpha = Math.max(alpha, 0.4); },
    count: () => ({ nodes: nodes.length, links: links.length }),
  };
  return { svg, api };
}

/* barre de commandes commune des graphes vivants */
function liveControls(api, defaults) {
  const d = Object.assign({ charge: 3200, len: 80 }, defaults || {});
  const frz = h("button", { class: "btn" }, "⏸ Figer");
  frz.onclick = () => { frz.textContent = api.toggleFreeze() ? "▶ Relancer la physique" : "⏸ Figer"; };
  return h("div", { class: "row" },
    h("span", { class: "small" }, "Répulsion ", h("input", { type: "range", min: 600, max: 9000, step: 100, value: d.charge, style: { width: "110px" }, oninput: (e) => api.setCharge(+e.target.value) })),
    h("span", { class: "small" }, "Longueur des liens ", h("input", { type: "range", min: 30, max: 220, step: 5, value: d.len, style: { width: "110px" }, oninput: (e) => api.setLen(+e.target.value) })),
    h("label", { class: "small" }, h("input", { type: "checkbox", checked: true, onchange: (e) => api.setPulses(e.target.checked) }), " impulsions"),
    frz, h("button", { class: "btn", onclick: () => api.shuffle() }, "🔀 Mélanger"), h("button", { class: "btn", onclick: () => api.unpin() }, "📌 Tout libérer"), h("button", { class: "btn", onclick: () => api.recenter() }, "⌖ Recentrer"));
}
const LIVE_HELP = "Glissez un nœud : ses voisins suivent comme des neurones reliés par des ressorts · double-clic = épingler · molette = zoom · glisser le fond = déplacer la vue · survol = voir les relations.";
