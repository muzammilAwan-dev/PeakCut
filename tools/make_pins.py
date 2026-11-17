"""Fill in one entry of studio/pins.json: downloads the file once, measures its SHA-256 and size, checks that the
files PeakCut needs are inside, and writes the entry. Run this on a computer with internet, then commit pins.json.

    python tools/make_pins.py ffmpeg  <direct https address of the zip>  --version <release name>  [--sha256 <publisher's value>]
    python tools/make_pins.py deno    <direct https address of the zip>  --version 2.3.5           [--sha256 <publisher's value>]

Where to get the address and the publisher's fingerprint (check these yourself, they change):
  ffmpeg: a dated release on https://github.com/BtbN/FFmpeg-Builds/releases (use the win64 GPL zip, NOT the "latest"
          link, which moves) and the checksums.sha256 file in the same release.
  deno:   https://github.com/denoland/deno/releases, the file deno-x86_64-pc-windows-msvc.zip (version 2.3.0 or newer).

Pass --sha256 with the publisher's fingerprint whenever there is one: the entry is then written only if your download
matches it. Without it, the fingerprint is simply what you downloaded, so compare it with the release page by eye.
Only the Windows 64-bit entry is filled here (--platform changes that)."""
import argparse, json, shutil, sys, tempfile, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import bootstrap as b

PINS = Path(__file__).resolve().parent.parent / "studio" / "pins.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tool", choices=sorted(b.TOOLS))
    ap.add_argument("url")
    ap.add_argument("--version", required=True)
    ap.add_argument("--sha256", default="")
    ap.add_argument("--platform", default="win64")
    a = ap.parse_args()
    b._check_url(a.url)
    data = json.loads(PINS.read_text(encoding="utf-8"))
    plat = data["tools"][a.tool]["platforms"].get(a.platform)
    if plat is None:
        sys.exit(f"pins.json has no {a.platform} entry for {a.tool}: add its 'files' first")
    tmp = Path(tempfile.mkdtemp(prefix="pins-"))
    try:
        got = tmp / "download"
        import urllib.request
        opener = urllib.request.build_opener(b._SafeRedirects)
        done = 0
        with opener.open(urllib.request.Request(a.url, headers={"User-Agent": "make-pins"}), timeout=60) as r, open(got, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk); done += len(chunk)
                print(f"\r  {done / 1048576:.0f} MB", end="", flush=True)
        print()
        digest = b.sha256_file(got)
        if a.sha256 and a.sha256.lower() != digest:
            sys.exit(f"NOT WRITTEN: your download is {digest}, the publisher says {a.sha256.lower()}")
        with zipfile.ZipFile(got) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir()]
        for target, member in plat["files"].items():
            hits = [n for n in names if n == member or n.endswith("/" + member)]
            if len(hits) != 1:
                sys.exit(f"NOT WRITTEN: {member!r} is in the zip {len(hits)} times (needs exactly once)")
        plat.update(url=a.url, sha256=digest, size=done)
        data["tools"][a.tool]["version"] = a.version
        PINS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"written: {a.tool} {a.version} {a.platform}\n  sha256 {digest}")
        if not a.sha256:
            print("  WARNING: no publisher fingerprint was given. Compare the value above with the release page before committing.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
