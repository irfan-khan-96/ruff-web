// Bump on deploys that change cached assets; old caches are deleted on activate.
// v2: pages are no longer cached, so v1 caches (which held private pages) go away.
// v3: script.js handles delete confirmations (CSP blocks the old inline onclick).
// v4: share.js handles refused joins (full rooms, join limits).
const CACHE_VERSION = "ruff-v4";
// Public static assets only. Never pre-cache or cache app pages: they contain
// a logged-in user's stashes and would survive logout on shared devices.
const CORE_ASSETS = [
  "/static/styles.css",
  "/static/script.js",
  "/static/share.js",
  "/static/images/mascot.svg",
  "/static/images/mural.svg",
  "/static/manifest.json"
];

const OFFLINE_HTML =
  '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  "<title>Offline - Ruff</title>" +
  '<body style="font-family:sans-serif;text-align:center;padding:3rem 1rem">' +
  "<h1>You're offline</h1><p>Reconnect to see your stashes.</p></body>";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => (key === CACHE_VERSION ? null : caches.delete(key)))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.mode === "navigate") {
    // Network only; show a generic offline page instead of cached private pages
    event.respondWith(
      fetch(request).catch(
        () => new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })
      )
    );
    return;
  }

  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    // Stale-while-revalidate: serve from cache, refresh it in the background
    // so updated assets reach returning users on their next visit
    event.respondWith(
      caches.open(CACHE_VERSION).then((cache) =>
        cache.match(request).then((cached) => {
          const network = fetch(request)
            .then((response) => {
              if (response.ok) cache.put(request, response.clone());
              return response;
            })
            .catch(() => cached);
          return cached || network;
        })
      )
    );
  }
  // Everything else (API calls, Socket.IO, CDN scripts) goes straight to the network
});
