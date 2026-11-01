var VER = 'midicn-1.1.0-8b107928cd38';
var PRECACHE = ["/", "/404.html", "/assets/ui/base.614a243f8b9a.css", "/assets/ui/runtime.226055688a37.js"];
/* midicn shared offline worker. Generated constants are prepended by install_core. */
var PAGE_CACHE = VER + '-pages';
var PAGE_LIMIT = 80;

async function remember(cacheName, request, response) {
  if (!response || !response.ok || response.type === 'opaque') return;
  var cache = await caches.open(cacheName);
  await cache.put(request, response.clone());
  if (cacheName === PAGE_CACHE) {
    var keys = await cache.keys();
    await Promise.all(keys.slice(0, Math.max(0, keys.length - PAGE_LIMIT))
      .map(function (key) { return cache.delete(key); }));
  }
}

self.addEventListener('install', function (event) {
  event.waitUntil(Promise.all(PRECACHE.map(async function (url) {
    try { await remember(VER, url, await fetch(url, {cache: 'reload'})); }
    catch (_) { /* A transient failure must not prevent offline installation. */ }
  })).then(function () { return undefined; }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    var keys = await caches.keys();
    // Keep unrelated application caches on the same origin.
    await Promise.all(keys.filter(function (key) {
      return /^midicn-\d+(?:\.\d+){2}(?:-[0-9a-f]+)?(?:-pages)?$/.test(key) &&
        key !== VER && key !== PAGE_CACHE;
    }).map(function (key) { return caches.delete(key); }));
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', function (event) {
  var request = event.request;
  var url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    // Network first: a successful publish is visible on the very next navigation.
    event.respondWith((async function () {
      try {
        var response = await event.preloadResponse || await fetch(request);
        event.waitUntil(remember(PAGE_CACHE, request, response).catch(function () {}));
        return response;
      } catch (_) {
        return await caches.match(request) || await caches.match('/') || Response.error();
      }
    })());
  } else if (url.pathname.startsWith('/assets/')) {
    event.respondWith((async function () {
      var cached = await caches.match(request);
      if (cached) return cached;
      var response = await fetch(request);
      event.waitUntil(remember(VER, request, response).catch(function () {}));
      return response;
    })());
  }
});
