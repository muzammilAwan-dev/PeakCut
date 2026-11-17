"""The pool's memory: how much each AI service and model has been used this minute and today, which ones are
cooling down after a rate-limit or an error, and which ones are switched off. It is kept in a small SQLite file in
the data folder, so it survives a restart and travels with the folder.

Two tables:
  ai_ledger        one row per service, model and time bucket: requests and tokens used in it
  ai_ledger_state  one row per service (model "") or per model: cooldown, failures in a row, disabled reason

Only the standard library is used. Every method is safe to call from several threads. If the file cannot be opened
or is damaged, the pool keeps working with a memory-only ledger (it just forgets at restart)."""
import sqlite3
import threading
import time


class Ledger:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        self.lock = threading.RLock()
        self.in_memory = self.path == ":memory:"
        self.db = self._open(self.path)

    def _open(self, path):
        try:
            db = sqlite3.connect(path, check_same_thread=False, timeout=10)
            if path != ":memory:":
                db.execute("PRAGMA journal_mode=WAL")          # readers and the writer do not block each other
            self._create(db)
            return db
        except sqlite3.Error:
            if path == ":memory:":
                raise
            self.in_memory = True                    # damaged or locked file: carry on without saving
            db = sqlite3.connect(":memory:", check_same_thread=False)
            self._create(db)
            return db

    @staticmethod
    def _create(db):
        db.executescript("""
            CREATE TABLE IF NOT EXISTS ai_ledger (
                provider TEXT NOT NULL, model TEXT NOT NULL, bucket TEXT NOT NULL,
                req INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (provider, model, bucket));
            CREATE TABLE IF NOT EXISTS ai_ledger_state (
                provider TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                cooldown_until REAL NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0,
                rate_hits INTEGER NOT NULL DEFAULT 0, schema_fail INTEGER NOT NULL DEFAULT 0,
                ok_total INTEGER NOT NULL DEFAULT 0, fail_total INTEGER NOT NULL DEFAULT 0,
                disabled TEXT NOT NULL DEFAULT '', updated REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (provider, model));
        """)
        db.commit()

    # ------------------------------------------------------------ use in time buckets
    def used(self, provider, model, buckets) -> dict:
        """{bucket: (requests, tokens)} for the buckets asked about (zeros when never used)."""
        out = {b: (0, 0) for b in buckets}
        with self.lock:
            for b in buckets:
                row = self.db.execute("SELECT req, tokens FROM ai_ledger WHERE provider=? AND model=? AND bucket=?", (provider, model, b)).fetchone()
                if row:
                    out[b] = (int(row[0]), int(row[1]))
        return out

    def add(self, provider, model, buckets, req=0, tokens=0):
        """Add to every bucket given (for example the current minute and the current day)."""
        with self.lock:
            for b in buckets:
                self.db.execute(
                    "INSERT INTO ai_ledger (provider, model, bucket, req, tokens) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(provider, model, bucket) DO UPDATE SET req=MAX(0, req+excluded.req), tokens=MAX(0, tokens+excluded.tokens)",
                    (provider, model, b, int(req), int(tokens)))
            self.db.commit()

    def prune(self, keep_buckets_after: str):
        """Forget minute buckets older than the given one ('m' + minute number) and day buckets older than 3 days are
        left to prune_days. Minute buckets sort as numbers, so they are compared as numbers."""
        with self.lock:
            cut = int(keep_buckets_after[1:])
            self.db.execute("DELETE FROM ai_ledger WHERE bucket LIKE 'm%' AND CAST(substr(bucket, 2) AS INTEGER) < ?", (cut,))
            self.db.commit()

    def prune_days(self, oldest_day: str):
        with self.lock:
            self.db.execute("DELETE FROM ai_ledger WHERE bucket LIKE 'd%' AND substr(bucket, 2) < ?", (oldest_day,))
            self.db.commit()

    # ------------------------------------------------------------ state of a service or a model
    _COLS = ("cooldown_until", "fails", "rate_hits", "schema_fail", "ok_total", "fail_total", "disabled")

    def state(self, provider, model="") -> dict:
        with self.lock:
            row = self.db.execute("SELECT cooldown_until, fails, rate_hits, schema_fail, ok_total, fail_total, disabled "
                                  "FROM ai_ledger_state WHERE provider=? AND model=?", (provider, model)).fetchone()
        return dict(zip(self._COLS, row)) if row else dict(zip(self._COLS, (0.0, 0, 0, 0, 0, 0, "")))

    def update(self, provider, model="", **changes):
        """Set some of the state fields to new values (see add_to to count up or down)."""
        bad = set(changes) - set(self._COLS)
        if bad:
            raise ValueError(f"unknown state field {sorted(bad)}")
        with self.lock:
            cur = self.state(provider, model)
            cur.update(changes)
            self.db.execute(
                "INSERT INTO ai_ledger_state (provider, model, cooldown_until, fails, rate_hits, schema_fail, ok_total, fail_total, disabled, updated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider, model) DO UPDATE SET cooldown_until=excluded.cooldown_until, "
                "fails=excluded.fails, rate_hits=excluded.rate_hits, schema_fail=excluded.schema_fail, ok_total=excluded.ok_total, "
                "fail_total=excluded.fail_total, disabled=excluded.disabled, updated=excluded.updated",
                (provider, model, float(cur["cooldown_until"]), int(cur["fails"]), int(cur["rate_hits"]), int(cur["schema_fail"]),
                 int(cur["ok_total"]), int(cur["fail_total"]), str(cur["disabled"])[:200], time.time()))
            self.db.commit()

    def add_to(self, provider, model="", **counters):
        """Count up (or down) some of the counters: fails, rate_hits, schema_fail, ok_total, fail_total."""
        with self.lock:
            cur = self.state(provider, model)
            self.update(provider, model, **{k: max(0, int(cur[k]) + int(v)) for k, v in counters.items()})

    def all_states(self) -> list:
        with self.lock:
            rows = self.db.execute("SELECT provider, model, cooldown_until, fails, rate_hits, schema_fail, ok_total, fail_total, disabled "
                                   "FROM ai_ledger_state ORDER BY provider, model").fetchall()
        return [dict(zip(("provider", "model") + self._COLS, r)) for r in rows]

    def close(self):
        with self.lock:
            try:
                self.db.close()
            except sqlite3.Error:
                pass
