"""Builds the portable Windows folder and zip: unzip it anywhere and double-click the launcher. No installer, no Python needed.

    python tools/build_portable.py [--out dist] [--minor 13] [--dry-run]

Run it on a Windows computer with internet. It finds the Python version by itself (the newest one that has ready-made
files for every package in requirements.txt, the same rule as tools/pyenv.py), downloads that version's "embeddable"
Python from python.org, installs the packages into the folder, copies the app and writes the launcher.
ffmpeg and Deno are NOT put in the zip: the app fetches them on first start from the pinned, checked list
(studio/pins.json), so the zip stays small and no GPL program is bundled.

Folder it makes:
    <App>\\<App>.bat        double-click this
    <App>\\python\\         the embeddable Python
    <App>\\site-packages\\  the packages
    <App>\\app\\            the program (studio, web)
    <App>\\bin\\            ffmpeg and Deno arrive here on first start
    <App>\\data\\           everything the user makes, settings and keys: copy this folder to move house

The embeddable Python's fingerprint is remembered in tools/portable.lock.json the first time and checked on every
later build; on Windows the python.exe inside must also carry the Python Software Foundation's signature."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from studio import branding  # noqa: E402
import pyenv  # noqa: E402

LOCK = ROOT / "tools" / "portable.lock.json"
APP_FILES = ("requirements.txt", "requirements-optional.txt", "LICENSE", "README.md", "VERSION")
APP_DIRS = ("studio", "web")
SKIP = {"__pycache__", ".git", ".venv", "data", "bin", "tests", ".claude"}


def embed_url(minor, listing=None, exists=None):
    """Address of the newest embeddable 64-bit Python 3.<minor> on python.org (checked, since late patches can be source only)."""
    html = listing if listing is not None else pyenv._get("https://www.python.org/ftp/python/").read().decode("utf-8", "replace")
    patches = sorted({int(m) for m in re.findall(rf'href="3\.{minor}\.(\d+)/"', html)}, reverse=True)
    check = exists or (lambda u: pyenv._get(u, method="HEAD").status == 200)
    for n in patches[:8]:
        url = f"https://www.python.org/ftp/python/3.{minor}.{n}/python-3.{minor}.{n}-embed-amd64.zip"
        try:
            if check(url):
                return url
        except Exception:  # noqa: BLE001 - a missing file is an HTTP error
            continue
    raise RuntimeError(f"no embeddable Python 3.{minor} was found on python.org")


def patch_pth(text: str) -> str:
    """Lets the embedded Python see the packages and the app, and switches `site` on (it is off in the embeddable build)."""
    lines = [l for l in text.splitlines() if l.strip() and not l.strip().lstrip("#").strip() == "import site"
             and not l.lstrip().startswith("# Uncomment")]
    for extra in (r"..\site-packages", r"..\app"):
        if extra not in lines:
            lines.append(extra)
    lines.append("import site")
    return "\n".join(lines) + "\n"


def launcher_text(name: str, prefix: str) -> str:
    return f"""@echo off
