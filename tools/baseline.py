"""Runs the whole test suite on this computer and saves everything it prints into baseline-windows.txt.

    python tools/baseline.py [--yes] [--out FILE]

It first makes sure a suitable Python and virtual environment exist (tools/pyenv.py decides what is suitable, so no
version is written down here), then runs tests/run.py inside it. The text file is what you send to Claude.
Standard library only; runs on any Python 3.8 or newer."""
import argparse
import datetime
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pyenv  # noqa: E402

ROOT = pyenv.ROOT


def tools_report(say):
    ffmpeg = shutil.which("ffmpeg")
    say(f"ffmpeg: {ffmpeg or 'NOT FOUND on the PATH (the app can fetch one into bin/ once pins are filled in)'}")
    if ffmpeg:
        try:
            out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=60).stdout
            say("libx264 encoder: " + ("yes" if "libx264" in out else "NO (clips cannot be made with this ffmpeg)"))
        except (OSError, subprocess.SubprocessError) as e:
            say(f"ffmpeg did not run: {e}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="install Python without asking if none suitable is found")
    ap.add_argument("--out", default=str(ROOT / "baseline-windows.txt"))
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    with open(a.out, "w", encoding="utf-8") as log:
        def say(line=""):
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
        say(f"Baseline on {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        say(f"{platform.platform()}  |  running tools with Python {platform.python_version()}")
        try:
            vpy = pyenv.ensure(a.yes, say)
        except (RuntimeError, subprocess.CalledProcessError) as e:
            say(f"\nProblem: {e}")
            say("Exit code 1")
            return 1
        say(f"Environment: {vpy}")
        tools_report(say)
        say("\nRunning the tests...")
        rc = pyenv.run([vpy, "tests/run.py"], say, cwd=ROOT)
        say(f"Exit code {rc}")
        return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
