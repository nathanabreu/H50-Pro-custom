// Cartão "Notificações" (em Configurações): canais ntfy / Telegram / webhook e os eventos de cada um.
// Os segredos (tópico, token, URL) nunca voltam inteiros da API; campo em branco = manter o que já existe.
(function () {
  const H = window.H50;
  const { $, el, api, toast, openSheet, chip } = H;

  const HELP = {
    ntfy: "Instale o app ntfy no celular, inscreva-se em um tópico difícil de adivinhar e cole aqui o endereço completo (ex.: https://ntfy.sh/meu-topico-secreto-123).",
    telegram: "Crie um bot com o @BotFather (ele dá o token) e descubra o seu chat_id (por exemplo com o @userinfobot).",
    webhook: "Recebe um POST em JSON: {event, robot, title, text, ts}. Serve para integrar com Home Assistant, n8n etc.",
  };
  const btn = (text, fn, cls = "") => { const b = el("button", { textContent: text, className: cls }); b.onclick = fn; return b; };
  const label = (text, input) => el("label", {}, text, input);

  async function render() {
    const host = $("#notify-card");
    if (!host) return;
    let d;
    try { d = await api("GET", "/api/notify"); } catch { host.hidden = true; return; }
    host.hidden = false;
    const rows = d.channels.map((c) => el("div", { className: "list-row" },
      el("div", {}, el("div", {}, c.name, c.enabled ? "" : el("span", { className: "pill-tag warn", textContent: "desligado" })),
        el("div", { className: "muted small", textContent: `${d.types[c.type]} · ${c.events.length} evento(s) · ${c.url_hint || (c.has_token ? "token guardado" : "")}` })),
      el("div", { className: "rb-actions" },
        btn("Testar", () => test(c)), btn("Editar", () => openEdit(c, d)))));
    host.replaceChildren(
      el("div", { className: "card-label", textContent: "Notificações" }),
      ...(rows.length ? rows : [el("p", { className: "muted small", textContent: "Nenhum canal ainda. Adicione um para receber avisos (limpeza concluída, falhas, tanque cheio…) fora de casa." })]),
      el("div", { className: "bar" }, btn("Adicionar canal", () => openEdit(null, d), "primary")));
  }

  async function test(c) {
    try {
      const r = await api("POST", "/api/notify/test", { id: c.id });
      toast(r.ok ? `Enviado para ${c.name}` : `Falhou: ${r.error}`, !r.ok);
    } catch (e) { toast(e.message, true); }
  }

  function openEdit(c, d) {
    const isNew = !c;
    c = c || { type: "ntfy", name: "", enabled: true, events: ["cleaning_done", "fault", "offline"] };
    const f = {
      name: el("input", { value: c.name, maxLength: 40, placeholder: "Nome (ex.: Meu celular)" }),
      type: el("select", {}, ...Object.entries(d.types).map(([v, l]) => el("option", { value: v, textContent: l, selected: v === c.type }))),
      url: el("input", { type: "password", autocomplete: "off", placeholder: c.url_hint ? `(mantido: ${c.url_hint})` : "https://…" }),
      token: el("input", { type: "password", autocomplete: "off", placeholder: c.has_token ? "(mantido)" : "token do bot" }),
      chat: el("input", { autocomplete: "off", placeholder: "chat_id", value: c.chat_id || "" }),
      enabled: el("input", { type: "checkbox", checked: c.enabled }),
    };
    const help = el("p", { className: "muted small" });
    const urlBox = label("Endereço", f.url), tokBox = label("Token do bot", f.token), chatBox = label("chat_id", f.chat);
    const sync = () => {
      help.textContent = HELP[f.type.value];
      urlBox.hidden = f.type.value === "telegram";
      tokBox.hidden = chatBox.hidden = f.type.value !== "telegram";
    };
    f.type.onchange = sync;
    sync();
    const evs = Object.entries(d.events).map(([id, text]) => {
      const cb = el("input", { type: "checkbox", checked: c.events.includes(id), value: id });
      return { id, cb, node: el("label", { className: "set-row" }, el("span", { textContent: text }), cb) };
    });
    const form = el("form", { className: "form-grid", onsubmit: (e) => e.preventDefault() },
      label("Nome", f.name), label("Tipo", f.type), urlBox, tokBox, chatBox, help,
      el("div", { className: "sheet-h", textContent: "Avisar quando" }), ...evs.map((e) => e.node),
      el("label", { className: "set-row" }, el("span", { textContent: "Canal ligado" }), f.enabled));
    const body = [form];
    if (!isNew) body.push(btn("Remover canal", () => remove(c, d)));
    openSheet(isNew ? "Novo canal" : `Editar ${c.name}`, body, {
      confirmLabel: "Salvar",
      confirm: async () => {
        const ch = { id: c.id, name: f.name.value, type: f.type.value, enabled: f.enabled.checked,
          events: evs.filter((e) => e.cb.checked).map((e) => e.id), chat_id: f.chat.value };
        if (f.url.value) ch.url = f.url.value;
        if (f.token.value) ch.token = f.token.value;
        const others = d.channels.filter((x) => x.id !== c.id);
        await api("PUT", "/api/notify", { channels: [...others, ch] });
        toast("Canal salvo");
        render();
      },
    });
  }

  function remove(c, d) {
    api("PUT", "/api/notify", { channels: d.channels.filter((x) => x.id !== c.id) })
      .then(() => { $("#sheet").close(); toast("Canal removido"); render(); })
      .catch((e) => toast(e.message, true));
  }

  H.renderNotify = render;
})();
