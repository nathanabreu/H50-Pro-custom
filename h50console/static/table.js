// Tabela filtrável e ordenável (JS puro). Uso:
//   Table.render(el, columns, rows, {rowClass, footer, group})
// columns: [{key, label, render(row) -> string|Node, num, filter=true, sort=true}]
// O estado (filtros e ordenação) fica guardado no próprio elemento entre re-renderizações.
(function () {
  function text(v) { return v === null || v === undefined ? "" : String(v); }

  function cell(col, row) {
    const v = col.render ? col.render(row) : row[col.key];
    return v instanceof Node ? v : document.createTextNode(text(v));
  }

  function sortValue(col, row) {
    const v = col.sortValue ? col.sortValue(row) : row[col.key];
    return v === null || v === undefined ? "" : v;
  }

  function render(el, columns, rows, opts = {}) {
    const st = el._tbl || (el._tbl = { filters: {}, sort: opts.sort || null, desc: !!opts.desc });
    let data = rows.filter(r => columns.every(c => {
      const f = st.filters[c.key];
      if (!f) return true;
      const v = c.render ? c.render(r) : r[c.key];
      const s = v instanceof Node ? v.textContent : text(v);
      return s.toLowerCase().includes(f.toLowerCase());
    }));
    if (st.sort) {
      const col = columns.find(c => c.key === st.sort);
      if (col) data = data.slice().sort((a, b) => {
        const x = sortValue(col, a), y = sortValue(col, b);
        const r = typeof x === "number" && typeof y === "number" ? x - y : text(x).localeCompare(text(y), "pt-BR", { numeric: true });
        return st.desc ? -r : r;
      });
    }

    const focused = document.activeElement && el.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const table = document.createElement("table");
    const thead = table.createTHead();
    const hr = thead.insertRow();
    for (const c of columns) {
      const th = document.createElement("th");
      th.textContent = c.label;
      if (c.num) th.style.textAlign = "right";
      if (c.sort !== false) {
        if (st.sort === c.key) th.className = "sorted" + (st.desc ? " desc" : "");
        th.onclick = () => { st.desc = st.sort === c.key ? !st.desc : false; st.sort = c.key; render(el, columns, rows, opts); };
      }
      hr.appendChild(th);
    }
    if (opts.filters !== false) {
      const fr = thead.insertRow();
      fr.className = "filters";
      for (const c of columns) {
        const th = document.createElement("th");
        if (c.filter !== false) {
          const inp = document.createElement("input");
          inp.placeholder = "filtrar";
          inp.dataset.key = c.key;
          inp.value = st.filters[c.key] || "";
          inp.oninput = () => { st.filters[c.key] = inp.value; render(el, columns, rows, opts); };
          th.appendChild(inp);
        }
        fr.appendChild(th);
      }
    }
    const tb = table.createTBody();
    let lastGroup;
    for (const r of data) {
      if (opts.group && !st.sort) {
        const g = opts.group(r);
        if (g !== lastGroup) {
          const gr = tb.insertRow();
          gr.className = "group";
          const td = gr.insertCell();
          td.colSpan = columns.length;
          td.textContent = g;
          lastGroup = g;
        }
      }
      const tr = tb.insertRow();
      if (opts.rowClass) tr.className = opts.rowClass(r) || "";
      for (const c of columns) {
        const td = tr.insertCell();
        if (c.num) td.className = "num";
        td.appendChild(cell(c, r));
      }
    }
    if (!data.length) {
      const td = tb.insertRow().insertCell();
      td.colSpan = columns.length;
      td.className = "muted";
      td.textContent = rows.length ? "nada corresponde ao filtro" : "sem dados";
    }
    if (opts.footer) {
      const tf = table.createTFoot().insertRow();
      const vals = opts.footer(data);
      for (const c of columns) {
        const td = tf.insertCell();
        if (c.num) td.className = "num";
        td.textContent = text(vals[c.key]);
      }
    }
    const wrap = document.createElement("div");
    wrap.className = "tbl-wrap";
    wrap.appendChild(table);
    el.replaceChildren(wrap);
    if (focused) {
      const inp = el.querySelector(`input[data-key="${focused}"]`);
      if (inp) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    }
  }

  window.Table = { render };
})();
