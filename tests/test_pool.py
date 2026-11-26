"""The free AI pool against a pretend AI server on this computer: failover, cooldowns, repair retries, a refused key,
the privacy setting, waiting for the next minute, a restart, and the end of the line (clips picked by loudness).
No real service is called and no key is needed."""
import calendar, collections, http.server, importlib.util, json, os, shutil, sys, tempfile, threading, time
from pathlib import Path
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-pool-")
os.environ.update(PEAKCUT_LLM_CACHE="0", PEAKCUT_AI_PROVIDER="pool", PEAKCUT_AI_KEY="", PEAKCUT_BOOTSTRAP="0", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
os.environ.pop("PEAKCUT_AI_PRIVACY", None)
sys.path.insert(0, ".")
from unittest.mock import MagicMock
missing = {m for m in ("httpx", "sqlalchemy", "soundfile", "psycopg") if importlib.util.find_spec(m) is None}   # this test needs none of them
for mod in ("httpx", "sqlalchemy", "sqlalchemy.event", "soundfile", "psycopg"):
    if mod.split(".")[0] in missing:
        sys.modules[mod] = MagicMock()
import numpy as np
from studio import ai, brain, config, jsoncheck, pool, vault
from studio.ledger import Ledger

fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

work = Path(tempfile.mkdtemp(prefix="pc-pool-w-"))

# ================================================================ the answer checker
S = brain.SCHEMA
good = {"start": 20, "end": 50, "score": 80, "hook": "H", "title": "T", "description": "D", "hashtags": ["a"], "reason": "R"}
out, dropped = jsoncheck.clean([{**good, "start": None}, good], S)
check("jsoncheck: one bad item is dropped, the good one stays", (len(out), dropped, out[0]["start"]), (1, 1, 20.0))
out, dropped = jsoncheck.clean([{**good, "start": "20", "score": 85.4, "hook": 5, "extra": "x", "highlight_words": "nope"}], S)
check("jsoncheck: numeric text, 85.4 as an integer, a number as text, unknown fields removed, a wrong optional field removed",
      (out[0]["start"], out[0]["score"], out[0]["hook"], "extra" in out[0] or "highlight_words" in out[0]), (20.0, 85, "5", False))
check("jsoncheck: a bare object where a list is wanted is refused", isinstance(jsoncheck.clean({"items": [good]}, S)[0], list), True)
for bad, why in (({"oops": 1}, "list"), ([{"start": None}], "no item"), ("text", "list"), ([{**good, "start": float("nan")}], "no item")):
    try: jsoncheck.clean(bad, S); res = False
    except jsoncheck.BadAnswer as e: res = why in str(e)
    check(f"jsoncheck: refuses {str(bad)[:30]!r}", res, True)
check("jsoncheck: an empty list is a fine answer", jsoncheck.clean([], S), ([], 0))
check("jsoncheck: a list of text for the caption schema", jsoncheck.clean(["a", 5, None, ["x"]], {"type": "ARRAY", "items": {"type": "STRING"}}), (["a", "5"], 2))
check("jsoncheck: lower-case type names work", jsoncheck.clean([1, "2"], {"type": "array", "items": {"type": "integer"}}), ([1, 2], 0))
check("jsoncheck: a very long list is cut", len(jsoncheck.clean(list(range(1000)), {"type": "ARRAY", "items": {"type": "INTEGER"}})[0]), jsoncheck.MAX_ITEMS)

# ================================================================ a pretend AI server
script = collections.defaultdict(list)        # provider -> replies to give next, in order
hits = collections.Counter()
seen = []                                      # (provider, request body)
def ok_reply(items=None, tin=500, tout=50):
    return {"status": 200, "body": {"choices": [{"message": {"content": json.dumps(items if items is not None else [good])}}],
                                    "usage": {"prompt_tokens": tin, "completion_tokens": tout}}}
def text_reply(text, tin=500, tout=50):
    return {"status": 200, "body": {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": tin, "completion_tokens": tout}}}
def err(status, body="", headers=None, delay=0):
    return {"status": status, "body": {"error": {"message": body}}, "headers": headers or {}, "delay": delay}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        who = self.path.split("/")[1]
        hits[who] += 1; seen.append((who, req, self.headers.get("Authorization", "")))
        step = script[who].pop(0) if script[who] else ok_reply()
        if step.get("delay"): time.sleep(step["delay"])
        data = json.dumps(step["body"]).encode()
        try:
            self.send_response(step["status"])
            for k, v in (step.get("headers") or {}).items(): self.send_header(k, v)
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        except OSError:
            pass
class Srv(http.server.ThreadingHTTPServer):
    def handle_error(self, *a): pass
srv = Srv(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

class Clock:
    def __init__(self): self.t = float(calendar.timegm((2026, 11, 17, 12, 0, 0)))
    def __call__(self): return self.t
    def sleep(self, s): self.sleeps.append(s); self.t += s
    sleeps = []

def prov(pid, trains="no", verified="2026-11-15", tier=1, limits=None, local=False, models=None, key=True, base=None, **extra):
    lim = {"rpm": None, "rpd": None, "tpm": None, "tpd": None, "reset": "utc", **(limits or {})}
    d = {"id": pid, "label": pid.upper(), "adapter": "openai", "base_url": base or f"http://127.0.0.1:{PORT}/{pid}/v1",
         "key_env": f"{pid.upper()}_KEY", "enabled_default": True, "needs_key": key, "local": local,
         "privacy": {"trains_on_data": trains, "source_url": "https://example.test/terms", "verified_on": verified},
         "models": [{"id": "m", "ctx": 100000, "json_mode": "object", "tier": tier, "limits": lim, "status": "active"}] if models is None else models}
    d.update(extra); return d

def make(provs, ledger_path=":memory:", env=None, clock=None, consent=True, **kw):
    cat = work / f"cat-{len(list(work.glob('cat-*')))}.json"
    cat.write_text(json.dumps({"providers": provs}), encoding="utf-8")
    keys = {f"{p['id'].upper()}_KEY": "k-" + p["id"] * 8 for p in provs}
    clock = clock or Clock(); clock.sleeps = []
    pl = pool.Pool(pool.Catalog(cat), Ledger(ledger_path), pool.Settings(work / f"s-{cat.stem}.json", env={**keys, **(env or {})}),
                   clock=clock, sleep=clock.sleep, timeout=kw.pop("timeout", 5), est_out=kw.pop("est_out", 100), **kw)
    pl.clock_obj = clock
    if consent: pl.settings.change(None, "consent", True)
    return pl
ask = lambda pl, prompt="Find clips.", schema=S: pl.complete_json(prompt, schema)

def reset_server():
    script.clear(); hits.clear(); seen.clear()

# ================================================================ 429: fail over, skip until the cooldown ends
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [err(429, "slow down", {"Retry-After": "30"})]
r, tin, tout = ask(pl)
check("429: the next service answers", (hits["a"], hits["b"], pl.last_route(), (tin, tout)), (1, 1, "b/m", (500, 50)))
check("429: the answer is the checked, cleaned list", r[0]["start"], 20.0)
ask(pl)
check("429: the first service is skipped while it cools down", (hits["a"], hits["b"]), (1, 2))
pl.clock_obj.t += 31
ask(pl)
check("429: ...and used again after the cooldown", (hits["a"], pl.last_route()), (2, "a/m"))
check("429: a good answer clears the rate-limit counter", pl.ledger.state("a", "m")["rate_hits"], 0)

reset_server()
pl = make([prov("a")])
script["a"] = [err(429, "slow down")]
ask(pl)
check("429 without Retry-After: cools 30 s (short enough to wait), then succeeds on the same service",
      (hits["a"], round(pl.clock_obj.sleeps[0])), (2, 30))
reset_server()
pl = make([prov("a")])
script["a"] = [err(429, "Rate limit reached: requests per day (RPD) exceeded")]
try: ask(pl); res = None
except pool.PoolExhausted as e: res = str(e)
check("429 for a daily limit: no short wait, the pool gives up and says why",
      (hits["a"], res is not None and "cooling down" in res, pl.clock_obj.sleeps), (1, True, []))
st = pl.ledger.state("a", "m")
check("429 daily: cooled down until the daily reset", st["cooldown_until"] > pl.clock_obj.t + 3600, True)

# ================================================================ bad JSON: one repair retry, then the next service
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [text_reply("I think the best moment is at 20s, enjoy! SECRET-MODEL-WORDS"), ok_reply()]
ask(pl)
second = [b for w, b, _ in seen if w == "a"][1]["messages"][0]["content"]
check("not JSON: the same service is asked once more, naming the problem", (hits["a"], "could not be used" in second), (2, True))
check("...and the model's own words are never repeated back to it", "SECRET-MODEL-WORDS" not in second, True)
check("...and it counts as a quality signal, not an outage", (pl.ledger.state("a", "m")["schema_fail"], pl.ledger.state("a")["fails"]), (1, 0))
reset_server()
script["a"] = [text_reply('{"oops": 1}'), text_reply("garbage")]
r, _, _ = ask(pl)
check("wrong shape twice: the next service answers", (hits["a"], hits["b"], pl.last_route()), (2, 1, "b/m"))
reset_server()
script["a"] = [ok_reply([{**good, "start": None}, good])]
r, _, _ = ask(pl)
check("one bad item inside an otherwise good answer: kept the good one, no retry", (len(r), hits["a"]), (1, 1))
reset_server()
script["a"] = [ok_reply([{"start": None}])]
r, _, _ = ask(pl)
check("a list with no usable item counts as a bad answer (repair asked once)", (hits["a"], len(r)), (2, 1))

# ================================================================ 401: switched off, kept across a restart, back with a new key
reset_server()
db_file = work / "ledger.db"
pl = make([prov("a", tier=1), prov("b", tier=2)], db_file)
script["a"] = [err(401, "bad key k-aaaaaaaa")]
ask(pl)
ask(pl)
check("401: switched off after one try, never retried", (hits["a"], hits["b"]), (1, 2))
reason = [r["reason"] for r in pl.explain(100, 100) if r["provider"] == "a"][0]
check("401: the page can say why, without the key", ("key was refused" in reason, "k-aaaaaaaa" not in reason), (True, True))
pl.ledger.close()
pl2 = make([prov("a", tier=1), prov("b", tier=2)], db_file, clock=pl.clock_obj)
ask(pl2)
check("401: still switched off after a restart", (hits["a"], hits["b"]), (1, 3))
pl2.save_key("a", "brand-new-key-123")
ask(pl2)
check("401: a new key switches it on again", (hits["a"], pl2.last_route()), (2, "a/m"))
check("a key is sent as a bearer token and is not echoed into errors", seen[-1][2], "Bearer brand-new-key-123")
check("the key is saved in the settings file, and only its last four letters are shown",
      (vault.unseal(json.loads(Path(pl2.settings.path).read_text())["keys"]["a"]), [s["key_hint"] for s in pl2.status() if s["id"] == "a"][0]), ("brand-new-key-123", "-123"))

# ================================================================ other errors
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [err(500, "boom")]
ask(pl)
check("500: the other service answers, the failed one cools down for 60 s", (hits["b"], round(pl.ledger.state("a")["cooldown_until"] - pl.clock_obj.t)), (1, 60))
for i in range(2):
    pl.clock_obj.t += 61; script["a"] = [err(502, "bad gateway")]; ask(pl)
st = pl.ledger.state("a")
check("three server errors in a row open the breaker for 10 minutes", (st["fails"], round(st["cooldown_until"] - pl.clock_obj.t)), (3, 600))
pl.clock_obj.t += 601; ask(pl)
check("...and a good answer afterwards closes it", (pl.last_route(), pl.ledger.state("a")["fails"]), ("a/m", 0))
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)], timeout=0.3)
script["a"] = [err(200, delay=1.0)]
ask(pl)
check("a reply that takes too long counts as an outage of that service", (pl.last_route(), pl.ledger.state("a")["fails"]), ("b/m", 1))
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [err(404, "no such model")]
ask(pl); ask(pl)
check("404: that model is switched off", (hits["a"], hits["b"], "not found" in pl.ledger.state("a", "m")["disabled"]), (1, 2, True))
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [err(400, "bad request")] * 3
ask(pl); ask(pl)
check("400 on every format: the model is parked for 2 minutes and the next one used", (hits["a"], pl.last_route()), (3, "b/m"))
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [err(400, "no response_format"), ok_reply()]
ask(pl)
check("a model that refuses an extra setting is asked again without it", (hits["a"], "response_format" in seen[0][1], "response_format" in seen[1][1]), (2, True, True))

# ================================================================ everything fails: PoolExhausted, then clips by loudness
reset_server()
pl = make([prov("a", tier=1), prov("b", tier=2)])
script["a"] = [err(500, "x")] * 5; script["b"] = [err(503, "y")] * 5
try: ask(pl); msg = ""
except pool.PoolExhausted as e: msg = str(e)
check("all services failing: PoolExhausted", (msg.startswith("No free AI service"), "A:" in msg and "B:" in msg), (True, True))
check("...its text never contains what would make brain.ask_ai sleep and retry", ("HTTP 429" in msg or "HTTP 5" in msg), False)

words = [{"w": f"w{i}", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(240)]
loud = np.zeros(120); loud[50:55] = 9
pool._pool = pl                                                # brain -> ai -> the pool under test
check("ai.ready(): the pool counts as set up once a key is there", (ai.provider(), ai.ready(), ai.models()), ("pool", True, ["auto"]))
reset_server(); script["a"] = [err(500, "x")] * 9; script["b"] = [err(500, "y")] * 9
pl.clock_obj.t += 700
log = []
clips, info = brain.find_clips(words, loud, 120.0, log=log.append)
check("pool dead: clips are still made, by loudness, and the job says so", (len(clips) >= 1, "loudness" in info["note"], info["model"]), (True, True, None))
reset_server()
pl.clock_obj.t += 700
script["a"] = [ok_reply([{**good, "start": None, "end": 30}, {**good, "start": 20, "end": 50, "score": 80}])]
log.clear()
clips, info = brain.find_clips(words, loud, 120.0, log=log.append)
check("pool alive, one bad item in the answer: the window survives (audit D7)", (len(clips), info["model"], log), (1, "a/m", []))
reset_server()
pl.clock_obj.t += 700
script["a"] = [ok_reply([{**good, "start": None}])] * 2
script["b"] = [text_reply("nonsense")] * 2
clips, info = brain.find_clips(words, loud, 120.0, log=log.append)
check("pool answers only unusable items: falls back to loudness instead of returning nothing", (len(clips) >= 1, "loudness" in info["note"]), (True, True))
pool._pool = None

# ================================================================ limits: spacing by the minute, and too-big requests
reset_server()
pl = make([prov("t", limits={"tpm": 1000})])
prompt = "x" * 1500
ask(pl, prompt)
ask(pl, prompt)
check("tokens per minute: the second request waits for the next minute instead of failing",
      (hits["t"], len(pl.clock_obj.sleeps), 59 < pl.clock_obj.sleeps[0] < 61), (2, 1, True))
reset_server()
pl = make([prov("t", limits={"tpm": 1000})])
try: ask(pl, "x" * 6000); res = "answered"
except pool.PoolExhausted as e: res = str(e)
check("a request bigger than the per-minute allowance is refused without waiting", (hits["t"], "per-minute allowance" in res, pl.clock_obj.sleeps), (0, True, []))
reset_server()
pl = make([prov("t", tier=1, limits={"tpm": 1000}), prov("u", tier=2)])
ask(pl, prompt); ask(pl, prompt)
check("tokens per minute: another service takes the second request without any waiting", (hits["t"], hits["u"], pl.clock_obj.sleeps), (1, 1, []))
reset_server()
pl = make([prov("t", limits={"rpm": 5})])
for _ in range(4): ask(pl)
check("requests per minute: 80% of 5 is 4, so the fifth waits for the next minute", (hits["t"], pl.clock_obj.sleeps), (4, []))
ask(pl)
check("...the fifth request waited", (hits["t"], len(pl.clock_obj.sleeps)), (5, 1))
reset_server()
pl = make([prov("t", limits={"rpd": 1})])
ask(pl)
try: ask(pl); res = "answered"
except pool.PoolExhausted: res = "exhausted"
check("requests per day used up: no waiting a whole day, it says so", (res, pl.clock_obj.sleeps), ("exhausted", []))
reset_server()
pl = make([prov("small", models=[{"id": "m", "ctx": 500, "json_mode": "object", "tier": 1, "status": "active"}])])
try: ask(pl, "x" * 3000); res = "answered"
except pool.PoolExhausted as e: res = str(e)
check("a request bigger than the model's context is not sent", (hits["small"], "too big" in res), (0, True))
check("a model without JSON mode is never used",
      [r["reason"] for r in make([prov("n", models=[{"id": "m", "ctx": 9999, "json_mode": "none", "tier": 1, "status": "active"}])]).explain(10, 10)][0], "this model cannot answer in JSON")

# ================================================================ order: tier, then room left, then failures
reset_server()
pl = make([prov("lo", tier=2), prov("hi", tier=1)])
ask(pl)
check("best tier first, whatever the catalog order", pl.last_route(), "hi/m")
reset_server()
pl = make([prov("p", tier=1, limits={"rpm": 100}), prov("q", tier=1, limits={"rpm": 100})])
for _ in range(10): pl.ledger.add("p", "m", ["m" + str(int(pl.clock_obj.t // 60))], req=1)
ask(pl)
check("same tier: the one with more room left", pl.last_route(), "q/m")

# ================================================================ a restart keeps cooldowns and counts
reset_server()
db_file2 = work / "ledger2.db"
pl = make([prov("a", tier=1), prov("b", tier=2)], db_file2)
script["a"] = [err(429, "later", {"Retry-After": "300"})]
ask(pl); pl.ledger.close()
pl = make([prov("a", tier=1), prov("b", tier=2)], db_file2, clock=pl.clock_obj)
ask(pl)
used = pl.ledger.used("b", "m", ["m" + str(int(pl.clock_obj.t // 60))])
check("restart: the cooldown is remembered, the counts too", (hits["a"], hits["b"], used["m" + str(int(pl.clock_obj.t // 60))][0]), (1, 2, 2))

# ================================================================ privacy
provs = [prov("p1", "no"), prov("p2", "no", verified="2026-01-01"), prov("p3", "depends"), prov("p4", "unknown"), prov("p5", "yes"),
         prov("p6", "yes", local=True, key=False, models=[], verified="2020-01-01")]
pl = make(provs)
pl.settings.change(None, "local_models", ["llama3.1"])
okset = lambda: sorted({r["provider"] for r in pl.explain(100, 100) if r["ok"]})
check("privacy strict (the default): only 'no' terms checked within 90 days, plus the local model", (pl.settings.privacy(), okset()), ("strict", ["p1", "p6"]))
pl.set_privacy("relaxed")
check("privacy relaxed: also 'depends', 'unknown' and stale checks, still not 'yes'", okset(), ["p1", "p2", "p3", "p4", "p6"])
pl.set_privacy("any")
check("privacy any: everything", okset(), ["p1", "p2", "p3", "p4", "p5", "p6"])
os.environ["PEAKCUT_AI_PRIVACY"] = "strict"
check("PEAKCUT_AI_PRIVACY overrides the saved setting", pl.settings.privacy(), "strict")
os.environ["PEAKCUT_AI_PRIVACY"] = "bogus"
check("a nonsense privacy value means strict", pl.settings.privacy(), "strict")
os.environ.pop("PEAKCUT_AI_PRIVACY")
try: pl.set_privacy("loose"); res = False
except ValueError: res = True
check("...it raises", res, True)
reset_server(); pl.set_privacy("strict")
for _ in range(3): ask(pl)
check("strict mode never calls a service that may train on the text", (hits["p3"], hits["p4"], hits["p5"], hits["p2"], hits["p1"]), (0, 0, 0, 0, 3))
prev = pl.preview("hello")
check("consent preview: says who would get the text, and whether it leaves this computer",
      ([x["provider"] for x in prev["sends_to"]], prev["leaves_this_computer"], prev["privacy"], prev["chars"]), (["P1", "P6"], True, "strict", 5))
pl2 = make([prov("loc", "yes", local=True, key=False, models=[])]); pl2.settings.change(None, "local_models", ["m1"])
check("consent preview: a local-only setup says nothing leaves", (pl2.preview("hi")["leaves_this_computer"], [x["local"] for x in pl2.preview("hi")["sends_to"]]), (False, [True]))
check("a local service with no model chosen is not used", [r["reason"] for r in make([prov("loc", local=True, key=False, models=[])]).explain(10, 10)], ["no model chosen"])

# ================================================================ keys, switches, account ids
reset_server()
cf = prov("cf", base=f"http://127.0.0.1:{PORT}/cf/{{account_id}}/v1", needs=["account_id"], account_id_env="CF_ACCOUNT")
pl = make([cf, prov("nokey")], env={"NOKEY_KEY": ""})
check("no key: not used, and says so", [r["reason"] for r in pl.explain(10, 10) if r["provider"] == "nokey"], ["no key saved"])
check("an account id that is needed but missing: not used", [r["reason"] for r in pl.explain(10, 10) if r["provider"] == "cf"], ["its account id is not saved"])
check("nothing set up means the pool is not ready", pl.ready(), False)
pl.settings.env["CF_ACCOUNT"] = "abcdef123456"
check("...with the account id it is ready", pl.ready(), True)
# the path contains the account id, so the pretend server sees it as the first path part ("cf")
ask(pl)
check("the account id is put into the address", (hits["cf"], seen[-1][0]), (1, "cf"))
pl.set_enabled("cf", False)
check("a service can be switched off", [r["reason"] for r in pl.explain(10, 10) if r["provider"] == "cf"], ["switched off"])
for bad in ("", "short", "has space in it"):
    try: pl.save_key("cf", bad); res = bad == ""
    except ValueError: res = bad != ""
    check(f"save_key({bad!r}) {'clears' if bad == '' else 'is refused'}", res, True)
try: pl.save_key("nonexistent", "abcdefgh123"); res = False
except ValueError: res = True
check("a key for an unknown service is refused", res, True)
st = pl.status()
check("status() gives a settings page what it needs and no key", ("abcdef" in json.dumps(st), [s["id"] for s in st]), (False, ["cf", "nokey"]))

# ================================================================ the catalog
cat_dir = work / "catalogs"; cat_dir.mkdir()
(cat_dir / "d.json").write_text(json.dumps({"providers": [prov("a"), {"id": "BAD ID"}, prov("web", base="http://example.com/v1"), dict(prov("weird"), adapter="telnet"), "string", prov("b")]}))
(cat_dir / "u.json").write_text(json.dumps({"providers": [dict(prov("b"), label="Mine"), prov("c")]}))
c = pool.Catalog(cat_dir / "d.json", cat_dir / "u.json")
check("catalog: unusable entries are ignored (bad id, plain http to the internet, unknown adapter, not an object)", [p["id"] for p in c.providers()], ["a", "b", "c"])
check("catalog: the user's file replaces an entry with the same id", [p["label"] for p in c.providers() if p["id"] == "b"], ["Mine"])
(cat_dir / "u.json").write_text("{ broken")
time.sleep(0.01); os.utime(cat_dir / "u.json", None)
check("catalog: a broken user file is ignored, the bundled one stays", [p["id"] for p in pool.Catalog(cat_dir / "d.json", cat_dir / "u.json").providers()], ["a", "b"])
check("catalog: a missing file means no services, not a crash", pool.Catalog(cat_dir / "none.json").providers(), [])
real = pool.Catalog(Path("studio") / "providers.default.json").providers()
check("the bundled catalog loads: groq, cloudflare, ollama on by default; gemini only when switched on",
      ([p["id"] for p in real], {p["id"]: p["enabled_default"] for p in real}), (["groq", "cloudflare", "ollama", "gemini"], {"groq": True, "cloudflare": True, "ollama": True, "gemini": False}))
check("the bundled catalog: every service names its data-terms source and check date",
      all(p["privacy"]["source_url"].startswith("https://") and p["privacy"]["verified_on"] for p in real), True)
check("the bundled catalog: the Groq limits from the plan are there", [m["limits"]["tpm"] for p in real if p["id"] == "groq" for m in p["models"]][0], 8000)
sp = pool.Settings(work / "nofile.json", env={})
check("settings: with no file everything is the default", (sp.privacy(), sp.local_models(), sp.key(real[0])), ("strict", [], ""))

# ================================================================ the ai.py seam
ai._saved.update(at=None)
check("ai: 'pool' is a provider, needs no key of its own, and is listed for the settings page",
      ("pool" in ai.PROVIDERS, "pool" in ai.NO_KEY, any(p["id"] == "pool" and not p["needs_key"] for p in ai.public()["providers"])), (True, True, True))
check("ai: the list of models for the pool is just 'auto'", ai.list_models("pool"), ["auto"])
pool._pool = make([prov("a")]); reset_server()
out, tin, tout = ai.call("auto", "hello", S)
check("ai.call('auto') goes through the pool", (out[0]["hook"], tin, tout, ai.route("auto")), ("H", 500, 50, "a/m"))
pool._pool = None

# ================================================================ a retired model on the Gemini-style transport
reset_server()
calls = []
def fake_gemini(p, m, key, prompt, schema, timeout):
    calls.append(m["id"])
    if m["id"] != "new-model":
        raise pool.ProviderError(404, None, "not found")
    return {"ok": True}, 1, 1
gm = [{"id": i, "ctx": 100000, "json_mode": "schema", "tier": 1, "limits": {"rpm": None, "rpd": None, "tpm": None, "tpd": None, "reset": "utc"}, "status": "active"} for i in ("old-a", "old-b", "new-model")]
pg = make([prov("g", models=gm, adapter="gemini")], transports={"gemini": fake_gemini})
r = pg.probe("g")
check("a key check skips models the service no longer has", (r["key_ok"], r["model"], calls), (True, "new-model", ["old-a", "old-b", "new-model"]))
check("the missing ones are switched off, the working one is not", (pg.ledger.state("g", "old-a")["disabled"] != "", pg.ledger.state("g", "new-model")["disabled"]), (True, ""))

srv.shutdown()
print("ALL PASSED" if not fails else f"{len(fails)} failed: {fails}")
shutil.rmtree(work, ignore_errors=True)
sys.exit(1 if fails else 0)
