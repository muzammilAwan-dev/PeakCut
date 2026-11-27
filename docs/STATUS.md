# Status (update at the end of every slice)

Branch: `develop`. Last updated: 2026-11-19 (everything that can be built and tested offline is built; the real-test list is `docs/RELEASE_TEST.md`).

| Slice | Scope (short) | State |
| --- | --- | --- |
| Task 1 | Audit (`docs/AUDIT.md`) | done |
| S0 | Fork hygiene, branding, CI, VERSION, update check | done (Windows suite green) |
| S1 | Engine bootstrap: ffmpeg, Deno | built; pins filled (2026-11-26); first-run fetch not yet tried |
| S1b | yt-dlp nightly + daily check | **not built** (needs internet to verify; yt-dlp is pinned in `requirements.txt`) |
| S2 | Pool backend | done (Windows green) |
| S2b | Pool settings tab, consent dialog, key-save check | **built**, checked in a real browser; real providers UNVERIFIED |
| S3 | Portable build + launcher | **built, never run**: `python tools/build_portable.py` on Windows |
| S4 | Answer cache, clip fingerprint, safe output, Stop button, supervisor | **built**, tested with real ffmpeg |
| S5 | Eval harness (`tools/eval.py`) | built; needs a labelled set (`docs/EVAL.md`) |
| S6 | Quality: speech+loudness fallback, 60 s overlap between parts | built; candidate pre-scoring for the AI **not built** (needs eval data first) |
| S6d | Hindi/Urdu speech model | **not built**: needs a second speech model with word timings, which cannot be checked offline. Roman-letter captions already exist |
| S6e | Undo one edit | built (one step, swaps with the edit). Review queue not built |
| S6f | Follow-the-face layout | built, optional (`requirements-optional.txt`), real face test passes with OpenCV |
| S6b | Optional extras | not built |
| S7 | Key vault (Windows DPAPI) | built; real Windows sealing UNVERIFIED |
| S8 | Browser extension "Clip this" | built; never loaded into a real browser |
| S9 | Activity log + "Find working models" | **built** (sandbox-tested incl. real browser); real providers UNVERIFIED |
| S-Brand | Name ViralCut, new logos, `VIRALCUT_*` settings | done (the GitHub repository name is unchanged) |
| Release | Clean-VM test | **owner**: follow `docs/RELEASE_TEST.md` |

Sandbox suite: all passed. Windows suite 2026-11-26: all passed except 2 key-file checks that did not expect Windows key sealing (test fixed in rev 12).

## Baseline
**First Windows attempt (2026-11-17): did not run.** The machine has Python 3.14.6; `pip install -r requirements.txt` failed on numpy 2.2.6 (no 3.14 wheel, no C compiler). Fix: `tools\windows-baseline.bat` now finds a Python that fits (or offers to install one) by itself, so just run it again. ffmpeg was found at `C:\ffmpeg\bin`.

**Windows baseline (2026-11-18, Win 11, Python 3.13.17 picked by `tools/pyenv.py`): all 16 test files pass, exit 0** (after fixing two Windows-only bugs in `tools/claude_pack.py` / its test). Only a harmless starlette warning (`httpx2`).

**Sandbox, real suite (2026-11-18, Linux, Python 3.13, wheels from `claude-pack`):** `python tests/run.py` -> 16 files, 510 checks, **all passed**, no skips. This includes `tests/test_ai.py` and the server half of `tests/test_updates.py`, previously unrun. Warning only: starlette says `httpx` in `TestClient` is deprecated (prefers `httpx2`); harmless now.


## Open questions for the owner
- Trademark and domain check for ViralCut.
- Path of the extracted FuseClip reference folder (kept outside the repo; never opened).

## Known UNVERIFIED (resolve by experiment before relying on them)
- `studio/pins.json` filled 2026-11-26 on Windows (`tools/fill_pins.py`): ffmpeg autobuild-2026-11-25-12-41 (hash matches the publisher's), Deno 2.9.8 (no publisher hash; trusted on first download). Not yet used by a real first-run fetch.
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
- Every free provider: limits, model ids, the check request (`GET /models` and the 3 JSON-mode tries) and Cloudflare's path.
- `tools/build_portable.py` and `tools/fill_pins.py` on Windows (asset names of the BtbN and Deno releases are assumed from memory).
- Windows key sealing (`studio/vault.py`); moving `data/` to another computer asks for keys again.
- Browser extension in a real Chrome or Edge; with sign-in switched on (`PEAKCUT_ACCOUNTS=1`) the extension door is untested.
- Follow-the-face quality on real streams (the built-in detector sees front-facing faces only).
- A stuck video is stopped after 20 minutes without any change; a clip being cut at that moment finishes first.
