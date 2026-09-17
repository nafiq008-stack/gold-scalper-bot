self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());
self.addEventListener('fetch', (event) => {
  // Pass-through - we want fresh data every time, no offline caching of state
  event.respondWith(fetch(event.request));
});
