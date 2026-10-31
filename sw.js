/* midicn core v0.9.0 —— 一份 SW，装进每个站的根目录
   策略：HTML 网络优先（改了立刻能看到），资产缓存优先（切站不再重复下载）。
   切站"像站内切换"靠的就是这条：目标页的 HTML 在指针按下时已经开始取。 */
var VER = 'midicn-0.9.0';
var PRECACHE = ["/", "/assets/core/midicn.afe1dd9b5e.css", "/assets/core/shell.e04edf7096.js", "/assets/core/theme.8087c75b5a.js", "/assets/core/v6-data.e07754c398.css", "/manifest.json"];
self.addEventListener('install', function (e) {
  /* 逐个取、单个失败不牵连整体：运行期容错，构建判据另行核对产物。 */
  e.waitUntil(caches.open(VER).then(function (c) {
    return Promise.all(PRECACHE.map(function (u) {
      return fetch(u).then(function (r) {
        if (r && r.ok) c.put(u, r.clone());
      }).catch(function () { /* 缺一个文件不该让整个 SW 装不上 */ });
    }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== VER; })
                        .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;         /* 跨源（含其它子域）不接管 */
  if (req.mode === 'navigate') {
    /* stale-while-revalidate：先给缓存的那一版，同时后台取新的 */
    e.respondWith(caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (res.ok) caches.open(VER).then(function (c) { c.put(req, res.clone()); });
        return res;
      });
      return hit || net;
    }));
    return;
  }
  if (url.pathname.indexOf('/assets/') === 0) {
    e.respondWith(caches.match(req).then(function (hit) {
      return hit || fetch(req).then(function (res) {
        if (res.ok) caches.open(VER).then(function (c) { c.put(req, res.clone()); });
        return res;
      });
    }));
  }
});
