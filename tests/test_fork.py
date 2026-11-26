"""The fork's own basics: the licence keeps both notices, nothing points at the original project's name or links,
the update check looks at this fork only, a zip without .git still knows its version, and the app's name lives
in one file. No network, no AI key."""
import json, os, re, shutil, sys, tempfile
from pathlib import Path
os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-fork-"))
sys.path.insert(0, ".")
from studio import branding, config, updates
ROOT = Path(__file__).resolve().parent.parent
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

# the upstream name is built from pieces so this file does not contain it in one piece
UPSTREAM = "haziq" + "ahmedqasmi"
UPSTREAM_SHORT = "haziq" + ".builds"

# ---- licence: both notices, the fork's line first
lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
check("LICENSE has the fork line", "Copyright (c) 2026 Amfaiz" in lic)
check("LICENSE keeps the original notice", "Copyright (c) 2026 PeakCut contributors" in lic)
check("the fork line comes above the original one", lic.index("Amfaiz") < lic.index("PeakCut contributors"))
check("LICENSE is still the MIT text", "Permission is hereby granted, free of charge" in lic)

# ---- no text or link in the app mentions the original author (the docs folder is history and is left out)
skip_dirs = {".git", "docs", "__pycache__", "data", ".venv", "venv"}
hits = []
for p in ROOT.rglob("*"):
    if not p.is_file() or set(p.relative_to(ROOT).parts) & skip_dirs or p.name == "test_fork.py":
        continue
    if p.suffix.lower() in {".png", ".jpg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".zip", ".onnx", ".pyc"}:
        continue
    try:
        text = p.read_text(encoding="utf-8").lower()
    except (UnicodeError, OSError):
        continue
    if UPSTREAM in text or UPSTREAM_SHORT in text:
        hits.append(str(p.relative_to(ROOT)))
check("no file outside docs/ names the original author", hits, [])

# ---- defaults point at this fork only
check("the update repository is this fork", updates.REPO, branding.REPO)
check("the dashboard's code link is this fork", config.REPO_URL in ("", branding.REPO_URL) or "PEAKCUT_REPO_URL" in os.environ, True)
check("the 'Follow' link is empty (so the button is hidden) unless set", config.FOLLOW_URL == "" or "PEAKCUT_FOLLOW_URL" in os.environ, True)
check("branding: repo link is built from the repo name", branding.REPO_URL, "https://github.com/" + branding.REPO)
check("branding: copyright line matches LICENSE", branding.COPYRIGHT in lic, True)

# ---- a mocked GitHub answer produces no notice text that names the original author
class R:
    status_code = 200
    def __init__(self, d): self._d = d
    def json(self): return self._d
asked = []
def fake_get(url, timeout=None, headers=None, params=None):
    asked.append(url)
    return R({"ahead_by": 1, "commits": [{"sha": "abcdef1234", "commit": {"message": "Fix a thing", "committer": {"date": "2026-11-17T10:00:00Z"}}}]})
updates.httpx.get = fake_get
note = updates._ask_github("e" * 40)
check("GitHub is asked about this fork only", asked and asked[0].startswith(f"https://api.github.com/repos/{branding.REPO}/compare/"), True)
check("the notice text does not name the original author", UPSTREAM not in json.dumps(note).lower(), True)
check("the notice links to this fork", note["url"].startswith(branding.REPO_URL), True)

# ---- the version of a copy without .git (a downloaded zip)
real_root = config.ROOT
fake = Path(tempfile.mkdtemp(prefix="pc-ver-"))
try:
    config.ROOT = fake
    check("no .git and no VERSION: unknown", updates.current(), "")
    (fake / "VERSION").write_text("a" * 40 + "\n", encoding="utf-8")
    check("VERSION file gives the version", updates.current(), "a" * 40)
    (fake / "VERSION").write_text("A" * 40 + "\n", encoding="utf-8")
    check("...capital letters are accepted", updates.current(), "a" * 40)
    (fake / "VERSION").write_text("v1.2.3\n", encoding="utf-8")
    check("a VERSION that is not a commit id is ignored", updates.current(), "")
    (fake / "VERSION").write_text("a" * 40 + "; rm -rf /\n" + "b" * 40, encoding="utf-8")
    check("a VERSION with extra text on the line is ignored", updates.current(), "")
    (fake / "VERSION").write_bytes(b"\xff\xfe\x00bad")
    check("a VERSION that is not text is ignored, no crash", updates.current(), "")
    (fake / "VERSION").write_text("a" * 40, encoding="utf-8")
    (fake / ".git").mkdir()
    (fake / ".git" / "HEAD").write_text("c" * 40 + "\n")
    check("when both exist, .git wins", updates.current(), "c" * 40)
    shutil.rmtree(fake / ".git")
    asked.clear()
    updates._state.update(checked=0, result=None)
    got = updates.check(force=True)
    check("check() works from a VERSION file alone (no .git)",
          (len(asked) == 1 and asked[0].endswith("/compare/" + "a" * 40 + "..." + updates.BRANCH), bool(got and got["behind"] == 1)), (True, True))
finally:
    config.ROOT = real_root
    shutil.rmtree(fake, ignore_errors=True)

# ---- the name lives in one file, and old setting names keep working
check("branding has the app name", branding.APP_NAME and branding.COMPANY == "Amfaiz")
check("the data folder name is 'data'", branding.DATA_DIR_NAME, "data")
for k in ("PEAKCUT_T1", "NEWAPP_T1"):
    os.environ.pop(k, None)
os.environ["PEAKCUT_T1"] = "old"
check("old name works", branding.env("T1"), "old")
real = (branding.ENV_PREFIX, branding.LEGACY_ENV_PREFIX)
branding.ENV_PREFIX = "NEWAPP"
try:
    check("after a rename the old name still works", branding.env("T1"), "old")
    os.environ["NEWAPP_T1"] = "new"
    check("...and the new name wins when both are set", branding.env("T1"), "new")
    check("names are listed newest first", branding.env_names("T1"), ["NEWAPP_T1", "PEAKCUT_T1"])
    os.environ["NEWAPP_T1"] = ""
    check("an empty new value counts as not set", branding.env("T1"), "old")
finally:
    branding.ENV_PREFIX, branding.LEGACY_ENV_PREFIX = real
    os.environ.pop("PEAKCUT_T1", None); os.environ.pop("NEWAPP_T1", None)
check("two prefixes: newest first, old name still understood", branding.env_names("X"), ["VIRALCUT_X", "PEAKCUT_X"])
check("missing setting gives the default", branding.env("NOT_THERE_AT_ALL", "d"), "d")

# ---- repository files that later slices rely on
gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
check(".gitignore lets the portable launcher in", "!installer/*.bat" in gi and gi.index("*.bat") < gi.index("!installer/*.bat"))
ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
check("CI runs on Windows and Linux", "windows-latest" in ci and "ubuntu-latest" in ci and "tests/run.py" in ci)
check("CONTRIBUTING.md and DECISIONS.md exist", (ROOT / "CONTRIBUTING.md").is_file() and (ROOT / "docs" / "DECISIONS.md").is_file())

import importlib
os.environ["VIRALCUT_PORT"] = "8123"; os.environ["PEAKCUT_PORT"] = "9999"
check("the new setting prefix works for every setting and wins over the old one", importlib.reload(config).PORT, 8123)
os.environ.pop("VIRALCUT_PORT"); importlib.reload(config)
check("the old setting prefix still works", config.PORT, 9999)
os.environ.pop("PEAKCUT_PORT"); importlib.reload(config)
check("the product name shown is ViralCut", branding.APP_NAME, "ViralCut")
print("ALL PASSED" if not fails else f"{len(fails)} failed")
if "PEAKCUT_DATA" in os.environ and os.environ["PEAKCUT_DATA"].startswith(tempfile.gettempdir()) and "pc-fork-" in os.environ["PEAKCUT_DATA"]:
    shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
