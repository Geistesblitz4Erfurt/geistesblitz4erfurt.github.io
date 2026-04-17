/* SL-Pron Service Worker — Voice-Pack cache controller.
 *
 * Strategies:
 *   shell       → cache-first  (install-time precache)
 *   voicepack   → cache-first  (explicitly installed via install.js)
 *   api/data    → stale-while-revalidate
 *   other       → network only
 *
 * Versioning: bumping SHELL_CACHE forces reinstall. Voice-pack cache name is
 * pinned to the manifest version, so old packs stay until the user updates.
 */

const SHELL_CACHE = 'sl-pron-shell-v1';
const PACK_CACHE_PREFIX = 'sl-pron-voicepack-';
const DATA_CACHE = 'sl-pron-data-v1';

const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/install.html',
  '/web_test/install.js',
  '/web_test/voice_fallback.js',
  '/web_test/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await Promise.all(SHELL_ASSETS.map(async (u) => {
      try { await cache.add(new Request(u, { cache: 'reload' })); }
      catch (_) { /* optional asset missing in dev */ }
    }));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL_CACHE, DATA_CACHE]);
    // voice-pack caches are kept unless explicitly evicted via message
    const names = await caches.keys();
    await Promise.all(names.map(n => {
      if (keep.has(n) || n.startsWith(PACK_CACHE_PREFIX)) return;
      return caches.delete(n);
    }));
    await self.clients.claim();
  })());
});

// Messaging API: install.js talks to us through here.
self.addEventListener('message', (event) => {
  const msg = event.data || {};
  if (msg.type === 'SKIP_WAITING') self.skipWaiting();
  if (msg.type === 'EVICT_PACK' && msg.cacheName) {
    event.waitUntil(caches.delete(msg.cacheName));
  }
  if (msg.type === 'PING') {
    event.ports[0] && event.ports[0].postMessage({ type: 'PONG', now: Date.now() });
  }
});

function isVoicepackAsset(url) {
  return url.pathname.startsWith('/data/api/voicepack/')
      || url.pathname.startsWith('/data/audio/words/')
      || url.pathname === '/data/api/phrasebook.json.gz'
      || url.pathname === '/data/api/phrasebook_index.json';
}

async function cacheFirst(request) {
  // Check every pack cache (covers version upgrades).
  const names = (await caches.keys()).filter(n => n.startsWith(PACK_CACHE_PREFIX));
  for (const n of names) {
    const c = await caches.open(n);
    const hit = await c.match(request, { ignoreSearch: true });
    if (hit) return hit;
  }
  const net = await fetch(request);
  // Don't auto-populate the pack cache — install.js owns that policy.
  return net;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(DATA_CACHE);
  const hit = await cache.match(request);
  const netPromise = fetch(request).then(res => {
    if (res.ok) cache.put(request, res.clone());
    return res;
  }).catch(() => hit);
  return hit || netPromise;
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;

  if (isVoicepackAsset(url)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/data/api/')) {
    event.respondWith(staleWhileRevalidate(event.request));
    return;
  }
  if (SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      const hit = await cache.match(event.request);
      return hit || fetch(event.request);
    })());
  }
});
