"""The log file: one line per thing that happened, kept in data/logs/viralcut.log.

Read it when something goes wrong ("what did Gemini answer?"). It is rotated (5 files of about 5 MB), so it never fills the disk.

What goes in: the server starting, every web request (method, path, status, time), keys being saved (only the last four letters),
every request to an AI service (service, model, status code, time, and the reply when it is a check or an error), model checks,
jobs starting, finishing and failing (with the error text).

What never goes in: a key, a password, a cookie, or the text of your videos. Replies to real clip-finding requests are logged
as a size only; set VIRALCUT_LOG_LEVEL=debug (or PEAKCUT_LOG_LEVEL) to also log the first 300 characters of them.
"""
import logging
import logging.handlers
import re
import threading
import time
import traceback

from . import config

_LOG = logging.getLogger("viralcut")
_lock = threading.Lock()
_ready = False
_secrets = set()                    # exact key values to blank out, as soon as the app has seen them
MAX_VALUE = 400

# Shapes of keys and tokens that are blanked even when the app has not seen them (a key pasted inside an error message, say).
_SHAPES = re.compile(
    r"(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z_\-]{16,}|csk-[0-9A-Za-z]{16,}|"
    r"(?i:bearer)\s+[0-9A-Za-z._\-~+/=]{12,}|(?i:x-goog-api-key|api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?[0-9A-Za-z._\-~+/=]{8,}|"
    r"dpapi:[0-9A-Za-z+/=]{20,})")


def level() -> str:
    v = str(config.env("PEAKCUT_LOG_LEVEL", "info") or "info").strip().lower()
    return v if v in ("debug", "info", "warning", "off") else "info"


def path():
    return config.DATA_DIR / "logs" / "viralcut.log"


def remember_secret(value):
    """Tell the log a key so it can blank it out wherever it appears."""
    v = str(value or "").strip()
    if len(v) >= 8:
        with _lock:
            _secrets.add(v)


def clean(value, limit=MAX_VALUE) -> str:
    s = str(value).replace("\r", " ").replace("\n", " ")
    for v in list(_secrets):
        s = s.replace(v, "<key>")
    s = _SHAPES.sub("<hidden>", s)
    return s if len(s) <= limit else s[:limit] + f"...(+{len(s) - limit})"


def setup():
    """Open the log file. Safe to call again. A failure to write the log never stops the app."""
    global _ready
    with _lock:
        if _ready or level() == "off":
            return
        try:
            p = path()
            p.parent.mkdir(parents=True, exist_ok=True)
            h = logging.handlers.RotatingFileHandler(p, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%Y-%m-%d %H:%M:%S"))
            _LOG.handlers[:] = [h]
            _LOG.setLevel(logging.DEBUG if level() == "debug" else logging.INFO)
            _LOG.propagate = False
            _ready = True
        except OSError:
            _ready = False


def log(event, _level="info", **fields):
    """One line: `event key=value key=value`. Values are cleaned and shortened."""
    if level() == "off":
        return
    if not _ready:
        setup()
    if not _ready:
        return
    parts = [event]
    for k, v in fields.items():
        if v is None or v == "":
            continue
        s = clean(v).replace('"', "'")
        parts.append(f'{k}="{s}"' if re.search(r"[\s=\"]", s) else f"{k}={s}")
    try:
        getattr(_LOG, _level if _level in ("debug", "info", "warning", "error") else "info")(" ".join(parts))
    except Exception:  # noqa: BLE001 - logging must never break the app
        pass


def error(event, exc=None, **fields):
    """An error with its traceback on following lines (cleaned)."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc is not None else ""
    log(event, "error", error=repr(exc) if exc is not None else "", **fields)
    if tb and _ready:
        try:
            _LOG.error(clean(tb, 4000).replace("  ", " "))
        except Exception:  # noqa: BLE001
            pass


def tail(lines=300) -> str:
    """The last lines of the log, for the settings page."""
    lines = max(1, min(2000, int(lines)))
    try:
        data = path().read_bytes()[-400_000:].decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    return "\n".join(data[-lines:])


class Timer:
    def __init__(self):
        self.t0 = time.time()

    def ms(self) -> int:
        return int((time.time() - self.t0) * 1000)
