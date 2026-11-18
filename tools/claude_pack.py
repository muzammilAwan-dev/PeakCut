"""Packs things for Claude (or anyone) into small zip files, and puts them back together.

Why: the sandbox Claude works in has no internet, and uploads are limited to 30 MB per file. Run this on a
computer WITH internet. It collects what is needed, splits it into parts that are each a valid zip under the limit,
and writes a manifest with SHA-256 fingerprints so a missing or damaged part is noticed instead of silently used.

    python tools/claude_pack.py wheels             Python packages (Linux build) so Claude can run the app and the tests
    python tools/claude_pack.py model              the English speech model (about 480 MB: many parts; optional)
    python tools/claude_pack.py files A B C ...    any files or folders (a sample video, a log, test output)
    python tools/claude_pack.py join PARTS_FOLDER --to DEST     put the parts back together (used on the receiving side)

Output goes to ./claude-pack/ (change with --out). Upload every .zip in that folder. Nothing private is collected:
wheels come from PyPI, the model from the project's public download address, files are only the ones you name.

Standard library only; works on Windows, macOS and Linux (Python 3.9 or newer)."""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 30_000_000                      # bytes: each output zip stays under this (the chat upload limit is 30 MB)
DEFAULT_CHUNK_MIB = 24                  # 24 MiB = 25.2 MB per part; the zip wrapper adds a few hundred bytes
MANIFEST = "manifest.json"
CHUNK = "chunk.bin"
SANDBOX_FILE = Path(__file__).with_name("sandbox.json")


