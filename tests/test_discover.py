"""The log file and the "find working models" check, against a pretend AI service on this computer. No key, no internet."""
import http.server, json, os, sys, tempfile, threading
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-disc-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_AI_PROVIDER="", PEAKCUT_AI_MODELS="", PEAKCUT_AI_KEY="", PEAKCUT_AI_KEY_FILE="",
                  PEAKCUT_AI_BASE_URL="", PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765", PEAKCUT_BOOTSTRAP="0", PEAKCUT_LLM_CACHE="0",
                  NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
for v in ("PEAKCUT_AI_CONSENT", "PEAKCUT_AI_PRIVACY", "PEAKCUT_LOG_LEVEL"):
    os.environ.pop(v, None)
sys.path.insert(0, ".")
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

KEY = "good-key-SECRET-123456"
posts = []
OK = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body):
        data = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + KEY: return self._send(401, {"error": "bad key"})
        self._send(200, {"data": [{"id": n} for n in ("text-embedding-1", "gone-model", "busy-model", "plain-model", "fast-mini-2", "old-big-pro", "whisper-large")]})
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); m = req["model"]; posts.append(m)
        if m == "gone-model": return self._send(404, {"error": "model not found, key " + KEY})
        if m == "busy-model": return self._send(429, {"error": "quota"})
        if m == "plain-model": return self._send(200, {"choices": [{"message": {"content": "I am sorry"}}]})
        self._send(200, OK)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
(DATA / "providers.json").write_text(json.dumps({"providers": [{
    "id": "mock", "label": "Mock", "adapter": "openai", "base_url": f"http://127.0.0.1:{PORT}/v1", "key_env": "MOCK_KEY", "enabled_default": True,
    "privacy": {"trains_on_data": "no", "source_url": "https://example.test/t", "verified_on": __import__("datetime").date.today().isoformat()},
    "models": [{"id": "gone-model", "ctx": 100000, "json_mode": "unknown", "tier": 1,
                "limits": {"rpm": None, "rpd": None, "tpm": None, "tpd": None, "reset": "utc", "source": "unknown"}, "status": "active"}]}]}), encoding="utf-8")

from fastapi.testclient import TestClient
from studio import applog, db, pool, server
db.init()
BASE = "http://127.0.0.1:8765"; H_ = {"Origin": BASE}
c = TestClient(server.app, base_url=BASE, follow_redirects=False)
put = lambda path, body: c.put(path, json=body, headers=H_)
post = lambda path, body: c.post(path, json=body, headers=H_)
svc = lambda j, pid="mock": next(x for x in j["services"] if x["id"] == pid)

# ---- the log file: cleaning
applog.remember_secret("my-own-key-98765432")
c1 = applog.clean("failed with my-own-key-98765432 and Bearer abcdefghijklmnop1234 and AIzaSyA1234567890abcdefghijklmnop")
check("keys are blanked out of log text", ("my-own-key" in c1, "abcdefghijklmnop1234" in c1, "AIzaSy" in c1), (False, False, False))
check("long text is shortened", len(applog.clean("x" * 5000)) < 500, True)
check("a normal word is left alone", applog.clean("status 404 not found for model gemini-3.5-flash-lite"), "status 404 not found for model gemini-3.5-flash-lite")

# ---- the server wrote its start-up lines (the TestClient runs the start-up hooks only inside a with-block)
with TestClient(server.app, base_url=BASE, follow_redirects=False) as c2:
    c2.get("/api/status")
t = applog.tail(500)
check("start-up is logged with the version, Python and data folder", ("server.start" in t, "python=" in t, "server.ready" in t), (True, True, True))
check("web requests are logged with status and time", ('request method=GET path=/api/status status=200' in t, " ms=" in t), (True, True))

# ---- saving a key
j = put("/api/pool/key", {"provider": "mock", "key": KEY}).json()
put("/api/pool/consent", {"on": True})
t = applog.tail(500)
check("saving a key is logged, with the last four letters only", ("pool.key_saved provider=mock key_ends_in=3456" in t, KEY in t, "SECRET" in t), (True, False, False))
check("consent is logged", "pool.consent on=True" in t, True)

# ---- find the working models
r = post("/api/pool/discover", {"provider": "mock"})
check("the finder runs", r.status_code, 200)
d = r.json()["discover"]
by = {x["id"]: x for x in d["tested"]}
check("embedding and speech models are not even tried", ("text-embedding-1" in by, "whisper-large" in by, "text-embedding-1" in posts), (False, False, False))
check("a missing model is reported as not found with its status", (by["gone-model"]["status"], by["gone-model"]["code"], by["gone-model"]["ok"]), ("not_found", 404, False))
check("a busy model is kept but marked busy", (by["busy-model"]["status"], by["busy-model"]["code"]), ("busy", 429))
check("a model that answers without JSON is not used", (by["plain-model"]["status"], by["plain-model"]["ok"]), ("not_json", False))
check("a working model is marked working", (by["fast-mini-2"]["status"], by["fast-mini-2"]["ok"], by["fast-mini-2"]["json_mode"]), ("working", True, "object"))
check("the best guess comes first: small, fast and recent before big 'pro'", d["preferred"][0], "fast-mini-2")
check("the results are saved and shown on the page", sorted(m["id"] for m in svc(r.json())["found"]["models"]), sorted(by))

# ---- the pool now uses only models that answered
use = [m["id"] for m in svc(r.json())["models"]]
check("the pool uses the working models, not the one that vanished", ("fast-mini-2" in use, "gone-model" in use, "plain-model" in use), (True, False, False))
posts.clear()
out, tin, tout = pool.get().complete_json("x", {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}})
check("a real request goes to the best working model", (out, posts[:1]), ({"ok": True}, ["fast-mini-2"]))

# ---- logging of the tests and the request
t = applog.tail(800)
check("every test request is logged with its status code", ("pool.discover.test provider=mock model=gone-model status=404" in t, "model=busy-model status=429" in t, "model=fast-mini-2 status=200" in t), (True, True, True))
check("an error reply is logged, with the key blanked out", ("model not found" in t, KEY in t), (True, False))
check("the normal request is logged as a size, not its text", ("pool.request provider=mock model=fast-mini-2 status=200" in t, "characters" in t), (True, True))
check("the summary line names the preferred models", "pool.discover provider=mock listed=5" in t and "preferred=fast-mini-2" in t, True)

# ---- the routes
j = c.get("/api/log?lines=50").json()
check("the log can be read from the settings page", (j["path"].endswith("viralcut.log"), "pool.discover" in j["text"]), (True, True))
check("and downloaded", (c.get("/api/log/download").status_code, "pool.discover" in c.get("/api/log/download").text), (200, True))

# ---- a bad key is reported, not guessed
put("/api/pool/key", {"provider": "mock", "key": "wrong-key-0000000"})
r = post("/api/pool/discover", {"provider": "mock"})
check("a refused key stops the check with a plain message", (r.status_code, "did not accept" in r.json()["detail"]), (400, True))
check("without a key the finder says so", post("/api/pool/discover", {"provider": "groq"}).status_code, 400)

srv.shutdown()
print("ALL PASSED" if not fails else f"{len(fails)} failed: {fails}")
import shutil; shutil.rmtree(DATA, ignore_errors=True)
sys.exit(1 if fails else 0)
