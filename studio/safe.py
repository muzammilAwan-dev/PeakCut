"""Small helpers for what is safe to show a user."""
import re

_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]*[\\/][^\s'\"]+")


_COLOUR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[[0-9;]{1,8}m")      # the colour codes yt-dlp puts around "ERROR:"


def friendly(e, limit=600) -> str:
    """An error message for the user: trimmed, with colour codes and any server file paths removed."""
    return _PATH.sub("[file]", _COLOUR.sub("", str(e))[-limit:])

