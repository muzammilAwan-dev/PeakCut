"""S6: a better last resort when no AI answers, and reading across the join between two parts of a long video."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-q-")
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0")
sys.path.insert(0, ".")
import numpy as np
from studio import brain, jobs
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

def speech(a, b, step=0.5, text=None, per_line=8):
    out, t, i = [], a, 0
    while t < b:
        w = (text[i % len(text)] if text else "word")
        if (i + 1) % per_line == 0: w += "."
        out.append({"w": w, "s": round(t, 2), "e": round(t + 0.4, 2)}); t += step; i += 1
    return out

# ---- the last resort when the pool is empty
dur = 300
db = np.full(dur, -30.0); db[140:165] = -10.0                       # a loud stretch at 140-165 s
db += np.random.RandomState(1).normal(0, 0.3, dur)
words = speech(0, 300)
clips = brain.fallback_by_loudness(db, words, 3, 45, float(dur), 15)
check("fallback: clips are returned, no more than asked", 1 <= len(clips) <= 3, True)
check("fallback: the best one holds the loud stretch", any(c["start"] <= 150 <= c["end"] for c in clips), True)
check("fallback: lengths stay inside the limits (with the small padding)", all(14 <= c["end"] - c["start"] <= 46 for c in clips), True)
check("fallback: no two share more than a sliver (30% rule)", all(min(a["end"], b["end"]) - max(a["start"], b["start"]) <= 0.3 * (b["end"] - b["start"]) for i, a in enumerate(clips) for b in clips[i + 1:]), True)
starts = {round(max(0, w["s"] - 0.15), 2) for w in words}
check("fallback: each clip starts at a line of speech, not mid-word", all(c["start"] in starts or c["start"] == 0 for c in clips), True)
check("fallback: the note on each clip says why", all("AI was unavailable" in c["reason"] for c in clips), True)
check("fallback: no speech, no clips", brain.fallback_by_loudness(db, [], 3, 45, float(dur)), [])
gappy = speech(0, 40) + speech(200, 240)                              # speech only at the ends; the loud part is silent
only = brain.fallback_by_loudness(db, gappy, 2, 45, float(dur))
check("fallback: never picks a stretch with no speech", all(any(c["start"] <= w["s"] <= c["end"] for w in gappy) for c in only), True)
excited = speech(0, 120, text=["so", "what", "happened", "next?"], per_line=4)
check("fallback: still works when the loudness reading is missing", len(brain.fallback_by_loudness(np.zeros(0), excited, 2, 40, 120.0)) >= 1, True)

# ---- reading across the join of two parts
prior = speech(540, 600)                                              # last minute of part 1 (absolute seconds)
bw = speech(0, 120)                                                    # part 2, counted from its own start
read, base = jobs.with_lead(prior, bw, 600.0, 60)
check("overlap: the AI reads 60 s of the part before", (base, read[0]["s"], round(read[-1]["e"], 1)), (540.0, 0.0, 179.9))
check("overlap: this part's words are moved after the lead-in", next(w for w in read if w["s"] >= 60)["s"], 60.0)
check("overlap: nothing duplicated or dropped", len(read), len(prior) + len(bw))
check("overlap: the first part has no lead-in", jobs.with_lead([], bw, 0.0, 60), (bw, 0.0))
check("overlap: a lead-in never reaches before the start of the file", jobs.with_lead(speech(0, 20), bw, 20.0, 60)[1], 0.0)
read2, base2 = jobs.with_lead(prior, bw, 600.0, 0)
check("overlap: a lead of 0 changes nothing", (read2[0]["s"], base2), (0.0, 600.0))
# a moment 580-620 s crosses the join: found in the lead-in coordinates, mapped back to the file
moment = {"start": 40.0, "end": 80.0}
check("overlap: a clip that crosses the join maps back to file time", (round(moment["start"] + base, 1), round(moment["end"] + base, 1)), (580.0, 620.0))
check("overlap: a moment the earlier part already has is dropped", brain._overlaps(580.0, 620.0, [{"start": 575.0, "end": 615.0}]), True)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
