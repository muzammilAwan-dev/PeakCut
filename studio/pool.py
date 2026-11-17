"""The free AI pool: asks several AI services in turn so that one running out of free allowance, going down or
answering badly does not stop a video. When every service is used up, it says so with PoolExhausted, and the
caller falls back to picking clips by loudness (brain.find_clips already does).

How one request goes:
  1. Work out which service/model pairs may be used right now ("eligible"): switched on, has a key, passes the
     privacy setting, big enough for the request, not cooling down, and under 80% of every known limit.
  2. Use the best one: best tier first, then the most room left, then the fewest recent failures.
  3. A rate-limit reply (429) puts that model on cooldown (the time the service asked for, else 30 s doubling to
     15 min; until the daily reset when the limit is a daily one). A server error or timeout cools the whole service
     down for 60 s, and for 10 min after three in a row. A refused key (401/403) switches the service off until a
     new key is saved. A missing model (404) switches that model off.
  4. An answer that is not JSON, or does not fit the schema, is asked for once more (telling the model what was
     wrong, never repeating its own words back). If it fails again, the next service is used.
  5. Nothing eligible but something only waiting for the next minute: wait for it (up to 75 s), so a service with
     8,000 tokens a minute is used again a minute later instead of failing. Otherwise: PoolExhausted.

What happened is kept in the ledger (studio/ledger.py), so cooldowns and counts survive a restart.

Privacy (PEAKCUT_AI_PRIVACY or privacy in data/pool.json):
  strict (default)  only services whose data terms say they do not train on your text, checked in the last 90 days
  relaxed           also services where it depends or is unknown
  any               also services that may train on it
A service that runs on this computer (Ollama) always passes. Speech-to-text always stays on this computer; the
transcript text is what is sent to a service.

Keys: one per service, from data/pool.json or from the environment variable named in the catalog (GROQ_API_KEY ...).
The catalog is studio/providers.default.json; data/providers.json can add or replace services.

Only the standard library is used here, so the pool can be tested without any network package."""
import datetime
import http.client
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import branding, jsoncheck
from .ledger import Ledger

ADAPTERS = ("openai", "gemini")
PRIVACY_MODES = ("strict", "relaxed", "any")
TRAINS = ("no", "yes", "depends", "unknown")
FRESH_DAYS = 90                  # strict mode: how recent the data-terms check must be
LIMIT_SHARE = 0.8                # use at most this part of a published limit
DAILY = re.compile(r"per day|daily|\brpd\b|\btpd\b|requests per day|tokens per day", re.I)
REPAIR_NOTE = ("\n\nYour previous answer could not be used ({why}). Answer again with JSON only, no other text, "
               "following the required format exactly.")


class PoolExhausted(RuntimeError):
    """No service can answer right now. The text never contains "HTTP 429" or "HTTP 5": brain.ask_ai would treat that as a
    reason to sleep and retry, and the pool has already done its own waiting."""


class ProviderError(Exception):
    """A service answered with an error, or could not be reached (status None)."""

    def __init__(self, status, retry_after=None, body="", kind="http"):
        super().__init__(f"status {status}" if status else kind)
        self.status, self.retry_after, self.body, self.kind = status, retry_after, body or "", kind


class NotJSON(ValueError):
    """The reply was not usable JSON at all."""


class _Retry(Exception):
    """Internal: this attempt is over; look for the next service."""


