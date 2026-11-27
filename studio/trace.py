"""A paper trail for each video: what was heard, and exactly what the AI was asked and answered.

Written into the video's own folder, in `trace/`:
  transcript.txt   the words, with times, as written by the speech model (or borrowed from YouTube), so you can play the video
                   and check by ear whether it was heard right
  ai-001-....txt   one file per question to the AI: the full prompt, the model that answered, and its reply

Why it is a separate place from the activity log: these files hold the text of the video, so they stay with the video and are
deleted with it. The activity log only says that a file was written.

Default: on when ViralCut is used by one person (no sign-in), off on a shared site (it would keep other people's text).
PEAKCUT_TRACE=1 or 0 overrides.
"""
import re
import threading
from pathlib import Path

from . import applog, config

_here = threading.local()
MAX_FILES = 300


def enabled() -> bool:
    v = str(config.env("PEAKCUT_TRACE", "") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return not config.ACCOUNTS


def use(job_dir):
    """The video the work on this thread belongs to (None to stop)."""
    _here.dir = Path(job_dir) / "trace" if job_dir else None


def folder():
    d = getattr(_here, "dir", None)
    return d if d and enabled() else None


def _stamp(sec):
    sec = max(0.0, float(sec))
    return f"{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:{sec % 60:04.1f}"


def transcript(words, header: dict):
    """(Re)writes transcript.txt. Called each time more of the video has been heard."""
    d = folder()
    if not d:
        return
    try:
        d.mkdir(parents=True, exist_ok=True)
        lines, cur, last_end = [], [], None
        for w in words:
            if cur and (w["s"] - last_end > 0.8 or len(cur) >= 14):
                lines.append(cur)
                cur = []
            cur.append(w)
            last_end = w["e"]
        if cur:
            lines.append(cur)
        head = [f"{k}: {v}" for k, v in header.items() if v not in (None, "")]
        body = [f"[{_stamp(l[0]['s'])}] " + " ".join(str(w.get("w", "")) for w in l) for l in lines]
        (d / "transcript.txt").write_text("\n".join(head + [f"words: {len(words)}", "", *body]) + "\n", encoding="utf-8")
    except OSError as e:
        applog.log("trace.failed", "warning", error=repr(e))


def exchange(purpose, prompt, reply=None, model="", tokens=0, ms=0, note="", error=""):
    """One question to the AI and what came back."""
    d = folder()
    if not d:
        return
    try:
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.glob("ai-*.txt"))) + 1
        if n > MAX_FILES:
            return
        slug = re.sub(r"-+", "-", "".join(c if c.isalnum() else "-" for c in purpose.lower())).strip("-")[:30] or "call"
        f = d / f"ai-{n:03d}-{slug}.txt"
        import json
        out = [f"purpose: {purpose}", f"model: {model}", f"tokens: {tokens}", f"ms: {ms}", f"note: {note}" if note else "",
               f"error: {error}" if error else "", "", "=== PROMPT ===", prompt, "", "=== REPLY ===",
               json.dumps(reply, ensure_ascii=False, indent=1) if reply is not None else "(none)"]
        f.write_text("\n".join(x for x in out if x is not None) + "\n", encoding="utf-8")
        applog.log("trace.ai", file=f.name, prompt_chars=len(prompt), answered=reply is not None, model=model)
    except OSError as e:
        applog.log("trace.failed", "warning", error=repr(e))
