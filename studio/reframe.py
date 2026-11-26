"""Optional: keeps a speaker's face in the middle of a vertical clip made from a wide video.

Off unless OpenCV is installed (requirements-optional.txt). A clip asks for it by choosing the layout "Follow the face".
If no face is found for most of the clip, or anything goes wrong, the clip is made with the normal blurred layout instead:
this can never stop a clip from being made. Manual layout choices always win: it only runs when that layout was picked.

How it works: a frame every half second is searched for faces (OpenCV's built-in detector, run on this computer; nothing is
sent anywhere). The biggest face wins. The crop window then follows it smoothly: it ignores small movements, moves at a
calm speed and never jumps, so the picture does not shake. The path is handed to ffmpeg as one formula."""
import subprocess
import tempfile
from pathlib import Path

STEP = 0.5            # seconds between looks
MIN_SHARE = 0.3       # fewer faces than this share of the looks: do not reframe
DEADBAND = 0.12       # the face may wander this share of the window's width before the window moves
SPEED = 0.45          # most the window may move per second, as a share of its width
MAX_KEYS = 40         # points in the formula given to ffmpeg


def available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def window_width(src_h: int) -> int:
    """Width of the 9:16 window cut from a video this tall (even, as video needs)."""
    return int(src_h * 9 / 16) // 2 * 2


def follow(points, src_w, src_h, duration):
    """points: [(time, face centre x in pixels)] in clip time, only where a face was seen.
    Returns [(time, window left edge in pixels)] (smooth), or None when there is too little to go on."""
    cw = window_width(src_h)
    looks = max(1, int(duration / STEP))
    if cw >= src_w or len(points) < max(2, MIN_SHARE * looks):
        return None
    lo, hi = 0.0, float(src_w - cw)
    pts = sorted(points)
    keys, x = [], min(hi, max(lo, pts[0][1] - cw / 2))
    t = 0.0
    while t <= duration + 1e-6:
        near = min(pts, key=lambda p: abs(p[0] - t))[1]            # the nearest sighting; it holds through short gaps
        target = min(hi, max(lo, near - cw / 2))
        gap = target - x
        if abs(gap) > DEADBAND * cw:
            step = SPEED * cw * STEP
            x += max(-step, min(step, gap))
        keys.append((round(t, 2), round(x, 1)))
        t += STEP
    if len(keys) > MAX_KEYS:                                        # thin out evenly, keeping the first and the last
        pick = sorted({round(i * (len(keys) - 1) / (MAX_KEYS - 1)) for i in range(MAX_KEYS)})
        keys = [keys[i] for i in pick]
    return keys


def expression(keys) -> str:
    """ffmpeg formula for the window's left edge over time: straight lines between the points. Numbers only, so nothing
    from a video can end up inside it."""
    if not keys:
        return "0"
    out = f"{keys[-1][1]:.1f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        if t1 > t0:
            out = f"if(lt(t,{t1:.2f}),{x0:.1f}+({x1:.1f}-{x0:.1f})*(t-{t0:.2f})/{t1 - t0:.2f},{out})"
    return out


def look(src: Path, start: float, duration: float, src_w: int, src_h: int):
    """[(clip time, face centre x)] for each look where a face is found, or None when OpenCV is not installed."""
    try:
        import cv2
    except ImportError:
        return None
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    if cascade.empty():
        return None
    out, tmp = [], Path(tempfile.mkdtemp(prefix="pkf"))
    try:
        # one small picture per look, made by ffmpeg (it already reads every format we accept)
        scale = 640 / src_w if src_w > 640 else 1.0
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{duration:.2f}", "-i", str(src), "-an",
                        "-vf", f"fps={1 / STEP},scale=iw*{scale:.4f}:-2", "-q:v", "4", str(tmp / "f%04d.jpg")], check=True, timeout=300)
        for i, f in enumerate(sorted(tmp.glob("f*.jpg"))):
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            faces = cascade.detectMultiScale(img, 1.1, 5, minSize=(max(24, img.shape[0] // 14),) * 2)
            if len(faces):
                x, _y, w, _h = max(faces, key=lambda r: r[2] * r[3])
                out.append((i * STEP, (x + w / 2) / scale))
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
        tmp.rmdir()
    return out


def plan(src: Path, start: float, end: float, src_w: int, src_h: int):
    """The window formula for this clip, or None (use the normal layout instead)."""
    try:
        if src_w <= src_h:
            return None
        pts = look(src, start, end - start, src_w, src_h)
        keys = follow(pts, src_w, src_h, end - start) if pts else None
        return expression(keys) if keys else None
    except Exception:  # noqa: BLE001 - never stop a clip over this
        return None
