"""Scoring for clip-picking: did the system pick the moments that people picked?
A pick is a hit when it overlaps a human pick by at least half of the shorter of the two."""
import json
import random
from pathlib import Path

import numpy as np


def overlap_share(a, b) -> float:
    """Overlap as a share of the shorter span (0 to 1)."""
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    shorter = min(a["end"] - a["start"], b["end"] - b["start"])
    return max(0.0, inter) / shorter if shorter > 0 else 0.0


def is_hit(pick, humans) -> bool:
    return any(overlap_share(pick, h) >= 0.5 for h in humans)


def matched(picks, humans) -> int:
    """How many picks hit, where each human pick can be found only once (two picks inside the same human moment
    are one find, not two)."""
    free, n = list(humans), 0
    for p in picks:
        for h in free:
            if overlap_share(p, h) >= 0.5:
                free.remove(h)
                n += 1
                break
    return n


def precision_at_k(picks, humans, k) -> float:
    """Of the k best picks (highest score first), the share that hit. Fewer than k picks counts as misses."""
    top = sorted(picks, key=lambda p: -float(p.get("score", 0)))[:k]
    return matched(top, humans) / k if k > 0 else 0.0


def recall(picks, humans) -> float:
    """Of the human picks, the share that some pick found."""
    return sum(is_hit(h, picks) for h in humans) / len(humans) if humans else 0.0


def agreement(a, b) -> float:
    """How much two people agree: the average of 'share of A found in B' and 'share of B found in A'."""
    if not a or not b:
        return 0.0
    return (sum(is_hit(x, b) for x in a) / len(a) + sum(is_hit(y, a) for y in b) / len(b)) / 2


def human_union(annotators) -> list:
    """Spans either person picked, with near-copies folded together, so a pick matching one of them counts."""
    out = []
    for span in sorted((s for a in annotators for s in a), key=lambda s: s["start"]):
        if not any(overlap_share(span, o) >= 0.5 for o in out):
            out.append(span)
    return out


def bootstrap_ci(values, n=2000, seed=1, alpha=0.05):
    """(mean, low, high) of the mean over videos. A fixed seed, so the same data always gives the same answer."""
    v = np.asarray(list(values), dtype=float)
    if len(v) == 0:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(float(np.mean([v[rng.randrange(len(v))] for _ in range(len(v))])) for _ in range(n))
    return float(v.mean()), means[int(alpha / 2 * n)], means[min(n - 1, int((1 - alpha / 2) * n))]


def per_hour(amount, duration_s) -> float:
    return amount / (duration_s / 3600) if duration_s > 0 else 0.0


def load_video(folder: Path) -> dict:
    """One labelled video: words.json, labels.json, meta.json and (optional) loudness.json."""
    folder = Path(folder)
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8")) if (folder / "meta.json").is_file() else {}
    words = json.loads((folder / "words.json").read_text(encoding="utf-8"))
    labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    duration = float(meta.get("duration") or (max((w["e"] for w in words), default=0) + 1))
    loud = folder / "loudness.json"
    db = np.array(json.loads(loud.read_text(encoding="utf-8")), dtype=float) if loud.is_file() else np.zeros(int(duration) + 1)
    return {"name": folder.name, "meta": meta, "words": words, "db": db, "duration": duration, "annotators": labels["annotators"]}


def load_set(root: Path) -> list:
    return [load_video(f) for f in sorted(Path(root).iterdir()) if (f / "words.json").is_file() and (f / "labels.json").is_file()]
