"""Run a PeakCut test file with the network-only dependencies stubbed, because pip installs are blocked in this container.
NOT a substitute for the real suite: only for tests that never touch the stubbed parts."""
import sys, runpy, types
from unittest.mock import MagicMock
for name in ("httpx", "sqlalchemy", "sqlalchemy.event", "soundfile", "psycopg", "yt_dlp", "sherpa_onnx", "fastapi", "fastapi.testclient", "fastapi.concurrency", "fastapi.responses", "uvicorn"):
    sys.modules[name] = MagicMock()
sys.path.insert(0, ".")
runpy.run_path(sys.argv[1], run_name="__main__")
