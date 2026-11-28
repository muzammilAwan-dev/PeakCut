"""Finds out, on this computer, what YouTube lets ViralCut do. Run it with the app's Python:

    .venv\\Scripts\\python.exe tools\\yt_check.py [video link]

It tries one video as a visitor and then with each browser you are signed in to, tries to fetch the video's captions
(the ones the owner wrote, then YouTube's own), and writes a plain report to yt-check.txt. No cookie, key or password is
printed or saved. Send yt-check.txt back so the app can be tuned from real results. Takes about a minute."""
import importlib.metadata as md
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import applog  # noqa: E402
from studio.media import TEST_VIDEOS  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else ""
out = []


def say(line=""):
    print(line)
    out.append(line)


def short(e):
    return applog.clean(str(e).replace("\n", " "), 160)


def version(pkg):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return "not installed"


def ydl(extra):
    import yt_dlp
    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20, **extra})


GONE = ("unavailable", "private video", "has been removed", "not available in your country")


def try_info(label, extra):
    """Reads the video (or, with no link given, the first of a few public videos that this country can see)."""
    global URL
    t = time.time()
    last = None
    for link in ([URL] if URL else ["https://www.youtube.com/watch?v=" + v for v in TEST_VIDEOS]):
        try:
            with ydl(extra) as y:
                i = y.extract_info(link, download=False)
            URL = link
            say(f"{label:<10} OK    {time.time() - t:4.1f}s  {str(i.get('title'))[:50]}")
            return i
        except Exception as e:  # noqa: BLE001
            last = e
            if not any(g in str(e).lower() for g in GONE):
                break
    say(f"{label:<10} FAIL  {time.time() - t:4.1f}s  {short(last)}")
    return None


def captions(info, extra):
    manual, auto = info.get("subtitles") or {}, info.get("automatic_captions") or {}
    spoken = next((k for k in auto if k.endswith("-orig")), "") or info.get("language") or "unknown"
    say(f"spoken language: {spoken}; captions written by a person: {', '.join(sorted(manual)[:10]) or 'none'}; "
        f"YouTube's own: {', '.join(sorted(auto)[:5]) or 'none'}{' ...' if len(auto) > 5 else ''}")
    base = spoken.split("-")[0].replace("-orig", "")
    wanted = []
    mk = next((k for k in sorted(manual) if k.split("-")[0] == base), None)
    if mk:
        wanted.append(("person", mk, manual[mk]))
    ak = next((k for k in auto if k.endswith("-orig")), None) or (spoken if spoken in auto else None)
    if ak:
        wanted.append(("youtube", ak, auto[ak]))
    if not wanted:
        say("no captions to fetch: ViralCut would use its own speech model")
    for kind, k, fmts in wanted:
        track = next((f for f in fmts if f.get("ext") == "json3" and f.get("url")), None)
        if not track:
            say(f"{kind:<8} {k}: no json3 file offered")
            continue
        for attempt in (1, 2):
            t = time.time()
            try:
                with ydl(extra) as y:
                    data = json.loads(y.urlopen(track["url"]).read(40_000_000))
                n = sum(len(e.get("segs") or []) for e in data.get("events", []))
                say(f"{kind:<8} {k}: OK  {n} pieces  {time.time() - t:4.1f}s")
                break
            except Exception as e:  # noqa: BLE001
                say(f"{kind:<8} {k}: attempt {attempt} FAIL  {short(e)}")
                time.sleep(5)


say(f"ViralCut YouTube check   {time.strftime('%Y-%m-%d %H:%M')}   video: {URL or '(a public test video)'}")
say(f"yt-dlp {version('yt-dlp')}   bgutil plugin: {version('bgutil-ytdlp-pot-provider')}   "
    f"deno: {shutil.which('deno') or 'not on PATH'}   node: {shutil.which('node') or 'not on PATH'}")
say()
say("1. Can the video be read?")
visitor = try_info("visitor", {})
good = {}
if visitor:
    good["visitor"] = {}
for name in ("firefox", "edge", "chrome", "brave"):
    r = try_info(name, {"cookiesfrombrowser": (name,)})
    if r:
        good[name] = {"cookiesfrombrowser": (name,)}
    time.sleep(1)
say()
say("2. Captions")
use = next(iter(good), None)
if use:
    say(f"(using: {use})")
    info = visitor if use == "visitor" else try_info("again", good[use])
    if info:
        captions(info, good[use])
else:
    say("nothing could read the video, so captions were not tried")
say()
say("Meaning: 'visitor OK' = nothing more is needed on this network. 'visitor FAIL' and a browser OK = turn on Settings > "
    "YouTube access. Every line FAIL = YouTube refuses this network or account; send this file back.")
Path("yt-check.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\nSaved yt-check.txt")
