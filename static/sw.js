// Service worker: offline fallback only.
// Static files are cached by the browser itself (long-lived, content-hashed
// URLs), and pages are never cached here: they hold a user's stashes and
// would outlive logout on shared devices.
// v5: stops caching static files; deletes all earlier caches.
const CACHE_VERSION = "ruff-v5";

const OFFLINE_HTML =
  '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  "<title>Offline</title>" +
  '<body style="font-family:system-ui,sans-serif;text-align:center;padding:3rem 1rem;background:#fffdf6;color:#1f2d2b">' +
  "<h1>You're offline</h1><p>Reconnect to get to your stash. Anything you were writing is kept on this device.</p></body>";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })
    )
  );
});
