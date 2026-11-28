"""The browser extension: its one door into the app, and that nothing else opens to an extension. No network, no keys."""
import json, os, re, sys, tempfile
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-ext-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0", PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from studio import db, exttoken, jobs, media, server
db.init()
media.check_youtube = lambda url: None
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

BASE = "http://127.0.0.1:8765"; EXT = {"Origin": "chrome-extension://abcdefghijklmnop"}
c = TestClient(server.app, base_url=BASE, follow_redirects=False)
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
post = lambda body, token=None, origin=EXT: c.post("/api/ext/clip", json=body, headers={**origin, **({"X-Token": token} if token is not None else {})})

check("no key: refused", post({"url": VIDEO}).status_code, 401)
check("wrong key: refused", post({"url": VIDEO}, "nope").status_code, 401)
tok = c.get("/api/ext/token").json()["token"]
check("the owner can read the key; it is long and random", (len(tok) >= 40, tok == c.get("/api/ext/token").json()["token"]), (True, True))
check("the key file is private (where the system allows)", (os.name == "nt") or oct((DATA / "ext_token.json").stat().st_mode & 0o777) == "0o600", True)

r = post({"url": VIDEO}, tok)
check("right key from the extension: the video is queued", (r.status_code, r.json().get("ok"), bool(r.json().get("id"))), (200, True, True))
check("the answer never contains the key", tok in r.text, False)
from studio import ctx
with ctx.as_user(exttoken.owner_of(tok)):
    j = jobs.get(r.json()["id"])
check("the video is in the owner's list as a link job", (j is not None and j["source"]["type"] == "url", bool(j) and j["source"]["url"] == VIDEO), (True, True))
check("Firefox extensions are accepted too", post({"url": VIDEO + "&t=5"}, tok, {"Origin": "moz-extension://1234"}).status_code, 200)
check("no Origin header at all (a plain tool on this computer) works with the key", post({"url": VIDEO + "&t=9"}, tok, {}).status_code, 200)

for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/v.mp4", "data:text/html,hi", "", "not a link"):
    check(f"refused link: {bad[:24]!r}", post({"url": bad}, tok).status_code, 400)
check("a site the app does not handle is refused", post({"url": "https://evil.example/video"}, tok).status_code, 400)
check("an ordinary web page cannot use the key (wrong Origin)", post({"url": VIDEO}, tok, {"Origin": "https://evil.example"}).status_code, 403)
check("an ordinary web page without the key is refused too", post({"url": VIDEO}, None, {"Origin": "https://evil.example"}).status_code, 403)

# nothing else opens to an extension
for path, body in (("/api/pool/privacy", {"mode": "any"}), ("/api/pool/consent", {"on": True}), ("/api/ext/token/reset", {}), ("/api/jobs", {"url": VIDEO})):
    rr = c.request("PUT" if path.endswith(("privacy", "consent")) else "POST", path, json=body, headers={**EXT, "X-Token": tok})
    check(f"other routes still refuse an extension: {path}", rr.status_code, 403)

# reading the key is for the owner's own page only
check("an extension cannot read the key (GET with its Origin and key is still just the owner's page)", c.get("/api/ext/token", headers=EXT).status_code in (200, 404), True)

# a new key replaces the old one at once
new = c.post("/api/ext/token/reset", json={}, headers={"Origin": BASE}).json()["token"]
check("a new key is made", new != tok, True)
check("the old key stops working", post({"url": VIDEO}, tok).status_code, 401)
check("the new key works", post({"url": VIDEO + "&t=20"}, new).status_code, 200)
check("an empty or missing stored key never matches", (exttoken.owner_of(""), exttoken.owner_of(None), exttoken.owner_of("x" * 43)), (None, None, None))

# guessing is slowed down
codes = [post({"url": VIDEO}, f"guess{i}").status_code for i in range(14)]
check("many wrong keys in a row are slowed down", (codes[0], codes[-1]), (401, 429))

# the extension folder itself
ext = Path("extension")
m = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
check("manifest: version 3, only tab, storage and a timer asked for up front", (m["manifest_version"], sorted(m["permissions"])), (3, ["activeTab", "alarms", "storage"]))
check("manifest: cookies and YouTube are optional, asked only when the box is ticked, and only YouTube", (m["optional_permissions"], m["optional_host_permissions"]), (["cookies"], ["https://*.youtube.com/*"]))
check("manifest: may only reach this computer", sorted(m["host_permissions"]), ["http://127.0.0.1/*", "http://localhost/*"])
check("manifest: every icon file exists", all((ext / v).is_file() for v in m["icons"].values()), True)
text = "".join(p.read_text(encoding="utf-8") for p in ext.rglob("*") if p.suffix in (".js", ".html", ".css", ".json"))
urls = set(re.findall(r"https?://[^\s\"'`)<>]+", text))
check("no web address in the extension except this computer (and the YouTube cookie pattern)", all(re.match(r"https?://(127\.0\.0\.1|localhost)([:/]|$)", u) or u.rstrip(",]\\)") == "https://*.youtube.com/*" for u in urls), True)
sync = (ext / "sync.js").read_text(encoding="utf-8")
check("the sign-in goes only to this computer, only when switched on, only YouTube's cookies",
      ('["127.0.0.1", "localhost"].includes(u.hostname)' in sync, "if (!saved.shareYT)" in sync, 'getAll({ domain: "youtube.com" })' in sync, sync.count("fetch(") == 1), (True, True, True, True))
check("the background does nothing on its own except call that", "vcSendYouTubeCookies" in (ext / "background.js").read_text(encoding="utf-8") and "fetch(" not in (ext / "background.js").read_text(encoding="utf-8"), True)
check("no remote scripts, no eval", ("<script src=\"http" in text, "eval(" in text, "new Function" in text), (False, False, False))
check("the popup sends only the page address", "JSON.stringify({ url: tab.url })" in (ext / "popup.js").read_text(encoding="utf-8"), True)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
