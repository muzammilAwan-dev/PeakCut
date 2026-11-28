"""YouTube's bot check: the opt-in browser sign-in, found and used only after a refusal. No network, no browser needed."""
import json, os, sys, tempfile
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-yta-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
os.environ.pop("PEAKCUT_YT_COOKIES", None)
sys.path.insert(0, ".")
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

from studio import db, media, ytaccess
db.init()
YT = "https://www.youtube.com/watch?v=abcdefghijk"

check("it is off until the owner allows it", (ytaccess.settings()["mode"], ytaccess.configured(), ytaccess.opts()), ("off", False, {}))
try: ytaccess.save("everything", ""); r = "saved"
except ValueError: r = "refused"
check("an unknown choice is refused", r, "refused")
try: ytaccess.save("file", str(DATA / "missing.txt")); r = "saved"
except ValueError: r = "refused"
check("a cookies file that is not there is refused", r, "refused")

# ---- automatic: Firefox first, because Chrome and Edge lock their cookies
looked = []
def fake_check(ok_names):
    def f(name):
        looked.append(name)
        return (True, "") if name in ok_names else (False, "could not decrypt" if name == "chrome" else "not installed")
    return f
ytaccess.save("auto")
ytaccess._check_browser = fake_check({"edge", "chrome"})
check("nothing is used before YouTube refuses", ytaccess.opts(), {})
check("activation finds a signed-in browser", ytaccess.activate(), True)
check("the first that works wins, in this order: Firefox, Edge, Chrome, Brave", (looked, ytaccess.state()["using"]), (["firefox", "edge"], "edge"))
check("then yt-dlp is given that browser", ytaccess.opts(), {"cookiesfrombrowser": ("edge",)})
ytaccess.save("auto")                                           # saving again starts over
check("saving again turns it off until the next refusal", (ytaccess.state()["in_use"], ytaccess.opts()), (False, {}))
looked.clear(); ytaccess._check_browser = fake_check(set())
check("no signed-in browser: it says so and why", (ytaccess.activate(), "chrome: could not decrypt" in ytaccess.state()["note"], looked), (False, True, ["firefox", "edge", "chrome", "brave"]))
ytaccess.save("firefox"); looked.clear(); ytaccess._check_browser = fake_check({"firefox"})
check("a chosen browser is the only one looked at", (ytaccess.activate(), looked), (True, ["firefox"]))
cf = DATA / "cookies.txt"; cf.write_text("# Netscape HTTP Cookie File\n")
ytaccess.save("file", str(cf)); ytaccess.activate()
check("a cookies file is passed straight on", ytaccess.opts(), {"cookiefile": str(cf)})
os.environ["PEAKCUT_YT_COOKIES"] = "edge"
check("the PEAKCUT_YT_COOKIES setting wins over the saved choice", (ytaccess.settings()["mode"], ytaccess.settings()["from_env"]), ("edge", True))
os.environ.pop("PEAKCUT_YT_COOKIES")

# ---- the retry after a refusal
calls = []
@media._retry_with_sign_in
def fetch(url):
    calls.append(bool(ytaccess.opts()))
    if not ytaccess.opts():
        media._yt_refused_until = 9e12
        raise media.YouTubeBlocked(media.YT_BLOCKED)
    return "got it"
ytaccess.save("auto"); ytaccess._check_browser = fake_check({"firefox"})
check("after a refusal it signs in and tries once more", (fetch(YT), calls, media.youtube_paused()), ("got it", [False, True], False))
calls.clear()
check("afterwards it keeps using the sign-in", (fetch(YT), calls), ("got it", [True]))
ytaccess.save("off"); calls.clear()
try: fetch(YT); r = "answered"
except media.YouTubeBlocked: r = "blocked"
check("when it is off, a refusal is passed on as before (no retry)", (r, calls), ("blocked", [False]))
ytaccess.save("auto"); ytaccess._check_browser = fake_check(set()); calls.clear()
try: fetch(YT); r = "answered"
except media.YouTubeBlocked: r = "blocked"
check("allowed, but no signed-in browser: still a clear refusal, tried once", (r, calls), ("blocked", [False]))
media._yt_refused_until = 0.0
ytaccess.save("auto"); ytaccess._check_browser = fake_check({"firefox"}); calls.clear()
@media._retry_with_sign_in
def other(url):
    calls.append(1); raise media.YouTubeBlocked("x")
try: other("https://www.twitch.tv/videos/1"); r = "answered"
except media.YouTubeBlocked: r = "blocked"
check("other sites never trigger a sign-in", (r, calls), ("blocked", [1]))

# ---- the routes
from fastapi.testclient import TestClient
from studio import server
BASE = "http://127.0.0.1:8765"; H = {"Origin": BASE}
c = TestClient(server.app, base_url=BASE, follow_redirects=False)
j = c.get("/api/youtube").json()
check("the page can read the choice", (j["mode"], j["paused"]), ("auto", False))
r = c.put("/api/youtube", json={"mode": "firefox"}, headers=H)
check("and change it", (r.status_code, r.json()["mode"]), (200, "firefox"))
check("a bad choice gets a plain message", (c.put("/api/youtube", json={"mode": "x"}, headers=H).status_code), 400)
media.info = lambda url: {"title": "Me at the zoo"}
t = c.post("/api/youtube/test", json={}, headers=H).json()
check("the test button reports success", (t["ok"], "Me at the zoo" in t["message"]), (True, True))
def blocked(url): raise media.YouTubeBlocked(media.YT_BLOCKED)
media.info = blocked
t = c.post("/api/youtube/test", json={}, headers=H).json()
check("and a refusal", (t["ok"], "not a bot" in t["message"]), (False, True))
log = (DATA / "logs" / "viralcut.log").read_text(encoding="utf-8") if (DATA / "logs" / "viralcut.log").exists() else ""
check("the choices and the test are in the activity log", ("youtube.access" in log, "youtube.test" in log), (True, True))


