"""Gets the helper programs ViralCut needs (ffmpeg and ffprobe, and Deno for YouTube) into the `bin/` folder.

How it works, in plain words:
  * `bin/` beside the app is put first on the PATH once, when ViralCut starts. Every place that runs `ffmpeg` or
    `ffprobe` by name then finds the copy in `bin/` first, with no change to those places.
  * If `bin/` cannot be written to (a read-only drive), a per-user folder is used instead.
  * A program is downloaded only when it is missing or not good enough (ffmpeg must have the H.264 encoder and the
    caption filter; Deno must be version 2.3.0 or newer). The second start downloads nothing.
  * Every download is pinned: `studio/pins.json` holds the exact address and the SHA-256 fingerprint. A file whose
    fingerprint differs is thrown away. A program with no pin is never downloaded.
  * Downloads can be resumed, are tried three times, and are written to a temporary file first. A working program is
    only replaced after the new one passed the check, so a failed download never breaks what already works.
  * Offline is fine: the app starts and uses whatever is there.

Nothing here imports the rest of the app, so it can run on its own: `python -m studio.bootstrap`.

    PEAKCUT_BIN_DIR       use this folder instead of bin/
    PEAKCUT_PINS_FILE     use another pins file (tests)
    PEAKCUT_BOOTSTRAP=0   do not fetch anything at start"""
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import branding

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_ARCHIVE_BYTES = 1 << 30                     # nothing we fetch is bigger than 1 GiB
MIN_DENO = (2, 3, 0)
TOOLS = ("ffmpeg", "deno")
_SHA = re.compile(r"[0-9a-f]{64}")
_lock = threading.RLock()
_bin: "Path | None" = None
_status: dict = {"running": False, "tools": {}}
_done = threading.Event()
_sleep = time.sleep                              # tests replace this so retries do not wait


class DownloadError(Exception):
    """A download or install step failed; the message is safe to show (it never holds a key or a private path)."""


# ---------------------------------------------------------------- where the programs live
def platform_key() -> str:
    """win64, linux64, or something like win-arm64 (for which nothing is pinned)."""
    import platform
    machine = (platform.machine() or "").lower()
    x64 = machine in ("amd64", "x86_64")
    if sys.platform == "win32":
        return "win64" if x64 else f"win-{machine}"
    if sys.platform.startswith("linux"):
        return "linux64" if x64 else f"linux-{machine}"
    return f"{sys.platform}-{machine}"


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("x", encoding="ascii")
        probe.unlink()
        return True
    except OSError:
        return False


def bin_dir() -> Path:
    """The folder the programs live in: PEAKCUT_BIN_DIR, else bin/ beside the app, else a per-user folder."""
    global _bin
    with _lock:
        if _bin is None:
            given = branding.env("BIN_DIR")
            if given:
                _bin = Path(given)
            elif _writable(ROOT / "bin"):
                _bin = ROOT / "bin"
            else:
                base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
                _bin = Path(base) / branding.APP_NAME / "bin"
        return _bin


def use_bin_dir() -> Path:
    """Put the programs folder first on the PATH, once. Safe to call again."""
    d = bin_dir()
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if not parts or os.path.normcase(parts[0]) != os.path.normcase(str(d)):
        os.environ["PATH"] = os.pathsep.join([str(d)] + [p for p in parts if p and os.path.normcase(p) != os.path.normcase(str(d))])
    return d


# ---------------------------------------------------------------- the pins
def pins_path() -> Path:
    return Path(branding.env("PINS_FILE") or Path(__file__).with_name("pins.json"))


