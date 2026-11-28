"""Model lists: logged in full, and the ones our own list calls good are suggested first. No network, no keys."""
import os, sys, tempfile
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-mh-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0")
sys.path.insert(0, ".")
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

from studio import ai, applog, pool

REC = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
a, b = "gemini-3.5-flash-lite", "gemini-3.9-pro-preview"
check("a recommended model beats a newer unknown one", pool.rank_model(a, [], REC) > pool.rank_model(b, [], REC))
check("earlier in our list ranks higher", pool.rank_model(REC[0], [], REC) > pool.rank_model(REC[2], [], REC))
check("a dated copy of a recommended model gets a smaller lift", pool.rank_model("gemini-3.5-flash-lite-001", [], REC) > pool.rank_model("gemini-3.5-flash-lite-x", [], []) - 1 and pool.rank_model("gemini-3.5-flash-lite-001", [], REC) < pool.rank_model(a, [], REC))
check("nothing recommended: the old order is unchanged", pool.rank_model(a, ["x"]) == pool.rank_model(a, ["x"], ()))

# the service's real catalog keeps the list, and a hand-edited entry cannot smuggle odd text in
cat = pool.Catalog(Path("studio/providers.default.json"))
g = next(p for p in cat.providers() if p["id"] == "gemini")
check("the bundled catalog carries the recommended models", g["recommended"][0], "gemini-3.5-flash-lite")
bad = pool._clean_provider({"id": "x", "adapter": "openai", "base_url": "https://example.com/v1", "recommended": ["ok-1", "bad id; rm", 5, "also/ok:2"]})
check("odd entries are dropped", bad["recommended"], ["ok-1", "also/ok:2"])

# logging a long list loses nothing
names = [f"model-number-{i:03d}-flash" for i in range(60)]
applog.log_list("test.models", names, provider="gemini")
lines = [l for l in applog.tail(100).splitlines() if "test.models" in l]
joined = ",".join(l.split("items=", 1)[1].split(" ")[0] for l in lines)
check("every model name is in the log, over several lines", (len(lines) > 1, joined.split(",") == names), (True, True))
check("each line says which part it is", "part=1/" in lines[0], True)

# the suggestion: only from the listed models, our list first, no speech/image models
listed = ["gemini-embedding-001", "gemini-3.9-pro-preview", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.0-flash-live", "gemini-3.8-flash"]
sug = ai.suggest_models("gemini", listed)
check("suggested models come from the list, ours first", sug[:2], ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"])
check("embedding and live models are never suggested", not any("embed" in m or "live" in m for m in sug), True)
check("an unknown service still gets a sensible order", ai.suggest_models("openai", ["gpt-9-mini", "text-embedding-3", "gpt-9-pro-preview"])[0], "gpt-9-mini")
log = applog.tail(300)
check("the log shows the list, the suggestion and what was missing", ("ai.models " in log, "ai.models.suggested" in log, "recommended_in_list" in log), (True, True, True))

print("ALL PASSED" if not fails else f"{len(fails)} failed: {fails}")
sys.exit(1 if fails else 0)
