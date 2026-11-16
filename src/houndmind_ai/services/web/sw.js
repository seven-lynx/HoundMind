// The console's service worker: the app shell survives a slow or briefly absent device (#176).
//
// It only ever runs in a **secure context** - `https://` or `localhost` - and the device serves plain
// http on the LAN by default (`settings.api.tls_enabled: false`), so on a default install this file is
// never registered: `lib.js` asks `isSecureContext` before it registers anything. `docs/INSTALL.md`
// carries the TLS steps.
//
// Two rules, and they are the ones a control plane needs:
//   - `/api/` is never cached. A cached `/state` is a console showing a dog that is not there, and a
//     cached token or log would be worse than a blank panel.
//   - Everything else is **network first**, cache second. Online, the browser always gets the current
//     `app.js` - the document is served `no-cache` for exactly that reason - and the cache only
//     answers when the network does not.
//
// A worker belongs to one origin, and so does the console: switching to another dog is a navigation to
// that dog's own origin, where that dog's worker answers (#179).

const CACHE = "houndmind-shell-v1";
const SHELL = ["/", "/static/index.html", "/static/icon.svg", "/static/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      // A shell that failed to precache is not a reason to block the install: the fetch handler
      // caches on the way through, and `skipWaiting` gets the worker active either way.
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // `return` without `respondWith` hands the request to the browser, uncached.
  if (url.pathname.startsWith("/api/")) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches
            .open(CACHE)
            .then((cache) => cache.put(request, copy))
            .catch(() => undefined);
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then((cached) => {
          if (cached) return cached;
          if (request.mode === "navigate") {
            return new Response(
              '<!doctype html><meta charset="utf-8"><title>HoundMind</title>' +
                '<body style="font:15px system-ui;padding:2rem">The console is offline and this page ' +
                "was never cached. Reconnect to the dog, then reload.</body>",
              { headers: { "Content-Type": "text/html; charset=utf-8" } }
            );
          }
          return Response.error();
        })
      )
  );
});
