"""Fetching ffmpeg and Deno: pinned, resumable, safe, and harmless when offline. Everything runs against a small
web server on this computer that serves a made-up zip, so nothing real is downloaded and no key is needed."""
import hashlib, http.server, io, json, os, shutil, socket, sys, tempfile, threading, zipfile
from pathlib import Path
os.environ.setdefault("PEAKCUT_DATA", tempfile.mkdtemp(prefix="pc-boot-data-"))
os.environ["PEAKCUT_BOOTSTRAP"] = "1"
sys.path.insert(0, ".")
from studio import bootstrap as b
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

work = Path(tempfile.mkdtemp(prefix="pc-boot-"))
BIN = work / "bin"
os.environ["PEAKCUT_BIN_DIR"] = str(BIN)
b._bin = None
b._sleep = lambda s: None                         # retries do not wait in tests
b.platform_key = lambda: "testplat"
real_path = os.environ["PATH"]

# ---- a made-up release: a zip with two programs inside a folder, like the real ffmpeg zip
def make_zip(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in members.items():
            z.writestr(k, v)
    return buf.getvalue()
FF = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(8000))   # 256 KB that does not compress
PAYLOAD = make_zip({"pkg/bin/fakeffmpeg": FF, "pkg/bin/fakeprobe": b"PROBE" * 1000, "pkg/readme.txt": b"hi"})
SHA = hashlib.sha256(PAYLOAD).hexdigest()

