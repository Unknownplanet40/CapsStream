/**
 * CapsStream Service Worker (sw.js)
 * Enterprise-grade PWA Service Worker engineered to prevent stale-cache traps:
 * 1. Strict Network-First for HTML navigations and core scripts.
 * 2. 100% bypass for video streaming, Range requests, and live APIs.
 * 3. Cache-First only for immutable vendor CDNs and fonts.
 * 4. Automatic purge of old caches on activation.
 */

const CACHE_NAME = "capsstream-core-v2.22.3";
const OFFLINE_FALLBACK_URL = "/offline.html";

const PRECACHE_ASSETS = [
  "/offline.html",
  "/static/manifest.webmanifest",
  "/static/img/favicon.png",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
  "/static/img/icon-maskable-512.png",
  "/static/img/apple-touch-icon.png",
  "/static/img/placeholder.svg"
];

// Install: precache offline fallback and essential assets
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch((err) => {
        console.warn("[SW] Precache asset fetch warning:", err);
      });
    }).then(() => {
      return self.skipWaiting();
    })
  );
});

// Activate: clean up obsolete cache versions immediately
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name.startsWith("capsstream-") && name !== CACHE_NAME)
          .map((name) => {
            console.log("[SW] Purging outdated cache:", name);
            return caches.delete(name);
          })
      );
    }).then(() => {
      return self.clients.claim();
    })
  );
});

// Fetch: smart routing with strict stream and API exclusion
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. Only handle GET requests
  if (req.method !== "GET") {
    return;
  }

  // 2. COMPLETE BYPASS for Media Streaming, Transcoding, and Range requests
  // Service workers MUST NOT cache 206 Partial Content or video streams
  if (
    url.pathname.startsWith("/stream/") ||
    url.pathname.startsWith("/transcode/") ||
    url.pathname.startsWith("/api/videos/") ||
    req.headers.has("range")
  ) {
    return;
  }

  // 3. COMPLETE BYPASS for Live API Calls (Health, DB, Profiles, Progress, Scan)
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // 4. HTML Page Navigations (Network-First with Offline Page Fallback)
  if (req.mode === "navigate" || (req.headers.get("accept") && req.headers.get("accept").includes("text/html"))) {
    event.respondWith(
      fetch(req)
        .then((networkRes) => {
          return networkRes;
        })
        .catch(() => {
          return caches.match(OFFLINE_FALLBACK_URL).then((fallback) => {
            return fallback || new Response("CapsStream Offline", {
              headers: { "Content-Type": "text/plain" }
            });
          });
        })
    );
    return;
  }

  // 5. Immutable Third-Party CDNs (Fonts, Phosphor Icons, Vue) - Cache-First
  const isCDN = (
    url.hostname.includes("fonts.googleapis.com") ||
    url.hostname.includes("fonts.gstatic.com") ||
    url.hostname.includes("unpkg.com")
  );

  if (isCDN) {
    event.respondWith(
      caches.match(req).then((cachedRes) => {
        if (cachedRes) return cachedRes;
        return fetch(req).then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const resClone = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, resClone));
          }
          return networkRes;
        });
      })
    );
    return;
  }

  // 6. App Scripts & Styles (Network-First so local server changes apply immediately)
  if (url.pathname.startsWith("/static/js/") || url.pathname.startsWith("/static/css/")) {
    event.respondWith(
      fetch(req)
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const resClone = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, resClone));
          }
          return networkRes;
        })
        .catch(() => {
          return caches.match(req);
        })
    );
    return;
  }

  // 7. Static App Icons & Images (Cache-First)
  if (url.pathname.startsWith("/static/img/")) {
    event.respondWith(
      caches.match(req).then((cachedRes) => {
        if (cachedRes) return cachedRes;
        return fetch(req).then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const resClone = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, resClone));
          }
          return networkRes;
        });
      })
    );
    return;
  }
});

// Client Message Listener
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
