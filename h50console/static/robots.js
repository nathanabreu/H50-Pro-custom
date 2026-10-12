// Tela "Robôs": conta Xiaomi (QR), lista da frota e menus de adicionar / editar / testar / remover.
// Usa os auxiliares do app.js (window.H50). Tokens nunca chegam aqui: a API só informa `has_token`.
(function () {
  const H = window.H50;
  const { $, el, api, toast, run, openSheet, confirmAction, chip } = H;

  const VIA = { cloud: "nuvem", lan: "rede local" };
  const TRANSPORT = {
    auto: "Automático: rede local, com a nuvem de reserva (recomendado)",
    lan: "Só rede local",
    cloud: "Só nuvem Xiaomi (para quando o app roda fora de casa)",
  };
  const label = (text, input) => el("label", {}, text, input);
  const field = (props) => el("input", { autocomplete: "off", ...props });

  // ---- cartão da conta Xiaomi ------------------------------------------------------------------------
  function cloudCard(host, st, onChange) {
    const out = [];
    if (st.state === "ok") {
      const logout = el("button", { textContent: "Sair da conta" });
      logout.onclick = () => confirmAction(
        "Desconectar a conta Xiaomi? O mapa, o histórico completo e o controle pela nuvem param; o controle pela rede local continua.",
        () => run("Sair", async () => { await api("POST", "/api/cloud/logout"); onChange(); }));
      out.push(el("div", { className: "bar" }, el("strong", { textContent: "Conectada" }),
        el("span", { className: "muted", textContent: `conta ${st.user_id} · servidor ${st.country || "?"}` }), logout));
    } else {
      const expired = st.state === "expired";
      out.push(el("p", { className: expired ? "warn" : "muted", textContent: expired
        ? "A sessão da conta expirou. Entre de novo para voltar a usar mapa, histórico e controle pela nuvem."
        : "Conecte com o QR code: abra o Xiaomi Home no celular (logado na sua conta, inclusive Google), toque em escanear e confirme. Nenhuma senha passa por este app." }));
      const start = el("button", { className: "primary", textContent: st.state === "waiting" ? "Gerar outro QR" : "Gerar QR code" });
      start.onclick = () => run("QR", async () => { await api("POST", "/api/cloud/qr"); onChange(); });
      out.push(el("div", { className: "bar" }, start, el("span", { className: "muted small",
        textContent: st.state === "waiting" ? "aguardando confirmação no celular…" : st.state === "error" ? `erro: ${st.error}` : "" })));
      if (st.state === "waiting" && st.qr) {
        out.push(el("div", { className: "center" },
          el("img", { src: st.qr, alt: "QR code de login Xiaomi", width: 220, height: 220 }),
          el("p", { className: "small muted" }, "Vale 5 minutos. ",
            el("a", { href: st.qr, target: "_blank", rel: "noopener", textContent: "Abrir em outra aba" }))));
      }
    }
    host.replaceChildren(...out);
  }

  // ---- lista da frota ------------------------------------------------------------------------------------
  let poll = null;
  async function robos() {
    const [list, st] = await Promise.all([
      H.reloadRobots(), api("GET", "/api/cloud/status").catch(() => ({ state: "none" })),
    ]);
    cloudCard($("#rb-cloud"), st, robos);
    clearTimeout(poll);                                     // com o QR na tela, confere a cada 3 s
    if (st.state === "waiting") poll = setTimeout(() => location.hash === "#robos" && robos(), 3000);
    const host = $("#t-robots");
    host.replaceChildren(...(list.length ? list.map(robotCard)
      : [el("p", { className: "muted", textContent: "Nenhum robô cadastrado ainda." })]));
    $("#robot-add").onclick = openAdd;
  }

  function robotCard(r) {
    const head = el("div", { className: "rb-head" });
    const title = el("div", {}, el("strong", { textContent: r.name }));
    if (r.id === H.robotId) title.append(el("span", { className: "pill-tag ok", textContent: "ativo" }));
    if (!r.supported) title.append(el("span", { className: "pill-tag warn", textContent: "modelo sem suporte verificado", title: r.model }));
    const state = r.online === false ? chip("sem resposta", "warn")
      : r.status_label ? chip(`${r.status_label}${r.battery != null ? " · " + r.battery + " %" : ""}`, r.active ? "on" : "") : chip("…");
    head.append(title, state);
    const via = r.online ? VIA[r.via] || r.via : null;
    const info = [r.model, r.ip || "sem IP", via && `via ${via}`, (TRANSPORT[r.transport] || r.transport).split(":")[0].split(" (")[0]]
      .filter(Boolean).join(" · ");
    return el("div", { className: "card rb-card" }, head, el("div", { className: "muted small", textContent: info }), actions(r));
  }

  function actions(r) {
    const mk = (text, fn) => { const b = el("button", { textContent: text }); b.onclick = fn; return b; };
    return el("div", { className: "rb-actions" },
      mk("Abrir", () => { H.setRobot(r.id); location.hash = "#inicio"; }),
      mk("Editar", () => openEdit(r)),
      mk("Testar", () => testRobot(r)),
      mk("Achar pelo DID", async () => {
        try {
          const x = await api("POST", `/api/robots/${r.id}/locate`);
          toast(x.changed ? `IP atualizado: ${x.ip} (${x.source})` : `IP confirmado: ${x.ip}`);
          robos();
        } catch (e) { toast(e.message, true); }
      }));
  }

  async function testRobot(r) {
    openSheet(`Testar ${r.name}`, [el("p", { className: "muted", textContent: "Testando…" })]);
    try {
      const t = await api("POST", `/api/robots/${r.id}/test`);
      const line = (text, x) => el("div", { className: "list-row" }, el("span", { textContent: text }),
        x ? chip(x.ok ? `ok · ${x.ms} ms` : `falhou: ${x.error || "sem resposta"}`, x.ok ? "on" : "warn") : chip("não configurado"));
      openSheet(`Testar ${r.name}`, [line(`Rede local${r.ip ? " (" + r.ip + ")" : ""}`, t.lan), line("Nuvem Xiaomi", t.cloud)]);
    } catch (e) {
      openSheet(`Testar ${r.name}`, [el("p", { className: "err", textContent: e.message })]);
    }
  }

  // ---- adicionar -------------------------------------------------------------------------------------------
  async function addRobot(body, btn) {
    if (btn) btn.disabled = true;
    try {
      const r = await api("POST", "/api/robots", body);
      $("#sheet").close();
      toast(`${r.name} adicionado`);
      if (r.warning) setTimeout(() => toast(r.warning), 2600);
      if (r.model_warning) setTimeout(() => toast(r.model_warning, true), 5200);
      await H.reloadRobots();
      if (H.robots.length === 1 || !H.robotId) H.setRobot(r.id);
      robos();
    } catch (e) {
      toast(e.message, true);
      if (btn) btn.disabled = false;
    }
  }

  function manualForm() {
    const f = {
      name: field({ placeholder: "Nome (opcional)", maxLength: 40 }),
      ip: field({ placeholder: "IP, ex.: 192.168.1.50 (pode ficar vazio se informar o DID)" }),
      token: field({ type: "password", placeholder: "32 caracteres hexadecimais", maxLength: 32 }),
      did: field({ placeholder: "DID (opcional; o app descobre)" }),
      transport: el("select", {}, ...Object.entries(TRANSPORT).map(([v, l]) => el("option", { value: v, textContent: l }))),
    };
    const go = el("button", { className: "primary", textContent: "Adicionar" });
    go.onclick = () => addRobot({ name: f.name.value, ip: f.ip.value, token: f.token.value, did: f.did.value,
      transport: f.transport.value }, go);
    const node = el("form", { className: "form-grid", onsubmit: (e) => { e.preventDefault(); go.click(); } },
      label("Nome", f.name), label("IP", f.ip), label("Token", f.token),
      label("DID", f.did), label("Como falar com o robô", f.transport), go);
    return { node, fill(o) { if (o.did) f.did.value = o.did; if (o.ip) f.ip.value = o.ip; if (o.name) f.name.value = o.name; f.token.focus(); } };
  }

  async function openAdd() {
    openSheet("Adicionar robô", [el("p", { className: "muted", textContent: "Procurando na conta Xiaomi e na rede local…" })]);
    let d;
    try { d = await api("GET", "/api/robots/discover"); } catch (e) { d = { devices: [], cloud: { state: "none", error: e.message } }; }
    const manual = manualForm();
    const body = [];
    if (d.cloud.state !== "ok") body.push(el("p", { className: "warn small",
      textContent: "Conta Xiaomi não conectada: sem ela não há token automático. Conecte a conta nesta tela ou use o cadastro manual." }));
    if (d.cloud.error) body.push(el("p", { className: "err small", textContent: d.cloud.error }));
    if (!d.devices.length) body.push(el("p", { className: "muted", textContent: "Nenhum aspirador encontrado." }));
    for (const x of d.devices) {
      const tags = [el("span", { className: "pill-tag", textContent: x.source === "conta" ? "conta Xiaomi" : "rede local" })];
      if (x.supported === false) tags.push(el("span", { className: "pill-tag warn", textContent: "modelo sem suporte verificado" }));
      const btn = el("button", { className: x.added || !x.has_token ? "" : "primary",
        textContent: x.added ? "Já cadastrado" : x.has_token ? "Adicionar" : "Informar token", disabled: !!x.added });
      btn.onclick = x.has_token ? () => addRobot({ did: x.did, name: x.name }, btn)
        : () => manual.fill({ did: x.did, ip: x.lan_ip, name: x.name });
      body.push(el("div", { className: "dev-row" },
        el("div", {}, el("div", {}, x.name || `Aparelho ${x.did}`, ...tags),
          el("div", { className: "muted small", textContent: [x.model, x.lan_ip || x.localip, `DID ${x.did}`].filter(Boolean).join(" · ") })),
        btn));
    }
    body.push(el("div", { className: "sheet-h", textContent: "Cadastro manual" }), manual.node);
    openSheet("Adicionar robô", body);
  }

  // ---- editar / remover --------------------------------------------------------------------------------------
  function openEdit(r) {
    const name = field({ value: r.name, maxLength: 40 });
    const ip = field({ value: r.ip || "", placeholder: "IP na rede local" });
    const token = field({ type: "password", placeholder: r.has_token ? "(mantido; digite para trocar)" : "32 caracteres hexadecimais" });
    const tr = el("select", {}, ...Object.entries(TRANSPORT).map(([v, l]) => el("option", { value: v, textContent: l, selected: v === r.transport })));
    const find = el("button", { textContent: "Achar pelo DID" });
    find.onclick = async () => {
      try { const x = await api("POST", `/api/robots/${r.id}/locate`); ip.value = x.ip; toast(`Achei: ${x.ip} (${x.source})`); }
      catch (e) { toast(e.message, true); }
    };
    const rm = el("button", { textContent: "Remover robô…" });
    rm.onclick = () => openRemove(r);
    openSheet(`Editar ${r.name}`, [el("form", { className: "form-grid", onsubmit: (e) => e.preventDefault() },
      label("Nome", name), label("IP", ip), find, label("Token", token), label("Como falar com o robô", tr),
      el("p", { className: "muted small", textContent: `DID ${r.did || "ainda desconhecido"} · modelo ${r.model}` }), rm)], {
      confirmLabel: "Salvar",
      confirm: async () => {
        const body = { name: name.value, ip: ip.value, transport: tr.value };
        if (token.value) body.token = token.value;
        await api("PUT", `/api/robots/${r.id}`, body);
        toast("Robô atualizado");
        await H.reloadRobots();
        robos();
      },
    });
  }

  function openRemove(r) {
    const chk = el("input", { type: "checkbox" });
    openSheet(`Remover ${r.name}?`, [
      el("p", { textContent: "O robô deixa de aparecer no app. Isso não afeta o robô nem a conta Xiaomi." }),
      el("label", { className: "set-row" }, chk, "Apagar também o histórico e o mapa guardados deste robô"),
    ], {
      confirmLabel: "Remover",
      confirm: async () => {
        await api("DELETE", `/api/robots/${r.id}?delete_data=${chk.checked ? 1 : 0}`);
        toast("Robô removido");
        await H.reloadRobots();
        robos();
      },
    });
  }

  H.views.robos = robos;
  H.renderCloudCard = cloudCard;
})();
