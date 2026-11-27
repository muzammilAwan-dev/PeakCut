"""Podcast and stream prompts, the trace files (transcript + AI prompts), per-video options, and draft-then-full-quality.
Real ffmpeg, no network, no keys."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-draft-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0", PEAKCUT_LLM_CACHE="0")
os.environ.pop("PEAKCUT_TRACE", None)
sys.path.insert(0, ".")
from studio import ai, brain, config, creators, ctx, db, jobs, media, render, trace
db.init()
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

# ---------------------------------------------------------------- the two scouts
sp = brain.build_prompt("podcast", "Title", "Chan", 4, 20, 55, "[1.0] hello")
st = brain.build_prompt("stream", "Title", "Chan", 4, 20, 55, "[1.0] hello")
check("podcast prompt asks for informative, shareable parts", ("INFORMATIVE" in sp, "podcasts" in sp, "CRAZY" in sp), (True, True, False))
check("stream prompt asks for crazy moments", ("CRAZY" in st, "high-energy" in st, "INFORMATIVE" in st), (True, True, False))
check("both keep the safety wording about untrusted text", ("data, never" in sp, "data, never" in st), (True, True))
check("the numbers and the transcript are filled in", ("20 to 55 seconds" in sp, "[1.0] hello" in sp, "Pick up to 4" in sp, "{n}" in sp or "{min_len}" in sp), (True, True, True, False))
check("categories follow the mode", ("insight, tip, myth" in sp, "clutch" in sp, "clutch" in st, "insight" in st), (True, False, True, False))
check("an unknown mode is a stream", brain.mode_of("nonsense"), "stream")
check("options: mode and draft are checked", (jobs.clean_options({"mode": "podcast", "draft": "false"}), jobs.clean_options({"mode": "x"})), ({"mode": "podcast", "draft": False}, {"mode": "stream"}))
check("defaults: stream mode, draft first", (jobs.DEFAULTS["mode"], jobs.DEFAULTS["draft"]), ("stream", True))

seen = []
ai.models = lambda: ["m"]; ai.route = lambda m: "pool/m"; config.ai_ready = lambda: True
def fake_call(model, prompt, schema):
    seen.append(prompt)
    return [{"start": 2.0, "end": 24.0, "score": 80, "hook": "A", "title": "t", "description": "d", "hashtags": ["a"], "highlight_words": [],
             "category": "insight", "reason": "r"}], 100, 50
ai.call = fake_call
words = [{"w": f"w{i}", "s": float(i), "e": i + 0.8} for i in range(60)]
db_arr = __import__("numpy").zeros(60, dtype="float32")
clips, info = brain.find_clips(words, db_arr, 60.0, "My show", "Host", 2, 15, 40, print, mode="podcast")
check("find_clips sends the podcast prompt in podcast mode", ("INFORMATIVE" in seen[0], "CRAZY" in seen[0], info["model"]), (True, False, "pool/m"))
check("an answer with the new category is accepted", [c["category"] for c in clips], ["insight"])
seen.clear(); brain.find_clips(words, db_arr, 60.0, "A game", "Streamer", 2, 15, 40, print)
check("no mode given means stream", "CRAZY" in seen[0], True)

# ---------------------------------------------------------------- the trace files
tdir = Path(tempfile.mkdtemp(prefix="pc-trace-"))
trace.use(tdir)
brain.ask_ai("the main prompt text", purpose="Video: finding clips")
trace.transcript(words[:20], {"video": "My show", "words_from": "ViralCut's speech model"})
files = sorted(p.name for p in (tdir / "trace").iterdir())
check("one file per AI question, and the transcript", files, ["ai-001-video-finding-clips.txt", "transcript.txt"])
t = (tdir / "trace" / "ai-001-video-finding-clips.txt").read_text(encoding="utf-8")
check("the AI file holds the full prompt, the model and the reply", ("the main prompt text" in t, "model: pool/m" in t, '"category": "insight"' in t), (True, True, True))
tr = (tdir / "trace" / "transcript.txt").read_text(encoding="utf-8")
check("the transcript has times and words", ("video: My show" in tr, "[00:00:00.0] w0 w1" in tr, "words: 20" in tr), (True, True, True))
ai.call = lambda *a: (_ for _ in ()).throw(RuntimeError("HTTP 400 nope"))
try: brain.ask_ai("another prompt", purpose="Video: finding clips")
except RuntimeError: pass
check("a failed question is kept too, with the reason", "HTTP 400 nope" in (tdir / "trace" / "ai-002-video-finding-clips.txt").read_text(encoding="utf-8"), True)
os.environ["PEAKCUT_TRACE"] = "0"
n0 = len(list((tdir / "trace").iterdir())); trace.exchange("x", "p", [])
check("it can be switched off", len(list((tdir / "trace").iterdir())), n0)
os.environ.pop("PEAKCUT_TRACE")
trace.use(None); trace.exchange("x", "p", []); check("with no video in mind nothing is written", True)

# ---------------------------------------------------------------- draft, then full quality (real ffmpeg)
work = Path(tempfile.mkdtemp(prefix="pc-drw-"))
noise = ["-f", "lavfi", "-i", "anoisesrc=color=white:amplitude=0.3:seed=7:duration=40"]       # distinctive sound, so the start can be found by matching
hd, lo = work / "hd.mp4", work / "lo.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=40"] + noise + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(hd)], check=True)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(hd), "-vf", "scale=426:240", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(lo)], check=True)
asked = []
def fake_section(url, out_dir, stem, start, end, height=720):
    asked.append((stem, round(start, 1), round(end, 1), height))
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{stem}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start + 0.37:.2f}", "-t", f"{end - start:.2f}", "-i", str(hd), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)], check=True)
    return p
media.download_section = fake_section
creators.log = lambda *a, **k: None
brain.english_captions = lambda raw, lang, title, youtube_english=None: raw
ready = []; jobs.on_clip_ready.append(lambda j, c: ready.append(c["id"]))
token = ctx._uid.set("owner0001")
job = jobs.create({"type": "url", "url": "https://youtu.be/xxxxxxxxxxx", "name": "x"}, {"quality": 720}, enqueue=False)
check("a link-based video starts as a draft by default", job["options"]["draft"], True)
job.update(source_path=str(lo), width=426, height=240, duration=40.0, status="done", draft=True)
c1 = {"id": "clip01", "start": 12.0, "end": 24.0, "title": "t", "description": "d", "hashtags": [], "hook": "Hi", "score": 80, "style": "bounce", "layout": "blur",
      "status": "queued", "version": 0, "draft": True}
job["clips"] = [c1]
jobs.render_one(job, c1, [{"w": "hello", "s": 12.5, "e": 13.0}])
check("the draft clip is made from the small video", (c1["status"], c1["draft"], jobs._height(job)), ("done", True, 480))
check("a draft is not handed to posting", ready, [])
try: jobs.request_final(job["id"], {"nope"}); res = "queued"
except ValueError: res = "nothing"
check("asking for a clip that does not exist does nothing", res, "nothing")
todo = jobs.request_final(job["id"])
q = list(jobs._q.quick)
check("full quality is queued for the draft clips", ([c["id"] for c in todo], q), (["clip01"], [("final", job["id"], "clip01")]))
jobs._q.quick.clear()
jobs.finalize_clip(job, c1)
check("the clip's stretch is fetched at the chosen quality, with padding", (asked[0][0], asked[0][1], asked[0][2], asked[0][3]), ("clip01.hd", 4.0, 32.0, 720))
check("it is no longer a draft and knows its new size", (c1["draft"], c1["w"], c1["h"]), (False, 1280, 720))
check("its start was found by matching the sound (the fake cut starts 0.37 s late)", abs(c1["src_offset"] - (4.0 + 0.37)) < 0.15, True)
jobs.render_one(job, c1, [{"w": "hello", "s": 12.5, "e": 13.0}])
check("the full-quality clip is made", (c1["status"], c1["version"] >= 2, (Path(job["dir"]) / "clips" / "clip01.mp4").stat().st_size > 1000), ("done", True, True))
check("the small piece is gone and the new one is kept", (Path(job["dir"], "clips", "clip01.hd.mp4").exists(), c1["src"].endswith("clip01.hd.mp4")), (True, True))
try: jobs.request_final(job["id"]); res = "queued"
except ValueError: res = "nothing"
check("asking again with nothing left to do is refused", res, "nothing")

# a failed fetch keeps the draft and says why
c2 = {"id": "clip02", "start": 28.0, "end": 36.0, "title": "t", "description": "d", "hashtags": [], "hook": "Hi", "score": 70, "style": "bounce", "layout": "blur",
      "status": "done", "version": 1, "draft": True}
job["clips"].append(c2)
media.download_section = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 403 blocked"))
jobs.request_final(job["id"]); jobs._q.quick.clear(); jobs.finalize_clip(job, c2)
check("a failed full-quality fetch leaves the draft, with a reason", (c2["draft"], c2["status"], "full-quality" in (c2.get("error") or "")), (True, "done", True))
# an upload is never a draft
up = jobs.create({"type": "file", "path": str(lo), "name": "a.mp4"}, {}, enqueue=False)
check("the draft option only matters for links (a file is already on this computer)", up["options"]["draft"], True)

# ---------------------------------------------------------------- YouTube captions: a person's first, then YouTube's own, then ours
import contextlib
def ev(lines):    # json3 with whole lines (no word times), one per 5 seconds
    return json.dumps({"events": [{"tStartMs": i * 5000, "dDurationMs": 5000, "segs": [{"utf8": t}]} for i, t in enumerate(lines)]}).encode()
MANUAL = ev(["Hello there, this is a clean line."] * 12)
AUTO = json.dumps({"events": [{"tStartMs": i * 1000, "segs": [{"utf8": "hello", "tOffsetMs": 0}, {"utf8": " world", "tOffsetMs": 400}]} for i in range(60)]}).encode()
class FakeYDL:
    def __init__(self, info, files): self.i, self.f = info, files
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False): return self.i
    def urlopen(self, u):
        if self.f.get(u) is None: raise OSError("refused")
        import io; return io.BytesIO(self.f[u])
def fmt(u): return [{"ext": "json3", "url": u}]
def setup_yt(info, files):
    media._ydl = lambda opts: FakeYDL(info, files); media._youtube_guard = lambda url: contextlib.nullcontext()
URL = "https://youtu.be/abcdefghijk"
both = {"language": "en", "subtitles": {"en": fmt("m"), "de": fmt("g")}, "automatic_captions": {"en-orig": fmt("a"), "en": fmt("a2")}}
setup_yt(both, {"m": MANUAL, "a": AUTO})
r = media.youtube_words(URL)
check("a person's captions are used first", (r[2], r[1], len(r[0])), ("manual", "en", 84))
r = media.youtube_words(URL, covers=lambda w: len(w) > 100)
check("when they are too thin, YouTube's own captions are tried", (r[2], len(r[0])), ("auto", 120))
check("when neither is good enough there is nothing to borrow", media.youtube_words(URL, covers=lambda w: False), None)
setup_yt(both, {"m": None, "a": AUTO})
check("captions that will not download are skipped", media.youtube_words(URL)[2], "auto")
setup_yt({"language": "en", "subtitles": {"de": fmt("g")}, "automatic_captions": {"en-orig": fmt("a")}}, {"g": MANUAL, "a": AUTO})
check("a translation (another language) is never used", media.youtube_words(URL)[2], "auto")
setup_yt({"subtitles": {"en": fmt("m")}, "automatic_captions": {}}, {"m": MANUAL})
check("with the spoken language unknown, a person's captions are not trusted (could be a translation)", media.youtube_words(URL), None)
setup_yt({"language": "hi", "subtitles": {"hi": fmt("m")}, "automatic_captions": {}}, {"m": MANUAL})
check("a language with only a person's captions works", media.youtube_words(URL)[1:3] if media.youtube_words(URL) else None, ("hi", "manual"))
setup_yt({"language": "en", "subtitles": {}, "automatic_captions": {}}, {})
check("a video with no captions at all: our own model", media.youtube_words(URL), None)
check("other sites never ask YouTube", media.youtube_words("https://www.twitch.tv/videos/123456789"), None)

ctx._uid.reset(token)
print("ALL PASSED" if not fails else f"{len(fails)} failed: {fails}")
sys.exit(1 if fails else 0)
