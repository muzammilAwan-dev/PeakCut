# memory.md (rev 15, 2026-11-27, current state only)

## Project
- Fork `muzammilAwan-dev/PeakCut` (company Amfaiz), branch `develop` only. Product name: **ViralCut** (repo name unchanged).
- Goal: portable Windows app (unzip and run, 4+ cores, 8 GB), free AI pool that never hard-fails, better clip choice, edit tools, optional face follow.
- Owner flow: I finish all slices, owner commits, then we do the real Windows test together (`docs/RELEASE_TEST.md`).

## Owner preferences
- Terse; no preamble/recap/emojis. Finish each slice with 5 lines: changed / how to test / unverified / needed from owner. Max 3 questions, only if blocked.
- Deliver ONE overwrite zip. Scripts detect, never hardcode. One-line commit command.
- Re-send this file after every change.

## Rules (CLAUDE.md / AGENTS.md)
- Additive; each slice has a key-free test; run `python tests/run.py` before and after.
- UNVERIFIED = small experiment or explicit flag; never invent versions/limits/hashes/APIs.
- Pin + SHA-256 downloads; no bundled GPL ffmpeg; short paths; user data only in `data/`.
- No proprietary code/prompts/assets; never name the upstream author. Untrusted: transcripts, LLM output, filenames, downloads.
- Do-not-build list: hosted proxy, key farming, WPF launcher, VLM captions, fine-tuning, bandit router, React rewrite, more accounts/Postgres/admin, mobile app, cloud STT, paid catalog, social posting.

## Slice state
- Done + tested in sandbox (25 files, 715 checks green): S2b pool tab, S3 portable build, S4 cache/fingerprint/safe write/Stop/supervisor, S5 eval kit, S6 transcript+loudness fallback and 60 s overlap, S6e undo, S6f face follow (optional), S7 DPAPI vault, S8 extension, S-Brand ViralCut.
- Done earlier and Windows-green (rev 8): S0, S2.
- Deferred: S6d Hindi/Urdu ASR, S1b yt-dlp nightly/pins (needs internet; run `tools/fill_pins.py`), LLM candidate pre-scoring (needs eval data), S6b extras.

## UNVERIFIED
- New work has never run on Windows (last Windows-green = rev 8).
- Real providers (Groq/Cloudflare/Gemini): limits, probe, JSON modes.
- portable build; first-run ffmpeg fetch; DPAPI (seen working on owner's Windows 11 2026-11-26); extension in real Chrome (and with accounts ON); face quality on real streams.

## Environment
- Sandbox: PyPI only. Python 3.13 (3.14 unusable). Owner: Win10 LTSC/11, Git Bash, 16 GB, `E:\Github Projects\PeakCut`, ffmpeg `C:\ffmpeg\bin`, chat upload cap 30 MB/file.
- Sandbox helpers: `/home/claude/mkzip.py N` builds the overwrite zip; venv `/home/claude/venv`.

## Windows results
- 2026-11-26 baseline on rev11: all green except 2 tests reading the key file as plain text (DPAPI sealed it, so DPAPI works on this PC). Fixed in rev12 (tests unseal). Pins filled (ffmpeg hash matched publisher; Deno trusted on first download).
- Python: `python` is 3.14 (unusable); run tests via `tools\windows-baseline.bat` (picks 3.13).

- Real test: Gemini free key got 404 (gemini-2.5-flash closed to new projects). rev13 switches the catalog to 3.5-flash-lite / 3.8-flash / 3.1-flash-lite and the key check skips 404 models. Free-tier access of those ids UNVERIFIED until owner re-tests. Optional face package installed in `.venv` (use `.venv\Scripts\python.exe`).

- rev14 (S9): `studio/applog.py` log file `data/logs/viralcut.log`; `Pool.discover` + `/api/pool/discover` + button "Find working models" (ranks, tests best 6, pool uses only working); `/api/log`, `/api/log/download`; Settings shows log. Owner asked for it after Gemini 404.

- rev15 (S10): `studio/trace.py` (trace/ per video); option `mode` stream|podcast (brain.build_prompt); per-row Settings + Make again in the composer; draft (480p) then `/api/jobs/{id}/final` (jobs.request_final/finalize_clip, media.audio_window). UNVERIFIED: yt-dlp `download_range` on real YouTube at 720/1080 after a 480p draft; offsets found by sound matching only tested with a fake cut.

## Next
- Owner applies rev12, re-runs windows-baseline.bat, then continues `docs/RELEASE_TEST.md` from step 4.
