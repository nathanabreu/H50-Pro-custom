// Editor de mapa em RASCUNHO: monta paredes virtuais e móveis sobre o mapa e mostra o resultado e as mudanças.
// Nada é gravado no robô (o servidor responde 501 em /api/map/edit/save até o formato de escrita ser validado).
(function () {
  const H = window.H50;
  const { $, el, api, toast, run, openSheet } = H;

  const FURN = [[1220, "Sofá"], [1400, "Mesa"], [1740, "Liteira"]];
  const TOOLS = [["wall", "Parede virtual"], ["furniture", "Móvel"], ["erase", "Apagar"]];

  // menor distância (mm) de um ponto a um segmento
  function distSeg(px, py, [x1, y1, x2, y2]) {
    const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }
  function inPoly(px, py, p) {            // 4 cantos [x1,y1,...]
    let inside = false;
    for (let i = 0, j = p.length - 2; i < p.length; j = i, i += 2) {
      if ((p[i + 1] > py) !== (p[j + 1] > py) && px < ((p[j] - p[i]) * (py - p[i + 1])) / (p[j + 1] - p[i + 1]) + p[i]) inside = !inside;
    }
    return inside;
  }

  async function openEditor() {
    const state = { tool: "wall", furn: 1400, ops: [], start: null, map: null, busy: false };
    const box = el("div", { textContent: "Carregando…", "data-maxh": "0.5" });
    const toolBar = el("div", { className: "me-tools" });
    const hint = el("p", { className: "muted small" });
    const changes = el("ul", { className: "me-changes" });
    const furnPick = el("select", { "aria-label": "Tipo de móvel" }, ...FURN.map(([v, n]) => el("option", { value: v, textContent: n })));
    furnPick.value = state.furn;
    furnPick.onchange = () => { state.furn = +furnPick.value; };

    const hints = {
      wall: () => state.start ? "Toque no ponto final da parede." : "Toque no ponto inicial da parede.",
      furniture: () => "Toque onde o móvel deve ficar (tamanho padrão do tipo).",
      erase: () => "Toque numa parede ou móvel para apagar.",
    };

    async function refresh() {
      if (state.busy) return;
      state.busy = true;
      try {
        const d = await api("POST", "/api/map/edit/preview", { ops: state.ops });
        state.map = d.map;
        changes.replaceChildren(...(d.changes.length ? d.changes : ["Sem mudanças ainda."]).map((t) => el("li", { textContent: t })));
      } catch (e) {
        state.ops.pop();                  // a última operação foi recusada: desfaz e mostra o motivo
        state.start = null;
        toast(e.message, true);
        if (!state.map) { box.textContent = e.message; return; }
      } finally { state.busy = false; }
      draw();
    }

    function draw() {
      box.textContent = "";
      hint.textContent = hints[state.tool]();
      for (const b of toolBar.querySelectorAll("button[data-tool]")) b.classList.toggle("on", b.dataset.tool === state.tool);
      furnPick.hidden = state.tool !== "furniture";
      MapView.render(box, { ...state.map, _grid: undefined, robot: null, path: [] }, { onPoint: onPoint, marks: state.start ? [state.start] : [] });
    }

    function push(op) { state.ops.push(op); return refresh(); }

    function onPoint(x, y) {
      const m = state.map;
      if (state.tool === "wall") {
        if (!state.start) { state.start = [x, y]; return draw(); }
        const [x1, y1] = state.start;
        state.start = null;
        return push({ op: "add_wall", x1, y1, x2: x, y2: y });
      }
      if (state.tool === "furniture") return push({ op: "add_furniture", type: state.furn, cx: x, cy: y });
      // apagar: o móvel sob o ponto, senão a parede mais próxima (até 30 cm)
      const f = m.furniture.find((q) => inPoly(x, y, q.pos));
      if (f) return push({ op: "remove_furniture", id: f.id });
      let best = null;
      m.walls.forEach((w, i) => { const d = distSeg(x, y, w); if (d < 300 && (!best || d < best.d)) best = { d, id: m.wall_ids[i] }; });
      if (best) return push({ op: "remove_wall", id: best.id });
      toast("Nada para apagar aí");
    }

    for (const [id, label] of TOOLS) {
      const b = el("button", { textContent: label, "data-tool": id });
      b.onclick = () => { state.tool = id; state.start = null; draw(); };
      toolBar.append(b);
    }
    toolBar.append(furnPick);
    const undo = el("button", { textContent: "Desfazer" });
    undo.onclick = () => { if (!state.ops.length) return; state.ops.pop(); state.start = null; refresh(); };
    const clear = el("button", { textContent: "Limpar rascunho" });
    clear.onclick = () => { state.ops = []; state.start = null; refresh(); };
    const backup = el("button", { textContent: "Fazer backup do mapa" });
    backup.onclick = () => run("Backup do mapa", async () => {
      const r = await api("POST", "/api/map/backup");
      toast(`Backup salvo: ${r.name} (${r.backups.length} guardado(s))`);
    });
    const save = el("button", { className: "primary", textContent: "Salvar no robô", disabled: true,
      title: "Ainda não: o formato de escrita no robô precisa ser validado com o robô na base (veja o backlog)." });

    openSheet("Editar mapa (rascunho)", [
      el("p", { className: "muted small", textContent: "Monte móveis e paredes virtuais e veja o resultado. Nada é enviado ao robô: " +
        "a gravação ainda depende de testes supervisionados. Use para planejar." }),
      toolBar, hint, box,
      el("div", { className: "bar" }, undo, clear, backup, save),
      el("div", { className: "card-label", textContent: "Mudanças do rascunho" }), changes,
    ]);
    await refresh();
  }

  window.addEventListener("load", () => {
    const b = $("#map-edit");
    if (!b) return;
    b.hidden = false;
    b.onclick = () => openEditor().catch((e) => toast(e.message, true));
    if (new URLSearchParams(location.search).has("edit")) setTimeout(b.onclick, 1500);     // ?edit abre direto (capturas de tela)
  });
})();
