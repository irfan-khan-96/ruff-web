// Service worker: opens the app offline.
// Notes live in IndexedDB, so the pages themselves are empty shells; they are
// fetched from the network first and the last good copy is kept for offline
// use. Static files have content-hashed URLs and are kept on first use.
// Signing out deletes both caches (see script.js), so nothing outlives it.
// v6: offline shells and static files.
const CACHE_VERSION = "ruff-v6";
const PAGES = `${CACHE_VERSION}-pages`;
const STATIC = `${CACHE_VERSION}-static`;

// Pages kept for offline use (the server marks a page X-Offline-Shell when it
// is safe to keep: no one-off messages in it); a stash opens in the sheet shell
const SHELLS = ["/", "/stashes", "/pass", "/lounge"];
const NOTE_PAGE = /^\/stashes\/[0-9a-f-]{36}$/;

const OFFLINE_HTML =
  '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  "<title>Offline</title>" +
  '<body style="font-family:system-ui,sans-serif;text-align:center;padding:3rem 1rem;background:#fffdf6;color:#1f2d2b">' +
  "<h1>You're offline</h1><p>This page needs a connection. Your notes are safe on this device.</p></body>";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(CACHE_VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

const keep = (cacheName, request, response) => {
  if (response.ok && !response.redirected && response.type === "basic") {
    const copy = response.clone();
    caches.open(cacheName).then((cache) => cache.put(request, copy));
  }
  return response;
};

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    const shell = SHELLS.includes(url.pathname) ? url.pathname : NOTE_PAGE.test(url.pathname) ? "/" : null;
    event.respondWith(
      fetch(request)
        .then((response) => (shell === url.pathname && !url.search && response.headers.get("X-Offline-Shell")
          ? keep(PAGES, shell, response) : response))
        .catch(async () => (shell && (await caches.match(shell, { cacheName: PAGES })))
          || new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } }))
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request, { cacheName: STATIC }).then((hit) => hit || fetch(request).then((response) => keep(STATIC, request, response)))
    );
  }
});
