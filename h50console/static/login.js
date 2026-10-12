// Tela de login e de primeiro acesso (sem dependências; carregada sem sessão).
(function () {
  const $ = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  // só aceita voltar para um caminho DENTRO do app (evita redirecionamento aberto)
  const next = (() => {
    const n = params.get("next") || "/";
    return n.startsWith("/") && !n.startsWith("//") && !n.includes("\\") ? n : "/";
  })();

  async function call(path, body) {
    const r = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "X-H50": "1", ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data.error || `erro ${r.status}`), { status: r.status });
    return data;
  }

  async function init() {
    const st = await call("/api/auth/status");
    if (st.authenticated && !st.setup_required) { location.replace(next); return; }
    const setup = st.setup_required;
    $("#sub").textContent = setup
      ? "Primeiro acesso: crie a senha do painel. O código aparece no console onde o app foi iniciado."
      : "Digite a senha para continuar.";
    $("#title").textContent = setup ? "Criar senha" : "Entrar";
    $("#go").textContent = setup ? "Criar senha e entrar" : "Entrar";
    $("#code-box").hidden = !setup;
    $("#pw2-box").hidden = !setup;
    $("#pw").autocomplete = setup ? "new-password" : "current-password";
    $("#form").hidden = false;
    (setup ? $("#code") : $("#pw")).focus();

    $("#form").onsubmit = async (e) => {
      e.preventDefault();
      $("#err").textContent = "";
      if (setup && $("#pw").value !== $("#pw2").value) { $("#err").textContent = "As senhas não são iguais."; return; }
      $("#go").disabled = true;
      try {
        await call(setup ? "/api/auth/setup" : "/api/auth/login",
          setup ? { code: $("#code").value, password: $("#pw").value } : { password: $("#pw").value });
        location.replace(next);
      } catch (err) {
        $("#err").textContent = err.message;
        $("#go").disabled = false;
        $("#pw").select();
      }
    };
  }
  init().catch((e) => { $("#sub").textContent = "Não foi possível falar com o servidor: " + e.message; });
})();