# ---- the stand-in web server
mode = {"kind": "ok", "hits": 0, "ranges": [], "fail_left": 0, "data": PAYLOAD, "redirect": ""}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        mode["hits"] += 1
        rng = self.headers.get("Range")
        mode["ranges"].append(rng)
        data = mode["data"]
        if mode["kind"] == "404":
            return self.send_error(404)
        if mode["kind"] == "flaky500" and mode["fail_left"] > 0:
            mode["fail_left"] -= 1
            return self.send_error(500)
        if mode["kind"] == "redirect":
            self.send_response(302); self.send_header("Location", mode["redirect"]); self.end_headers(); return
        start = 0
        if rng and mode["kind"] != "ignore-range":
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data):
                return self.send_error(416)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if mode["kind"] == "drop-once" and mode["fail_left"] > 0:
            mode["fail_left"] -= 1
            self.wfile.write(body[: len(body) // 2])        # the connection ends half way
            self.wfile.flush()
            return
        self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/release.zip"

def write_pins(**over):
    plat = {"url": URL, "sha256": SHA, "size": len(PAYLOAD), "archive": "zip",
            "files": {"fakeffmpeg": "bin/fakeffmpeg", "fakeprobe": "bin/fakeprobe"}}
    plat.update(over)
    pins = work / "pins.json"
    pins.write_text(json.dumps({"schema": 1, "tools": {"ffmpeg": {"version": "test-1", "platforms": {"testplat": plat}}}}), encoding="utf-8")
    os.environ["PEAKCUT_PINS_FILE"] = str(pins)
def reset(kind="ok", fail_left=0, data=None):
    shutil.rmtree(BIN, ignore_errors=True); BIN.mkdir(parents=True)
    mode.update(kind=kind, hits=0, ranges=[], fail_left=fail_left, data=data or PAYLOAD)
# the stand-in check "is ffmpeg good enough": it is, once our made-up program is in bin/
b.PROBES["ffmpeg"] = lambda: ((BIN / "fakeffmpeg").is_file(), "ffmpeg was not found")
ens = lambda: b.ensure_tool("ffmpeg")

# ---- 1. nothing pinned: nothing is fetched
reset(); (work / "pins.json").write_text("{ not json", encoding="utf-8"); os.environ["PEAKCUT_PINS_FILE"] = str(work / "pins.json")
r = ens()
check("a broken pins file: nothing pinned, no download, no crash", (r["state"], mode["hits"]), ("unsupported", 0))
write_pins(sha256="")
r = ens()
check("a pin without a SHA-256: refused, nothing fetched", (r["state"], mode["hits"]), ("not-pinned", 0))
write_pins(sha256="XYZ")
check("a pin with a malformed SHA-256: refused", (ens()["state"], mode["hits"]), ("not-pinned", 0))

# ---- 2. first run: downloads, checks, installs
write_pins(); reset()
seen = []
r = b.ensure_tool("ffmpeg", progress=lambda n, d, t: seen.append((d, t)))
check("first run downloads", (r["state"], r["detail"]), ("downloaded", "test-1"))
check("both programs are installed with the right content",
      ((BIN / "fakeffmpeg").read_bytes() == FF, (BIN / "fakeprobe").read_bytes() == b"PROBE" * 1000), (True, True))
check("only the named files were taken out of the zip", sorted(p.name for p in BIN.iterdir() if p.is_file()), ["fakeffmpeg", "fakeprobe", "versions.json"])
check("the version and fingerprint are written down", b.read_versions()["ffmpeg"]["sha256"], SHA)
check("progress was reported and ended at the full size", bool(seen) and seen[-1][0] == len(PAYLOAD) and all(x <= y for x, y in zip([s[0] for s in seen], [s[0] for s in seen][1:])), True)
hits = mode["hits"]

# ---- 3. second run: nothing downloaded
r = ens()
check("second run downloads nothing", (r["state"], mode["hits"]), ("ready", hits))

# ---- 4. a good copy already on the PATH: nothing downloaded
reset()
b.PROBES["ffmpeg"] = lambda: (True, "")
check("a good ffmpeg already found: used as is, no download", (ens()["state"], mode["hits"]), ("present", 0))
b.PROBES["ffmpeg"] = lambda: ((BIN / "fakeffmpeg").is_file(), "ffmpeg was not found")

# ---- 5. a wrong fingerprint: thrown away, the old working copy is untouched
reset()
(BIN / "fakeffmpeg").write_bytes(b"OLD-WORKING")
b.PROBES["ffmpeg"] = lambda: (False, "too old")
write_pins(sha256="0" * 64)
r = ens()
check("wrong fingerprint: refused", (r["state"], "SHA-256" in r["detail"]), ("failed", True))
check("...the old copy is still there, unchanged", (BIN / "fakeffmpeg").read_bytes(), b"OLD-WORKING")
check("...no temporary files are left", sorted(p.name for p in BIN.iterdir()), ["fakeffmpeg"])
check("...and it did not retry a bad fingerprint", mode["hits"], 1)
b.PROBES["ffmpeg"] = lambda: ((BIN / "fakeffmpeg").is_file(), "ffmpeg was not found")
write_pins()

# ---- 6. resume after the connection drops
reset("drop-once", fail_left=1)
r = ens()
check("a cut connection is resumed and finishes", r["state"], "downloaded")
check("...the second request asked only for the rest", (len(mode["ranges"]), mode["ranges"][0], str(mode["ranges"][1]).startswith("bytes=")), (2, None, True))
reset("ignore-range", fail_left=0)
(BIN).mkdir(exist_ok=True)
# a half-finished part left from an earlier run, and a server that ignores Range and sends everything again
(BIN / "ffmpeg.download.part").write_bytes(PAYLOAD[:1000])
check("a leftover part and a server that ignores Range: starts over and succeeds", ens()["state"], "downloaded")
reset("ok")
(BIN / "ffmpeg.download.part").write_bytes(PAYLOAD[:1000])
check("a leftover part is resumed", (ens()["state"], str(mode["ranges"][0])), ("downloaded", "bytes=1000-"))
reset("ok")
(BIN / "ffmpeg.download.part").write_bytes(b"garbage that is not from the real file")
check("a damaged leftover part is dropped and the download is redone", ens()["state"], "downloaded")

# ---- 7. server trouble
reset("flaky500", fail_left=2)
check("two server errors, then success: retried", (ens()["state"], mode["hits"]), ("downloaded", 3))
reset("flaky500", fail_left=9)
r = ens()
check("a server that keeps failing: gives up after 3 tries, no crash", (r["state"], mode["hits"]), ("failed", 3))
reset("404")
r = ens()
check("404: no pointless retries", (r["state"], mode["hits"]), ("failed", 1))
reset("redirect"); mode["redirect"] = "http://example.com/evil.zip"
r = ens()
check("a redirect to plain http is refused", (r["state"], "https" in r["detail"]), ("failed", True))
write_pins(url="http://example.com/release.zip")
reset()
r = ens()
check("a plain-http pin is refused without touching the network", (r["state"], mode["hits"]), ("failed", 0))
write_pins(url="ftp://example.com/release.zip")
check("a non-web pin is refused", ens()["state"], "failed")
write_pins()

# ---- 8. offline: the app still starts
s = socket.socket(); s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]; s.close()
write_pins(url=f"http://127.0.0.1:{dead}/release.zip"); reset()
r = ens()
check("offline: reports failure, does not raise", (r["state"], "no connection" in r["detail"]), ("failed", True))
res = b.ensure_all(tools=("ffmpeg",))
check("ensure_all offline returns normally", [x["state"] for x in res], ["failed"])
t = b.start_background()
t.join(10)
check("start_background finishes by itself and wait() returns", (not t.is_alive(), b.wait(1)), (True, True))
check("status() lists each program", sorted(b.status()["tools"]) and b.status()["running"] is False, True)
os.environ["PEAKCUT_BOOTSTRAP"] = "0"
check("PEAKCUT_BOOTSTRAP=0: nothing is started", b.start_background(), None)
os.environ["PEAKCUT_BOOTSTRAP"] = "1"
write_pins()

# ---- 9. hostile or broken archives
reset(data=b"this is not a zip file")
write_pins(sha256=hashlib.sha256(b"this is not a zip file").hexdigest(), size=0)
check("a file that is not a zip (even with a matching pin) is refused", ens()["state"], "failed")
bad = make_zip({"pkg/readme.txt": b"nothing useful"})
reset(data=bad); write_pins(sha256=hashlib.sha256(bad).hexdigest(), size=len(bad))
r = ens()
check("a zip without the pinned file: refused, nothing installed", (r["state"], sorted(p.name for p in BIN.iterdir())), ("failed", []))
dup = make_zip({"a/bin/fakeffmpeg": b"1", "b/bin/fakeffmpeg": b"2", "a/bin/fakeprobe": b"3"})
reset(data=dup); write_pins(sha256=hashlib.sha256(dup).hexdigest(), size=len(dup))
check("a name that appears twice in the zip is refused", ens()["state"], "failed")
trav = make_zip({"../../evil": b"x", "pkg/bin/fakeffmpeg": b"ok", "pkg/bin/fakeprobe": b"ok"})
reset(data=trav); write_pins(sha256=hashlib.sha256(trav).hexdigest(), size=len(trav))
r = ens()
check("a zip holding '../' names: only the pinned names are written, nothing escapes",
      (r["state"], (work / "evil").exists(), (work.parent / "evil").exists(), sorted(p.name for p in BIN.iterdir() if p.is_file())),
      ("downloaded", False, False, ["fakeffmpeg", "fakeprobe", "versions.json"]))
reset(); write_pins(files={"../evil": "bin/fakeffmpeg"})
r = ens()
check("a pins file with a '../' target name is refused", (r["state"], (work / "evil").exists()), ("failed", False))
reset(); write_pins(size=10)
check("a download bigger than the pinned size is stopped", ens()["state"], "failed")
write_pins()

# ---- 10. where the programs live, and the PATH
b._bin = None
real_pins_env = os.environ.pop("PEAKCUT_BIN_DIR")
os.environ["PEAKCUT_BIN_DIR"] = str(work / "elsewhere")
check("PEAKCUT_BIN_DIR is respected", b.bin_dir(), work / "elsewhere")
b._bin = None
os.environ.pop("PEAKCUT_BIN_DIR")
blocker = work / "a-file"; blocker.write_text("x")
real_root = b.ROOT
b.ROOT = blocker                                   # bin/ cannot be made inside a file: like a read-only drive
os.environ["LOCALAPPDATA"] = str(work / "appdata")
check("a folder that cannot be written falls back to a per-user folder", b.bin_dir(), work / "appdata" / b.branding.APP_NAME / "bin")
b.ROOT = real_root
b._bin = None
os.environ["PEAKCUT_BIN_DIR"] = str(BIN)
d = b.use_bin_dir(); d2 = b.use_bin_dir()
parts = os.environ["PATH"].split(os.pathsep)
check("bin/ is first on the PATH, once", (parts[0], parts.count(str(BIN))), (str(BIN), 1))
check("the rest of the PATH is kept", all(p in parts for p in real_path.split(os.pathsep) if p), True)
os.environ["PATH"] = real_path

# ---- 11. is a program good enough? (the command output is made up)
realrun, realwhich = b._run, b.shutil.which
b.shutil.which = lambda n: "/x/" + n
GOOD_ENC = " V....D libx264              libx264 H.264 / AVC\n"
GOOD_FLT = " T.. ass                V->V       Render ASS subtitles\n ... loudnorm           A->A       EBU R128\n T.. boxblur            V->V       Blur\n"
b._run = lambda cmd, timeout=20: GOOD_ENC if "-encoders" in cmd else GOOD_FLT
check("ffmpeg with libx264 and the filters is good", b.probe_ffmpeg(), (True, ""))
b._run = lambda cmd, timeout=20: " V....D mpeg4 MPEG-4\n" if "-encoders" in cmd else GOOD_FLT
ok, why = b.probe_ffmpeg()
check("ffmpeg without libx264 is not good", (ok, "libx264" in why), (False, True))
b._run = lambda cmd, timeout=20: GOOD_ENC if "-encoders" in cmd else " T.. boxblur V->V\n"
ok, why = b.probe_ffmpeg()
check("ffmpeg without the caption filter is not good", (ok, "ass" in why), (False, True))
b.shutil.which = lambda n: None
check("no ffmpeg at all is reported", b.probe_ffmpeg()[0], False)
b.shutil.which = lambda n: "/x/" + n
for out, want in (("deno 2.3.0 (stable, release, x86_64-pc-windows-msvc)\nv8 13.0", True), ("deno 2.2.9 (stable)", False),
                  ("deno 2.10.1 (stable)", True), ("deno 3.0.0", True), ("deno 1.46.3", False), ("nonsense", False)):
    b._run = lambda cmd, timeout=20, o=out: o
    check(f"deno version check: {out.splitlines()[0][:12]!r} -> {want}", b.probe_deno()[0], want)
b._run, b.shutil.which = realrun, realwhich
def boom(*a, **k): raise OSError("no such program")
b._run = boom
b.shutil.which = lambda n: "/x/" + n
check("a program that will not start is reported, no crash", (b.probe_ffmpeg()[0], b.probe_deno()[0]), (False, False))
b._run, b.shutil.which = realrun, realwhich

# ---- 12. the shipped pins file is either empty or complete, never half filled
real_pins = json.loads((Path(__file__).resolve().parent.parent / "studio" / "pins.json").read_text(encoding="utf-8"))
bad = []
for tool, e in real_pins["tools"].items():
    for plat, p in e["platforms"].items():
        filled = [bool(p.get("url")), bool(p.get("sha256")), bool(p.get("size"))]
        if any(filled) and not all(filled):
            bad.append(f"{tool}/{plat}: partly filled")
        if all(filled):
            if not (p["url"].startswith("https://") and b._SHA.fullmatch(p["sha256"]) and e.get("version")):
                bad.append(f"{tool}/{plat}: bad url, fingerprint or version")
        for tgt in p["files"]:
            try: b._safe_name(tgt)
            except b.DownloadError: bad.append(f"{tool}: unsafe name {tgt}")
check("the shipped pins file is valid and never half filled", bad, [])
check("the shipped pins ask for ffmpeg, ffprobe and deno", sorted(f for e in real_pins["tools"].values() for p in e["platforms"].values() for f in p["files"]), ["deno.exe", "ffmpeg.exe", "ffprobe.exe"])

srv.shutdown()
print("ALL PASSED" if not fails else f"{len(fails)} failed")
shutil.rmtree(work, ignore_errors=True)
sys.exit(1 if fails else 0)
