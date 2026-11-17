"""The Python finder: no version is written down, so this checks the rules it uses. PyPI answers and Pythons are faked,
so no internet is needed. Covers: which wheel files fit which Python, which Python a package allows, the supported-version
table (including the Python 3.14 + numpy case that failed for real), choosing among installed Pythons, the offline fallback,
finding an installer, and replacing a virtual environment that does not fit."""
import os, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, "tools")
import pyenv
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

WIN = "win-amd64"
def fits(name, minors=range(8, 16)): return [m for m in minors if pyenv.wheel_ok(name, m, WIN)]

check("a Windows cp313 wheel fits only Python 3.13", fits("numpy-2.2.6-cp313-cp313-win_amd64.whl"), [13])
check("a stable-ABI wheel (abi3) fits its version and every newer one", fits("pydantic_core-2-cp311-abi3-win_amd64.whl"), [11, 12, 13, 14, 15])
check("a pure Python wheel fits everything", fits("idna-3-py3-none-any.whl"), list(range(8, 16)))
check("a 32-bit wheel does not fit a 64-bit Windows", fits("x-1-cp313-cp313-win32.whl"), [])
check("a Linux wheel does not fit Windows", fits("x-1-cp313-cp313-manylinux_2_17_x86_64.whl"), [])
check("a source archive is not a wheel", pyenv.wheel_ok("numpy-2.2.6.tar.gz", 13, WIN), False)
check("a Linux machine accepts manylinux wheels", pyenv.wheel_ok("x-1-cp313-cp313-manylinux_2_28_x86_64.whl", 13, "linux-x86_64"), True)

check("requires_python '>=3.9,<4' allows 3.13", pyenv.requires_ok(">=3.9,<4", 13), True)
check("requires_python '>=3.10' refuses 3.9", pyenv.requires_ok(">=3.10", 9), False)
check("requires_python '<3.13' refuses 3.13", pyenv.requires_ok(">=3.8,<3.13", 13), False)
check("no requires_python allows anything", pyenv.requires_ok(None, 14), True)

# a fake PyPI, shaped like the real one, with numpy only up to Python 3.13 (what really happened)
def whl(name, py, abi="none", plat="any", req=None):
    return {"packagetype": "bdist_wheel", "filename": f"{name}-1-{py}-{abi}-{plat}.whl", "requires_python": req}
FAKE = {
    "numpy": [whl("numpy", f"cp3{m}", f"cp3{m}", "win_amd64") for m in (10, 11, 12, 13)],
    "idna": [whl("idna", "py3", req=">=3.8")],
    "newpkg": [whl("newpkg", "cp311", "abi3", "win_amd64", req=">=3.11")],
    "srconly": [{"packagetype": "sdist", "filename": "srconly-1.tar.gz"}],
}
def fetch_for(names):
    def fetch(url):
        for n in names:
            if f"/{n}/" in url: return {"urls": FAKE[n]}
        raise OSError("unknown package")
    return fetch
real_plat = pyenv.sysconfig.get_platform
pyenv.sysconfig.get_platform = lambda: WIN                      # pretend to be 64-bit Windows
try:
    table, offline = pyenv.supported_minors([("numpy", "2.2.6"), ("idna", "3")], fetch_for(["numpy", "idna"]), range(9, 16))
    ok = sorted(m for m, why in table.items() if not why)
    check("numpy with no 3.14 file makes 3.14 unusable and 3.13 usable", (ok, offline), ([10, 11, 12, 13], False))
    check("the reason names the package and the version", "numpy 2.2.6" in " ".join(table[14]) and "3.14" in " ".join(table[14]), True)
    table2, _ = pyenv.supported_minors([("numpy", "2.2.6"), ("newpkg", "1")], fetch_for(["numpy", "newpkg"]), range(9, 16))
    check("a package that needs >=3.11 removes 3.10", sorted(m for m, w in table2.items() if not w), [11, 12, 13])
    table3, _ = pyenv.supported_minors([("srconly", "1")], fetch_for(["srconly"]), range(9, 16))
    check("a package with only a source file does not block any version", all(not w for w in table3.values()), True)
    table4, off4 = pyenv.supported_minors([("numpy", "2.2.6"), ("ghost", "9")], fetch_for(["numpy"]), range(9, 16))
    check("when PyPI cannot answer, the offline default is used and flagged", (off4, sorted(table4)), (True, list(pyenv.FALLBACK)))
finally:
    pyenv.sysconfig.get_platform = real_plat

