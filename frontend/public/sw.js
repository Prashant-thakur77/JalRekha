self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open('jalrekha-v1').then((cache) =>
      cache.addAll(['/', '/manifest.webmanifest', '/favicon.svg']),
    ),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse.ok) {
            const responseClone = networkResponse.clone();
            caches.open('jalrekha-v1').then((cache) => {
              cache.put(event.request, responseClone);
            });
          }

          return networkResponse;
        })
        .catch(() => caches.match('/'));
    }),
  );
});