def load_sandbox(path=SANDBOX_FILE) -> dict:
    """What the receiving sandbox runs, read from tools/sandbox.json so a change needs no code edit.
    A missing or damaged file is an error with a plain message (--py still overrides the Python version)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        py, plats = str(data["python"]), [str(p) for p in data["platforms"]]
        if not py.replace(".", "").isdigit() or not plats or not all(p.replace("_", "").isalnum() for p in plats):
            raise ValueError("bad values")
        return {"python": py, "platforms": plats}
    except (OSError, KeyError, ValueError, TypeError) as e:
        raise ValueError(f"{path} could not be read ({e}). It must hold \"python\" (like 3.13) and \"platforms\" (a list).") from e


try:
    _SB = load_sandbox()
except ValueError as _e:                 # keep the tool usable; say what happened
    print(f"Note: {_e} Using Python 3.13 on Linux x86-64 for this run.", file=sys.stderr)
    _SB = {"python": "3.13", "platforms": ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64"]}
TARGET_PY = _SB["python"]
MANYLINUX = _SB["platforms"]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ---------------------------------------------------------------- split into parts
def split(payload: Path, name: str, out: Path, chunk_bytes: int, notes=None) -> list:
    """Cut `payload` into parts, each written as a valid zip that holds chunk.bin and manifest.json."""
    if chunk_bytes < 1 or chunk_bytes > LIMIT - 4096:
        raise ValueError("the part size must be positive and under the upload limit")
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("the pack name may hold letters, digits, - and _ only")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob(f"claude-pack-{name}-*-of-*.zip"):          # parts of an earlier run would be mixed up with the new ones
        old.unlink()
    size = payload.stat().st_size
    count = max(1, -(-size // chunk_bytes))
    hashes, h_all = [], hashlib.sha256()
    with open(payload, "rb") as f:                                   # pass 1: fingerprints
        for _ in range(count):
            data = f.read(chunk_bytes)
            hashes.append(sha256_bytes(data))
            h_all.update(data)
    manifest = {"format": 1, "name": name, "parts": count, "bytes": size, "sha256": h_all.hexdigest(), "chunk_bytes": chunk_bytes,
                "chunk_sha256": hashes, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "notes": notes or []}
    text = json.dumps(manifest, indent=1)
    written = []
    with open(payload, "rb") as f:                                   # pass 2: the zips
        for i in range(count):
            data = f.read(chunk_bytes)
            dest = out / f"claude-pack-{name}-{i + 1:02d}-of-{count:02d}.zip"
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:    # the data is already compressed
                z.writestr(MANIFEST, text)
                z.writestr(f"{CHUNK}", data)
            if dest.stat().st_size >= LIMIT:
                raise RuntimeError(f"{dest.name} is {dest.stat().st_size} bytes, over the limit")
            written.append(dest)
    return written


# ---------------------------------------------------------------- put the parts back together
def _read_part(p: Path):
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        if sorted(names) != sorted([MANIFEST, CHUNK]):
            raise ValueError(f"{p.name}: unexpected content {names}")
        return json.loads(z.read(MANIFEST).decode("utf-8")), z.read(CHUNK)


def join(parts_dir, dest: Path, name=None) -> Path:
    """Verify every part and rebuild the payload zip, then extract it into dest. Raises ValueError with a plain reason."""
    found = {}
    folders = parts_dir if isinstance(parts_dir, (list, tuple)) else [parts_dir]
    for folder in folders:
        for p in sorted(Path(folder).glob("**/claude-pack-*.zip")):
            try:
                m, data = _read_part(p)
            except (zipfile.BadZipFile, ValueError, KeyError) as e:
                raise ValueError(f"{p.name} is damaged or not a pack part ({e}). Upload that file again.")
            if name and m["name"] != name:
                continue
            idx = int(p.stem.split("-")[-3]) - 1
            found.setdefault(m["name"], {"m": m, "parts": {}})
            if found[m["name"]]["m"]["sha256"] != m["sha256"]:
                raise ValueError(f"parts of '{m['name']}' come from two different packs; remove the old ones")
            found[m["name"]]["parts"][idx] = data
    if not found:
        raise ValueError("no claude-pack-*.zip parts were found")
    if len(found) > 1:
        raise ValueError(f"several packs found ({', '.join(sorted(found))}); pass --name")
    (pack_name, g), = found.items()
    m = g["m"]
    missing = [i + 1 for i in range(m["parts"]) if i not in g["parts"]]
    if missing:
        raise ValueError(f"missing part(s) {missing} of {m['parts']}")
    h = hashlib.sha256()
    for i in range(m["parts"]):                       # check every part before writing anything
        if sha256_bytes(g["parts"][i]) != m["chunk_sha256"][i]:
            raise ValueError(f"part {i + 1} is damaged (its fingerprint does not match). Upload it again.")
        h.update(g["parts"][i])
    if h.hexdigest() != m["sha256"]:
        raise ValueError("the joined file does not match the fingerprint in the manifest")
    dest.mkdir(parents=True, exist_ok=True)
    payload = dest / f"{pack_name}.payload.zip"
    with open(payload, "wb") as out:
        for i in range(m["parts"]):
            out.write(g["parts"][i])
    return payload


def extract_safe(payload: Path, dest: Path) -> list:
    """Unzip, refusing names that would land outside dest."""
    dest = dest.resolve()
    done = []
    with zipfile.ZipFile(payload) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest != target and dest not in target.parents:
                raise ValueError(f"refusing {info.filename!r}: it would leave the folder")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            done.append(str(target.relative_to(dest)))
    return done


# ---------------------------------------------------------------- what to collect
def pip_args(requirements: Path, target: Path, py=TARGET_PY, one=None) -> list:
    """The pip command that downloads Linux wheels for the receiving sandbox, from any computer."""
    plats = [x for p in MANYLINUX for x in ("--platform", p)]
    base = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--python-version", py, "--implementation", "cp",
            "--abi", "cp" + py.replace(".", ""), *plats, "--dest", str(target), "--disable-pip-version-check"]
    return base + ([one] if one else ["-r", str(requirements)])


def collect_wheels(workdir: Path, py=TARGET_PY) -> tuple:
    """Download the wheels. If one package has no Linux wheel, the others still come and the failure is reported."""
    req = ROOT / "requirements.txt"
    wheels = workdir / "wheels"
    wheels.mkdir(parents=True)
    notes = []
    r = subprocess.run(pip_args(req, wheels, py))
    if r.returncode != 0:
        notes.append("the all-at-once download failed; each requirement was tried on its own")
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                rr = subprocess.run(pip_args(req, wheels, py, one=line))
                if rr.returncode != 0:
                    notes.append(f"FAILED: {line}")
    if not any(wheels.iterdir()):
        raise RuntimeError("no wheel could be downloaded; check the internet connection")
    shutil.copy2(req, workdir / "requirements.txt")
    notes.append("wheels for Python " + py + ", " + MANYLINUX[0])
    notes.append("sha256: " + "; ".join(f"{p.name}={sha256_file(p)[:12]}" for p in sorted(wheels.iterdir())))
    return workdir, notes


def collect_model(workdir: Path) -> tuple:
    sys.path.insert(0, str(ROOT))
    os.environ["PEAKCUT_DATA"] = str(workdir / "data")
    os.environ["PEAKCUT_BOOTSTRAP"] = "0"
    from studio import fetch_model                                   # the project's own downloader (checks the archive paths)
    fetch_model.main()
    return workdir / "data", ["speech model for studio/config.py ASR_MODEL_NAME"]


def make_payload(root: Path, files: list, payload: Path):
    """Zip the given files (paths relative to root) without recompressing what is already compressed."""
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_STORED) as z:
        for rel in files:
            z.write(root / rel, rel.replace("\\", "/"))


def pack_folder(folder: Path, name: str, out: Path, chunk_mib: int, notes) -> list:
    folder = folder.resolve()
    rels = [str(p.relative_to(folder)) for p in sorted(folder.rglob("*")) if p.is_file()]
    with tempfile.TemporaryDirectory() as t:
        payload = Path(t) / "payload.zip"
        make_payload(folder, rels, payload)
        return split(payload, name, out, chunk_mib * 1024 * 1024, notes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["wheels", "model", "files", "join"])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out", default="claude-pack")
    ap.add_argument("--to", default="unpacked")
    ap.add_argument("--py", default=TARGET_PY, help="the Python version of the receiving sandbox")
    ap.add_argument("--chunk-mib", type=int, default=DEFAULT_CHUNK_MIB)
    ap.add_argument("--name", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.what == "join":
        payload = join([Path(p) for p in (a.paths or ["."])], Path(a.to), a.name)
        names = extract_safe(payload, Path(a.to))
        print(f"joined and verified; {len(names)} files extracted into {a.to}")
        return 0
    if a.what == "files":
        if not a.paths:
            ap.error("name at least one file or folder")
        with tempfile.TemporaryDirectory() as t:
            stage = Path(t) / "stage"
            stage.mkdir()
            for p in map(Path, a.paths):
                if not p.exists():
                    ap.error(f"{p} does not exist")
                shutil.copytree(p, stage / p.name) if p.is_dir() else shutil.copy2(p, stage / p.name)
            parts = pack_folder(stage, a.name or "files", out, a.chunk_mib, [f"files: {', '.join(Path(p).name for p in a.paths)}"])
    else:
        with tempfile.TemporaryDirectory() as t:
            work = Path(t) / "work"
            work.mkdir()
            folder, notes = collect_wheels(work, a.py) if a.what == "wheels" else collect_model(work)
            parts = pack_folder(folder, a.name or a.what, out, a.chunk_mib, notes)
    print(f"\n{len(parts)} file(s) written to {out.resolve()}:")
    for p in parts:
        print(f"  {p.name}  {p.stat().st_size / 1e6:.1f} MB")
    print("Upload every .zip from that folder to Claude.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as e:
        print(f"\nProblem: {e}")
        sys.exit(1)
