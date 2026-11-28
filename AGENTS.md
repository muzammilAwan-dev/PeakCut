# Working on ViralCut

A short map for contributors and AI coding assistants.

## Run and test

- Run: `python -m studio.server` (settings from `.env`; see `.env.example`). Needs a Python that has ready-made files for every pinned package (`python tools/pyenv.py check` says which versions; 3.14 does not work yet) and `ffmpeg`. `python tools/pyenv.py ensure` builds `.venv` with the right one.
- Speech model, once: `python -m studio.fetch_model`.
- Tests: `python tests/run.py`. It starts a throwaway copy on a spare port with an empty data folder. Run it
  before and after any change to `studio/`. No keys needed.
- To try a risky change by hand without touching real data:
  `PEAKCUT_DATA=<temp folder> PEAKCUT_PORT=8766 python -m studio.server`.

## Where things are

| File | What it does |
|---|---|
| `studio/server.py` | Every web route, and the gate that runs before each request (who is asking, limits, headers) |
| `studio/config.py` | Every setting, read from environment variables |
| `studio/ai.py` | The only code that talks to an AI service, and the AI settings saved from the dashboard (`ai.json` in the data folder) |
| `studio/brain.py` | The prompts: finding clips, live judging, hooks and titles, caption fixes |
| `studio/branding.py` | The app's name, repository, copyright line, data folder name and setting prefix, in one place (for the later rename) |
| `studio/bootstrap.py`, `studio/pins.json` | Puts `bin/` first on the PATH; fetches ffmpeg and Deno only when missing, from pinned, hash-checked downloads |
| `studio/pool.py`, `studio/ledger.py`, `studio/providers.default.json` | The free AI pool: failover, cooldowns, privacy filter, repair retry. The ledger is a small SQLite file in `data/` |
| `studio/jsoncheck.py` | Checks an AI answer against its schema and keeps only the usable items |
| `tools/pyenv.py`, `tools/baseline.py`, `tools/find-python.bat` | Find or install a Python that fits, build `.venv`, run the whole test suite and save the log (`windows-baseline.bat`). No version is written down: it is computed from PyPI |
| `tools/claude_pack.py`, `tools/sandbox.json` | Packs files into zips under 30 MB and joins them again (for working with an offline assistant) |
| `studio/applog.py` | The log file (`data/logs/viralcut.log`): `applog.log(event, key=value...)`. Blanks keys. Never log prompts or video text |
| `studio/ytaccess.py` | Opt-in browser sign-in for YouTube's bot check (`data/youtube.json`). Used only after a refusal; `media._retry_with_sign_in` retries once |
| `studio/trace.py` | Per-video paper trail in `trace/`: transcript and every AI prompt with its reply (default on without sign-in) |
| `studio/llmcache.py` | Remembers AI answers (by prompt) so asking again costs nothing |
| `studio/vault.py` | Seals saved keys with Windows DPAPI (falls back to plain text, never loses a key) |
| `studio/reframe.py` | Optional follow-the-face crop (OpenCV, default off) |
| `studio/exttoken.py` | The pairing key for the browser extension in `extension/` |
| `studio/evalkit.py`, `tools/eval.py` | Scores clip picking against human picks (`docs/EVAL.md`) |
| `tools/build_portable.py`, `tools/fill_pins.py` | Builds the portable zip; fills `studio/pins.json` from release pages |
| `studio/usage.py` | The record of AI calls and tokens shown on the AI usage page |
| `studio/jobs.py` | The video pipeline and the fair queue |
| `studio/live.py` | Live recording and clipping |
| `studio/transcribe.py`, `studio/asr_worker.py` | Speech to text, here or on a second machine |
| `studio/render.py` | Cutting, layouts and captions (ffmpeg and Pillow) |
| `studio/media.py` | Downloading (yt-dlp), probing, audio |
| `studio/auth.py`, `studio/account.py`, `studio/admin.py` | Sign-in, deleting things, the admin dashboard |
| `studio/db.py` | Database tables (SQLAlchemy core; SQLite or PostgreSQL) |
| `web/index.html` | The whole signed-in app, one file, no build step |

## Rules worth knowing

- **Sign-in is off by default** (`config.ACCOUNTS`): every request then belongs to one built-in owner
  (`auth.local_user()`). With `PEAKCUT_ACCOUNTS=1` it is a normal multi-user site. Both paths are tested.
- **Who is asking** always comes from the session (`ctx.uid()`), never from the request body. Background threads
  set it themselves with `ctx.as_user(...)`.
- **Anything that changes what a user sees must call `ctx.bump()`**. The page polls `/api/sync`, which answers
  from memory when that user's counter has not moved.
- **Text from videos is untrusted**: it goes into prompts through `brain._safe` and out through `brain._text`.
- **The free pool** (`PEAKCUT_AI_PROVIDER=pool`): add a service by adding an entry to `studio/providers.default.json` (it needs a
  data-terms source URL and a check date, or strict privacy excludes it). `pool.complete_json` raises `PoolExhausted` when nothing can
  answer; `brain.find_clips` then picks clips by loudness. Its message must never contain "HTTP 429" or "HTTP 5".
- **Adding an AI provider**: add a row to `PROVIDERS` in `studio/ai.py`. If it speaks the OpenAI chat format that
  is all; otherwise add one function that returns `(parsed JSON, tokens in, tokens out)`.
- **Clips are rendered in a short temporary folder** and moved into place (`render.render_clip`): ffmpeg's caption
  step cannot open paths longer than 260 characters on Windows.
- **Secrets** are read from the environment or from files named by `*_FILE` settings. Never write a key, a real
  address or a personal path into a tracked file.
- **Pages** are plain HTML, CSS and JavaScript. Keep the existing palette, no shadows, and hover states that
  change colour only.
- Comments and messages are written in plain language for people who do not program. Keep that tone.