setlocal
title {name}
cd /d "%~dp0"
if not exist data mkdir data
set "{prefix}_DATA=%~dp0data"
set "{prefix}_BIN_DIR=%~dp0bin"
set "{prefix}_HOST=127.0.0.1"
set "PATH=%~dp0bin;%~dp0python;%PATH%"
set "PYTHONNOUSERSITE=1"
echo Starting {name}. Keep this window open while you use it; close it to stop.
echo When it says it is ready, your browser opens by itself. If not, open http://127.0.0.1:8765
start "" /b cmd /c "timeout /t 6 /nobreak >nul & start http://127.0.0.1:8765"
python\\python.exe -m studio.server
echo.
echo {name} stopped. Press any key to close.
pause >nul
"""


def copy_app(src: Path, dst: Path) -> list:
    out = []
    for d in APP_DIRS:
        for p in sorted((src / d).rglob("*")):
            rel = p.relative_to(src)
            if p.is_dir() or SKIP & set(rel.parts) or p.suffix in (".pyc", ".pyo"):
                continue
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst / rel)
            out.append(str(rel).replace("\\", "/"))
    for f in APP_FILES:
        if (src / f).is_file():
            shutil.copyfile(src / f, dst / f)
            out.append(f)
    return out


def pip_command(py, target: Path, req: Path, minor: int) -> list:
    return [str(py), "-m", "pip", "install", "--no-input", "--only-binary=:all:", "--platform", "win_amd64", "--implementation", "cp",
            "--python-version", f"3.{minor}", "--abi", f"cp3{minor}", "--target", str(target), "-r", str(req)]


def lock_check(url: str, digest: str, lock=LOCK, say=print):
    """Trust on first use: the first build records the fingerprint, every later build must match it."""
    data = json.loads(lock.read_text(encoding="utf-8")) if lock.is_file() else {}
    have = data.get(url)
    if have and have != digest:
        raise RuntimeError("The embeddable Python does not match the fingerprint saved by an earlier build. Not used.")
    if not have:
        data[url] = digest
        lock.write_text(json.dumps(data, indent=1), encoding="utf-8")
        say(f"First build with this Python: its SHA-256 is {digest}. Saved in {lock.name}. Commit that file.")


def make_zip(folder: Path, out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, Path(folder.name) / p.relative_to(folder))
    return out


def build(out_dir: Path, minor=None, dry=False, say=print, with_extras=True):
    if os.name != "nt" and not dry:
        raise RuntimeError("Run this on Windows (the zip holds the Windows build of Python and the packages).")
    plan = pyenv.plan()
    ok = plan["ok"]
    if not ok:
        raise RuntimeError("No Python version has ready-made files for every package.")
    minor = int(minor or max(ok))
    if minor not in ok:
        raise RuntimeError(f"Python 3.{minor} cannot install every package (usable: {', '.join('3.' + str(m) for m in ok)}).")
    name = branding.APP_NAME
    url = embed_url(minor)
    folder = out_dir / name
    say(f"{name}: Python 3.{minor} -> {url}")
    if dry:
        say(f"(dry run) would build {folder} and {out_dir / (name + '-portable.zip')}")
        return None
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "python").mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="pc-embed-"))
    try:
        zpath = tmp / "embed.zip"
        say("Downloading the embeddable Python ...")
        with pyenv._get(url, timeout=60) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        lock_check(url, hashlib.sha256(zpath.read_bytes()).hexdigest(), say=say)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(folder / "python")
        if not pyenv.signature_ok(folder / "python" / "python.exe"):
            raise RuntimeError("python.exe in the download is not signed by the Python Software Foundation. Stopped.")
        pth = next((folder / "python").glob("python3*._pth"))
        pth.write_text(patch_pth(pth.read_text(encoding="utf-8")), encoding="utf-8")
        say("Installing the packages (a few minutes) ...")
        subprocess.run(pip_command(sys.executable, folder / "site-packages", ROOT / "requirements.txt", minor), check=True)
        optional = ROOT / "requirements-optional.txt"
        if with_extras and optional.is_file():
            say("Installing the optional extras (follow-the-face) ...")
            subprocess.run(pip_command(sys.executable, folder / "site-packages", optional, minor), check=True)
        say("Copying the app ...")
        copy_app(ROOT, folder / "app")
        (folder / "bin").mkdir()
        (folder / "data").mkdir()
        (folder / f"{name}.bat").write_text(launcher_text(name, branding.ENV_PREFIX).replace("\n", "\r\n"), encoding="ascii")
        (folder / "READ ME FIRST.txt").write_text(f"{name}\r\n\r\n1. Double-click {name}.bat\r\n2. Your browser opens. The first start downloads a video tool (about 160 MB); it only happens once.\r\n"
                                                  f"3. Your projects and settings are in the 'data' folder. Copy the whole folder to move to another computer.\r\n", encoding="ascii")
        z = make_zip(folder, out_dir / f"{name}-portable.zip")
        say(f"Done: {z} ({z.stat().st_size // 1048576} MB)")
        return z
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--minor", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-extras", action="store_true", help="leave out requirements-optional.txt (follow-the-face)")
    a = ap.parse_args(argv)
    try:
        build(Path(a.out).resolve(), a.minor, a.dry_run, with_extras=not a.no_extras)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
        print(f"Stopped: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
