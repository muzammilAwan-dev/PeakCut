"""The app's name and where it lives, in one place.

New code reads the name, the repository, the copyright line, the data folder name and the setting prefix from here
instead of writing them out. That way the later rename (slice S-Brand) changes this one file, not fifty.

Nothing here imports another ViralCut module, so any file can use it, and it needs no packages.

Settings keep working under their old names: `env("AI_KEY")` first looks for `<ENV_PREFIX>_AI_KEY` and then for the
old `PEAKCUT_AI_KEY`."""
import os

APP_NAME = "ViralCut"
COMPANY = "Amfaiz"
COPYRIGHT = "Copyright (c) 2026 Amfaiz"

# where updates come from and where the dashboard's "Star on GitHub" button goes: this fork only
REPO = "muzammilAwan-dev/PeakCut"
REPO_URL = f"https://github.com/{REPO}"

DATA_DIR_NAME = "data"            # lives beside the app, so a copied folder keeps its projects and settings
ENV_PREFIX = "VIRALCUT"           # the prefix new settings are written with
LEGACY_ENV_PREFIX = "PEAKCUT"     # the old prefix, always still understood


def env_names(suffix: str) -> list:
    """Every variable name that sets this option, newest name first, without repeats."""
    names = [f"{ENV_PREFIX}_{suffix}", f"{LEGACY_ENV_PREFIX}_{suffix}"]
    return [n for i, n in enumerate(names) if n not in names[:i]]


def env(suffix: str, default=None):
    """The value of one setting by its short name, e.g. env("AI_KEY"). The new name wins over the old one.
    An empty value counts as not set, the same way the rest of the app treats it."""
    for name in env_names(suffix):
        v = os.environ.get(name)
        if v not in (None, ""):
            return v
    return default
