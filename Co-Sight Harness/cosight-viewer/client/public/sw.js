// SPDX-License-Identifier: Apache-2.0
/**
 * @description Service Worker for caching static assets and handling push notifications.
 */

// Bump this any time the SW logic changes — old clients will install the new
// SW, drop their existing caches in `activate`, and `skipWaiting` so the
// freshly-built bundle starts being served on the very next request.
const CACHE_NAME = "dashboard-v5";

self.addEventListener("install", () => {
  // No pre-cache: network-first below means the cache fills lazily, and
  // there's nothing to "warm" — the v1 SW was pre-caching `/`, which is
  // exactly the file most likely to go stale after a rebuild.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Skip WebSocket and Vite HMR endpoints
  if (url.pathname.startsWith("/ws") || url.pathname.includes("__vite")) return;
  // Skip API requests.
  // We identify API calls by:
  //   1. Path starting with /api/
  //   2. Content-Type containing application/json (set by api.ts)
  //   3. Accept header containing application/json (also common for API calls)
  if (url.pathname.startsWith("/api/")) return;
  const acceptHeader = request.headers.get("accept") || "";
  const contentTypeHeader = request.headers.get("content-type") || "";
  const hasJson =
    acceptHeader.includes("application/json") ||
    contentTypeHeader.includes("application/json");
  const isNavigation = request.mode === "navigate";
  const isStaticAsset =
    url.pathname.startsWith("/assets/") ||
    url.pathname.startsWith("/sw.js") ||
    url.pathname.startsWith("/manifest") ||
    /\.(png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot|css)(\?.*)?$/.test(url.pathname);
  // Skip non-navigation, non-static requests that use JSON (i.e. API calls)
  if (!isNavigation && !isStaticAsset && hasJson) return;
  // Also skip any request whose path matches known API patterns in local mode.
  // These are the API route prefixes registered in server/index.js.
  const localApiPrefixes = [
    "/sessions",
    "/agents",
    "/events",
    "/stats",
    "/hooks",
    "/pricing",
    "/settings",
    "/push",
    "/import",
    "/updates",
    "/tasks",
    "/run",
    "/files",
    "/task-flow",
    "/cc-config",
    "/portal",
    "/health",
    "/openapi.json",
    "/docs",
  ];
  for (const prefix of localApiPrefixes) {
    if (url.pathname === prefix || url.pathname.startsWith(prefix + "/")) return;
  }

  // Hashed bundles under /assets/ are immutable for a given URL — cache-first
  // is safe and fast. A new build emits new filenames, so stale entries simply
  // don't get re-requested.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok && response.type === "basic") {
              const clone = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return response;
          })
      )
    );
    return;
  }

  // Everything else (navigations, sw.js, manifest, icons, root /): network-first
  // with cache fallback. The user always gets the freshest UI while online and
  // a sensible fallback when offline.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok && response.type === "basic") {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request).then((c) => c || caches.match("/")))
  );
});

// --- Push notifications (existing) ---

self.addEventListener("push", (event) => {
  const data = event.data
    ? event.data.json()
    : { title: "Co-Sight Viewer", body: "New notification" };
  const { title, ...options } = data;
  event.waitUntil(self.registration.showNotification(title, { silent: false, ...options }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: "window" }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.focus) {
          return client.focus();
        }
      }
    })
  );
});
