"""S4: the answer cache, the clip fingerprint (nothing is remade when nothing changed), all-or-nothing output files,
stopping a video, and the supervisor. Real ffmpeg, no network, no keys."""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-s4-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0")
os.environ.pop("PEAKCUT_LLM_CACHE", None)
sys.path.insert(0, ".")
from studio import ai, brain, config, creators, ctx, db, jobs, llmcache, render
db.init()
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

# ---------------------------------------------------------------- the answer cache
S = brain.SCHEMA
check("cache: nothing stored yet", llmcache.get("p1", S), None)
llmcache.put("p1", S, [{"a": 1}], "grp/m", 40)
check("cache: an answer comes back", llmcache.get("p1", S), ([{"a": 1}], "grp/m"))
check("cache: another prompt or another shape is a different entry", (llmcache.get("p2", S), llmcache.get("p1", {"x": 1})), (None, None))
os.environ["PEAKCUT_LLM_CACHE"] = "0"
check("cache: can be switched off", (llmcache.get("p1", S), llmcache.enabled()), (None, False))
os.environ.pop("PEAKCUT_LLM_CACHE")
old_ttl = llmcache.TTL; llmcache.TTL = -1
check("cache: an old answer is not used", llmcache.get("p1", S), None); llmcache.TTL = old_ttl
old_max = llmcache.MAX_ROWS; llmcache.MAX_ROWS = 3
for i in range(6): llmcache.put(f"q{i}", S, [i], "m"); time.sleep(0.01)
check("cache: only the newest are kept", (llmcache.get("q5", S) is not None, llmcache.get("q0", S)), (True, None)); llmcache.MAX_ROWS = old_max
check("cache: clear says how many it removed", llmcache.clear() >= 3, True)

calls = []
good = [{"start": 1, "end": 20, "score": 80, "hook": "H", "title": "T", "description": "D", "hashtags": ["a"], "reason": "R"}]
ai.call = lambda model, prompt, schema: (calls.append(prompt) or (good, 100, 20))
ai.models = lambda: ["m"]
ai.route = lambda m: "pool/m"
config.ai_ready = lambda: True
out1 = brain.ask_ai("find clips in this", purpose="Video: finding clips")
out2 = brain.ask_ai("find clips in this", purpose="Video: finding clips")
check("ask_ai: the same question is asked once", (len(calls), out2[0] == out1[0], out2[1], out2[2]), (1, True, "pool/m", 0))
brain.ask_ai("a live moment", purpose="Live check"); brain.ask_ai("a live moment", purpose="Live check")
check("ask_ai: live checks are never cached", len(calls), 3)
ai.call = lambda *a: (_ for _ in ()).throw(RuntimeError("HTTP 400 nope"))
try: brain.ask_ai("new question", purpose="Video: finding clips"); res = "answered"
except RuntimeError: res = "failed"
check("ask_ai: a failure is not stored", (res, llmcache.get("new question", S)), ("failed", None))

# ---------------------------------------------------------------- real ffmpeg: a small test video
work = Path(tempfile.mkdtemp(prefix="pc-s4w-"))
vid = work / "in.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=8", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(vid)], check=True)
clip = {"start": 1.0, "end": 6.0, "layout": "blur", "style": "bounce", "hook": "Hi", "highlight_words": []}
words = [{"w": "hello", "s": 1.2, "e": 1.6}, {"w": "world", "s": 1.7, "e": 2.2}]
r0 = render.revision(vid, clip, words, 640, 360)
check("revision: stable for the same input", render.revision(vid, dict(clip), list(words), 640, 360), r0)
check("revision: changes with the times, the style, the layout, the hook, a word and the source size",
      len({r0, render.revision(vid, {**clip, "start": 1.5}, words, 640, 360), render.revision(vid, {**clip, "style": "x"}, words, 640, 360),
           render.revision(vid, {**clip, "layout": "fit"}, words, 640, 360), render.revision(vid, {**clip, "hook": "Yo"}, words, 640, 360),
           render.revision(vid, clip, [{"w": "hello", "s": 1.2, "e": 1.6}, {"w": "there", "s": 1.7, "e": 2.2}], 640, 360), render.revision(vid, clip, words, 1280, 720)}), 7)

