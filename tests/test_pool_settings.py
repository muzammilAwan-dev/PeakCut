"""The free-pool settings routes, the consent gate and the key-save check, against a pretend AI service on this computer.
No real service is called and no key is needed."""
import http.server, json, os, sys, tempfile, threading
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-poolset-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_AI_PROVIDER="", PEAKCUT_AI_MODELS="", PEAKCUT_AI_KEY="", PEAKCUT_AI_KEY_FILE="",
                  PEAKCUT_AI_BASE_URL="", PEAKCUT_PUBLIC_URL="http://127.0.0.1:8765", PEAKCUT_BOOTSTRAP="0", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
for v in ("PEAKCUT_AI_CONSENT", "PEAKCUT_AI_PRIVACY"):
    os.environ.pop(v, None)
sys.path.insert(0, ".")
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

mode = {"v": "schema"}        # which JSON setting the pretend service accepts
hits = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body):
        data = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        hits.append(("GET", self.path)); auth = self.headers.get("Authorization", "")
        if auth != "Bearer good-key-123456": return self._send(401, {"error": {"message": "bad key " + auth}})
        self._send(200, {"data": [{"id": "m1"}, {"id": "m2"}]})
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); hits.append(("POST", req.get("response_format", {}).get("type", "none")))
        if self.headers.get("Authorization") != "Bearer good-key-123456": return self._send(401, {"error": {"message": "no"}})
        rf = req.get("response_format", {}).get("type")
        if rf == "json_schema" and mode["v"] != "schema": return self._send(400, {"error": {"message": "unsupported"}})
        if rf == "json_object" and mode["v"] == "none": return self._send(400, {"error": {"message": "unsupported"}})
        item = {"start": 20, "end": 50, "score": 80, "hook": "H", "title": "T", "description": "D", "hashtags": ["a"], "reason": "R"}
        self._send(200, {"choices": [{"message": {"content": json.dumps([item])}}], "usage": {"prompt_tokens": 50, "completion_tokens": 5}})
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
(DATA / "providers.json").write_text(json.dumps({"providers": [{
    "id": "mock", "label": "Mock", "adapter": "openai", "base_url": f"http://127.0.0.1:{PORT}/v1", "key_env": "MOCK_KEY", "enabled_default": True,
    "privacy": {"trains_on_data": "no", "source_url": "https://example.test/t", "verified_on": __import__("datetime").date.today().isoformat()},
    "models": [{"id": "m1", "ctx": 100000, "json_mode": "unknown", "tier": 1,
                "limits": {"rpm": None, "rpd": None, "tpm": None, "tpd": None, "reset": "utc", "source": "unknown"}, "status": "active"}]}]}), encoding="utf-8")

from fastapi.testclient import TestClient
from studio import ai, brain, db, pool, server
db.init()
BASE = "http://127.0.0.1:8765"; H_ = {"Origin": BASE}
c = TestClient(server.app, base_url=BASE, follow_redirects=False)
put = lambda path, body: c.put(path, json=body, headers=H_)
post = lambda path, body: c.post(path, json=body, headers=H_)
svc = lambda j, pid="mock": next(x for x in j["services"] if x["id"] == pid)

j = c.get("/api/pool").json()
check("the page lists the services, the bundled ones too", (svc(j)["label"], any(x["id"] == "groq" for x in j["services"])), ("Mock", True))
check("nothing is in use or allowed yet", (j["active"], j["consent"], j["privacy"]), (False, False, "strict"))

j = put("/api/pool/key", {"provider": "mock", "key": "good-key-123456"}).json()
check("a saved key shows only its last four letters", (svc(j)["has_key"], svc(j)["key_hint"], "good-key" in json.dumps(j)), (True, "3456", False))
check("without consent the online service is not used", (svc(j)["usable"], "OK" in svc(j)["reason"]), (False, True))
try: pool.get().complete_json("hello", brain.SCHEMA); res = "answered"
except pool.PoolExhausted as e: res = "waiting"
check("without consent a request is refused, nothing is sent", (res, [h for h in hits if h[0] == "POST"]), ("waiting", []))

pv = post("/api/pool/preview", {"chars": 7000}).json()
check("the preview says what leaves the computer and to whom", (pv["leaves_this_computer"], pv["sends_to"]), (False, []))   # still blocked: consent not given
j = put("/api/pool/consent", {"on": True}).json()
pv = post("/api/pool/preview", {"chars": 7000}).json()
check("after consent the preview names the service", ([x["provider"] for x in pv["sends_to"]], pv["leaves_this_computer"], pv["chars"]), (["Mock"], True, 7000))
check("consent is remembered", c.get("/api/pool").json()["consent"], True)