def load_pins() -> dict:
    """The pins file as a dict. A missing or broken file gives {}: nothing is then downloaded."""
    try:
        d = json.loads(pins_path().read_text(encoding="utf-8"))
        return d.get("tools", {}) if isinstance(d, dict) and isinstance(d.get("tools"), dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _safe_name(name: str) -> str:
    """A file name only: no folders, no '..', no drive letters. Names come from pins.json, which is checked anyway."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", name or "") or name in (".", ".."):
        raise DownloadError("the pins file holds an unsafe file name")
    return name


# ---------------------------------------------------------------- downloading
def _check_url(url: str):
    u = urllib.parse.urlparse(url)
    if u.scheme == "https" and u.hostname:
        return
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"):      # only this computer (tests)
        return
    raise DownloadError("only https addresses are allowed for downloads")


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)                       # a redirect may not lead to plain http
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str, size: int = 0, progress=None, tries: int = 3, timeout: int = 30) -> Path:
    """Fetch `url` into `dest`, resuming a part that was cut short, and keep it only if its SHA-256 matches.
    progress(done_bytes, total_bytes) is called as it goes. Raises DownloadError."""
    _check_url(url)
    if not _SHA.fullmatch(sha256 or ""):
        raise DownloadError("this download has no valid SHA-256 pin")
    cap = min(MAX_ARCHIVE_BYTES, int(size * 1.05) + 4096) if size else MAX_ARCHIVE_BYTES
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    opener = urllib.request.build_opener(_SafeRedirects)
    last = "unknown error"
    for attempt in range(max(1, tries)):
        have = part.stat().st_size if part.exists() else 0
        try:
            headers = {"User-Agent": f"{branding.APP_NAME}-bootstrap"}
            if have:
                headers["Range"] = f"bytes={have}-"
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                if have and r.status != 206:
                    have = 0                         # the server sent the whole file again: start over
                have_at_start = have
                length = int(r.headers.get("Content-Length") or 0)
                total = have + length if length else size
                if total and total > cap:
                    raise DownloadError("the file is bigger than expected")
                done = have
                with open(part, "ab" if have else "wb") as out:
                    while True:
                        chunk = r.read(1 << 18)
                        if not chunk:
                            break
                        done += len(chunk)
                        if done > cap:
                            raise DownloadError("the file is bigger than expected")
                        out.write(chunk)
                        if progress:
                            progress(done, total)
            if (length and done - have_at_start != length) or (size and part.stat().st_size != size):
                raise OSError("the file arrived incomplete")
            if sha256_file(part) != sha256:
                resumed = have > 0
                part.unlink(missing_ok=True)
                if resumed:
                    last = "the saved part was damaged; starting again"
                    continue
                raise DownloadError("the downloaded file does not match its SHA-256 pin, so it was thrown away")
            os.replace(part, dest)
            return dest
        except DownloadError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 416:                        # we already hold more than the server has: start over
                part.unlink(missing_ok=True)
                last = "restarting the download"
            elif e.code in (408, 429) or e.code >= 500:
                last = f"the server answered {e.code}"
            else:
                raise DownloadError(f"the server answered {e.code} for this address")
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            last = "no connection" if isinstance(e, urllib.error.URLError) else (str(e)[:120] or "network error")
        if attempt + 1 < max(1, tries):
            _sleep(min(8, 0.5 * 2 ** attempt))
    raise DownloadError(f"could not download it ({last})")


def _install_zip(archive: Path, files: dict, outdir: Path):
    """Take the named files out of the zip, check them, then move them into place all together.
    Only the file names listed in the pins are written; names inside the zip are never used as paths."""
    staged = []
    try:
        with zipfile.ZipFile(archive) as z:
            members = {i.filename: i for i in z.infolist() if not i.is_dir()}
            for target, member in files.items():
                _safe_name(target)
                hits = [n for n in members if n == member or n.endswith("/" + member)]
                if len(hits) != 1:
                    raise DownloadError(f"{target} was not found exactly once in the download")
                info = members[hits[0]]
                if info.file_size > MAX_ARCHIVE_BYTES:
                    raise DownloadError("a file inside the download is too big")
                tmp = outdir / (target + ".new")
                written = 0
                with z.open(info) as src, open(tmp, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size + 1:
                            raise DownloadError("a file inside the download is larger than it says")
                        dst.write(chunk)
                staged.append((tmp, outdir / target))
        for tmp, final in staged:
            if os.name != "nt":
                os.chmod(tmp, 0o755)
            os.replace(tmp, final)               # fails (and keeps the old file) if the old one is running on Windows
        staged = []
    except zipfile.BadZipFile:
        raise DownloadError("the download is not a valid zip file")
    except PermissionError:
        raise DownloadError("a program is in use, so it was not replaced. Close ViralCut's clips and try again")
    finally:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- is a program good enough?
def _run(cmd, timeout=20) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    return (p.stdout or "") + (p.stderr or "")


def probe_ffmpeg():
    """(good enough, why not). Rendering needs the H.264 encoder (libx264) and the caption, loudness and blur filters."""
    exe, probe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not exe or not probe:
        return False, "ffmpeg or ffprobe was not found"
    try:
        enc, flt = _run([exe, "-hide_banner", "-encoders"]), _run([exe, "-hide_banner", "-filters"])
    except (OSError, subprocess.SubprocessError):
        return False, "ffmpeg did not run"
    if "libx264" not in enc:
        return False, "this ffmpeg has no H.264 encoder (libx264)"
    for f in ("ass", "loudnorm", "boxblur"):
        if not re.search(rf"\s{f}\s", flt):
            return False, f"this ffmpeg lacks the {f} filter"
    return True, ""


def probe_deno():
    exe = shutil.which("deno")
    if not exe:
        return False, "deno was not found"
    try:
        out = _run([exe, "--version"])
    except (OSError, subprocess.SubprocessError):
        return False, "deno did not run"
    m = re.search(r"deno\s+(\d+)\.(\d+)\.(\d+)", out)
    if not m:
        return False, "could not read deno's version"
    if tuple(int(x) for x in m.groups()) < MIN_DENO:
        return False, f"deno {m.group(0)[5:]} is older than {'.'.join(map(str, MIN_DENO))}"
    return True, ""


PROBES = {"ffmpeg": probe_ffmpeg, "deno": probe_deno}


# ---------------------------------------------------------------- what is installed
def _versions_file() -> Path:
    return bin_dir() / "versions.json"


def read_versions() -> dict:
    try:
        d = json.loads(_versions_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _write_versions(d: dict):
    f = _versions_file()
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, f)


def ensure_tool(name: str, progress=None) -> dict:
    """Make sure one program is there. Returns {"tool", "state", "detail"}; never raises.
    state: ready (installed earlier, nothing done), present (found on the PATH and good enough), downloaded,
    not-pinned, unsupported, failed."""
    def out(state, detail=""):
        return {"tool": name, "state": state, "detail": detail}
    try:
        with _lock:
            use_bin_dir()
            entry = load_pins().get(name) or {}
            plat = (entry.get("platforms") or {}).get(platform_key()) if isinstance(entry, dict) else None
            pin = plat.get("sha256") if isinstance(plat, dict) else None
            files = list(((plat or {}).get("files") or {}).keys())
            have = read_versions().get(name) or {}
            installed = bool(files) and all((bin_dir() / f).is_file() for f in files)
            if installed and pin and have.get("sha256") == pin:
                return out("ready")
            ok, why = PROBES[name]()
            if ok:
                return out("present")           # good enough already: no big download just because a pin moved on
            if not isinstance(plat, dict):
                return out("unsupported", f"{why or 'a newer version is needed'}. Nothing is pinned for {platform_key()}: install {name} yourself.")
            if not _SHA.fullmatch(pin or "") or not plat.get("url"):
                return out("not-pinned", f"{why or 'update needed'}. The download for {name} is not pinned yet (see docs/STATUS.md), so nothing was fetched.")
            folder = bin_dir()
            if not _writable(folder):
                return out("failed", "the programs folder cannot be written to")
            archive = folder / (name + ".download")
            try:
                download(plat["url"], archive, pin, int(plat.get("size") or 0), (lambda d, t: progress(name, d, t)) if progress else None)
                if str(plat.get("archive", "zip")) != "zip":
                    raise DownloadError("this download type is not supported")
                _install_zip(archive, dict(plat.get("files") or {}), folder)
            finally:
                archive.unlink(missing_ok=True)
            if name in PROBES:
                ok, why = PROBES[name]()
                if not ok:
                    raise DownloadError(f"installed, but it is not good enough: {why}")
            v = read_versions()
            v[name] = {"version": str(entry.get("version") or ""), "sha256": pin, "installed": int(time.time())}
            _write_versions(v)
            return out("downloaded", str(entry.get("version") or ""))
    except DownloadError as e:
        return out("failed", str(e))
    except Exception as e:  # noqa: BLE001 - starting up must never crash because of a download
        return out("failed", f"{type(e).__name__}: {str(e)[:120]}")


def ensure_all(tools=TOOLS, progress=None) -> list:
    """Run ensure_tool for each program and keep the answers for status()."""
    results = []
    with _lock:
        _status["running"] = True
    try:
        for t in tools:
            r = ensure_tool(t, progress)
            results.append(r)
            with _lock:
                _status["tools"][t] = r
    finally:
        with _lock:
            _status["running"] = False
        _done.set()
    return results


def status() -> dict:
    with _lock:
        return {"running": _status["running"], "tools": {k: dict(v) for k, v in _status["tools"].items()}, "bin": str(bin_dir())}


def start_background():
    """Called when the server starts. Fetches in a separate thread so the app opens at once; offline just means
    nothing new is fetched. PEAKCUT_BOOTSTRAP=0 turns it off."""
    if branding.env("BOOTSTRAP", "1") == "0":
        _done.set()
        return None
    _done.clear()
    t = threading.Thread(target=ensure_all, name="bootstrap", daemon=True)
    t.start()
    return t


def wait(timeout: float = 0.0) -> bool:
    """True once the start-up check has finished (or was turned off). A job that needs ffmpeg can wait on this."""
    return _done.wait(timeout)


def _main():
    use_bin_dir()
    print(f"Programs folder: {bin_dir()}")
    last = {"t": 0.0}

    def show(name, done, total):
        if time.time() - last["t"] > 1 or (total and done >= total):
            last["t"] = time.time()
            print(f"  {name}: {done / 1048576:.0f} of {total / 1048576:.0f} MB" if total else f"  {name}: {done / 1048576:.0f} MB", flush=True)
    bad = 0
    for r in ensure_all(progress=show):
        print(f"{r['tool']}: {r['state']}" + (f" ({r['detail']})" if r["detail"] else ""))
        bad += r["state"] in ("failed",)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_main())