# ---------------------------------------------------------------- the catalog
def _date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _limit(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _clean_model(m) -> "dict | None":
    if not isinstance(m, dict) or not re.fullmatch(r"[\w.\-:/@]{1,120}", str(m.get("id") or "")):
        return None
    if str(m.get("status") or "active") != "active":
        return None
    lim = m.get("limits") if isinstance(m.get("limits"), dict) else {}
    reset = str(lim.get("reset") or "utc")
    return {"id": str(m["id"]), "ctx": _limit(m.get("ctx")) or 8192,
            "json_mode": str(m.get("json_mode")) if str(m.get("json_mode")) in ("schema", "object", "none", "unknown") else "unknown",
            "tier": min(3, max(1, int(m["tier"]))) if isinstance(m.get("tier"), int) and not isinstance(m.get("tier"), bool) else 3,
            "limits": {k: _limit(lim.get(k)) for k in ("rpm", "rpd", "tpm", "tpd")} | {"reset": reset if reset in ("utc", "pacific", "rolling") else "utc"}}


def _clean_provider(p) -> "dict | None":
    """One catalog entry in a safe, complete shape; None when it cannot be used. Entries can come from a file the
    user edited, so nothing is trusted."""
    if not isinstance(p, dict) or not re.fullmatch(r"[a-z0-9_-]{1,30}", str(p.get("id") or "")):
        return None
    base = str(p.get("base_url") or "").strip().rstrip("/")
    if not (re.fullmatch(r"https://[^\s]+", base) or re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:\d+)?(/[^\s]*)?", base)):
        return None
    if p.get("adapter") not in ADAPTERS:
        return None
    pr = p.get("privacy") if isinstance(p.get("privacy"), dict) else {}
    key_env = str(p.get("key_env") or "")
    return {"id": p["id"], "label": str(p.get("label") or p["id"])[:60], "adapter": p["adapter"], "base_url": base,
            "key_env": key_env if re.fullmatch(r"[A-Z0-9_]{1,60}", key_env) else "",
            "needs": [n for n in (p.get("needs") or []) if n == "account_id"],
            "account_id_env": str(p.get("account_id_env") or "") if re.fullmatch(r"[A-Z0-9_]{1,60}", str(p.get("account_id_env") or "")) else "",
            "needs_key": p.get("needs_key") is not False, "local": p.get("local") is True,
            "enabled_default": p.get("enabled_default") is True, "signup_url": str(p.get("signup_url") or "")[:200],
            "privacy": {"trains_on_data": pr.get("trains_on_data") if pr.get("trains_on_data") in TRAINS else "unknown",
                        "source_url": str(pr.get("source_url") or "")[:300], "verified_on": _date(pr.get("verified_on"))},
            "models": [m for m in (_clean_model(x) for x in (p.get("models") or [])) if m]}


class Catalog:
    """The services the pool knows, from the bundled file and (replacing entries with the same id) a user file."""

    def __init__(self, default_path, user_path=None):
        self.default_path, self.user_path = Path(default_path), Path(user_path) if user_path else None
        self._stamp, self._items = None, []

    @staticmethod
    def _read(path) -> list:
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return []
        return d.get("providers", []) if isinstance(d, dict) and isinstance(d.get("providers"), list) else []

    def providers(self) -> list:
        stamp = tuple(p.stat().st_mtime_ns if p and p.exists() else 0 for p in (self.default_path, self.user_path))
        if stamp != self._stamp:
            merged = {}
            for raw in self._read(self.default_path) + (self._read(self.user_path) if self.user_path else []):
                c = _clean_provider(raw)
                if c:
                    merged[c["id"]] = c
            self._items, self._stamp = list(merged.values()), stamp
        return self._items


# ---------------------------------------------------------------- the owner's choices
class Settings:
    """data/pool.json: keys, switches, privacy mode, local model names. The file is for the person who runs this
    computer. (Encrypting it is slice S7, together with the other key files.)"""

    def __init__(self, path, env=None):
        self.path, self.env = Path(path), env
        self._at, self._data, self._lock = None, {}, threading.RLock()

    def _environ(self):
        return os.environ if self.env is None else self.env

    def data(self) -> dict:
        with self._lock:
            try:
                at = self.path.stat().st_mtime_ns
            except OSError:
                at = 0
            if at != self._at:
                try:
                    d = json.loads(self.path.read_text(encoding="utf-8")) if at else {}
                except (OSError, ValueError, UnicodeError):
                    d = {}
                self._data, self._at = (d if isinstance(d, dict) else {}), at
            return self._data

    def _save(self, d):
        with self._lock:
            tmp = self.path.with_name(self.path.name + ".tmp")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.path)
            self._at = None

    def _section(self, name) -> dict:
        v = self.data().get(name)
        return v if isinstance(v, dict) else {}

    def privacy(self) -> str:
        v = str(branding.env("AI_PRIVACY") or self.data().get("privacy") or "strict").strip().lower()
        return v if v in PRIVACY_MODES else "strict"

    def key(self, p) -> str:
        v = self._section("keys").get(p["id"])
        if isinstance(v, str) and v.strip():
            return v.strip()
        return (self._environ().get(p["key_env"]) or "").strip() if p["key_env"] else ""

    def account_id(self, p) -> str:
        v = self._section("account_ids").get(p["id"])
        if isinstance(v, str) and v.strip():
            return v.strip()
        return (self._environ().get(p["account_id_env"]) or "").strip() if p["account_id_env"] else ""

    def enabled(self, p) -> bool:
        v = self._section("enabled").get(p["id"])
        return v if isinstance(v, bool) else p["enabled_default"]

    def local_models(self) -> list:
        v = self.data().get("local_models")
        return [str(x) for x in v if re.fullmatch(r"[\w.\-:/@]{1,120}", str(x))][:5] if isinstance(v, list) else []

    def change(self, section, name, value):
        with self._lock:
            d = dict(self.data())
            if section is None:
                d[name] = value
            else:
                d[section] = {**self._section(section), name: value}
                if value in (None, ""):
                    d[section].pop(name, None)
            self._save(d)


