"""Finds a Python that can run ViralCut, and builds the project's virtual environment with it.

Nothing about versions is written down here. Instead:
  1. It looks for every Python on this computer (the Windows `py` launcher, the PATH, the usual install folders).
  2. It reads requirements.txt and asks PyPI which files each pinned package has, then works out which Python
     versions have a ready-made file for EVERY package on this kind of computer. (That is exactly what failed for
     Python 3.14 and numpy 2.2.6: no file, so pip tried to compile it.) Offline, it falls back to 3.10 to 3.13.
  3. It uses the newest installed Python that is on that list. If there is none, it offers to install the newest
     one that is (Windows: the official installer from python.org, per user, signature checked).
  4. It makes .venv with it (and replaces a .venv made with one that does not fit), then installs requirements.txt.

    python tools/pyenv.py check              show what was found and what is chosen
    python tools/pyenv.py ensure [--yes]     do all of it; the last line printed is the venv's python

Standard library only. Runs on any Python 3.8 or newer."""
import argparse
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FALLBACK = (10, 11, 12, 13)                 # used only when PyPI cannot be reached
CANDIDATE_MINORS = range(8, 16)             # Python 3.8 ... 3.15 are looked at
FLOOR = 10                                  # the project's own lowest Python (AGENTS.md)


# ---------------------------------------------------------------- what PyPI says
def parse_requirements(path):
    """[(name, version)] for every `name==version` line. Other lines (comments, options) are skipped."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([A-Za-z0-9_.\-+!]+)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def platform_ok(plat_tag, here=None):
    """Is a wheel's platform part (win_amd64, manylinux..., any) usable on this computer? `here` is replaced in tests."""
    here = (here or sysconfig.get_platform()).replace("-", "_").replace(".", "_")
    if plat_tag == "any":
        return True
    if here.startswith("win"):
        return plat_tag == here
    if here.startswith("linux"):
        return plat_tag.startswith(("manylinux", "musllinux")) or plat_tag == here
    if here.startswith("macosx"):
        return plat_tag.startswith("macosx")
    return plat_tag == here


def requires_ok(spec, minor):
    """Does a `requires_python` text such as '>=3.9,<4' allow Python 3.<minor>?"""
    for part in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        m = re.fullmatch(r"(>=|<=|>|<|==|!=)\s*(\d+)(?:\.(\d+))?(?:\.\*|\.\d+)?", part)
        if not m:
            continue
        op, want = m.group(1), (int(m.group(2)), int(m.group(3) or 0))
        have = (3, minor)
        ok = {">=": have >= want, "<=": have <= want, ">": have > want, "<": have < want, "==": have == want, "!=": have != want}[op]
        if not ok:
            return False
    return True


def wheel_ok(filename, minor, here=None):
    """Does this .whl file run on CPython 3.<minor> here? (tags: python-abi-platform)"""
    if not filename.endswith(".whl"):
        return False
    parts = filename[:-4].split("-")
    if len(parts) < 5:
        return False
    py, abi, plat = parts[-3:]
    if not any(platform_ok(p, here) for p in plat.split(".")):
        return False
    for p in py.split("."):
        if p.startswith("py3") and abi == "none":
            return True
        m = re.fullmatch(r"cp3(\d+)", p)
        if m:
            n = int(m.group(1))
            if abi == "abi3" and n <= minor:
                return True
            if abi == f"cp3{n}" and n == minor:
                return True
            if abi.startswith("cp3") and re.fullmatch(r"cp3\d+", abi) and int(abi[3:]) == minor and n == minor:
                return True
    return False


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "pyenv-check", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def supported_minors(reqs, fetch=fetch_json, minors=CANDIDATE_MINORS):
    """({minor: [why not, ...]}, offline). A minor with an empty list can install every pinned package.
    `fetch` is replaced in tests."""
    def one(item):
        name, ver = item
        try:
            return item, fetch(f"https://pypi.org/pypi/{name}/{ver}/json").get("urls") or []
        except Exception:  # noqa: BLE001 - offline, blocked, or a version PyPI does not know
            return item, None
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        info = dict(ex.map(one, reqs))
    if any(v is None for v in info.values()):
        return {m: [] for m in FALLBACK}, True
    result = {}
    for minor in minors:
        blocked = []
        for (name, ver), files in info.items():
            wheels = [f for f in files if f.get("packagetype") == "bdist_wheel"]
            if not wheels:
                continue                     # only a source file exists: assumed buildable (pure Python)
            if not any(wheel_ok(f["filename"], minor) and requires_ok(f.get("requires_python"), minor) for f in wheels):
                blocked.append(f"{name} {ver} has no ready-made file for Python 3.{minor}")
        result[minor] = blocked
    return result, False


