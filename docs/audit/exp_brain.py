"""Experiments against studio/brain.py with network libs stubbed (pip blocked here). Reads the repo, changes nothing."""
import sys, os, tempfile
from unittest.mock import MagicMock
for n in ("httpx","sqlalchemy","sqlalchemy.event","soundfile","psycopg","yt_dlp","sherpa_onnx"):
    sys.modules[n] = MagicMock()
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="exp-")  # run from the repo root
sys.path.insert(0, ".")
import numpy as np
from studio import brain

words = [{"w": f"w{i}", "s": i*0.5, "e": i*0.5+0.4} for i in range(240)]   # 2 minutes of talk
log = []

# Experiment A: one clip in the AI's answer has start = null (a model slip). Does the window survive, and does the loudness fallback fire?
brain.config.ai_ready = lambda: True
def bad_ai(prompt, schema=None, purpose=""):
    return [{"start": None, "end": 30, "score": 90, "hook":"X","title":"t","description":"d","hashtags":[],"reason":"r"},
            {"start": 20, "end": 50, "score": 80, "hook":"OK","title":"t","description":"d","hashtags":[],"reason":"r"}], "m", 10
brain.ask_ai = bad_ai
clips, info = brain.find_clips(words, np.zeros(120), 120.0, log=log.append)
print("A) clips:", len(clips), "| info:", info, "| log:", log)

# Experiment B: same, but the model answers with a bare object instead of a list (some chat models do)
brain.ask_ai = lambda *a, **k: ({"oops": 1}, "m", 5)
log.clear()
clips, info = brain.find_clips(words, np.zeros(120), 120.0, log=log.append)
print("B) clips:", len(clips), "| info:", info, "| log:", log)

# Experiment C: how many tokens is a 15-minute window? (chars/3.5 heuristic from the plan)
talk = [{"w": w, "s": i*0.4, "e": i*0.4+0.3} for i, w in enumerate(("the quick brown fox jumps over a lazy dog and then something else happens ".split())*150)]
lines = brain.make_lines([w for w in talk if w["s"] < 900])
prompt = brain.HEAD.format(title="T", uploader="U", n=4) + brain.RULES.format(min_len=15, max_len=60, transcript=brain._fmt(lines))
print(f"C) 15-min window at ~150 wpm: {len(prompt)} chars, ~{len(prompt)/3.5:.0f} tokens (chars/3.5), words in window: {sum(1 for w in talk if w['w'] and w['s']<900)}")
