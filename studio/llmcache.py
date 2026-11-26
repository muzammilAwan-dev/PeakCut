"""Remembers what the AI answered, so asking the same thing again costs nothing.

The key is a fingerprint of the exact request (the prompt and the shape of the answer wanted), so a rerun of the same
video, a restart halfway through, or pressing "make again" on an unchanged clip makes no new AI call. Only answers
that passed the checks are stored. Live checks are not stored (they are about the moment, never asked twice).
A small SQLite file in the data folder; if it cannot be used the app simply asks the AI as before."""
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from . import branding, config

TTL = 30 * 86400            # an answer is reused for 30 days
MAX_ROWS = 4000             # the oldest are dropped past this
_lock = threading.Lock()
_db = None


def enabled() -> bool:
    return str(branding.env("LLM_CACHE", "1")).strip().lower() not in ("0", "false", "no", "off")


def key(prompt: str, schema) -> str:
    return hashlib.sha256(json.dumps([prompt, schema], sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _open():
    global _db
    if _db is None:
        path = Path(config.DATA_DIR) / "llm_cache.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        _db.execute("CREATE TABLE IF NOT EXISTS answers (k TEXT PRIMARY KEY, v TEXT NOT NULL, model TEXT NOT NULL, tokens INTEGER NOT NULL, at REAL NOT NULL)")
    return _db


def get(prompt: str, schema):
    """(answer, model) or None."""
    if not enabled():
        return None
    try:
        with _lock:
            row = _open().execute("SELECT v, model, at FROM answers WHERE k=?", (key(prompt, schema),)).fetchone()
        if row and time.time() - row[2] <= TTL:
            return json.loads(row[0]), row[1]
    except (sqlite3.Error, ValueError, OSError):
        pass
    return None


def put(prompt: str, schema, answer, model: str, tokens: int = 0):
    if not enabled():
        return
    try:
        with _lock:
            db = _open()
            db.execute("INSERT OR REPLACE INTO answers (k, v, model, tokens, at) VALUES (?,?,?,?,?)",
                       (key(prompt, schema), json.dumps(answer, ensure_ascii=False), str(model)[:120], int(tokens), time.time()))
            db.execute("DELETE FROM answers WHERE k IN (SELECT k FROM answers ORDER BY at DESC LIMIT -1 OFFSET ?)", (MAX_ROWS,))
            db.commit()
    except (sqlite3.Error, TypeError, ValueError, OSError):
        pass


def clear() -> int:
    try:
        with _lock:
            db = _open()
            n = db.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
            db.execute("DELETE FROM answers")
            db.commit()
            return n
    except (sqlite3.Error, OSError):
        return 0


def reset_connection():
    """For tests that point the data folder somewhere else."""
    global _db
    with _lock:
        if _db is not None:
            _db.close()
        _db = None
