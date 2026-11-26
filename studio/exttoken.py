"""The pairing key between the browser extension and this app.

The extension has no sign-in of its own, so it carries one long random key that only the owner can read (on the
"Browser extension" settings tab) and paste into the extension once. The key opens exactly one door: adding a video link.
It is kept in the data folder, made once, and can be replaced at any time (the old one stops working at once)."""
import hmac
import json
import os
import secrets
from pathlib import Path

from . import config


def _file() -> Path:
    return Path(config.DATA_DIR) / "ext_token.json"


def _read() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("token") and d.get("uid") else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict):
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, f)


def token_for(uid: str) -> str:
    """The owner's key (made on first use). It belongs to whoever first asked: videos it adds are theirs."""
    d = _read()
    if not d:
        d = {"token": secrets.token_urlsafe(32), "uid": uid}
        _write(d)
    return d["token"]


def reset(uid: str) -> str:
    _write({"token": secrets.token_urlsafe(32), "uid": uid})
    return _read()["token"]


def owner_of(candidate: str):
    """The user id this key belongs to, or None. Constant-time comparison, so timing reveals nothing."""
    d = _read()
    cand = str(candidate or "")
    if not d or not cand or not hmac.compare_digest(cand.encode("utf-8"), d["token"].encode("utf-8")):
        return None
    return d["uid"]