# ---------------------------------------------------------------- Pythons on this computer
def probe(exe):
    """(major, minor, micro) of a python executable, or None when it does not run."""
    try:
        out = subprocess.run([str(exe), "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"], capture_output=True, text=True, timeout=30)
        m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", out.stdout.strip())
        return tuple(int(x) for x in m.groups()) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def candidate_paths():
    paths = []
    if os.name == "nt":
        try:
            out = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=30).stdout
            paths += re.findall(r"([A-Za-z]:\\[^\r\n]*?python[w]?\.exe)", out, re.I)
        except (OSError, subprocess.SubprocessError):
            pass
        for pattern in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python3*\python.exe"),
                        os.path.expandvars(r"%ProgramFiles%\Python3*\python.exe"), r"C:\Python3*\python.exe"):
            paths += glob.glob(pattern)
    for name in ["python", "python3"] + [f"python3.{m}" for m in CANDIDATE_MINORS]:
        found = shutil.which(name)
        if found and "WindowsApps" not in found:        # the Microsoft Store shortcut is not a real Python
            paths.append(found)
    paths.append(sys.executable)
    seen, out = set(), []
    for p in paths:
        key = os.path.normcase(os.path.realpath(p))
        if key not in seen and os.path.isfile(p):
            seen.add(key)
            out.append(p)
    return out


def find_pythons(candidates=None, prober=probe):
    """[{exe, version}] for every working Python 3, newest first."""
    found = []
    for p in (candidate_paths() if candidates is None else candidates):
        v = prober(p)
        if v and v[0] == 3:
            found.append({"exe": str(p), "version": v})
    return sorted(found, key=lambda f: f["version"], reverse=True)


def choose(pythons, ok_minors):
    """The newest installed Python whose minor version is supported and not below the project's floor."""
    good = [p for p in pythons if p["version"][1] in ok_minors and p["version"][1] >= FLOOR]
    return good[0] if good else None


