"""Finding the right release files for the pins list, with a pretend GitHub. No network."""
import sys
sys.path.insert(0, "."); sys.path.insert(0, "tools")
import fill_pins as fp
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)
SHA = "a" * 64
def asset(n): return {"name": n, "browser_download_url": f"https://github.com/x/{n}"}
rels = [{"tag_name": "latest", "assets": [asset("ffmpeg-master-latest-win64-gpl.zip")]},
        {"tag_name": "autobuild-2026-11-17-12-00", "assets": [asset("ffmpeg-N-123-gabc-win64-gpl-shared.zip"), asset("ffmpeg-N-123-gabc-win64-gpl.zip"), asset("checksums.sha256")]},
        {"tag_name": "autobuild-2026-11-10-12-00", "assets": [asset("ffmpeg-N-100-gdef-win64-gpl.zip")]}]
sums = f"{SHA}  ffmpeg-N-123-gabc-win64-gpl.zip\n{'b' * 64}  ffmpeg-N-123-gabc-win64-gpl-shared.zip\n"
url, ver, sha = fp.find_ffmpeg(lambda u: rels, lambda u: sums)
check("ffmpeg: the newest dated release, the plain (not shared) build, the publisher's fingerprint", (url.endswith("ffmpeg-N-123-gabc-win64-gpl.zip"), ver, sha), (True, "autobuild-2026-11-17-12-00", SHA))
check("ffmpeg: the moving 'latest' link is never used", "latest" not in url, True)
_, _, none = fp.find_ffmpeg(lambda u: rels[2:], lambda u: "")
check("ffmpeg: no checksum file means no fingerprint (not an invented one)", none, "")
try: fp.find_ffmpeg(lambda u: rels[:1], lambda u: ""); res = "found"
except RuntimeError: res = "none"
check("ffmpeg: no usable release says so", res, "none")
dn = {"tag_name": "v2.5.1", "assets": [asset("deno-x86_64-pc-windows-msvc.zip"), asset("deno-x86_64-pc-windows-msvc.zip.sha256sum")]}
check("deno: version without the v, fingerprint read from the .sha256sum", fp.find_deno(lambda u: dn, lambda u: f"{SHA}  deno-x86_64-pc-windows-msvc.zip\n")[1:], ("2.5.1", SHA))
check("deno: a bare fingerprint file works too", fp.find_deno(lambda u: dn, lambda u: SHA)[2], SHA)
calls = []
class R:  # a stand-in for subprocess.run
    def __init__(s, c): calls.append(c); s.returncode = 0
fin = {"ffmpeg": lambda: (url, ver, SHA), "deno": lambda: ("https://github.com/d.zip", "2.5.1", "")}
check("without a publisher fingerprint it stops unless --yes", (fp.main([], fin, R), len(calls)), (1, 1))
check("the fingerprint is passed to the checker", "--sha256" in calls[0] and SHA in calls[0], True)
calls.clear()
check("--yes pins what was downloaded", (fp.main(["--yes"], fin, R), len(calls)), (0, 2))
check("--only picks one tool", (fp.main(["--only", "ffmpeg"], fin, R), len(calls)), (0, 3))
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
