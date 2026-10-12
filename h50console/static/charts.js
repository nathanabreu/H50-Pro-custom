// Gráficos em SVG puro para os dashboards. Specs (skill dataviz): barras <= 24px com ponta
// arredondada de 4px, linha de 2px, grade hairline sólida, tooltip em toda marca, legenda com >= 2
// séries, cores por papel (CSS vars --s1..--s5, --s-other, --seq-*), texto sempre em tinta de texto.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  };
  const div = (cls, text) => Object.assign(document.createElement("div"), { className: cls, textContent: text ?? "" });

  // ---- tooltip único ---------------------------------------------------------------------
  let tip;
  function showTip(evt, rows) {
    if (!tip) { tip = div("viz-tip"); document.body.append(tip); }
    tip.replaceChildren();
    for (const r of rows) {
      const line = div("viz-tip-row");
      if (r.color) { const k = div("viz-key"); k.style.background = r.color; line.append(k); }
      const v = document.createElement("strong"); v.textContent = r.value;
      line.append(v, document.createTextNode(r.label ? " " + r.label : ""));
      tip.append(line);
    }
    tip.hidden = false;
    const x = (evt.clientX ?? 0) + 14, y = (evt.clientY ?? 0) + 14;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(x, innerWidth - w - 8) + "px";
    tip.style.top = Math.min(y, innerHeight - h - 8) + "px";
  }
  const hideTip = () => tip && (tip.hidden = true);

  function focusTip(el, rowsFn) {
    el.setAttribute("tabindex", "0");
    el.addEventListener("pointermove", (e) => showTip(e, rowsFn()));
    el.addEventListener("pointerleave", hideTip);
    el.addEventListener("focus", () => { const b = el.getBoundingClientRect(); showTip({ clientX: b.right, clientY: b.top }, rowsFn()); });
    el.addEventListener("blur", hideTip);
  }

  // tabela de dados (alívio de contraste / acessibilidade)
  function dataTable(headers, rows) {
    const d = document.createElement("details");
    d.className = "viz-table";
    d.append(Object.assign(document.createElement("summary"), { textContent: "Ver dados" }));
    const t = document.createElement("table");
    const hr = t.createTHead().insertRow();
    for (const h of headers) hr.append(Object.assign(document.createElement("th"), { textContent: h }));
    const tb = t.createTBody();
    for (const r of rows) { const tr = tb.insertRow(); for (const c of r) tr.insertCell().textContent = c; }
    d.append(t);
    return d;
  }

  const niceMax = (v) => {
    if (v <= 0) return 1;
    const p = 10 ** Math.floor(Math.log10(v)), n = v / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
  };
  const width = (el) => Math.max(280, el.clientWidth || 600);

  // barra com ponta arredondada (4px) e base reta, crescendo de baseY para cima
  function colPath(x, y, w, h) {
    const r = Math.min(4, w / 2, h);
    return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
  }
  function barPath(x, y, w, h) {  // horizontal, cresce para a direita
    const r = Math.min(4, h / 2, w);
    return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`;
  }

  // ---- colunas (série única ao longo de categorias/dias) ------------------------------------
  function columns(el, data, { format = String, labelEvery = 1, height = 200, color = "var(--s1)", unit = "" } = {}) {
    const W = width(el), H = height, m = { t: 12, r: 8, b: 26, l: 40 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
    for (let i = 0; i <= 4; i++) {
      const y = m.t + ih - (ih * i) / 4;
      s.append(svg("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: "viz-grid" }));
      const t = svg("text", { x: m.l - 6, y: y + 4, "text-anchor": "end", class: "viz-axis" });
      t.textContent = format((max * i) / 4);
      s.append(t);
    }
    const band = iw / data.length, bw = Math.min(24, band * 0.7);
    data.forEach((d, i) => {
      const x = m.l + band * i + (band - bw) / 2;
      const h = (ih * d.value) / max;
      const g = svg("g", { class: "viz-mark" });
      g.append(svg("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, fill: "transparent" }));  // alvo
      if (h > 0) g.append(svg("path", { d: colPath(x, m.t + ih - h, bw, h), fill: color }));
      focusTip(g, () => [{ value: format(d.value) + unit, label: d.tip || d.label }]);
      s.append(g);
      if (i % labelEvery === 0 || i === data.length - 1) {
        const t = svg("text", { x: m.l + band * i + band / 2, y: H - 8, "text-anchor": "middle", class: "viz-axis" });
        t.textContent = d.label;
        s.append(t);
      }
    });
    s.append(svg("line", { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, class: "viz-base" }));
    el.replaceChildren(s, dataTable(["", "valor"], data.map((d) => [d.tip || d.label, format(d.value) + unit])));
  }

  // ---- barras horizontais (ranking) ---------------------------------------------------------
  function bars(el, data, { format = String, color = "var(--s1)", unit = "" } = {}) {
    const W = width(el), row = 30, m = { t: 4, r: 48, b: 4, l: Math.min(200, W * 0.4) };
    const H = m.t + m.b + row * Math.max(1, data.length), iw = W - m.l - m.r;
    const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
    data.forEach((d, i) => {
      const y = m.t + row * i, bh = 18, w = (iw * d.value) / max;
      const g = svg("g", { class: "viz-mark" });
      g.append(svg("rect", { x: 0, y, width: W, height: row, fill: "transparent" }));
      const lbl = svg("text", { x: m.l - 8, y: y + row / 2 + 4, "text-anchor": "end", class: "viz-label" });
      lbl.textContent = d.label;
      g.append(lbl);
      if (w > 0) g.append(svg("path", { d: barPath(m.l, y + (row - bh) / 2, w, bh), fill: color }));
      const val = svg("text", { x: m.l + w + 6, y: y + row / 2 + 4, class: "viz-value" });
      val.textContent = format(d.value) + unit;
      g.append(val);
      focusTip(g, () => [{ value: format(d.value) + unit, label: d.label }]);
      s.append(g);
    });
    s.append(svg("line", { x1: m.l, x2: m.l, y1: m.t, y2: H - m.b, class: "viz-base" }));
    el.replaceChildren(s);
    if (!data.length) el.replaceChildren(div("muted", "sem dados no período"));
  }

  // ---- linha temporal com cruz (bateria) ------------------------------------------------------
  function line(el, points, { x0, x1, yMax = 100, format = String, unit = "", height = 200, color = "var(--s1)", name = "" } = {}) {
    if (!points.length) return el.replaceChildren(div("muted", "sem dados no período"));
    const W = width(el), H = height, m = { t: 12, r: 12, b: 26, l: 40 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const t0 = +new Date(x0), t1 = +new Date(x1);
    const X = (t) => m.l + (iw * (+new Date(t) - t0)) / (t1 - t0 || 1);
    const Y = (v) => m.t + ih - (ih * v) / yMax;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
    for (let i = 0; i <= 4; i++) {
      const y = m.t + ih - (ih * i) / 4;
      s.append(svg("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: "viz-grid" }));
      const t = svg("text", { x: m.l - 6, y: y + 4, "text-anchor": "end", class: "viz-axis" });
      t.textContent = format((yMax * i) / 4);
      s.append(t);
    }
    timeTicks(s, t0, t1, X, H - 8);
    // degraus: o valor vale até a próxima mudança
    let d = "";
    points.forEach((p, i) => {
      const x = X(p.t), y = Y(p.v);
      d += i ? ` H${x} V${y}` : `M${x},${y}`;
    });
    s.append(svg("path", { d: d + ` V${m.t + ih} H${X(points[0].t)} Z`, fill: color, opacity: 0.1 }));
    s.append(svg("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = points[points.length - 1];
    s.append(svg("circle", { cx: X(last.t), cy: Y(last.v), r: 4, fill: color, stroke: "var(--panel)", "stroke-width": 2 }));
    const endLbl = svg("text", { x: X(last.t) - 8, y: Y(last.v) - 8, "text-anchor": "end", class: "viz-value" });
    endLbl.textContent = format(last.v) + unit;
    s.append(endLbl);
    // cruz + tooltip
    const cross = svg("line", { y1: m.t, y2: m.t + ih, class: "viz-cross", visibility: "hidden" });
    const hit = svg("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent", tabindex: 0 });
    s.append(cross, hit);
    const at = (t) => { let v = points[0]; for (const p of points) { if (+new Date(p.t) <= t) v = p; else break; } return v; };
    hit.addEventListener("pointermove", (e) => {
      const r = s.getBoundingClientRect(), x = ((e.clientX - r.left) / r.width) * W;
      const t = t0 + ((x - m.l) / iw) * (t1 - t0), p = at(t);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      showTip(e, [{ value: format(p.v) + unit, label: name, color }, { value: fmtTime(t) }]);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    el.replaceChildren(s, dataTable(["quando", name], points.map((p) => [fmtTime(p.t), format(p.v) + unit])));
  }

  // ---- faixa de status (segmentos categóricos no tempo) ---------------------------------------
  function band(el, segments, groups, { x0, x1, colors, height = 44 } = {}) {
    const W = width(el), m = { t: 4, r: 12, b: 24, l: 40 }, H = height + m.t + m.b, iw = W - m.l - m.r;
    const t0 = +new Date(x0), t1 = +new Date(x1);
    const X = (t) => m.l + (iw * (Math.max(+new Date(t), t0) - t0)) / (t1 - t0 || 1);
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
    s.append(svg("rect", { x: m.l, y: m.t, width: iw, height, class: "viz-empty", rx: 4 }));
    for (const seg of segments) {
      const x = X(seg.start), w = Math.max(1, X(seg.end) - x - 2);   // 2px de vão entre segmentos
      const g = svg("g", { class: "viz-mark" });
      g.append(svg("rect", { x, y: m.t, width: w, height, fill: colors[seg.group], rx: 2 }));
      focusTip(g, () => [{ value: seg.label, label: seg.group, color: colors[seg.group] },
        { value: `${fmtTime(seg.start)} → ${fmtTime(seg.end)}`, label: dur(seg.start, seg.end) }]);
      s.append(g);
    }
    timeTicks(s, t0, t1, (t) => m.l + (iw * (t - t0)) / (t1 - t0), H - 6);
    el.replaceChildren(s, legend(groups.map((g) => ({ label: g, color: colors[g] }))),
      dataTable(["início", "fim", "status", "grupo"], segments.map((x) => [fmtTime(x.start), fmtTime(x.end), x.label, x.group])));
  }

  // ---- mapa de calor dia × hora (sequencial, um matiz) ----------------------------------------
  function heat(el, matrix, rowsLabels, { unit = "limpezas" } = {}) {
    const W = width(el), m = { t: 4, r: 4, b: 22, l: 36 }, cols = 24, rows = matrix.length;
    const cw = (W - m.l - m.r) / cols, ch = 22, H = m.t + m.b + ch * rows;
    const max = Math.max(1, ...matrix.flat());
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img" });
    matrix.forEach((row, r) => {
      const t = svg("text", { x: m.l - 6, y: m.t + ch * r + ch / 2 + 4, "text-anchor": "end", class: "viz-axis" });
      t.textContent = rowsLabels[r];
      s.append(t);
      row.forEach((v, c) => {
        const g = svg("g", { class: "viz-mark" });
        const rect = svg("rect", { x: m.l + cw * c + 1, y: m.t + ch * r + 1, width: cw - 2, height: ch - 2, rx: 2 });
        if (v) { rect.setAttribute("fill", "var(--seq-hi)"); rect.setAttribute("fill-opacity", 0.18 + 0.82 * (v / max)); }
        else rect.setAttribute("class", "viz-empty");
        g.append(rect);
        focusTip(g, () => [{ value: `${v} ${unit}`, label: `${rowsLabels[r]} ${String(c).padStart(2, "0")}h` }]);
        s.append(g);
      });
    });
    for (let c = 0; c < cols; c += 3) {
      const t = svg("text", { x: m.l + cw * c + cw / 2, y: H - 6, "text-anchor": "middle", class: "viz-axis" });
      t.textContent = `${c}h`;
      s.append(t);
    }
    el.replaceChildren(s);
  }

  // ---- peças ------------------------------------------------------------------------------------
  function legend(items) {
    const l = div("viz-legend");
    for (const it of items) {
      const i = div("viz-legend-item");
      const k = div("viz-swatch"); k.style.background = it.color;
      i.append(k, document.createTextNode(it.label));
      l.append(i);
    }
    return l;
  }
  function tiles(el, items) {
    el.replaceChildren(...items.map((it) => {
      const t = div("viz-tile");
      t.append(div("viz-tile-label", it.label), div("viz-tile-value", it.value));
      if (it.sub) t.append(div("viz-tile-sub", it.sub));
      return t;
    }));
  }
  function timeTicks(s, t0, t1, X, y) {
    const span = t1 - t0, hour = 3600e3;
    const step = span <= 6 * hour ? hour : span <= 26 * hour ? 3 * hour : span <= 8 * 86400e3 ? 86400e3 : 7 * 86400e3;
    const first = Math.ceil(t0 / step) * step;
    for (let t = first; t <= t1; t += step) {
      const lbl = svg("text", { x: X(t), y, "text-anchor": "middle", class: "viz-axis" });
      lbl.textContent = step >= 86400e3 ? new Date(t).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })
        : new Date(t).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      s.append(lbl);
    }
  }
  const fmtTime = (t) => new Date(t).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const dur = (a, b) => {
    const m = Math.round((new Date(b) - new Date(a)) / 60000);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };

  window.Charts = { columns, bars, line, band, heat, tiles, legend, dur };
})();