# ---------------------------------------------------------------- numbers
def estimate_tokens(prompt: str, schema=None) -> int:
    """About how many tokens a request is: characters / 3.5, a cautious guess that needs no tokenizer."""
    return int(math.ceil((len(prompt) + (len(json.dumps(schema)) if schema else 0) + 200) / 3.5))


def _eff(limit):
    return max(1, int(limit * LIMIT_SHARE))


def _day_start(reset, now):
    """The start of the day that counts for this service's daily limit (Pacific time is taken as UTC-8: close enough)."""
    shift = -8 * 3600 if reset == "pacific" else 0
    return (int((now + shift) // 86400) * 86400) - shift


def _day_key(reset, now):
    return "d" + datetime.datetime.fromtimestamp(_day_start(reset, now), datetime.timezone.utc).strftime("%Y-%m-%d")


def _redact(text, key):
    return str(text).replace(key, "<key>") if key else str(text)


# ---------------------------------------------------------------- talking to the services (standard library only)
def _post(url, body, headers, timeout, key=""):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"{branding.APP_NAME}-pool", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read(8_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, _redact(e.read(4000).decode("utf-8", "replace"), key)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        reason = getattr(e, "reason", e)
        raise ProviderError(None, None, "", "timeout" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "network")


def _retry_after(headers) -> "float | None":
    try:
        v = float(headers.get("Retry-After")) if headers is not None and headers.get("Retry-After") else None
    except (TypeError, ValueError):
        return None
    return v if v is not None and 0 <= v <= 7 * 86400 else None


def send_openai(p, m, key, prompt, schema, timeout):
    """Any service that speaks the OpenAI chat format. Returns (answer, tokens in, tokens out)."""
    from . import ai
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    body = {"model": m["id"], "messages": [{"role": "user", "content": ai._wrapped(prompt, schema)}]}
    # most services accept both extras; a few models refuse one, so they are dropped on a refusal
    ladder = [{"temperature": 0.4, "response_format": {"type": "json_object"}}, {"response_format": {"type": "json_object"}}, {}]
    for extra in ladder:
        status, hdrs, text = _post(f"{p['base_url']}/chat/completions", {**body, **extra}, headers, timeout, key)
        if status not in (400, 422):
            break
    if status != 200:
        raise ProviderError(status, _retry_after(hdrs), _redact(text, key))
    try:
        data = json.loads(text)
        content = data["choices"][0]["message"].get("content")
        usage = data.get("usage") or {}
        out = ai._parse(content)
    except Exception:  # noqa: BLE001 - whatever is wrong with the reply, it is not usable JSON
        raise NotJSON("the reply was not usable JSON")
    return out, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def send_gemini(p, m, key, prompt, schema, timeout):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json", "responseSchema": schema}}
    status, hdrs, text = _post(f"{p['base_url']}/{m['id']}:generateContent", body, {"x-goog-api-key": key}, timeout, key)
    if status != 200:
        raise ProviderError(status, _retry_after(hdrs), _redact(text, key))
    try:
        data = json.loads(text)
        answer = json.loads("".join(x.get("text", "") for x in data["candidates"][0]["content"]["parts"]))
        u = data.get("usageMetadata", {})
        sent = int(u.get("promptTokenCount") or 0)
        return answer, sent, max(0, int(u.get("totalTokenCount") or 0) - sent)
    except Exception:  # noqa: BLE001
        raise NotJSON("the reply was not usable JSON")


TRANSPORTS = {"openai": send_openai, "gemini": send_gemini}


# ---------------------------------------------------------------- the pool
class Pool:
    def __init__(self, catalog, ledger, settings, clock=time.time, sleep=time.sleep, transports=None,
                 max_wait=75.0, total_wait=150.0, timeout=120.0, est_out=1500):
        self.catalog, self.ledger, self.settings = catalog, ledger, settings
        self.clock, self.sleep = clock, sleep
        self.transports = dict(TRANSPORTS if transports is None else transports)
        self.max_wait, self.total_wait, self.timeout, self.est_out = max_wait, total_wait, timeout, est_out
        self._tl = threading.local()

    # ---------------------------------------------------------- who could answer
    def _models(self, p) -> list:
        if p["local"]:
            return [{"id": mid, "ctx": 8192, "json_mode": "object", "tier": 3, "limits": {"rpm": None, "rpd": None, "tpm": None, "tpd": None, "reset": "utc"}}
                    for mid in self.settings.local_models()]
        return p["models"]

    def _resolved(self, p) -> "dict | None":
        """The service with {account_id} filled in, or None when a needed account id is missing."""
        if "{account_id}" not in p["base_url"]:
            return p
        acc = self.settings.account_id(p)
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", acc):
            return None
        return {**p, "base_url": p["base_url"].replace("{account_id}", acc)}

    def _privacy_reason(self, p, now) -> str:
        if p["local"]:
            return ""
        mode, trains = self.settings.privacy(), p["privacy"]["trains_on_data"]
        if mode == "any":
            return ""
        if mode == "relaxed":
            return "" if trains in ("no", "depends", "unknown") else "its data terms allow training on your text"
        if trains != "no":
            return "its data terms do not clearly say it keeps your text out of training"
        seen = p["privacy"]["verified_on"]
        if not seen or (datetime.date.fromtimestamp(now) - seen).days > FRESH_DAYS:
            return f"its data terms were not checked in the last {FRESH_DAYS} days"
        return ""

    def explain(self, est_in, est_out, now=None) -> list:
        """One row per service/model pair: whether it may be used now, and if not why, and how long to wait
        (None when waiting would not help, for example no key)."""
        now = self.clock() if now is None else now
        rows = []
        for index, p0 in enumerate(self.catalog.providers()):
            def row(m, ok, reason="", wait=None, headroom=1.0, fail_rate=0.0, p=p0, tier=None):
                rows.append({"provider": p["id"], "label": p["label"], "model": m["id"] if m else "", "ok": ok, "reason": reason,
                             "wait": wait, "tier": tier if tier is not None else (m["tier"] if m else 3), "headroom": headroom,
                             "fail_rate": fail_rate, "index": index, "p": p, "m": m})
            models = self._models(p0)
            if not self.settings.enabled(p0):
                row(None, False, "switched off"); continue
            sp = self.ledger.state(p0["id"])
            if sp["disabled"]:
                row(None, False, f"switched off: {sp['disabled']}"); continue
            key = self.settings.key(p0)
            if p0["needs_key"] and not p0["local"] and not key:
                row(None, False, "no key saved"); continue
            p = self._resolved(p0)
            if p is None:
                row(None, False, "its account id is not saved"); continue
            bad = self._privacy_reason(p, now)
            if bad:
                row(None, False, f"left out by the privacy setting: {bad}"); continue
            if not models:
                row(None, False, "no model chosen" if p["local"] else "no models listed"); continue
            for m in models:
                def r(ok, reason="", wait=None, headroom=1.0, fail_rate=0.0, m=m, p=p):
                    rows.append({"provider": p["id"], "label": p["label"], "model": m["id"], "ok": ok, "reason": reason, "wait": wait,
                                 "tier": m["tier"], "headroom": headroom, "fail_rate": fail_rate, "index": index, "p": p, "m": m})
                sm = self.ledger.state(p["id"], m["id"])
                if sm["disabled"]:
                    r(False, f"model switched off: {sm['disabled']}"); continue
                if m["json_mode"] == "none":
                    r(False, "this model cannot answer in JSON"); continue
                need = est_in + est_out
                if need > 0.9 * m["ctx"]:
                    r(False, "the request is too big for this model"); continue
                until = max(sp["cooldown_until"], sm["cooldown_until"])
                if until > now:
                    r(False, f"cooling down for {int(math.ceil(until - now))} s", wait=until - now); continue
                lim, reset = m["limits"], m["limits"]["reset"]
                mk, dk = "m" + str(int(now // 60)), _day_key(reset, now)
                got = self.ledger.used(p["id"], m["id"], [mk, dk])
                (rm, tm), (rd, td) = got[mk], got[dk]
                to_minute, to_reset = 60 - (now % 60) + 0.1, _day_start(reset, now) + 86400 - now + 1
                waits, shares = [], []
                if lim["rpm"]:
                    waits += [to_minute] if rm + 1 > _eff(lim["rpm"]) else []
                    shares.append(1 - rm / _eff(lim["rpm"]))
                if lim["tpm"]:
                    if need > _eff(lim["tpm"]):
                        r(False, "the request is bigger than this model's per-minute allowance"); continue
                    waits += [to_minute] if tm + need > _eff(lim["tpm"]) else []
                    shares.append(1 - tm / _eff(lim["tpm"]))
                if lim["rpd"]:
                    waits += [to_reset] if rd + 1 > _eff(lim["rpd"]) else []
                    shares.append(1 - rd / _eff(lim["rpd"]))
                if lim["tpd"]:
                    waits += [to_reset] if td + need > _eff(lim["tpd"]) else []
                    shares.append(1 - td / _eff(lim["tpd"]))
                total = sm["ok_total"] + sm["fail_total"] + sp["ok_total"] + sp["fail_total"]
                rate = (sm["fail_total"] + sp["fail_total"]) / total if total else 0.0
                if waits:
                    r(False, "this minute's or today's allowance is used up", wait=max(waits)); continue
                r(True, headroom=max(0.0, min(shares)) if shares else 1.0, fail_rate=rate)
        return rows

    @staticmethod
    def _order(row):
        return (row["tier"], -round(row["headroom"], 2), round(row["fail_rate"], 2), row["index"])

    def ready(self) -> bool:
        """Is anything set up that could answer (a key and so on), whether or not it is cooling down right now?"""
        return any(r["ok"] or r["wait"] is not None for r in self.explain(100, 100))

    # ---------------------------------------------------------- one request
    def complete_json(self, prompt, schema, purpose="AI call"):
        """Returns (answer, tokens in, tokens out). Raises PoolExhausted when no service can answer."""
        est_in, est_out = estimate_tokens(prompt, schema), self.est_out
        started, tried = self.clock(), set()
        for _ in range(24):
            now = self.clock()
            everyone = self.explain(est_in, est_out, now)
            rows = [r for r in everyone if (r["provider"], r["model"]) not in tried]
            usable = [r for r in rows if r["ok"]]
            if not usable:
                waits = [r["wait"] for r in rows if r["wait"] is not None]
                if waits and min(waits) <= self.max_wait and (now - started) + min(waits) <= self.total_wait:
                    self.sleep(min(waits) + 0.05)
                    continue
                raise PoolExhausted(self._why(everyone, tried))
            try:
                return self._call(min(usable, key=self._order), prompt, schema, est_in, est_out, tried)
            except _Retry:
                continue
        raise PoolExhausted("The free AI services kept failing, so none could be used for this request.")

    def _call(self, row, prompt, schema, est_in, est_out, tried):
        p, m = row["p"], row["m"]
        pid, mid, key = p["id"], m["id"], self.settings.key(p)
        now = self.clock()
        buckets = ["m" + str(int(now // 60)), _day_key(m["limits"]["reset"], now)]
        send = self.transports[p["adapter"]]
        ask, why = prompt, ""
        for second_try in (False, True):
            reserve = est_in + est_out
            self.ledger.add(pid, mid, buckets, req=1, tokens=reserve)       # counted before sending, so threads in step do not overshoot
            unusable = None
            try:
                raw, tin, tout = send(p, m, key, ask, schema, self.timeout)
            except NotJSON as e:                              # answered, but not with JSON: handled below like a wrong shape
                raw, tin, tout, unusable = None, 0, 0, e
            except ProviderError as e:
                self._on_error(p, m, e, tried)
                raise _Retry()
            except Exception:  # noqa: BLE001 - a broken transport counts as an outage of this service
                self._on_error(p, m, ProviderError(None, None, "", "network"), tried)
                raise _Retry()
            try:
                if unusable is not None or raw is None:
                    raise unusable or NotJSON("empty reply")
                out, dropped = jsoncheck.clean(raw, schema)
            except (NotJSON, jsoncheck.BadAnswer) as e:
                self.ledger.add(pid, mid, buckets, req=0, tokens=(tin + tout) - reserve if (tin or tout) else 0)
                why = str(e)
                self.ledger.add_to(pid, mid, schema_fail=1)
                if not second_try:
                    ask = prompt + REPAIR_NOTE.format(why=why[:120])
                    continue
                self.ledger.add_to(pid, mid, fail_total=1)
                tried.add((pid, mid))
                raise _Retry()
            if not (tin or tout):
                tin, tout = est_in, min(est_out, int(len(json.dumps(out)) / 3.5) + 1)
            self.ledger.add(pid, mid, buckets, req=0, tokens=(tin + tout) - reserve)
            self.ledger.add_to(pid, mid, ok_total=1)
            self.ledger.update(pid, mid, rate_hits=0)
            self.ledger.update(pid, "", fails=0)
            self._tl.route = f"{pid}/{mid}"
            self._tl.dropped = dropped
            return out, tin, tout
        raise _Retry()

    def _on_error(self, p, m, e, tried):
        """Remember what a failed request tells us about this service or model."""
        pid, mid, now, s = p["id"], m["id"], self.clock(), e.status
        self.ledger.add_to(pid, mid, fail_total=1)
        if s in (401, 403):
            self.ledger.update(pid, "", disabled=f"the key was refused (status {s}); save a new key to switch it on again")
            tried.add((pid, mid))
        elif s == 429:                                    # busy: not an outage, so the same model may be tried again after a wait
            hits = self.ledger.state(pid, mid)["rate_hits"]
            wait = e.retry_after if e.retry_after is not None else min(900.0, 30.0 * 2 ** hits)
            until = now + min(wait, 86400.0)
            if DAILY.search(e.body or ""):
                until = max(until, _day_start(m["limits"]["reset"], now) + 86400)
            self.ledger.update(pid, mid, cooldown_until=until, rate_hits=hits + 1)
        elif s in (404, 410):
            self.ledger.update(pid, mid, disabled=f"not found (status {s}); check the model name")
            tried.add((pid, mid))
        elif s == 413:
            tried.add((pid, mid))
        elif s is None or s >= 500 or s == 408:
            fails = self.ledger.state(pid)["fails"] + 1
            self.ledger.update(pid, "", fails=fails, cooldown_until=now + (600 if fails >= 3 else 60))
            tried.add((pid, mid))
        else:                                             # 400, 422 and other refusals of this particular request
            self.ledger.add_to(pid, mid, schema_fail=1)
            self.ledger.update(pid, mid, cooldown_until=now + 120)
            tried.add((pid, mid))

    @staticmethod
    def _why(rows, tried=()) -> str:
        seen, parts = set(), []
        for r in sorted(rows, key=lambda r: (r["index"], r["model"])):
            if r["provider"] in seen:
                continue
            seen.add(r["provider"])
            failed = (r["provider"], r["model"]) in tried
            parts.append(f"{r['label']}: {'did not give a usable answer to this request' if failed else (r['reason'] or 'not available')}")
        text = "; ".join(parts) or "no AI service is set up"
        return ("No free AI service can answer right now (" + text + ").")[:420]

    # ---------------------------------------------------------- for the pages and the consent preview
    def last_route(self) -> str:
        return getattr(self._tl, "route", "")

    def preview(self, prompt, schema=None) -> dict:
        """What would be sent, and to whom, before anything is sent."""
        est = estimate_tokens(prompt, schema)
        rows = sorted((r for r in self.explain(est, self.est_out) if r["ok"] or r["wait"] is not None), key=self._order)
        return {"privacy": self.settings.privacy(), "chars": len(prompt), "est_tokens": est,
                "sends_to": [{"provider": r["label"], "model": r["model"], "local": r["p"]["local"],
                              "trains_on_data": r["p"]["privacy"]["trains_on_data"]} for r in rows],
                "leaves_this_computer": any(not r["p"]["local"] for r in rows)}

    def status(self) -> list:
        """One entry per service for a settings page. Keys are never included, only the last four letters."""
        out, now = [], self.clock()
        rows = self.explain(100, 100, now)
        for p in self.catalog.providers():
            mine = [r for r in rows if r["provider"] == p["id"]]
            key = self.settings.key(p)
            state = self.ledger.state(p["id"])
            out.append({"id": p["id"], "label": p["label"], "local": p["local"], "enabled": self.settings.enabled(p),
                        "needs_key": p["needs_key"] and not p["local"], "has_key": bool(key), "key_hint": key[-4:] if len(key) >= 12 else "",
                        "disabled": state["disabled"], "trains_on_data": p["privacy"]["trains_on_data"], "signup_url": p["signup_url"],
                        "usable": any(r["ok"] for r in mine), "waiting": any((not r["ok"]) and r["wait"] is not None for r in mine),
                        "reason": next((r["reason"] for r in mine if not r["ok"]), ""),
                        "models": [{"id": r["model"], "ok": r["ok"], "reason": r["reason"]} for r in mine if r["model"]]})
        return out

    # ---------------------------------------------------------- changes from the settings page
    def save_key(self, provider_id, key):
        p = next((x for x in self.catalog.providers() if x["id"] == provider_id), None)
        key = str(key or "").strip()
        if not p:
            raise ValueError("Choose one of the services in the list.")
        if key and not re.fullmatch(r"\S{8,400}", key):
            raise ValueError("That does not look like a key.")
        self.settings.change("keys", provider_id, key)
        self.ledger.update(provider_id, "", disabled="", fails=0, cooldown_until=0.0)     # a new key gives the service a fresh start

    def set_enabled(self, provider_id, on: bool):
        if not any(x["id"] == provider_id for x in self.catalog.providers()):
            raise ValueError("Choose one of the services in the list.")
        self.settings.change("enabled", provider_id, bool(on))

    def set_privacy(self, mode):
        if mode not in PRIVACY_MODES:
            raise ValueError("Privacy is strict, relaxed or any.")
        self.settings.change(None, "privacy", mode)


# ---------------------------------------------------------------- the one pool of this app
_pool = None
_make_lock = threading.Lock()


def get() -> Pool:
    global _pool
    with _make_lock:
        if _pool is None:
            from . import config
            _pool = Pool(Catalog(Path(__file__).with_name("providers.default.json"), config.DATA_DIR / "providers.json"),
                         Ledger(config.DATA_DIR / "ai_ledger.db"), Settings(config.DATA_DIR / "pool.json"))
        return _pool


def ready() -> bool:
    return get().ready()


def complete_json(prompt, schema, purpose="AI call"):
    return get().complete_json(prompt, schema, purpose)


def route() -> str:
    """"service/model" that answered last on this thread, or "" when the pool was not used."""
    return get().last_route() if _pool else ""
