import type { DataBundle, Sentence, SlprosToken, WordEntry } from "./loader";
import { lookupWord } from "./loader";

export interface ResolvedToken {
    surface: string;
    entry: WordEntry | null;
    slpros: SlprosToken;
}

export function resolveSentence(bundle: DataBundle, sentenceId: string): {
    sentence: Sentence;
    tokens: ResolvedToken[];
} | null {
    const sentence = bundle.sentences[sentenceId];
    if (!sentence || !sentence.slpros1) return null;
    const tokens = sentence.slpros1.tokens.map((t) => ({
        surface: t.surface,
        entry: lookupWord(bundle, t.surface),
        slpros: t,
    }));
    return { sentence, tokens };
}

export function listCategories(bundle: DataBundle): string[] {
    const set = new Set<string>();
    for (const s of Object.values(bundle.sentences)) {
        if (s.category) set.add(s.category);
    }
    return [...set].sort();
}

export function sentencesInCategory(bundle: DataBundle, category: string): [string, Sentence][] {
    return Object.entries(bundle.sentences).filter(([, s]) => s.category === category);
}
