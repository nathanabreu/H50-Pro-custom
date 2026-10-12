// Tela "Manutenção": espaço, retenção, otimização, backup/restauração, exportação, logs e diagnóstico.
(function () {
  const H = window.H50;
  const { $, el, api, toast, run, openSheet, confirmAction } = H;

  const bytes = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`;
  const upt = (s) => s >= 86400 ? `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h` : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min` : `${Math.floor(s / 60)} min`;
  const row = (label, value) => el("div", { className: "set-row" }, el("span", { className: "muted", textContent: label }), el("span", { textContent: value }));

  async function manutencao() {
    const st = await api("GET", "/api/maintenance/status");
    $("#mt-about").replaceChildren(
      row("Versão", st.version), row("Python", st.python), row("Sistema", st.platform),
      row("No ar há", upt(st.uptime_s)), row("Pasta de dados", st.data_dir), row("Espaço usado", bytes(st.data_bytes)),
      row("Conta Xiaomi", { ok: "conectada", none: "não conectada", expired: "sessão expirada", waiting: "aguardando QR" }[st.cloud] || st.cloud));

    Table.render($("#mt-robots"), [
      { key: "name", label: "Robô" },
      { key: "db_bytes", label: "Banco", num: true, render: (r) => bytes(r.db_bytes), sortValue: (r) => r.db_bytes },
      { key: "changes", label: "Mudanças", num: true, render: (r) => r.rows.prop_change.toLocaleString("pt-BR"), sortValue: (r) => r.rows.prop_change },
      { key: "cleanings", label: "Limpezas", num: true, render: (r) => r.rows.cleaning_record },
      { key: "commands", label: "Comandos", num: true, render: (r) => r.rows.command_log },
      { key: "oldest", label: "Dados desde", render: (r) => r.oldest_change ? new Date(r.oldest_change).toLocaleDateString("pt-BR") : "—" },
    ], st.robots, { filters: false });

    $("#mt-days").value = st.retention_days;
    $("#mt-days-save").onclick = () => run("Retenção", async () => {
      await api("PUT", "/api/maintenance/retention", { days: Number($("#mt-days").value) });
      manutencao();
    });
    $("#mt-purge").onclick = () => confirmAction(
      `Apagar mudanças de propriedades com mais de ${st.retention_days} dias? O histórico de limpezas, os consumíveis e as falhas não são apagados.`,
      () => run("Limpar", async () => {
        const r = await api("POST", "/api/maintenance/purge");
        toast(`${r.reduce((a, x) => a + x.deleted, 0)} registro(s) apagado(s)`);
        manutencao();
      }));
    $("#mt-opt").onclick = () => run("Otimizar", async () => {
      const r = await api("POST", "/api/maintenance/optimize");
      toast(r.map((x) => `${bytes(x.before)} → ${bytes(x.after)}`).join(" · "));
      manutencao();
    });

    // ---- backup ----------------------------------------------------------------------------------
    $("#mt-bk-form").onsubmit = (e) => { e.preventDefault(); $("#mt-backup").onclick(); };
    $("#mt-rs-form").onsubmit = (e) => { e.preventDefault(); $("#mt-restore").onclick(); };
    $("#mt-backup").onclick = async () => {
      const pw = $("#mt-bk-pw").value;
      if (pw.length < 8) return toast("Use uma senha de backup com pelo menos 8 caracteres", true);
      await run("Backup", async () => {
        await H.download("POST", "/api/backup/create", { passphrase: pw, include_cloud: $("#mt-bk-cloud").checked });
      });
    };
    $("#mt-restore").onclick = () => {
      const f = $("#mt-rs-file").files[0], pw = $("#mt-rs-pw").value;
      if (!f) return toast("Escolha o arquivo .h50bak", true);
      confirmAction("Restaurar substitui os dados atuais (robôs, históricos, senha do painel e sessão da nuvem) pelos do backup. Você precisará entrar de novo.",
        () => run("Restaurar", async () => {
          const r = await fetch("/api/backup/restore", { method: "POST", headers: { "X-H50": "1", "X-H50-Passphrase": pw }, body: f });
          const d = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
          toast(`Restaurado: ${d.robots.length} robô(s)`);
          setTimeout(() => { location.href = "/"; }, 1200);
        }));
    };

    // ---- exportar, logs, diagnóstico ----------------------------------------------------------------
    $("#mt-csv").onclick = () => run("Exportar", () => H.download("GET", "/api/export/cleanings.csv"));
    $("#mt-support").onclick = () => run("Diagnóstico", () => H.download("GET", "/api/maintenance/support"));
    $("#mt-logs-refresh").onclick = loadLogs;
    await loadLogs();
  }

  async function loadLogs() {
    const logs = await api("GET", "/api/maintenance/logs?n=200");
    $("#mt-logs").textContent = logs.map((l) => `${l.ts} ${l.level.padEnd(7)} ${l.name}: ${l.msg}`).join("\n") || "(sem mensagens ainda)";
  }

  H.views.manutencao = manutencao;
})();
