import { AudioContext, type IAudioBuffer } from "standardized-audio-context";
import type { PlanStep } from "./prosody";

const bufferCache = new Map<string, Promise<IAudioBuffer>>();
let ctx: AudioContext | null = null;

function getCtx(): AudioContext {
    if (!ctx) ctx = new AudioContext();
    return ctx;
}

async function loadBuffer(url: string): Promise<IAudioBuffer> {
    const existing = bufferCache.get(url);
    if (existing) return existing;
    const p = (async () => {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
        const arr = await resp.arrayBuffer();
        return getCtx().decodeAudioData(arr);
    })();
    bufferCache.set(url, p);
    return p;
}

export async function playPlan(
    steps: PlanStep[],
    onStep?: (i: number, step: PlanStep) => void,
): Promise<void> {
    const audio = getCtx();
    await audio.resume();
    // Preload audio samples in parallel
    const urls = steps.filter((s) => s.audioUrl).map((s) => s.audioUrl!) as string[];
    await Promise.all(urls.map((u) => loadBuffer(u).catch(() => null)));

    let when = audio.currentTime + 0.05;
    const crossfade = 0.02;  // 20ms
    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        if (step.kind === "silence") {
            when += step.durationMs / 1000;
            continue;
        }
        if (step.kind === "audio" && step.audioUrl) {
            try {
                const buf = await loadBuffer(step.audioUrl);
                const src = audio.createBufferSource();
                src.buffer = buf;
                src.detune.value = step.detuneCents;
                const gain = audio.createGain();
                gain.gain.setValueAtTime(0, when);
                gain.gain.linearRampToValueAtTime(1, when + crossfade);
                gain.gain.setValueAtTime(1, when + buf.duration - crossfade);
                gain.gain.linearRampToValueAtTime(0, when + buf.duration);
                src.connect(gain).connect(audio.destination);
                src.start(when);
                if (onStep) setTimeout(() => onStep(i, step), (when - audio.currentTime) * 1000);
                when += buf.duration;
                continue;
            } catch (err) {
                console.warn("[player] audio fallback for", step.surface, err);
            }
        }
        // Synth fallback — delegate to fallback_tts
        const { synthIpa } = await import("./fallback_tts");
        const dur = step.durationMs / 1000;
        await synthIpa(step.ipa, step.detuneCents, when, dur);
        when += dur;
    }
    // Wait for everything to finish
    const waitMs = (when - audio.currentTime) * 1000;
    if (waitMs > 0) await new Promise((r) => setTimeout(r, waitMs));
}
