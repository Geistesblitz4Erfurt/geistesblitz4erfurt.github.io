import { loadBundle, lookupWord, type DataBundle } from "./loader";
import { listCategories, sentencesInCategory, resolveSentence } from "./lookup";
import { buildPlan } from "./prosody";
import { playPlan } from "./player";

const AUDIO_BASE = "/data/audio/";

async function main() {
    const statusEl = document.getElementById("audio-status")!;
    statusEl.textContent = "Lade Datenpaket…";
    let bundle: DataBundle;
    try {
        bundle = await loadBundle("/data/");
    } catch (err) {
        statusEl.textContent = `Fehler beim Laden: ${String(err)}`;
        return;
    }
    statusEl.textContent = `${Object.keys(bundle.sentences).length} Sätze, ${Object.keys(bundle.words).length} Wörter geladen.`;

    const cats = listCategories(bundle);
    const nav = document.getElementById("category-nav")!;
    const listEl = document.getElementById("sentence-list")!;

    function showCategory(cat: string) {
        for (const el of nav.querySelectorAll(".cat-btn")) {
            el.setAttribute("aria-pressed", el.textContent === cat ? "true" : "false");
        }
        const items = sentencesInCategory(bundle, cat);
        listEl.innerHTML = "";
        for (const [id, s] of items) {
            const card = document.createElement("article");
            card.className = "sentence-card";
            const qBadge = qualityBadge(bundle, s.tokens.map((t) => t.surface));
            card.innerHTML = `
                <div class="sl-text" lang="sl">${escapeHtml(s.sl)}</div>
                <button class="play-btn" aria-label="Abspielen">▶</button>
                <div class="en-text" lang="en">${escapeHtml(s.en ?? "")}</div>
                <div class="contour-tag">[${s.contour_type}]</div>
                <div class="quality">
                    <span class="quality-badge ${qBadge.cls}">${qBadge.text}</span>
                </div>
                <span></span>
            `;
            const btn = card.querySelector("button")!;
            btn.addEventListener("click", () => playSentence(bundle, id, btn, statusEl));
            listEl.appendChild(card);
        }
    }

    for (const cat of cats) {
        const btn = document.createElement("button");
        btn.className = "cat-btn";
        btn.textContent = cat;
        btn.addEventListener("click", () => showCategory(cat));
        nav.appendChild(btn);
    }
    if (cats.length) showCategory(cats[0]);
}

async function playSentence(bundle: DataBundle, id: string, btn: HTMLButtonElement, status: HTMLElement) {
    const resolved = resolveSentence(bundle, id);
    if (!resolved || !resolved.sentence.slpros1) {
        status.textContent = `Keine Prosodie für ${id}`;
        return;
    }
    btn.disabled = true;
    const resolveAudio = (surface: string) => {
        const e = lookupWord(bundle, surface);
        return e?.audio?.[0]?.path ?? null;
    };
    const plan = buildPlan(resolved.sentence.slpros1, AUDIO_BASE, resolveAudio);
    status.textContent = `Spiele „${resolved.sentence.sl}" ab (${plan.length} Schritte)`;
    try {
        await playPlan(plan);
    } catch (err) {
        status.textContent = `Fehler: ${String(err)}`;
    } finally {
        btn.disabled = false;
    }
}

function qualityBadge(bundle: DataBundle, surfaces: string[]): { cls: string; text: string } {
    let withAudio = 0;
    let total = 0;
    for (const s of surfaces) {
        const e = lookupWord(bundle, s);
        if (!e) continue;
        total++;
        if (e.audio.length > 0) withAudio++;
    }
    if (total === 0) return { cls: "fallback", text: "synth" };
    if (withAudio / total >= 0.8) return { cls: "good", text: "native" };
    if (withAudio / total >= 0.4) return { cls: "", text: "gemischt" };
    return { cls: "fallback", text: "synth" };
}

function escapeHtml(s: string): string {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

main();
