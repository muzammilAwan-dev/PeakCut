"""The scoring kit and the eval command. No keys, no network."""
import contextlib, io, json, os, sys, tempfile
from pathlib import Path
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-ev-")
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0", PEAKCUT_LLM_CACHE="0")
sys.path.insert(0, "."); sys.path.insert(0, "tools")
from studio import brain, evalkit
import eval as ev
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)
S = lambda a, b, score=50: {"start": a, "end": b, "score": score}
check("hit: exactly half of the shorter span counts", evalkit.is_hit(S(0, 20), [S(10, 30)]), True)
check("hit: just under half does not", evalkit.is_hit(S(0, 20), [S(10.5, 30)]), False)
check("hit: a short pick inside a long human pick is judged on the short one", evalkit.is_hit(S(10, 20), [S(0, 100)]), True)
check("hit: no overlap, or an empty span", (evalkit.is_hit(S(0, 5), [S(6, 9)]), evalkit.is_hit(S(5, 5), [S(0, 9)])), (False, False))
H = [S(0, 30), S(100, 130), S(200, 230)]
P = [S(5, 25, 90), S(300, 330, 80), S(105, 125, 70), S(500, 530, 10)]
check("p@k: the best k by score, hits over k", (evalkit.precision_at_k(P, H, 1), evalkit.precision_at_k(P, H, 2), evalkit.precision_at_k(P, H, 3)), (1.0, 0.5, 2 / 3))
check("p@k: two picks inside one human moment are one find", evalkit.precision_at_k([S(0, 14, 90), S(15, 29, 80)], [S(0, 30)], 2), 0.5)
check("p@k: fewer picks than k count as misses", evalkit.precision_at_k([S(0, 30)], H, 5), 0.2)
check("recall: human picks that were found", evalkit.recall(P, H), 2 / 3)
check("agreement: same picks is 1, nothing in common is 0", (evalkit.agreement(H, H), evalkit.agreement(H, [S(900, 930)])), (1.0, 0.0))
check("union: near-copies from two people fold into one", len(evalkit.human_union([[S(0, 30)], [S(2, 29)], [S(100, 130)]])), 2)
m = evalkit.bootstrap_ci([0.2, 0.4, 0.6, 0.8])
check("bootstrap: the mean is right, the range holds it, same seed same answer", (m[0], m[1] <= m[0] <= m[2], evalkit.bootstrap_ci([0.2, 0.4, 0.6, 0.8]) == m), (0.5, True, True))
check("bootstrap: nothing in, zeros out", evalkit.bootstrap_ci([]), (0.0, 0.0, 0.0))
check("per hour", evalkit.per_hour(1000, 1800), 2000.0)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res = ev.main(["--demo", "--systems", "loudness", "--k", "1,3", "--runs", "2"])
out = buf.getvalue()
check("demo: prints a table, the ranges and the agreement", all(x in out for x in ("== loudness ==", "mean p@1", "95% range", "agree with each other")), True)
s = res["loudness"]["summary"]
check("demo: the loudness system finds the loud talkative stretch in the made-up set", s["p@1"][0], 1.0)
check("demo: the two runs of a system with no randomness do not differ", s["run_to_run_spread"], 0.0)
check("demo: three videos were scored", len(res["loudness"]["rows"]), 3)

# the 'current' system with the AI stubbed: it must see the pick the AI returns, and cost tokens
tmp = Path(tempfile.mkdtemp()); ev.make_demo(tmp)
videos = evalkit.load_set(tmp)
brain.config.ai_ready = lambda: True
brain.ai.models = lambda: ["m"]; brain.ai.route = lambda m: "stub/m"
def fake_call(model, prompt, schema):
    return [{"start": 118, "end": 150, "score": 90, "category": "funny", "hook": "H", "title": "T", "description": "D", "hashtags": ["a"], "reason": "R"}], 500, 50
brain.ai.call = fake_call
r = ev.evaluate(videos[:1], ["current"], [1], runs=1)["current"]
check("current: the stubbed AI pick is scored and its tokens are counted", (r["rows"][0]["prec"][1], r["rows"][0]["tokens"] > 0, r["summary"]["tokens_per_hour"] > 0), (1.0, True, True))
try:
    with contextlib.redirect_stderr(io.StringIO()): ev.main(["--demo", "--systems", "nope"])
    refused = False
except SystemExit: refused = True
check("an unknown system is refused with a message, not a crash", refused, True)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