# probe
r = post("/api/pool/probe", {"provider": "mock"}).json()
check("the check: key accepted, models listed, JSON schema understood", (r["probe"]["key_ok"], r["probe"]["listed"], r["probe"]["json_mode"]), (True, ["m1", "m2"], "schema"))
check("the result is used for routing", pool.get().settings.probe_of("mock", "m1")["json_mode"], "schema")
check("the page sees the mode", svc(r)["models"][0]["json_mode"], "schema")
mode["v"] = "object"; hits.clear()
r = post("/api/pool/probe", {"provider": "mock"}).json()
check("an older service falls back to the object mode with two tries", (r["probe"]["json_mode"], [h for h in hits if h[0] == "POST"]), ("object", [("POST", "json_schema"), ("POST", "json_object")]))
mode["v"] = "none"; hits.clear()
r = post("/api/pool/probe", {"provider": "mock"}).json()
check("a service with no JSON setting is reported as such", (r["probe"]["json_mode"], len([h for h in hits if h[0] == "POST"])), ("none", 3))
check("...and the pool will not route to a model known to be unable", svc(r)["usable"], False)
mode["v"] = "schema"; post("/api/pool/probe", {"provider": "mock"})

# the pool answers now
out, tin, tout = pool.get().complete_json("Find clips.", brain.SCHEMA)
check("with consent the pool answers", (out[0]["start"], pool.get().last_route()), (20.0, "mock/m1"))

# a refused key
j = put("/api/pool/key", {"provider": "mock", "key": "wrong-key-99999"}).json()
r = post("/api/pool/probe", {"provider": "mock"}).json()
check("a refused key is reported and the service is switched off", (r["probe"]["key_ok"], svc(r)["disabled"], svc(r)["usable"]), (False, "key refused", False))
check("the refused key is not echoed back anywhere", "wrong-key" in json.dumps(r), False)
put("/api/pool/key", {"provider": "mock", "key": "good-key-123456"})
r = post("/api/pool/probe", {"provider": "mock"}).json()
check("a good key brings it back", (r["probe"]["key_ok"], svc(r)["usable"]), (True, True))

# other settings
check("privacy can be changed", put("/api/pool/privacy", {"mode": "relaxed"}).json()["privacy"], "relaxed")
check("a made-up privacy mode is refused", put("/api/pool/privacy", {"mode": "none"}).status_code, 400)
check("a made-up service is refused", put("/api/pool/key", {"provider": "nope", "key": "abcdefgh1234"}).status_code, 400)
check("a key with spaces is refused", put("/api/pool/key", {"provider": "mock", "key": "bad key here"}).status_code, 400)
check("an account id is only for services that use one", put("/api/pool/key", {"provider": "mock", "account_id": "abcd1234"}).status_code, 400)
check("a Cloudflare account id is saved", put("/api/pool/key", {"provider": "cloudflare", "account_id": "abcd1234ef"}).status_code, 200)
check("a bad account id is refused", put("/api/pool/key", {"provider": "cloudflare", "account_id": "a b/../c"}).status_code, 400)
check("local model names are checked", (put("/api/pool/local", {"models": "llama3.1, qwen2.5:7b"}).json()["local_models"], put("/api/pool/local", {"models": "bad name!"}).status_code), (["llama3.1", "qwen2.5:7b"], 400))
check("a service can be switched off", svc(put("/api/pool/enabled", {"provider": "mock", "on": False}).json())["enabled"], False)
check("a probe without a key is refused", post("/api/pool/probe", {"provider": "groq"}).status_code, 400)

# use the pool
check("using the pool is saved", (put("/api/pool/use", {"on": True}).json()["active"], ai.provider()), (True, "pool"))
check("turning it off here points to the AI tab", put("/api/pool/use", {"on": False}).status_code, 400)

# file hygiene
raw = (DATA / "pool.json").read_text(encoding="utf-8")
check("the key file is private to the owner (where the system allows)", (os.name == "nt") or oct((DATA / "pool.json").stat().st_mode & 0o777) == "0o600", True)
check("the page never receives a key", "good-key" in json.dumps(c.get("/api/pool").json()), False)
check("the environment can grant consent for unattended use", (os.environ.update(PEAKCUT_AI_CONSENT="1"), pool.Settings(DATA / "other.json").consent())[1], True)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
