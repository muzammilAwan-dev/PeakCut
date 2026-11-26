"""Scores clip-picking systems against clips that people picked.
  python tools/eval.py DIR [--systems loudness,current] [--k 5,10] [--runs 3] [--json OUT]
  python tools/eval.py --demo            (a small made-up set, to see how it works)
Each video is a folder in DIR with words.json, labels.json, meta.json and optionally loudness.json (see docs/EVAL.md)."""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import brain, evalkit  # noqa: E402


def sys_loudness(v, max_clips):
    return brain.fallback_by_loudness(v["db"], v["words"], max_clips, 60, v["duration"], 15), {}


def sys_current(v, max_clips):
    return brain.find_clips(v["words"], v["db"], v["duration"], v["meta"].get("title", ""), v["meta"].get("uploader", ""), max_clips, 15, 60, lambda m: None)


SYSTEMS = {"loudness": sys_loudness, "current": sys_current}      # add a new way of picking clips here


def evaluate(videos, systems, ks, runs=1, max_clips=10):
    result = {}
    for name in systems:
        rows = []
        for v in videos:
            humans = evalkit.human_union(v["annotators"])
            per_run = []
            for _ in range(runs):
                t0 = time.time()
                picks, info = SYSTEMS[name](v, max_clips)
                per_run.append({"prec": {k: evalkit.precision_at_k(picks, humans, k) for k in ks}, "recall": evalkit.recall(picks, humans),
                                "tokens": info.get("tokens", 0), "seconds": time.time() - t0, "model": info.get("model")})
            rows.append({"video": v["name"], "duration": v["duration"], "runs": per_run,
                         "prec": {k: float(np.mean([r["prec"][k] for r in per_run])) for k in ks},
                         "spread": {k: float(np.std([r["prec"][k] for r in per_run])) for k in ks},
                         "recall": float(np.mean([r["recall"] for r in per_run])),
                         "tokens": float(np.mean([r["tokens"] for r in per_run]))})
        total_h = sum(r["duration"] for r in rows)
        result[name] = {"rows": rows,
                        "summary": {f"p@{k}": evalkit.bootstrap_ci([r["prec"][k] for r in rows]) for k in ks}
                                   | {"recall": evalkit.bootstrap_ci([r["recall"] for r in rows]),
                                      "tokens_per_hour": evalkit.per_hour(sum(r["tokens"] for r in rows), total_h),
                                      "run_to_run_spread": float(np.mean([r["spread"][ks[0]] for r in rows]))}}
    return result


def report(result, ks):
    lines = []
    for name, r in result.items():
        lines.append(f"\n== {name} ==")
        lines.append(f"{'video':28}" + "".join(f"{'p@' + str(k):>8}" for k in ks) + f"{'recall':>8}{'tokens':>9}")
        for row in r["rows"]:
            lines.append(f"{row['video'][:27]:28}" + "".join(f"{row['prec'][k]:8.2f}" for k in ks) + f"{row['recall']:8.2f}{row['tokens']:9.0f}")
        s = r["summary"]
        for k in ks:
            m, lo, hi = s[f"p@{k}"]
            lines.append(f"mean p@{k}: {m:.2f}  (95% range {lo:.2f} to {hi:.2f})")
        m, lo, hi = s["recall"]
        lines.append(f"mean recall: {m:.2f}  (95% range {lo:.2f} to {hi:.2f})   tokens per hour of video: {s['tokens_per_hour']:.0f}   run-to-run spread: {s['run_to_run_spread']:.3f}")
    return "\n".join(lines)


def make_demo(root: Path):
    """Three small made-up videos: speech all the way through, one loud talkative stretch each, and two 'people' picking it."""
    rng = np.random.RandomState(7)
    for i, hot in enumerate((120, 400, 700)):
        d = root / f"demo{i + 1}"
        d.mkdir(parents=True)
        dur = 900
        words, t = [], 0.0
        while t < dur - 1:
            w = ("wow!" if hot <= t < hot + 30 and int(t) % 2 == 0 else "word") + ("." if int(t * 2) % 8 == 7 else "")
            words.append({"w": w, "s": round(t, 2), "e": round(t + 0.4, 2)})
            t += 0.5 if hot <= t < hot + 30 else 0.9
        db = rng.normal(-30, 1, dur)
        db[hot: hot + 30] += 18
        (d / "words.json").write_text(json.dumps(words), encoding="utf-8")
        (d / "loudness.json").write_text(json.dumps([round(float(x), 2) for x in db]), encoding="utf-8")
        (d / "meta.json").write_text(json.dumps({"title": "demo", "duration": dur, "genre": "demo", "language": "en"}), encoding="utf-8")
        (d / "labels.json").write_text(json.dumps({"annotators": [[{"start": hot - 2, "end": hot + 33}], [{"start": hot + 1, "end": hot + 29}]]}), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--systems", default="loudness")
    ap.add_argument("--k", default="5,10")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--json")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args(argv)
    if a.demo:
        a.dir = tempfile.mkdtemp(prefix="pc-evaldemo-")
        make_demo(Path(a.dir))
    if not a.dir:
        ap.error("give a folder, or use --demo")
    systems = [s for s in a.systems.split(",") if s]
    bad = [s for s in systems if s not in SYSTEMS]
    if bad:
        ap.error(f"unknown system {bad}; choose from {', '.join(SYSTEMS)}")
    ks = [int(x) for x in a.k.split(",")]
    videos = evalkit.load_set(Path(a.dir))
    if not videos:
        ap.error("no labelled videos found (each folder needs words.json and labels.json)")
    ag = [evalkit.agreement(v["annotators"][0], v["annotators"][1]) for v in videos if len(v["annotators"]) >= 2]
    result = evaluate(videos, systems, ks, a.runs)
    print(report(result, ks))
    if ag:
        print(f"\nHow much the two people agree with each other: {np.mean(ag):.2f} (1 = always). Scores above this are not meaningful.")
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
