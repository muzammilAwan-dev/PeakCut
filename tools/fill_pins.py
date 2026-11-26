"""Fills studio/pins.json for you: finds the newest dated ffmpeg release and the newest Deno release on GitHub, takes the
publisher's fingerprint from the release, downloads each file once and writes the entry (tools/make_pins.py does the
download and the check). Run it on a computer with internet, look at what it prints, then commit studio/pins.json.

    python tools/fill_pins.py [--yes] [--only ffmpeg|deno]

Without a publisher fingerprint it stops unless you pass --yes (the fingerprint is then simply what was downloaded).
ffmpeg is the GPL build because the app needs the x264 encoder. It is downloaded to the user's own computer on first
start; it is never put inside the app's zip."""
import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def api(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fill-pins", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "fill-pins"}), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _sha_from(body: str, filename: str) -> str:
    for line in body.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m and m.group(2).split("/")[-1] == filename:
            return m.group(1).lower()
    return ""


def find_ffmpeg(get_json=api, get_text=text):
    """(url, release name, publisher sha256 or '') of the newest dated BtbN build for Windows 64-bit (GPL)."""
    for rel in get_json("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases?per_page=30"):
        if not str(rel.get("tag_name", "")).startswith("autobuild-"):
            continue
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        name = next((n for n in assets if re.fullmatch(r"ffmpeg-N-\d+-g[0-9a-f]+-win64-gpl\.zip", n)), None)
        if name:
            sums = assets.get("checksums.sha256")
            return assets[name], rel["tag_name"], _sha_from(get_text(sums), name) if sums else ""
    raise RuntimeError("no dated ffmpeg release with a win64-gpl zip was found on BtbN/FFmpeg-Builds")


def find_deno(get_json=api, get_text=text):
    rel = get_json("https://api.github.com/repos/denoland/deno/releases/latest")
    name = "deno-x86_64-pc-windows-msvc.zip"
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    if name not in assets:
        raise RuntimeError(f"{name} is not in the newest Deno release")
    sums = assets.get(name + ".sha256sum")
    sha = ""
    if sums:
        body = get_text(sums).strip()
        sha = (re.match(r"^([0-9a-fA-F]{64})", body).group(1).lower() if re.match(r"^[0-9a-fA-F]{64}", body) else _sha_from(body, name))
    return assets[name], str(rel.get("tag_name", "")).lstrip("v"), sha


FINDERS = {"ffmpeg": find_ffmpeg, "deno": find_deno}


def main(argv=None, finders=None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--only", choices=sorted(FINDERS))
    a = ap.parse_args(argv)
    for tool, find in (finders or FINDERS).items():
        if a.only and tool != a.only:
            continue
        try:
            url, version, sha = find()
        except (RuntimeError, OSError, ValueError, KeyError) as e:
            print(f"{tool}: could not find a release ({e}). Use tools/make_pins.py by hand.")
            return 1
        print(f"{tool}: {version}\n  {url}\n  publisher fingerprint: {sha or 'none published'}")
        if not sha and not a.yes:
            print("  No fingerprint from the publisher; run again with --yes to pin what is downloaded.")
            return 1
        cmd = [sys.executable, str(HERE / "make_pins.py"), tool, url, "--version", version] + (["--sha256", sha] if sha else [])
        if runner(cmd).returncode != 0:
            print(f"{tool}: not pinned.")
            return 1
    print("Done. Commit studio/pins.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
