"""Getting past YouTube's "Sign in to confirm you're not a bot", without making anyone export files.

What the research says (see docs/DECISIONS.md, 2026-11-28): on a home internet connection the check mostly does not appear. When it does,
the fix that works for most people is to let yt-dlp read the YouTube sign-in from a browser that is already signed in. So:

  1. First every YouTube request goes out as a visitor (no sign-in, nothing of yours is used).
  2. Only if YouTube refuses (the bot check) and the owner has allowed it, ViralCut looks for a signed-in browser by itself
     (Firefox first, because Chrome and Edge on Windows lock their cookies against other programs), and repeats the request.
  3. It then keeps using that sign-in until ViralCut is closed.

It is OFF until the owner allows it (Settings, YouTube access) because a sign-in is personal. Use a spare Google account: heavy
automatic use can make YouTube challenge the account.

Saved in data/youtube.json as {"mode": "off" | "auto" | "firefox" | "edge" | "chrome" | "brave" | "file", "file": "<cookies.txt path>"}.
PEAKCUT_YT_COOKIES overrides it (same words, or a path to a cookies.txt file).
"""
import json
import os
import threading
from pathlib import Path

from . import applog, config

MODES = ("off", "auto", "firefox", "edge", "chrome", "brave", "file")
AUTO_ORDER = ("firefox", "edge", "chrome", "brave")
LOGIN_COOKIES = {"SAPISID", "__Secure-3PAPISID", "SID", "__Secure-1PSID", "LOGIN_INFO"}
_lock = threading.Lock()
_state = {"on": False, "how": "", "note": "", "tried": {}}      # on: sign-in is being used right now


def _path() -> Path:
    return config.DATA_DIR / "youtube.json"


def settings() -> dict:
    env = str(config.env("PEAKCUT_YT_COOKIES", "") or "").strip()
    if env:
        if env.lower() in MODES:
            return {"mode": env.lower(), "file": "", "from_env": True}
        return {"mode": "file", "file": env, "from_env": True}
    try:
        v = json.loads(_path().read_text(encoding="utf-8"))
        mode = v.get("mode") if v.get("mode") in MODES else "off"
        return {"mode": mode, "file": str(v.get("file") or ""), "from_env": False}
    except (OSError, ValueError, AttributeError):
        return {"mode": "off", "file": "", "from_env": False}


def save(mode: str, file: str = ""):
    if mode not in MODES:
        raise ValueError("Choose one of the options in the list.")
    file = (file or "").strip()
    if mode == "file" and not (file and Path(file).is_file()):
        raise ValueError("That cookies file was not found. Paste its full path.")
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps({"mode": mode, "file": file}), encoding="utf-8")
    with _lock:
        _state.update(on=False, how="", note="", tried={})       # start again with the new choice
    applog.log("youtube.access", mode=mode, file="yes" if file else "")


def configured() -> bool:
    return settings()["mode"] != "off"


def _login_in(jar) -> bool:
    try:
        return any(c.name in LOGIN_COOKIES and (c.domain.endswith("youtube.com") or c.domain.endswith("google.com")) for c in jar)
    except Exception:  # noqa: BLE001
        return False


def _check_browser(name: str):
    """(True, "") if this browser is signed in to YouTube and its cookies can be read, else (False, why)."""
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(name)
    except Exception as e:  # noqa: BLE001 - not installed, locked, or encrypted against other programs
        return False, str(e)[:160] or "could not be read"
    return (True, "") if _login_in(jar) else (False, "no YouTube sign-in found in it")


def activate() -> bool:
    """Turn the sign-in on (after YouTube refused). True when there is now something to try; False when it is not allowed or not found."""
    s = settings()
    with _lock:
        if _state["on"]:
            return True
        if s["mode"] == "off":
            return False
        if s["mode"] == "file":
            ok = Path(s["file"]).is_file()
            _state.update(on=ok, how="file" if ok else "", note="" if ok else "the cookies file was not found")
            applog.log("youtube.cookies", "info" if ok else "warning", how="file", ok=ok)
            return ok
        names = AUTO_ORDER if s["mode"] == "auto" else (s["mode"],)
        for n in names:
            ok, why = _check_browser(n)
            _state["tried"][n] = "ok" if ok else why
            applog.log("youtube.cookies", "info" if ok else "warning", how=n, ok=ok, why=why)
            if ok:
                _state.update(on=True, how=n, note="")
                return True
        _state["note"] = "No browser with a YouTube sign-in could be read. " + "; ".join(f"{k}: {v}" for k, v in _state["tried"].items())
        return False


def opts() -> dict:
    """The yt-dlp options that carry the sign-in, or {} while it is not in use."""
    with _lock:
        if not _state["on"]:
            return {}
        how = _state["how"]
    if how == "file":
        f = settings()["file"]
        return {"cookiefile": f} if f else {}
    return {"cookiesfrombrowser": (how,)}


def state() -> dict:
    s = settings()
    with _lock:
        return {"mode": s["mode"], "file": s["file"], "from_env": s["from_env"], "in_use": _state["on"], "using": _state["how"],
                "note": _state["note"], "tried": dict(_state["tried"])}
