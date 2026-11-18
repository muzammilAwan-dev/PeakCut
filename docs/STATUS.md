# Status (update at the end of every slice)

Branch: `develop`. Last updated: 2026-11-17 (S0, S1 and the S2 backend built in an offline sandbox; see the notes below).

| Slice | Scope (short) | State | Tag |
| --- | --- | --- | --- |
| Task 1 | Audit (`docs/AUDIT.md`) | done | n/a |
| S0 | Fork hygiene, `studio/branding.py`, CI, VERSION file, update check on the fork | **built**, tests pass in the sandbox; needs one run of `python tests/run.py` on Windows | no tag (no git here) |
| S1 | Engine bootstrap: ffmpeg, deno, yt-dlp into `bin/` on PATH | **built for ffmpeg and Deno** (54 checks); pins empty until `tools/make_pins.py` is run; yt-dlp nightly not done (S1b) | |
| S2 | Pool v0: `complete_json`, `ai_ledger`, cooldowns, privacy toggle | **backend built** (87 checks against a mock AI server); settings page and consent dialog not built (S2b) | |
| S1b | yt-dlp nightly + daily check, JS runtime proof (needs internet) | todo | |
| S2b | Pool settings page (keys, privacy, status), consent preview dialog, capability probe on key save | todo | |
| S3 | Portable build (embeddable Python, `data/` beside the app, launcher) | todo | |
| S4 | Remaining gaps only: LLM cache, revision key, cancel/supervisor, transactional output | todo | |
| S5 | Eval harness | todo | |
| S6 | Quality: per-item validation (fixes silent window drop), block overlap, candidate scoring | todo | |
| S6d | Hindi/Urdu pack | todo | |
| S6e | Manual editing, review queue, undo | todo | |
| S6f | Face reframing (default-off) | todo | |
| S6b | Optional extras | todo | |
| S7 | Security: key vault for 3 stores, LLM-output validation | todo | |
| S8 | Browser extension | todo | |
| S-Brand | Rename and rebrand | todo | |
| Release | Clean-VM test, zip build, README, merge notes | todo | |

## Baseline
**First Windows attempt (2026-11-17): did not run.** The machine has Python 3.14.6; `pip install -r requirements.txt` failed on numpy 2.2.6 (no 3.14 wheel, no C compiler). Fix: `tools\windows-baseline.bat` now finds a Python that fits (or offers to install one) by itself, so just run it again. ffmpeg was found at `C:\ffmpeg\bin`.

**Windows baseline (2026-11-18, Win 11, Python 3.13.17):** all test files passed except `tests/test_claude_pack.py`, which hit two Windows-only bugs: `join` deleted the payload while still open (WinError 32), and the test compared `/` with `\` paths. Both fixed 2026-11-18 (`tools/claude_pack.py`, `tests/test_claude_pack.py`); passes on Linux, **re-verify on Windows**. The log stopped at the pyenv and fork tests, so confirm they ran.

**Sandbox, real suite (2026-11-18, Linux, Python 3.13, wheels from `claude-pack`):** `python tests/run.py` -> 16 files, 510 checks, **all passed**, no skips. This includes `tests/test_ai.py` and the server half of `tests/test_updates.py`, previously unrun. Warning only: starlette says `httpx` in `TestClient` is deprecated (prefers `httpx2`); harmless now.

To record the real Windows baseline: run `tools\windows-baseline.bat` and attach `baseline-windows.txt`, or paste the output of `python tests/run.py` here.

## Open questions for the owner
- Product name candidates for S-Brand (2 to 3).
- Path of the extracted FuseClip reference folder (kept outside the repo).

## Known UNVERIFIED (resolve by experiment before relying on them)
- **The whole suite on Windows** after S0 to S2 (see Baseline). Passes on Linux.
- `studio/pins.json` is empty: ffmpeg and Deno addresses and SHA-256 values must be filled with `tools/make_pins.py` and compared with the publishers' checksum files.
- The pool catalog (`studio/providers.default.json`): every limit, model id, context size and data-terms statement was copied from PLAN section 4.1 and not re-checked; Cloudflare's OpenAI-compatible path, model id and context size are guesses flagged inside the file.
- A first-run on a clean Windows machine: does the background fetch finish before the first job needs ffmpeg? (`bootstrap.wait()` exists; no job calls it yet. S3.)
- CI (`.github/workflows/ci.yml`) has never run on GitHub; Linux may need ffmpeg installed.
- `yt-dlp-ejs` present and Deno found on PATH in a clean venv (S1, first step).
- Whisper large-v3-turbo speed on 4 cores and its peak RAM (S6d benchmark).
- YouTube auto-captions available for Urdu (live check).
- Live clipping real-time factor on a 4-core machine (D19).
- Free-provider JSON quality on Hindi and Urdu transcripts (S5 eval).
- Whether unsigned downloads trigger Windows warnings (decide before public release).
- sherpa-onnx native packaging on a clean Windows machine (S3 gate).
