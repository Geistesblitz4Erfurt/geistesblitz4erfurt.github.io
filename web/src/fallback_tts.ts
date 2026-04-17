/**
 * Last-resort TTS fallback. Used only when a word has no native audio AND no build-time pre-render.
 * Preference order inside this module:
 *   1. eSpeak-NG WASM (loaded from /vendor/espeak-ng.js) — IPA input, deterministic synthesis
 *   2. Web Speech API with sl-SI voice — browser-dependent, last resort
 */

// eSpeak WASM wrapper — loaded lazily. The vendored bundle is expected at /vendor/espeak-ng.js
// and must expose `EspeakNg(opts)` with a `.synthesize_ipa(ipa, {rate, pitch}) -> Float32Array` API.
interface EspeakModule {
    synthesize_ipa(ipa: string, opts: { rate: number; pitchCents: number }): Float32Array;
    sampleRate: number;
}

let espeakPromise: Promise<EspeakModule | null> | null = null;

async function loadEspeak(): Promise<EspeakModule | null> {
    if (espeakPromise) return espeakPromise;
    espeakPromise = (async () => {
        try {
            const mod = await import(/* @vite-ignore */ "/vendor/espeak-ng.js");
            if (typeof (mod as any).EspeakNg !== "function") return null;
            return (await (mod as any).EspeakNg({ language: "sl" })) as EspeakModule;
        } catch {
            return null;
        }
    })();
    return espeakPromise;
}

export async function synthIpa(
    ipa: string,
    pitchCents: number,
    when: number,
    targetDurationSec: number,
): Promise<void> {
    const espeak = await loadEspeak();
    if (espeak) {
        try {
            const { AudioContext } = await import("standardized-audio-context");
            const ctx = new AudioContext();
            const samples = espeak.synthesize_ipa(ipa, {
                rate: Math.max(0.5, Math.min(2, samplesDurationRate(espeak, ipa, targetDurationSec))),
                pitchCents,
            });
            const buf = ctx.createBuffer(1, samples.length, espeak.sampleRate);
            buf.copyToChannel(samples, 0);
            const src = ctx.createBufferSource();
            src.buffer = buf;
            src.connect(ctx.destination);
            src.start(when);
            return;
        } catch (err) {
            console.warn("[fallback_tts] espeak failed, using webspeech", err);
        }
    }
    // Web Speech API fallback
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const utter = new SpeechSynthesisUtterance(ipa);
        utter.lang = "sl-SI";
        utter.rate = 1;
        utter.pitch = 1 + pitchCents / 1200;
        window.speechSynthesis.speak(utter);
    }
}

function samplesDurationRate(mod: EspeakModule, ipa: string, targetSec: number): number {
    // eSpeak default rate ≈ 175 wpm. Adjust to fit our target envelope.
    // Naive: longer IPA → slower rate is not ideal. We'll rely on build-time rendering where possible.
    const expectedSec = Math.max(0.2, ipa.length * 0.06);
    return expectedSec / Math.max(0.2, targetSec);
}
