const CACHE_VERSION = "v3";
const APP_SHELL_CACHE = `palpitando-shell-${CACHE_VERSION}`;
const DATA_CACHE = `palpitando-data-${CACHE_VERSION}`;

const APP_SHELL_FILES = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./manifest.webmanifest",
  "./assets/pwa/icon-192.png",
  "./assets/pwa/icon-512.png",
  "./assets/pwa/apple-touch-icon.png",
  "./assets/pwa/favicon-32.png",
  "./assets/pwa/favicon-16.png",
  "./assets/logo_escura_2.png",
  "./assets/Logo_branca_2.png",
  "./termos.html",
  "./privacidade.html"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(APP_SHELL_CACHE).then((cache) => cache.addAll(APP_SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => ![APP_SHELL_CACHE, DATA_CACHE].includes(key))
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  if (response && response.ok) {
    cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("./index.html"))
    );
    return;
  }

  const isJsonData =
    url.pathname.endsWith("/predictions.json") ||
    url.pathname.endsWith("/history.json") ||
    url.pathname.endsWith("predictions.json") ||
    url.pathname.endsWith("history.json") ||
    url.pathname.endsWith("/predictions_nba.json") ||
    url.pathname.endsWith("/history_nba.json") ||
    url.pathname.endsWith("predictions_nba.json") ||
    url.pathname.endsWith("history_nba.json");

  if (isJsonData) {
    event.respondWith(networkFirst(request, DATA_CACHE));
    return;
  }

  event.respondWith(cacheFirst(request, APP_SHELL_CACHE));
});
