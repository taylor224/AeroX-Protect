/* AeroX Protect service worker (PLAN P5 §8.8) — web push display + deep-link click. */
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'AeroX Protect', body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'AeroX Protect';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      tag: data.tag || data.camera_id || 'axp',
      data: { deeplink: data.deeplink || '/' },
      badge: '/favicon.ico',
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.deeplink) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
