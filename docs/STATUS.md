# Status (update at the end of every slice)

Branch: `develop`. Last updated: 2026-11-16 (by the audit session; nothing built yet).

| Slice | Scope (short) | State | Tag |
| --- | --- | --- | --- |
| Task 1 | Audit (`docs/AUDIT.md`) | done | n/a |
| S0 | Fork hygiene, `studio/branding.py`, CI, VERSION file, update check on the fork | next | |
| S1 | Engine bootstrap: ffmpeg, deno, yt-dlp into `bin/` on PATH | todo | |
| S2 | Pool v0: `complete_json`, `ai_ledger`, cooldowns, privacy toggle | todo | |
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
Test baseline on the owner's Windows machine: **not yet recorded**. Paste the output of `python tests/run.py` here at the start of S0.

## Open questions for the owner
- Product name candidates for S-Brand (2 to 3).
- Path of the extracted FuseClip reference folder (kept outside the repo).

## Known UNVERIFIED (resolve by experiment before relying on them)
- `yt-dlp-ejs` present and Deno found on PATH in a clean venv (S1, first step).
- Whisper large-v3-turbo speed on 4 cores and its peak RAM (S6d benchmark).
- YouTube auto-captions available for Urdu (live check).
- Live clipping real-time factor on a 4-core machine (D19).
- Free-provider JSON quality on Hindi and Urdu transcripts (S5 eval).
- Whether unsigned downloads trigger Windows warnings (decide before public release).
- sherpa-onnx native packaging on a clean Windows machine (S3 gate).
