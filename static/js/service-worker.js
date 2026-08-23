// static/js/service-worker.js — served from "/" (see routes/offline.py's
// service_worker() route) so its scope covers the whole origin, including
// navigation to /hud itself. This is what makes the HUD loadable with zero
// internet at all: without a service worker, an offline visit never even
// gets Flask's response back, so there's no page for offline_model.js or
// offline_sync.js to run inside.
//
// Bump CACHE_VERSION on any shell-asset change -- it's the only thing that
// forces old clients to fetch the new files instead of serving stale ones
// forever from cache.
const CACHE_VERSION = 'friday-shell-v1';

const SHELL_ASSETS = [
  '/hud',
  '/static/css/hud.css',
  '/static/js/hud.js',
  '/static/js/hud_reticle.js',
  '/static/js/offline_model.js',
  '/static/js/offline_sync.js',
  '/static/vendor/wllama/wllama.min.js',
  '/static/vendor/wllama/wllama.wasm',
  '/static/manifest.json',
  '/static/icons/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only the app shell is handled here. Everything under /friday/, /command,
  // /budget etc. goes straight to the network untouched -- offline handling
  // for those lives in hud.js/offline_sync.js, which have the actual
  // context (chat history, what to show from the cached snapshot) needed to
  // answer well. A service worker faking those responses would just return
  // stale JSON with no way to tell the user it's stale.
  const isShellAsset = SHELL_ASSETS.includes(url.pathname) || event.request.mode === 'navigate';
  if (!isShellAsset || url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_VERSION).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match('/hud')))
  );
});
