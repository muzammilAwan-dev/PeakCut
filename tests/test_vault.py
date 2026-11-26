"""Sealed keys: round trip, never lost, other computer, and that the files on disk hold no plain key. A stand-in for
Windows' sealing is used here; the real Windows call is checked on Windows by the key-save check on the dashboard."""
import json, os, sys, tempfile
from pathlib import Path
DATA = Path(tempfile.mkdtemp(prefix="pc-vault-"))
os.environ["PEAKCUT_DATA"] = str(DATA)
os.environ.update(DATABASE_URL="", PEAKCUT_ACCOUNTS="0", PEAKCUT_BOOTSTRAP="0", PEAKCUT_AI_PROVIDER="", PEAKCUT_AI_KEY="")
sys.path.insert(0, ".")
from studio import ai, pool, vault
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)

def fake(data: bytes, protect: bool) -> bytes:            # reversible, and unreadable by eye
    return bytes(b ^ 0x5A for b in data[::-1]) if protect else bytes(b ^ 0x5A for b in data)[::-1]
KEY = "gsk_abcdef1234567890"
sealed = vault.seal(KEY, fake)
check("seal: not readable as the key, marked as sealed", (KEY in sealed, vault.is_sealed(sealed)), (False, True))
check("unseal: the same key comes back", vault.unseal(sealed, fake), KEY)
check("seal twice does not seal again", vault.seal(sealed, fake), sealed)
check("a plain stored key (older file) is still read", vault.unseal(KEY, fake), KEY)
check("empty stays empty", (vault.seal("", fake), vault.unseal("", fake)), ("", ""))
def broken(data, protect): raise OSError("no")
check("if sealing fails, the key is kept as it was (never lost)", vault.seal(KEY, broken), KEY)
def lossy(data, protect): return data[:-1] if not protect else data
check("if it would not open again, the key is kept as it was", vault.seal(KEY, lossy), KEY)
check("sealed on another computer: no key, no crash", vault.unseal(sealed, broken), "")
check("a damaged sealed value: no key, no crash", vault.unseal("dpapi:%%%not-base64", fake), "")
check("on this system (not Windows) sealing is off and the key stays plain", (os.name == "nt") or (vault.seal(KEY) == KEY), True)

# through the real stores, with the stand-in forced on
vault_seal, vault_unseal = vault.seal, vault.unseal
vault.seal = lambda t, backend=None: vault_seal(t, fake)
vault.unseal = lambda s, backend=None: vault_unseal(s, fake)
pl = pool.get()
pid = pl.catalog.providers()[0]["id"]
pl.save_key(pid, KEY)
raw = (DATA / "pool.json").read_text(encoding="utf-8")
check("pool: the file on disk holds no plain key", (KEY in raw, "dpapi:" in raw), (False, True))
p0 = next(x for x in pl.catalog.providers() if x["id"] == pid)
check("pool: the key is read back plain for use", pl.settings.key(p0), KEY)
check("pool: the dashboard still shows the last four", next(x for x in pl.status() if x["id"] == pid)["key_hint"], KEY[-4:])
ai.save("openai", ["gpt-x"], "", KEY + "AI")
raw = (DATA / "ai.json").read_text(encoding="utf-8")
check("ai: the file on disk holds no plain key", (KEY in raw, "dpapi:" in raw), (False, True))
check("ai: read back plain", ai.current()["key"], KEY + "AI")
check("ai: saving again without a new key keeps the key", (ai.save("openai", ["gpt-y"])["has_key"], ai.current()["key"]), (True, KEY + "AI"))
vault.unseal = lambda s, backend=None: vault_unseal(s, broken)       # "moved to another computer"
check("moved data: the service just has no key until it is pasted again", (pl.settings.key(p0), ai.current()["key"]), ("", ""))
print("ALL PASSED" if not fails else f"FAILED: {fails}"); sys.exit(1 if fails else 0)