def run(cmd, say=print, cwd=None):
    """Run a command, pass every line it prints to `say` (so a log file gets it too), return its exit code."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env,
                         text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        say(line.rstrip("\r\n"))
    return p.wait()


# ---------------------------------------------------------------- installing Python (Windows only)
def _get(url, timeout=30, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "pyenv-install"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest_installer(minor, listing=None, exists=None):
    """URL of the newest official 64-bit Windows installer for Python 3.<minor>. Some late patch releases are source
    only, so each version is checked for a real installer file, newest first."""
    html = listing if listing is not None else _get("https://www.python.org/ftp/python/").read().decode("utf-8", "replace")
    patches = sorted({int(m) for m in re.findall(rf'href="3\.{minor}\.(\d+)/"', html)}, reverse=True)
    check = exists or (lambda u: _get(u, method="HEAD").status == 200)
    for n in patches[:8]:
        url = f"https://www.python.org/ftp/python/3.{minor}.{n}/python-3.{minor}.{n}-amd64.exe"
        try:
            if check(url):
                return url
        except Exception:  # noqa: BLE001 - a missing file is an HTTP error
            continue
    raise RuntimeError(f"no installer for Python 3.{minor} was found on python.org")


def signature_ok(path):
    """Windows: is the file signed by the Python Software Foundation and not tampered with?"""
    cmd = (f"$s = Get-AuthenticodeSignature -FilePath '{path}'; "
           "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -like '*Python Software Foundation*') { 'OK' } else { 'BAD' }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return out.strip().endswith("OK")


def install_python(minor, assume_yes=False, say=print):
    if os.name != "nt":
        raise RuntimeError(f"Install Python 3.{minor} with your system's package manager (for example: sudo apt install python3.{minor}-venv), then run this again.")
    url = latest_installer(minor)
    if not assume_yes:
        ans = input(f"No suitable Python is installed. Install Python 3.{minor} for your user only (about 25 MB, from python.org)? [Y/n] ").strip().lower()
        if ans not in ("", "y", "yes"):
            raise RuntimeError("Cancelled. Install a supported Python yourself and run this again.")
    tmp = Path(tempfile.mkdtemp(prefix="pyinst-")) / url.rsplit("/", 1)[1]
    say(f"Downloading {url} ...")
    with _get(url, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if not signature_ok(tmp):
        raise RuntimeError("The downloaded installer is not signed by the Python Software Foundation, so it was not run.")
    say("Installing (a few minutes, no window)...")
    rc = run([tmp, "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0", "Include_test=0",
              "Include_pip=1", "Shortcuts=0", "AssociateFiles=0"], say)
    if rc != 0:
        raise RuntimeError(f"The Python installer stopped with code {rc}.")
    shutil.rmtree(tmp.parent, ignore_errors=True)


# ---------------------------------------------------------------- the virtual environment
def venv_python(venv):
    return Path(venv) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv(py, ok_minors, req=None, venv=None, say=print):
    venv = Path(venv or ROOT / ".venv")
    req = Path(req or ROOT / "requirements.txt")
    vp = venv_python(venv)
    if vp.exists():
        v = probe(vp)
        if not v or v[1] not in ok_minors:
            say(f"The existing .venv uses Python {'.'.join(map(str, v)) if v else '(broken)'}, which does not fit. Replacing it...")
            if venv.name != ".venv":
                raise RuntimeError(f"refusing to delete {venv}")
            shutil.rmtree(venv)
    if not venv_python(venv).exists():
        say(f"Making the virtual environment with Python {'.'.join(map(str, py['version']))} ...")
        if run([py["exe"], "-m", "venv", str(venv)], say) != 0:
            raise RuntimeError("The virtual environment could not be made. Read the lines above this message.")
    say("Installing the packages (quick when they are already there)...")
    rc = run([venv_python(venv), "-m", "pip", "install", "--disable-pip-version-check", "-r", req], say)
    if rc != 0:
        raise RuntimeError("The packages did not install. Read the lines above this message.")
    return venv_python(venv)


def plan(req=None, fetch=fetch_json, candidates=None, prober=probe):
    reqs = parse_requirements(req or ROOT / "requirements.txt")
    table, offline = supported_minors(reqs, fetch)
    ok = sorted(m for m, why in table.items() if not why)
    return {"table": table, "offline": offline, "ok": ok, "pythons": find_pythons(candidates, prober)}


def report(p) -> str:
    lines = [f"Python versions that can install every pinned package: {', '.join('3.' + str(m) for m in p['ok']) or 'none'}"
             + ("  (PyPI could not be reached: using the offline default)" if p["offline"] else "")]
    for m, why in sorted(p["table"].items()):
        if why and m >= 9:
            lines.append(f"  3.{m} is not usable: {why[0]}" + (f" (+{len(why) - 1} more)" if len(why) > 1 else ""))
    lines.append("Pythons found on this computer:")
    for f in p["pythons"] or []:
        mark = "usable" if f["version"][1] in p["ok"] and f["version"][1] >= FLOOR else "does not fit"
        lines.append(f"  {'.'.join(map(str, f['version']))}  {f['exe']}  ({mark})")
    if not p["pythons"]:
        lines.append("  none")
    return "\n".join(lines)


def ensure(assume_yes=False, say=print, req=None):
    p = plan(req)
    say(report(p))
    if not p["ok"]:
        raise RuntimeError("No Python version can install all the pinned packages. requirements.txt needs updating.")
    pick = choose(p["pythons"], p["ok"])
    if not pick:
        install_python(max(p["ok"]), assume_yes, say)
        p["pythons"] = find_pythons()
        pick = choose(p["pythons"], p["ok"])
        if not pick:
            raise RuntimeError("Python was installed but could not be found. Open a new window and run this again.")
    say(f"Using Python {'.'.join(map(str, pick['version']))} at {pick['exe']}")
    return ensure_venv(pick, p["ok"], req, say=say)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["check", "ensure"])
    ap.add_argument("--yes", action="store_true", help="install Python without asking")
    a = ap.parse_args(argv)
    try:
        if a.what == "check":
            p = plan()
            print(report(p))
            pick = choose(p["pythons"], p["ok"])
            print(f"Would use: {pick['exe'] if pick else 'nothing installed fits: would offer to install Python 3.' + str(max(p['ok'])) if p['ok'] else 'n/a'}")
            return 0
        print(ensure(a.yes))
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"\nProblem: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
