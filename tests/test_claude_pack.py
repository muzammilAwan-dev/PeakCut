"""The pack tool that splits files into small zips and joins them again: every part is a valid zip under the limit,
a missing, damaged, swapped or hostile part is refused, and a good set comes back byte for byte."""
import os, random, shutil, sys, tempfile, zipfile
from pathlib import Path
sys.path.insert(0, "tools")
import claude_pack as cp
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

def raises(fn, text):
    try: fn()
    except ValueError as e: return text in str(e)
    return False

w = Path(tempfile.mkdtemp(prefix="pc-pack-"))
rnd = random.Random(7)
src = w / "src"; (src / "sub").mkdir(parents=True)
(src / "a.bin").write_bytes(rnd.randbytes(300_000)); (src / "sub" / "b.txt").write_text("hello", encoding="utf-8")
out = w / "out"

with tempfile.TemporaryDirectory() as t:
    pay = Path(t) / "p.zip"; cp.make_payload(src, ["a.bin", "sub/b.txt"], pay)
    size = pay.stat().st_size
    parts = cp.split(pay, "demo", out, 100_000)
check("a payload is cut into the right number of parts", len(parts), -(-size // 100_000))
check("every part is a valid zip, named in order, under the limit",
      all(zipfile.is_zipfile(p) and p.stat().st_size < cp.LIMIT for p in parts) and [p.name for p in parts][0].endswith("-01-of-%02d.zip" % len(parts)), True)
check("the default part size leaves room under the 30 MB limit", cp.DEFAULT_CHUNK_MIB * 1024 * 1024 + 4096 < cp.LIMIT, True)

dest = w / "back"
payload = cp.join([out], dest)
names = cp.extract_safe(payload, dest / "files")
check("joined and extracted: same files, same bytes",
      (sorted(str(n).replace("\\", "/") for n in names), (dest / "files" / "a.bin").read_bytes() == (src / "a.bin").read_bytes()), (["a.bin", "sub/b.txt"], True))

# a part missing
spare = w / "spare"; spare.mkdir(); shutil.copy(parts[1], spare / parts[1].name); parts[1].unlink()
check("a missing part is named", raises(lambda: cp.join([out], w / "x"), "missing part(s) [2]"), True)
shutil.copy(spare / parts[1].name, parts[1])
# a damaged part: flip bytes inside the chunk while keeping a valid zip
bad = w / "bad"; shutil.copytree(out, bad)
victim = sorted(bad.glob("*.zip"))[0]
with zipfile.ZipFile(victim) as z: man, chunk = z.read(cp.MANIFEST), bytearray(z.read(cp.CHUNK))
chunk[10] ^= 0xFF
with zipfile.ZipFile(victim, "w") as z: z.writestr(cp.MANIFEST, man); z.writestr(cp.CHUNK, bytes(chunk))
check("a damaged part is detected", raises(lambda: cp.join([bad], w / "y"), "part 1 is damaged"), True)
# a file that is not a zip
junk = w / "junk"; junk.mkdir(); (junk / "claude-pack-demo-01-of-01.zip").write_bytes(b"not a zip")
check("a broken zip is reported by name", raises(lambda: cp.join([junk], w / "z"), "claude-pack-demo-01-of-01.zip is damaged"), True)
# parts of two different packs
other = w / "other"; other.mkdir()
with tempfile.TemporaryDirectory() as t:
    p2 = Path(t) / "q.zip"; cp.make_payload(src, ["sub/b.txt"], p2); cp.split(p2, "demo", other, 100_000)
mix = w / "mix"; shutil.copytree(out, mix); shutil.copy(next(other.glob("*.zip")), mix / "claude-pack-demo-02-of-99.zip")
check("parts from two packs are refused", raises(lambda: cp.join([mix], w / "m"), "two different packs"), True)
check("nothing found is reported", raises(lambda: cp.join([w / "empty_none"], w / "n"), "no claude-pack"), True)
# a hostile payload: a name that climbs out of the folder
evil = w / "evil.zip"
with zipfile.ZipFile(evil, "w") as z: z.writestr("../../escape.txt", "x")
check("a zip with a ../ name is refused", raises(lambda: cp.extract_safe(evil, w / "safe"), "leave the folder"), True)
check("...and nothing was written outside", (w.parent / "escape.txt").exists() or (w / "escape.txt").exists(), False)
# empty payload and bad names
check("a bad pack name is refused", raises(lambda: cp.split(evil, "../x", w / "o2", 1000), "letters, digits"), True)
check("a part size over the limit is refused", raises(lambda: cp.split(evil, "ok", w / "o3", 40_000_000), "upload limit"), True)
check("the upload limit is 30 MB", cp.LIMIT, 30_000_000)
pay2 = w / "p2.zip"; pay2.write_bytes(b"x" * 2500)
cp.split(pay2, "demo", out, 1000)
check("a new run replaces the parts of the old run instead of mixing with them", sorted(p.name for p in out.glob("claude-pack-demo-*.zip")), [f"claude-pack-demo-0{i}-of-03.zip" for i in (1, 2, 3)])
# the pip command for the sandbox
cmd = cp.pip_args(Path("requirements.txt"), Path("w"), "3.13")
check("pip asks for Linux Python 3.13 wheels only", ("--only-binary=:all:" in cmd, "cp313" in cmd, "--platform" in cmd, cmd.count("--platform") == len(cp.MANYLINUX)), (True, True, True, True))
shutil.rmtree(w, ignore_errors=True)
print("ALL PASSED" if not fails else f"{len(fails)} failed"); sys.exit(1 if fails else 0)
