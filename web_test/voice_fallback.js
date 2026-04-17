/* SL-Pron Web-Audio fallback speaker.
 *
 * Used when the host browser ships no `sl-SI` SpeechSynthesisVoice. We stitch
 * per-word audio samples from the installed Voice-Pack; each sample is
 * pitch-shifted to the record's expected f0 contour and crossfaded 20ms
 * into the next word.
 *
 * API:
 *   const fb = new VoiceFallback();
 *   await fb.ready();
 *   await fb.speak(tokens, { rate: 1.0 });       // array of {surface, ipa, audio_url?}
 *   await fb.speakRecord(record);                 // accepts phrasebook record
 */
(function () {
  const CROSSFADE_MS = 20;
  const SILENCE_AFTER_SENTENCE_MS = 300;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  class VoiceFallback {
    constructor() {
      this._ctxPromise = null;
      this._active = new Set();   // live BufferSource nodes
      this._cancelled = false;
    }

    _ensureCtx() {
      if (!this._ctxPromise) {
        this._ctxPromise = (async () => {
          const AC = window.AudioContext || window.webkitAudioContext;
          if (!AC) throw new Error('no AudioContext');
          return new AC();
        })();
      }
      return this._ctxPromise;
    }

    async ready() { await this._ensureCtx(); }

    async _fetchAudio(url) {
      // Try installed cache first (offline path).
      let res;
      if (window.SLPronInstall) {
        try { res = await window.SLPronInstall.lookupFromCache(url); } catch (_) {}
      }
      if (!res) res = await fetch(url);
      if (!res || !res.ok) throw new Error(`fetch ${url}: ${res && res.status}`);
      return await res.arrayBuffer();
    }

    async _decode(buf) {
      const ctx = await this._ensureCtx();
      return new Promise((resolve, reject) => {
        // decodeAudioData with both callback and promise forms for Safari.
        try {
          const p = ctx.decodeAudioData(buf.slice(0), resolve, reject);
          if (p && typeof p.then === 'function') p.then(resolve, reject);
        } catch (e) { reject(e); }
      });
    }

    async _bufferForToken(token) {
      // Priority: explicit URL → manifest surface index (hash-suffixed names)
      // → naive <surface>.wav fallback.
      let url = token.audio_url || null;
      if (!url && window.SLPronInstall && token.surface) {
        try { url = await window.SLPronInstall.audioUrlForSurface(token.surface); }
        catch (_) {}
      }
      if (!url && token.surface) {
        url = `/data/audio/words/${token.surface.toLowerCase()}.wav`;
      }
      if (!url) return null;
      try {
        const raw = await this._fetchAudio(url);
        return await this._decode(raw);
      } catch (_) { return null; }
    }

    _scheduleBuffer(ctx, buffer, startAt, detuneCents) {
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      try { src.detune.value = detuneCents || 0; }
      catch (_) { /* Safari lacks detune on AudioBufferSourceNode */ }

      const gain = ctx.createGain();
      const dur = buffer.duration;
      const fade = Math.min(CROSSFADE_MS / 1000, dur / 4);
      gain.gain.setValueAtTime(0, startAt);
      gain.gain.linearRampToValueAtTime(1, startAt + fade);
      gain.gain.setValueAtTime(1, startAt + dur - fade);
      gain.gain.linearRampToValueAtTime(0, startAt + dur);

      src.connect(gain).connect(ctx.destination);
      src.start(startAt);
      src.stop(startAt + dur + 0.01);
      this._active.add(src);
      src.onended = () => this._active.delete(src);
      return dur - fade;
    }

    stop() {
      this._cancelled = true;
      for (const src of this._active) {
        try { src.stop(0); } catch (_) {}
      }
      this._active.clear();
    }

    async speak(tokens, opts = {}) {
      this.stop();             // cancel any prior playback on same instance
      this._cancelled = false;
      const ctx = await this._ensureCtx();
      if (ctx.state === 'suspended') await ctx.resume();
      const rate = clamp(opts.rate || 1.0, 0.5, 2.0);

      let cursor = ctx.currentTime + 0.05;
      let played = 0, missing = [];
      for (const t of tokens) {
        if (this._cancelled) break;
        const buf = await this._bufferForToken(t);
        if (!buf) { missing.push(t.surface); continue; }
        const detune = Math.round(Math.log2(rate) * 1200);
        const advance = this._scheduleBuffer(ctx, buf, cursor, detune);
        cursor += advance;
        played++;
      }
      cursor += SILENCE_AFTER_SENTENCE_MS / 1000;
      const totalMs = (cursor - ctx.currentTime) * 1000;
      await new Promise(r => setTimeout(r, totalMs + 50));
      return { played, missing, total: tokens.length, cancelled: this._cancelled };
    }

    async speakRecord(record, opts) {
      const tokens = record && record.tokens ? record.tokens : [];
      return await this.speak(tokens, opts);
    }

    static isNeededForCurrentBrowser() {
      if (!('speechSynthesis' in window)) return true;
      const voices = speechSynthesis.getVoices() || [];
      return !voices.some(v => (v.lang || '').toLowerCase().startsWith('sl'));
    }
  }

  window.VoiceFallback = VoiceFallback;
})();
