/* Service Worker：外壳缓存优先，数据网络优先（失败回退缓存，支持离线查看上次内容） */
const SHELL = 'nfd-shell-v7';
const DATA = 'nfd-data-v7';
const SHELL_FILES = [
  './', './index.html', './css/style.css', './js/app.js',
  './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(SHELL)
      .then(c => Promise.allSettled(SHELL_FILES.map(f => c.add(f))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // API 接口：永远走网络，不缓存（否则会误报「在线」）
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(req).catch(() => new Response(
      JSON.stringify({ ok: false, offline: true }), { headers: { 'Content-Type': 'application/json' } })));
    return;
  }

  // 数据：网络优先，回退缓存
  if (url.pathname.includes('/data/')) {
    e.respondWith(
      fetch(req).then(r => {
        const copy = r.clone();
        caches.open(DATA).then(c => c.put(req, copy));
        return r;
      }).catch(() => caches.match(req).then(m => m || new Response(
        JSON.stringify({ offline: true }), { headers: { 'Content-Type': 'application/json' } })))
    );
    return;
  }

  // 外壳：缓存优先
  e.respondWith(
    caches.match(req).then(m => m || fetch(req).then(r => {
      const copy = r.clone();
      caches.open(SHELL).then(c => c.put(req, copy));
      return r;
    }))
  );
});