# ---- the browser extension's sign-in (the way that works for Chrome and Edge)
from studio import exttoken, safe
T = "\t"
good = "\n".join([
    "# Netscape HTTP Cookie File",
    f".youtube.com{T}TRUE{T}/{T}TRUE{T}2000000000{T}SAPISID{T}abcdef",
    f"#HttpOnly_.youtube.com{T}TRUE{T}/{T}TRUE{T}2000000000{T}__Secure-1PSID{T}xyz",
    f".google.com{T}TRUE{T}/{T}TRUE{T}2000000000{T}NID{T}n",
    f".bank.example{T}TRUE{T}/{T}TRUE{T}2000000000{T}secret{T}never", ""])
ytaccess.save("off")
check("the extension's sign-in is refused while YouTube access is off", ytaccess.receive_from_extension(good)[0], False)
ytaccess.save("auto")
ok, msg = ytaccess.receive_from_extension(good)
saved = ext = ytaccess.ext_file().read_text(encoding="utf-8")
check("accepted once allowed; only YouTube and Google lines are kept", (ok, "bank.example" not in saved, "SAPISID" in saved, "HttpOnly_.youtube.com" in saved), (True, True, True, True))
check("it is known as received", (ytaccess.ext_status()["has"], ytaccess.ext_status()["age_min"]), (True, 0))
check("no sign-in inside: refused and nothing replaced", (ytaccess.receive_from_extension(f".youtube.com{T}TRUE{T}/{T}TRUE{T}2000000000{T}PREF{T}x\n")[0], ytaccess.ext_file().read_text(encoding="utf-8")), (False, saved))
check("far too much: refused", ytaccess.receive_from_extension("x" * 300_000)[0], False)
looked.clear(); ytaccess.save("auto"); ytaccess._check_browser = fake_check({"firefox"})
check("automatic tries the extension's sign-in before any browser", (ytaccess.activate(), ytaccess.state()["using"], looked, ytaccess.opts()), (True, "extension", [], {"cookiefile": str(ytaccess.ext_file())}))
ytaccess.save("extension"); looked.clear()
check("the 'extension only' choice never opens a browser", (ytaccess.activate(), looked), (True, []))
ytaccess.forget_extension()
ytaccess.save("extension")
check("after Forget it is gone and activation says so", (ytaccess.ext_file().exists(), ytaccess.activate(), "extension" in ytaccess.state()["note"]), (False, False, True))
ytaccess.save("auto"); ytaccess.receive_from_extension(good)

# routes: only with the pairing key, and from an extension origin
EX = {"Origin": "chrome-extension://abcdefghijklmnop", "X-Token": "wrong"}
r = c.post("/api/ext/cookies", json={"cookies": good}, headers=EX)
check("a wrong key is refused", r.status_code, 401)
tok = c.get("/api/ext/token").json()["token"]
r = c.post("/api/ext/cookies", json={"cookies": good}, headers={**EX, "X-Token": tok})
check("the right key from an extension is accepted", (r.status_code, r.json().get("ok")), (200, True))
check("a web page of another site is still not (no extension origin)", c.post("/api/ext/cookies", json={"cookies": good}, headers={"Origin": "https://evil.example", "X-Token": tok}).status_code, 403)
ytaccess.save("off")
r = c.post("/api/ext/cookies", json={"cookies": good}, headers={**EX, "X-Token": tok})
check("with YouTube access off the extension is told to turn it on", (r.status_code, "Settings" in r.json()["detail"]), (409, True))
ytaccess.save("auto")
check("the page can see it and forget it", (c.get("/api/youtube").json()["extension"]["has"], c.delete("/api/youtube/cookies", headers=H).json()["extension"]["has"]), (True, False))
log = (DATA / "logs" / "viralcut.log").read_text(encoding="utf-8")
check("the log says a sign-in arrived but never what it was", ("youtube.cookies.received" in log, "abcdef" not in log, "__Secure-1PSID" not in log), (True, True, True))

# ---- the reachability check and plain error text
check("colour codes are removed from yt-dlp errors", safe.friendly("\x1b[0;31mERROR:\x1b[0m [youtube] x: This video is unavailable"), "ERROR: [youtube] x: This video is unavailable")
check("and the form where the escape was lost", safe.friendly("[0;31mERROR:[0m boom"), "ERROR: boom")
seen = []
def gone_then_ok(url):
    seen.append(url[-11:])
    if len(seen) < 2: raise RuntimeError("ERROR: [youtube] x: This video is unavailable")
    return {"title": "Second one"}
media.info = gone_then_ok
check("an unavailable test video moves on to the next one", (media.reach_check(), seen), ((True, "Second one"), list(media.TEST_VIDEOS[:2])))
def always_gone(url): raise RuntimeError("Video unavailable")
media.info = always_gone
check("all gone: a plain failure, not a bot check", media.reach_check()[0], False)
def timeout(url): raise RuntimeError("timed out")
seen.clear(); media.info = timeout
check("another kind of failure stops at once", (media.reach_check()[0]), False)
media.info = blocked
try: media.reach_check(); r = "answered"
except media.YouTubeBlocked: r = "blocked"
check("a bot check is raised, not swallowed", r, "blocked")

print("ALL PASSED" if not fails else f"{len(fails)} failed: {fails}")
sys.exit(1 if fails else 0)
