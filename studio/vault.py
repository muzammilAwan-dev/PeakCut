"""Keeps saved keys out of plain sight in the data folder.

On Windows a key is sealed with the signed-in user's own Windows login (DPAPI): another Windows user, a backup, or a
copied data folder cannot read it. Every key is opened again straight after sealing, and if that does not give the same key
it is kept as plain text instead, so a key is never lost to this. On other systems (and with PEAKCUT_VAULT=off) it stays
plain text in a file only the owner can open. Moving the data folder to another computer: sealed keys cannot be opened
there, so the dashboard shows the service as having no key and the key is pasted again once."""
import base64
import os

from . import branding

PREFIX = "dpapi:"


def _enabled() -> bool:
    return os.name == "nt" and str(branding.env("VAULT", "on")).strip().lower() not in ("off", "0", "no", "false")


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows could not do that")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def seal(text: str, backend=None) -> str:
    """What to write to disk for this key."""
    text = str(text or "")
    if not text or text.startswith(PREFIX):
        return text
    use = backend or (_dpapi if _enabled() else None)
    if use is None:
        return text
    try:
        sealed = PREFIX + base64.b64encode(use(text.encode("utf-8"), True)).decode("ascii")
        return sealed if unseal(sealed, backend) == text else text
    except Exception:  # noqa: BLE001 - never lose a key to the vault
        return text


def unseal(stored: str, backend=None) -> str:
    """The key itself, or "" when it was sealed on another computer or account."""
    stored = str(stored or "")
    if not stored.startswith(PREFIX):
        return stored
    use = backend or (_dpapi if os.name == "nt" else None)
    if use is None:
        return ""
    try:
        return use(base64.b64decode(stored[len(PREFIX):]), False).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


def is_sealed(stored: str) -> bool:
    return str(stored or "").startswith(PREFIX)
