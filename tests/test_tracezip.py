"""The paper trail of one video can be downloaded as a zip, only by its owner. No network."""
import io, os, sys, tempfile, zipfile
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-tz-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0", PEAKCUT_TRACE="1", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
sys.path.insert(0, ".")
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

from fastapi.testclient import TestClient
from studio import auth, db, jobs, server
db.init()
c = TestClient(server.app, base_url="http://127.0.0.1:8765", follow_redirects=False)
uid = auth.local_user().id
d = DATA / "j1"; (d / "trace").mkdir(parents=True)
(d / "trace" / "transcript.txt").write_text("0.0 hello world\n", encoding="utf-8")
(d / "trace" / "ai-001-video-finding-clips.txt").write_text("PROMPT ...\nREPLY ...\n", encoding="utf-8")
(d / "secret.txt").write_text("not part of the trail", encoding="utf-8")
jobs._jobs["20261128-aaaa1111"] = {"id": "20261128-aaaa1111", "user": uid, "kind": "video", "dir": str(d), "status": "done", "clips": [], "source": {"type": "url"}}
jobs._jobs["20261128-bbbb2222"] = {"id": "20261128-bbbb2222", "user": uid, "kind": "video", "dir": str(DATA / "none"), "status": "done", "clips": [], "source": {"type": "url"}}
jobs._jobs["20261128-cccc3333"] = {"id": "20261128-cccc3333", "user": "someone-else", "kind": "video", "dir": str(d), "status": "done", "clips": [], "source": {"type": "url"}}

r = c.get("/api/jobs/20261128-aaaa1111/trace")
z = zipfile.ZipFile(io.BytesIO(r.content)) if r.status_code == 200 else None
check("the trail downloads as a zip", (r.status_code, r.headers["content-type"]), (200, "application/zip"))
check("it holds the transcript and the AI questions, nothing else", sorted(z.namelist()), ["ai-001-video-finding-clips.txt", "transcript.txt"])
check("a video without a trail gets a plain message", (c.get("/api/jobs/20261128-bbbb2222/trace").status_code), 404)
check("somebody else's video is not found", c.get("/api/jobs/20261128-cccc3333/trace").status_code, 404)
check("a made-up id is not found", c.get("/api/jobs/../trace").status_code, 404)
print("ALL PASSED" if not fails else f"{len(fails)} failed: {fails}")
sys.exit(1 if fails else 0)
