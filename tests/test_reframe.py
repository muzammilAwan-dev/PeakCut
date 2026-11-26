"""Follow-the-face layout: the smooth path, the formula for ffmpeg, the fallback, and (when OpenCV is installed) a real face
found and kept in frame. Real ffmpeg, no network."""
import os, re, subprocess, sys, tempfile
from pathlib import Path
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-rf-")
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0")
sys.path.insert(0, ".")
from studio import reframe, render
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

W, Hh = 1280, 720
cw = reframe.window_width(Hh)
check("window: a 9:16 slice of a 720-high video, even width", (cw, cw % 2), (404, 0))
steady = [(i * 0.5, 900.0) for i in range(20)]
k = reframe.follow(steady, W, Hh, 9.5)
check("steady face: the window settles on it and stays", (abs(k[-1][1] - (900 - cw / 2)) < 1, k[-1][1] == k[-2][1]), (True, True))
wob = [(i * 0.5, 640 + (20 if i % 2 else -20)) for i in range(20)]
kw = reframe.follow(wob, W, Hh, 9.5)
check("a small wobble does not move the window (no shaking)", len({x for _t, x in kw}) <= 2, True)
jump = [(i * 0.5, 300.0 if i < 6 else 1000.0) for i in range(20)]
kj = reframe.follow(jump, W, Hh, 9.5)
steps = [abs(b[1] - a[1]) for a, b in zip(kj, kj[1:])]
check("a jump to the other side is followed calmly, never in one leap", (max(steps) <= reframe.SPEED * cw * reframe.STEP + 0.2, kj[-1][1] > kj[0][1] + 150), (True, True))
check("the window never leaves the picture", all(0 <= x <= W - cw for _t, x in reframe.follow([(0, -50), (1, 5000), (2, 640)], W, Hh, 2.0)), True)
check("too few sightings: no reframing", reframe.follow([(0.0, 600.0)], W, Hh, 20.0), None)
check("a vertical or square video is left alone", reframe.follow(steady, 720, 1280, 9.5), None)
check("many looks are thinned to a short formula", len(reframe.follow([(i * 0.5, 100 + (i * 9) % 900) for i in range(200)], W, Hh, 99.5)) <= reframe.MAX_KEYS, True)

# the formula really does what the path says
def ev(expr, t):
    f = lambda c, a, b: a if c else b
    return eval(re.sub(r"lt\(t,([\d.]+)\)", r"(t<\1)", expr).replace("if(", "f("), {"f": f, "t": t, "__builtins__": {}})
keys = [(0.0, 100.0), (1.0, 200.0), (2.5, 50.0)]
e = reframe.expression(keys)
check("formula: at the points it gives the path", [round(ev(e, t), 1) for t in (0.0, 1.0, 2.5, 3.0)], [100.0, 200.0, 50.0, 50.0])
check("formula: straight lines between points", round(ev(e, 0.5), 1), 150.0)
check("formula: only numbers and the time", re.fullmatch(r"[\d.,()+\-*/a-z]*", e) is not None and "$" not in e and ";" not in e, True)
check("formula: no path gives a plain 0", reframe.expression([]), "0")

# a wide test picture with a face on the right (needs OpenCV and a public-domain photo)
work = Path(tempfile.mkdtemp(prefix="pc-rfw-"))
try:
    import cv2
    from skimage import data
    from PIL import Image
    have = True
except ImportError:
    have = False; print("SKIP real-face checks (pip install -r requirements-optional.txt and scikit-image to run them)")
def make_video(path, face=True, dur=8):
    img = Image.new("RGB", (W, Hh), (30, 30, 60))
    if face:
        face_img = Image.fromarray(data.astronaut()).resize((420, 420)); img.paste(face_img, (780, 150))
    img.save(work / "bg.png")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(work / "bg.png"), "-f", "lavfi", "-i", f"sine=frequency=300:duration={dur}", "-t", str(dur),
                    "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
if have:
    v = work / "face.mp4"; make_video(v)
    pts = reframe.look(v, 0.0, 6.0, W, Hh)
    check("real: the face is found on most looks, on the right side", (len(pts) >= 8, all(x > 800 for _t, x in pts)), (True, True))
    expr = reframe.plan(v, 0.0, 6.0, W, Hh)
    check("real: a formula is made", bool(expr), True)
    clip = {"start": 0.0, "end": 6.0, "layout": "face", "style": "bounce", "hook": "", "highlight_words": []}
    out = work / "out"
    info = render.render_clip(v, out, "c1", clip, [], W, Hh)
    check("real: the clip is made with the face layout", info["layout"], "face")
    f = work / "frame.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "3", "-i", str(out / "c1.mp4"), "-frames:v", "1", str(f)], check=True)
    im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
    cas = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    fa = cas.detectMultiScale(im, 1.1, 5, minSize=(60, 60))
    check("real: the finished clip is 9:16 and the face is inside it, near the middle", (im.shape, len(fa) >= 1 and 200 < fa[0][0] + fa[0][2] / 2 < 880), ((1920, 1080), True))
    novid = work / "none.mp4"; make_video(novid, face=False)
    info = render.render_clip(novid, out, "c2", dict(clip), [], W, Hh)
    check("real: no face in the picture, the normal layout is used instead", info["layout"], "blur")
# fallback without OpenCV or after an error: never stops a clip
v2 = work / "plain.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=5", "-f", "lavfi", "-i", "sine=duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(v2)], check=True)
real_look = reframe.look
reframe.look = lambda *a, **k: None
info = render.render_clip(v2, work / "o3", "c3", {"start": 0.0, "end": 4.0, "layout": "face", "style": "bounce", "hook": "", "highlight_words": []}, [], W, Hh)
check("without OpenCV the face layout quietly becomes the normal one", (info["layout"], (work / "o3" / "c3.mp4").stat().st_size > 1000), ("blur", True))
def boom(*a, **k): raise RuntimeError("detector crashed")
reframe.look = boom
info = render.render_clip(v2, work / "o4", "c4", {"start": 0.0, "end": 4.0, "layout": "face", "style": "bounce", "hook": "", "highlight_words": []}, [], W, Hh)
check("a crash in the detector does not stop the clip", info["layout"], "blur")
reframe.look = real_look
check("the layout is offered only when OpenCV is there", ("face" in render.layouts()) == reframe.available(), True)
check("the plain layouts are always offered", all(k in render.layouts() for k in ("blur", "zoom", "crop")), True)
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
