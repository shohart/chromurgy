// Chromurgy Web Darkroom — Service Worker
const CACHE_NAME = "chromurgy-v1";
const STATIC_ASSETS = [
  "/darkroom",
  "/darkroom/static/darkroom.css",
  "/darkroom/static/darkroom.js",
  "/darkroom/static/site.webmanifest",
  "/darkroom/static/favicon.svg",
  "/darkroom/static/favicon-32x32.png",
  "/darkroom/static/icon-192x192.png",
  "/darkroom/static/icon-512x512.png",
  "/darkroom/static/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        // Individual asset failure should not block installation
        console.warn("[SW] Cache preload warning:", err);
      });
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Bypass API requests, non-GET requests, or websockets
  if (req.method !== "GET" || url.pathname.startsWith("/api/")) {
    return;
  }

  // Navigation requests: network first, fallback to cached /darkroom
  if (req.mode === "navigate" || url.pathname === "/darkroom" || url.pathname === "/") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put("/darkroom", copy));
          }
          return res;
        })
        .catch(() => caches.match("/darkroom"))
    );
    return;
  }

  // Static assets: stale-while-revalidate
  if (url.pathname.startsWith("/darkroom/static/")) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const fetchPromise = fetch(req)
          .then((networkRes) => {
            if (networkRes && networkRes.status === 200) {
              const copy = networkRes.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
            }
            return networkRes;
          })
          .catch(() => null);

        return cached || fetchPromise;
      })
    );
    return;
  }

  // Default fetch
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
