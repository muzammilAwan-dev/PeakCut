"""The portable build's logic that can be checked without Windows or the internet."""
import json, os, sys, tempfile, zipfile
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "tools")
import build_portable as bp
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

listing = '<a href="3.13.1/">x</a><a href="3.13.17/">x</a><a href="3.13.9/">x</a><a href="3.12.4/">x</a>'
check("embed url: newest patch that really has the file", bp.embed_url(13, listing, lambda u: "3.13.17" in u), "https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip")
check("embed url: skips a patch that is source only", bp.embed_url(13, listing, lambda u: "3.13.9" in u).endswith("3.13.9/python-3.13.9-embed-amd64.zip"), True)
try: bp.embed_url(13, listing, lambda u: False); res = "found"
except RuntimeError: res = "none"
check("embed url: says so when nothing is there", res, "none")

pth = "python313.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"
new = bp.patch_pth(pth)
check("pth: the packages and the app are on the path, site is on", (r"..\site-packages" in new, r"..\app" in new, new.strip().endswith("import site"), "#import site" in new), (True, True, True, False))
check("pth: running it twice changes nothing more", bp.patch_pth(new), new)

bat = bp.launcher_text("ViralCut", "VIRALCUT")
check("launcher: data and tools live beside it", all(x in bat for x in ('set "VIRALCUT_DATA=%~dp0data"', 'set "VIRALCUT_BIN_DIR=%~dp0bin"', r"python\python.exe -m studio.server")), True)
check("launcher: opens the browser and does not leave a Python of the user's on the path", ("start http://127.0.0.1:8765" in bat, 'PYTHONNOUSERSITE=1' in bat), (True, True))
check("launcher: plain ASCII (any Windows code page)", bat.isascii(), True)

cmd = bp.pip_command("py", Path("t"), Path("r.txt"), 13)
check("pip: only ready-made Windows files, for the chosen Python", ("--only-binary=:all:" in cmd, "win_amd64" in cmd, "cp313" in cmd, "3.13" in cmd), (True,) * 4)

src = Path(tempfile.mkdtemp()); dst = Path(tempfile.mkdtemp())
for f in ("studio/a.py", "studio/__pycache__/a.pyc", "web/index.html", "tests/t.py", "data/secret.json", "bin/ffmpeg.exe", "requirements.txt", "LICENSE"):
    (src / f).parent.mkdir(parents=True, exist_ok=True); (src / f).write_text("x")
got = sorted(bp.copy_app(src, dst))
check("copy: the app and its files, never data, tests, tools or caches", got, ["LICENSE", "requirements.txt", "studio/a.py", "web/index.html"])
check("copy: files really arrived", (dst / "studio" / "a.py").is_file() and not (dst / "data").exists(), True)

lock = Path(tempfile.mkdtemp()) / "lock.json"; said = []
bp.lock_check("u", "abc", lock, said.append)
check("lock: first build saves the fingerprint and says so", (json.loads(lock.read_text()), len(said)), ({"u": "abc"}, 1))
bp.lock_check("u", "abc", lock, said.append)
try: bp.lock_check("u", "zzz", lock, said.append); res = "used"
except RuntimeError: res = "refused"
check("lock: a different file for the same address is refused", (res, len(said)), ("refused", 1))

z = bp.make_zip(dst, Path(tempfile.mkdtemp()) / "o.zip")
names = zipfile.ZipFile(z).namelist()
check("zip: everything sits inside one folder", all(n.split("/")[0] == dst.name for n in names), True)
check("the build refuses to run on a computer that is not Windows (unless a dry run)", (os.name == "nt") or (bp.main(["--out", tempfile.mkdtemp()]) == 1), True)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