# choosing among installed Pythons
P = lambda v, exe=None: {"exe": exe or f"py{v[1]}", "version": v}
found = pyenv.find_pythons(["a", "b", "c", "d", "e"], prober=lambda p: {"a": (3, 14, 6), "b": (3, 13, 18), "c": (3, 11, 2), "d": None, "e": (2, 7, 18)}[p])
check("find_pythons keeps working Python 3 only, newest first", [f["version"][1] for f in found], [14, 13, 11])
check("choose takes the newest that is supported (skips 3.14)", pyenv.choose(found, [10, 11, 12, 13])["version"], (3, 13, 18))
check("choose returns nothing when none fits", pyenv.choose([P((3, 14, 6))], [10, 11, 12, 13]), None)
check("choose never goes below the project's lowest Python", pyenv.choose([P((3, 9, 1))], [9, 10]), None)

# the installer lookup
LISTING = '<a href="3.13.0/">3.13.0/</a><a href="3.13.9/">3.13.9/</a><a href="3.13.12/">3.13.12/</a><a href="3.12.4/">3.12.4/</a>'
asked = []
def exists(u): asked.append(u); return u.endswith("3.13.9-amd64.exe")           # the newest patch has no installer (source only)
url = pyenv.latest_installer(13, LISTING, exists)
check("the newest patch with a real installer is chosen, numerically", url, "https://www.python.org/ftp/python/3.13.9/python-3.13.9-amd64.exe")
check("patch 12 was tried before 9 (numeric order, not text order)", asked[0].endswith("3.13.12-amd64.exe"), True)
try: pyenv.latest_installer(99, LISTING, exists); got = "no error"
except RuntimeError as e: got = "3.99" in str(e)
check("a Python with no installer is a clear error", got, True)

# requirements parsing
w = Path(tempfile.mkdtemp(prefix="pc-pyenv-"))
(w / "r.txt").write_text("# comment\nfastapi==0.1  # x\n\nSQLAlchemy==2.0.57\npsycopg[binary]==3.3\n-r other.txt\nnotpinned>=1\n", encoding="utf-8")
check("requirements are read as name==version only", pyenv.parse_requirements(w / "r.txt"), [("fastapi", "0.1"), ("SQLAlchemy", "2.0.57"), ("psycopg", "3.3")])
real = pyenv.parse_requirements(Path("requirements.txt"))
check("the project's own requirements.txt parses to pinned packages", len(real) >= 10 and all(v[0].isdigit() for _, v in real), True)

# a venv made with an unsupported Python is replaced; a fitting one is kept (real venv, empty requirements, no network)
(w / "empty.txt").write_text("# nothing\n", encoding="utf-8")
here = sys.version_info[:3]
me = {"exe": sys.executable, "version": here}
venv = w / ".venv"
msgs = []
pyenv.ensure_venv(me, [here[1]], w / "empty.txt", venv, say=msgs.append)
(venv / "marker.txt").write_text("x")
pyenv.ensure_venv(me, [here[1]], w / "empty.txt", venv, say=msgs.append)
check("a venv whose Python fits is kept", (venv / "marker.txt").exists(), True)
pyenv.ensure_venv(me, [99], w / "empty.txt", venv, say=msgs.append)
check("a venv whose Python does not fit is replaced", (venv / "marker.txt").exists(), False)
check("it says why it replaced it", any("does not fit" in m for m in msgs), True)
other = w / "other-env"
pyenv.ensure_venv(me, [here[1]], w / "empty.txt", other, say=msgs.append)
try: pyenv.ensure_venv(me, [99], w / "empty.txt", other, say=msgs.append); got = "no error"
except RuntimeError as e: got = "refusing" in str(e)
check("it only ever deletes a folder named .venv", (got, other.exists()), (True, True))

# the streaming runner passes lines on, and returns the exit code
lines = []
rc = pyenv.run([sys.executable, "-c", "print('a'); import sys; print('b', file=sys.stderr); sys.exit(3)"], lines.append)
check("run() returns the exit code and passes stdout and stderr lines on", (rc, sorted(lines)), (3, ["a", "b"]))

# the real machine: offline here, so only the shape is checked
p = pyenv.plan(Path("requirements.txt"), fetch=fetch_for([]))
check("plan() falls back offline and still finds this Python", (p["offline"], bool(p["pythons"])), (True, True))
check("report() is readable text", "can install every pinned package" in pyenv.report(p), True)

shutil.rmtree(w, ignore_errors=True)
print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
