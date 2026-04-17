import { gunzipSync, strFromU8 } from "fflate";

export interface Syllable {
    phon: string;
    length: "L" | "S";
    tone: "R" | "F" | "-";
    dur_rel: number;
    f0_start_ct: number;
    f0_end_ct: number;
    is_stressed: boolean;
}

export interface WordAudio {
    path: string;
    format: string;
    source: string;
    license: string;
    duration_ms: number | null;
    speaker_meta: Record<string, unknown> | null;
}

export interface WordEntry {
    surface: string;
    ipa: string;
    accent_class: "RL" | "FL" | "RS" | "FS" | "L" | "S" | "-";
    syllables: string[];
    stress_syllable_idx: number;
    quality: number;
    sources: number;
    msd: string;
    msd_variants: string[];
    audio: WordAudio[];
}

export interface SlprosToken {
    surface: string;
    ipa: string;
    role: string;
    accent_class: string;
    stress_syllable_idx: number;
    syllables: Syllable[];
    pause_after_ms: number;
    f0_contour_tag: string;
}

export interface SentenceProsody {
    contour_type: "decl" | "q_yn" | "q_wh" | "excl" | "neutral";
    register: string;
    baseline_f0_hz: number;
    final_pause_ms: number;
    tokens: SlprosToken[];
}

export interface SentenceToken {
    surface: string;
    ipa: string;
    upos: string;
    role: string;
}

export interface Sentence {
    sl: string;
    en: string;
    category: string;
    register: string;
    contour_type: string;
    coverage: number;
    tokens: SentenceToken[];
    slpros1: SentenceProsody | null;
}

export interface DataBundle {
    words: Record<string, WordEntry>;
    sentences: Record<string, Sentence>;
}

async function fetchGzipJson<T>(url: string): Promise<T> {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
    const buf = new Uint8Array(await resp.arrayBuffer());
    const raw = gunzipSync(buf);
    return JSON.parse(strFromU8(raw)) as T;
}

export async function loadBundle(base = "/data/"): Promise<DataBundle> {
    const [words, sentences] = await Promise.all([
        fetchGzipJson<Record<string, WordEntry>>(base + "words.json.gz"),
        fetchGzipJson<Record<string, Sentence>>(base + "sentences.json.gz"),
    ]);
    return { words, sentences };
}

export function lookupWord(bundle: DataBundle, surface: string): WordEntry | null {
    return bundle.words[surface.toLowerCase()] ?? null;
}
