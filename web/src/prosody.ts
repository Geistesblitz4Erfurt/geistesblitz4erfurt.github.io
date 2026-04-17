import type { SentenceProsody, Syllable } from "./loader";

export interface PlanStep {
    kind: "audio" | "synth" | "silence";
    surface: string;
    ipa: string;
    syllables: Syllable[];
    stressSyllableIdx: number;
    accentClass: string;
    audioUrl: string | null;
    detuneCents: number;
    durationMs: number;
    pauseAfterMs: number;
}

const CENT_PER_SEMITONE = 100;

export function centsFromRatio(ratio: number): number {
    return Math.round((Math.log2(ratio) * 12 * CENT_PER_SEMITONE) * 10) / 10;
}

/**
 * Translate SLPROS-1 + resolved word entries into a concrete playback plan.
 * Each step is either a native audio sample (pitch-shifted by detuneCents) or a synth fallback.
 */
export function buildPlan(
    prosody: SentenceProsody,
    audioBase: string,
    resolveAudio: (surface: string) => string | null,
): PlanStep[] {
    const steps: PlanStep[] = [];
    const baseSyll = 180; // ms
    for (const tok of prosody.tokens) {
        const dur = tok.syllables.reduce((a, s) => a + s.dur_rel, 0) * baseSyll;
        const stressedSyll = tok.syllables[tok.stress_syllable_idx];
        // detune: map the F0 midpoint of the stressed syllable (in cents from baseline)
        let detune = 0;
        if (stressedSyll) {
            detune = (stressedSyll.f0_start_ct + stressedSyll.f0_end_ct) / 2;
        }
        const audioPath = resolveAudio(tok.surface);
        steps.push({
            kind: audioPath ? "audio" : "synth",
            surface: tok.surface,
            ipa: tok.ipa,
            syllables: tok.syllables,
            stressSyllableIdx: tok.stress_syllable_idx,
            accentClass: tok.accent_class,
            audioUrl: audioPath ? audioBase + audioPath : null,
            detuneCents: detune,
            durationMs: dur,
            pauseAfterMs: tok.pause_after_ms,
        });
        if (tok.pause_after_ms > 0) {
            steps.push({
                kind: "silence", surface: "", ipa: "", syllables: [], stressSyllableIdx: -1,
                accentClass: "-", audioUrl: null, detuneCents: 0,
                durationMs: tok.pause_after_ms, pauseAfterMs: 0,
            });
        }
    }
    if (prosody.final_pause_ms > 0) {
        steps.push({
            kind: "silence", surface: "", ipa: "", syllables: [], stressSyllableIdx: -1,
            accentClass: "-", audioUrl: null, detuneCents: 0,
            durationMs: prosody.final_pause_ms, pauseAfterMs: 0,
        });
    }
    return steps;
}
