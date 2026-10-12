// Service worker: o app abre mesmo sem rede (mostra a última tela) e pode ser instalado no celular.
// A API nunca passa por aqui: dados do robô vêm sempre da rede. Páginas e scripts: rede primeiro, cache de reserva.
const CACHE = "h50-shell-v2";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  event.respondWith((async () => {
    try {
      const res = await fetch(req);
      // só guarda respostas normais (sem redirecionamento para o login, que não pode ser servido do cache)
      if (res.ok && !res.redirected) (await caches.open(CACHE)).put(req, res.clone());
      return res;
    } catch {
      const hit = await caches.match(req);
      if (hit) return hit;
      throw new Error("sem rede e sem cópia guardada");
    }
  })());
});