# ---------------------------------------------------------------- output files: staged first, no stray files
out = work / "clips"; out.mkdir()
w1 = work / "w1"; w1.mkdir()
for ext, text in (("mp4", "v1"), ("jpg", "c1"), ("ass", "s1")): (w1 / f"c.{ext}").write_text(text)
render.commit(w1, out, "c")
check("commit: all three files arrive", sorted(p.name for p in out.iterdir()), ["c.ass", "c.jpg", "c.mp4"])
w2 = work / "w2"; w2.mkdir()
for ext, text in (("mp4", "v2"), ("jpg", "c2"), ("ass", "s2")): (w2 / f"c.{ext}").write_text(text)
real_replace, n = os.replace, [0]
def flaky(a, b):
    n[0] += 1
    if n[0] == 2: raise OSError("disk trouble")
    return real_replace(a, b)
render.os.replace = flaky
try: render.commit(w2, out, "c"); res = "ok"
except OSError: res = "failed"
render.os.replace = real_replace
check("commit: a failure half way leaves no stray .new files", (res, sorted(p.name for p in out.iterdir())), ("failed", ["c.ass", "c.jpg", "c.mp4"]))
# a rename cannot be undone: the fingerprint is saved only after all of them worked, so the next make repairs this
render.commit(w2, out, "c")
check("commit: a clean second run replaces everything", [(out / f"c.{e}").read_text() for e in ("mp4", "jpg", "ass")], ["v2", "c2", "s2"])
(out / "x.mp4.new").write_text("half"); (out / "sub").mkdir(); (out / "sub" / "y.jpg.new").write_text("half")
check("leftovers: half-written files are removed", (render.clean_leftovers(out), [p.name for p in out.glob("**/*.new")]), (2, []))

# ---------------------------------------------------------------- a clip is made once, then left alone
creators.log = lambda *a, **k: None
brain.english_captions = lambda raw, lang, title, youtube_english=None: raw
made = []
real_render = render.render_clip
render.render_clip = lambda *a, **k: (made.append(1) or real_render(*a, **k))
token = ctx._uid.set("owner0001")
job = jobs.create({"type": "file", "path": str(vid), "name": "in.mp4"}, {}, enqueue=False)
job.update(source_path=str(vid), width=640, height=360, duration=8.0, status="running")
c1 = {"id": "clip01", "start": 1.0, "end": 6.0, "title": "t", "description": "d", "hashtags": [], "hook": "Hi", "score": 80, "style": "bounce", "layout": "blur",
      "status": "queued", "version": 0}
job["clips"] = [c1]
jobs.render_one(job, c1, words)
check("first make: the clip is made", (c1["status"], made, bool(c1.get("rev")), (Path(job["dir"]) / "clips" / "clip01.mp4").stat().st_size > 1000), ("done", [1], True, True))
v1 = c1["version"]
c1["status"] = "queued"; jobs.render_one(job, c1, words)
check("second make with nothing changed: no new render, still done", (c1["status"], made, c1["version"]), ("done", [1], v1))
c1.update(status="queued", hook="Changed"); jobs.render_one(job, c1, words)
check("a changed hook makes a new render", (len(made), c1["version"]), (2, v1 + 1))
(Path(job["dir"]) / "clips" / "clip01.jpg").unlink()
c1["status"] = "queued"; jobs.render_one(job, c1, words)
check("a missing file is made again even with the same fingerprint", (len(made), c1["status"]), (3, "done"))
render.render_clip = real_render

