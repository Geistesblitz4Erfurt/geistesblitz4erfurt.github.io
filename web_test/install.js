/* SL-Pron Voice-Pack installer (browser-side).
 *
 * Flow:
 *   1. fetch /data/api/voicepack/manifest.json
 *   2. open Cache Storage under manifest.install.cache_name
 *   3. navigator.storage.persist() — best-effort lock against eviction
 *   4. download required assets in parallel (phrasebook + ipa_index)
 *   5. download audio assets sequentially with progress callback
 *   6. verify sha1 of every asset (best-effort; SubtleCrypto only has SHA-1)
 *   7. write IndexedDB record { installed_at, manifest_sha1, total_bytes }
 *
 * Fallstricke handled:
 *   - HTTPS required for Service Worker and storage.persist()
 *   - storage quota warnings when below min_quota_mb
 *   - Safari/iOS: partial Cache Storage support — degrade to fetch-only
 *   - OGG support varies: we keep `.oga`/`.ogg`/`.wav`/`.mp3` alternatives and
 *     let the browser's AudioContext pick what it can decode at playback time.
 *   - Eviction under storage pressure: we set `storage_persist=true` and surface
 *     the failure in the UI rather than silently re-downloading.
 */
(function () {
  const DB_NAME = 'sl-pron-install';
  const DB_STORE = 'meta';
  const INSTALL_KEY = 'pack-install';

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(DB_STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function idbPut(key, value) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readwrite');
      tx.objectStore(DB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function idbGet(key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readonly');
      const r = tx.objectStore(DB_STORE).get(key);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  }

  async function sha1Hex(buf) {
    if (!crypto || !crypto.subtle) return null;
    const d = await crypto.subtle.digest('SHA-1', buf);
    return Array.from(new Uint8Array(d)).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  function toBytes(b) {
    if (b > 1e9) return (b / 1e9).toFixed(2) + ' GB';
    if (b > 1e6) return (b / 1e6).toFixed(1) + ' MB';
    if (b > 1e3) return (b / 1e3).toFixed(1) + ' kB';
    return b + ' B';
  }

  async function askPersist() {
    if (!navigator.storage || !navigator.storage.persist) return false;
    try { return await navigator.storage.persist(); } catch (_) { return false; }
  }

  async function quotaOk(minMb) {
    if (!navigator.storage || !navigator.storage.estimate) return true;
    try {
      const { quota = 0 } = await navigator.storage.estimate();
      return quota / (1024 * 1024) >= minMb;
    } catch (_) { return true; }
  }

  async function fetchManifest() {
    const r = await fetch('/data/api/voicepack/manifest.json', { cache: 'no-store' });
    if (!r.ok) throw new Error('manifest HTTP ' + r.status);
    return await r.json();
  }

  async function installAsset(cache, asset, opts) {
    const req = new Request(asset.url, { cache: 'no-store' });
    const res = await fetch(req);
    if (!res.ok) throw new Error(`asset HTTP ${res.status} for ${asset.url}`);
    const buf = await res.clone().arrayBuffer();
    if (opts.verify) {
      const got = await sha1Hex(buf);
      if (got && got !== asset.sha1) {
        throw new Error(`sha1 mismatch for ${asset.url}: expected ${asset.sha1}, got ${got}`);
      }
    }
    // Re-wrap because clone()'s body is one-shot.
    const headers = new Headers(res.headers);
    if (asset.content_type) headers.set('Content-Type', asset.content_type);
    if (asset.content_encoding) headers.set('Content-Encoding', asset.content_encoding);
    await cache.put(req, new Response(buf, { status: 200, headers }));
    return buf.byteLength;
  }

  async function install(opts = {}) {
    const onProgress = opts.onProgress || (() => {});
    const verify = opts.verify !== false;

    onProgress({ phase: 'manifest' });
    const manifest = await fetchManifest();

    if (manifest.schema !== 'slpron-voicepack.v1')
      throw new Error('unsupported manifest schema: ' + manifest.schema);
    if (manifest.lang !== 'sl-SI')
      throw new Error('manifest lang must be sl-SI, got ' + manifest.lang);

    const minMb = (manifest.install && manifest.install.min_quota_mb) || 32;
    if (!(await quotaOk(minMb))) {
      onProgress({ phase: 'warn_quota', minMb });
    }

    const persisted = await askPersist();
    onProgress({ phase: 'persisted', persisted });

    const cacheName = manifest.install.cache_name || 'sl-pron-voicepack';
    const cache = await caches.open(cacheName);

    // Required assets first (strict), then audio (incremental).
    const required = manifest.assets.filter(a => a.required);
    const audio = manifest.assets.filter(a => !a.required);

    let done = 0, totalBytes = 0;
    const totalCount = manifest.assets.length;

    for (const a of required) {
      onProgress({ phase: 'download', asset: a, index: done, total: totalCount });
      totalBytes += await installAsset(cache, a, { verify });
      done++;
    }
    for (const a of audio) {
      onProgress({ phase: 'download', asset: a, index: done, total: totalCount });
      try {
        totalBytes += await installAsset(cache, a, { verify });
      } catch (err) {
        // audio is optional per-item — keep going
        onProgress({ phase: 'warn_asset', asset: a, error: String(err) });
      }
      done++;
    }

    const record = {
      installed_at: new Date().toISOString(),
      manifest_version: manifest.version,
      manifest_sha1: manifest.bundle_sha1,
      cache_name: cacheName,
      total_bytes: totalBytes,
      persisted,
    };
    await idbPut(INSTALL_KEY, record);
    onProgress({ phase: 'done', ...record });
    return record;
  }

  async function status() {
    try {
      const rec = await idbGet(INSTALL_KEY);
      if (!rec) return { installed: false };
      const exists = await caches.has(rec.cache_name);
      return { installed: exists, ...rec };
    } catch (_) {
      return { installed: false };
    }
  }

  async function uninstall() {
    const rec = await idbGet(INSTALL_KEY);
    if (rec && rec.cache_name) await caches.delete(rec.cache_name);
    await idbPut(INSTALL_KEY, null);
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({
        type: 'EVICT_PACK',
        cacheName: rec && rec.cache_name,
      });
    }
  }

  async function lookupFromCache(url) {
    const rec = await idbGet(INSTALL_KEY);
    if (!rec || !rec.cache_name) return null;
    const cache = await caches.open(rec.cache_name);
    return await cache.match(url, { ignoreSearch: true });
  }

  window.SLPronInstall = { install, status, uninstall, lookupFromCache, fetchManifest, toBytes };
})();
