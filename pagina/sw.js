const CACHE_NAME = 'gez-kino-v1';
const ASSETS = [
  './',
  './index.html',
  './banner.png',
  './manifest.json'
];

// Installieren & Assets in den Cache laden
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

// Netzwerk-Anfragen abfangen (Offline-Fähigkeit für Basis-Assets)
self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request);
    })
  );
});