# ---------------------------------------------------------------- undo one edit
clips_dir = Path(job["dir"]) / "clips"
(clips_dir / "clip01.mp4").write_bytes(b"OLD-VIDEO"); (clips_dir / "clip01.jpg").write_bytes(b"OLD-COVER")
c1.update(status="done", hook="Old hook"); job["status"] = "done"
check("undo: nothing to undo before any edit", jobs.undo_clip(job["id"], "clip01"), False)
jobs.request_render(job["id"], "clip01", {"hook": "New hook"})
check("undo: an edit sets the old version aside", (c1["prev"]["hook"], (clips_dir / "_prev" / "clip01.mp4").read_bytes(), c1["status"]), ("Old hook", b"OLD-VIDEO", "queued"))
(clips_dir / "clip01.mp4").write_bytes(b"NEW-VIDEO"); (clips_dir / "clip01.jpg").write_bytes(b"NEW-COVER"); c1["status"] = "done"
check("undo: not offered while a clip is still being made", (lambda: (c1.update(status="rendering"), jobs.undo_clip(job["id"], "clip01"), c1.update(status="done"))[1])(), False)
check("undo: the public view says it can be undone, and never shows the stored copy", ("prev" in jobs.public(job)["clips"][0], jobs.public(job)["clips"][0]["can_undo"]), (False, True))
v_before = c1["version"]
check("undo: goes back", (jobs.undo_clip(job["id"], "clip01"), c1["hook"], (clips_dir / "clip01.mp4").read_bytes(), (clips_dir / "clip01.jpg").read_bytes(), c1["version"] > v_before), (True, "Old hook", b"OLD-VIDEO", b"OLD-COVER", True))
check("undo: again brings the edit back", (jobs.undo_clip(job["id"], "clip01"), c1["hook"], (clips_dir / "clip01.mp4").read_bytes()), (True, "New hook", b"NEW-VIDEO"))
check("undo: no stray swap files", [p.name for p in (clips_dir / "_prev").glob("*.swap")], [])

# ---------------------------------------------------------------- stopping a video
j2 = jobs.create({"type": "file", "path": str(vid), "name": "b.mp4"}, {}, enqueue=False)
check("cancel: a video waiting in line stops at once", (jobs.cancel(j2["id"], "owner0001"), j2["status"], j2["error"]), (True, "error", "Stopped by you."))
check("cancel: stopping again does nothing", jobs.cancel(j2["id"], "owner0001"), False)
j3 = jobs.create({"type": "file", "path": str(vid), "name": "c.mp4"}, {}, enqueue=False); j3["status"] = "running"
check("cancel: somebody else cannot stop it", jobs.cancel(j3["id"], "other00002"), False)
check("cancel: the owner can", jobs.cancel(j3["id"], "owner0001"), True)
try: jobs._set(j3, stage="next step"); res = "went on"
except jobs.Cancelled as e: res = str(e)
check("cancel: a running video stops at its next step", res, "Stopped by you.")
try: jobs._check(j3); res = "went on"
except jobs.Cancelled: res = "stopped"
check("cancel: checked between steps too", res, "stopped")
j4 = jobs.create({"type": "file", "path": str(vid), "name": "d.mp4"}, {}, enqueue=False); j4["status"] = "done"
check("cancel: a finished video cannot be stopped", jobs.cancel(j4["id"], "owner0001"), False)

# ---------------------------------------------------------------- the supervisor
j5 = jobs.create({"type": "file", "path": str(vid), "name": "e.mp4"}, {}, enqueue=False); j5.update(status="running", beat=time.time())
j6 = jobs.create({"type": "file", "path": str(vid), "name": "f.mp4"}, {}, enqueue=False); j6.update(status="running", beat=time.time() - jobs.STALL - 5)
stopped = jobs.supervise_once()
check("supervisor: only the stuck video is stopped", (j6["id"] in stopped, j5["id"] in stopped, bool(j6.get("cancel")), bool(j5.get("cancel"))), (True, False, True, False))
check("supervisor: and its reason says what happened", "stopped responding" in j6["cancel_reason"], True)
ctx._uid.reset(token)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
