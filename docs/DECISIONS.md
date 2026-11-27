# Decisions and plan corrections

One line each, newest at the bottom. Format: date, slice, decision, why. Sources are linked where a web fact was used.

## Plan corrections from the audit (docs/AUDIT.md section 2)

| Date | Ref | Decision |
| --- | --- | --- |
| 2026-11-16 | D1/D2 | yt-dlp stays a Python library; `bin/` is put first on PATH once at startup. Zero call-site edits for ffmpeg, ffprobe or Deno. |
| 2026-11-16 | D3/D4 | Hindi and Urdu captions stay in Roman letters by default (shipped, tested behaviour). Script captions are opt-in in S6d. Parakeet is the English-only v2 model. |
| 2026-11-16 | D5 | S4 shrinks to the gaps: LLM cache, output revision key, cancel and supervisor, transactional output. |
| 2026-11-16 | D6 | Only block overlap is new (10-minute blocks); window overlap inside a block already exists. |
| 2026-11-16 | D7 | Per-item validation of the AI answer replaces per-window loss (S6/S7). |
| 2026-11-16 | D9/D10 | Pool interface is `complete_json(prompt, schema, purpose)`. The ledger is a new `ai_ledger` table; `usage` is not altered. |
| 2026-11-16 | D11 | The key vault covers all three plaintext stores (`ai.json`, `accounts.json`, OAuth app secrets) plus `.env`. |
| 2026-11-16 | D12/D13 | A `VERSION` file is the version fallback for a zip. The launcher is allowed past `.gitignore`. |
| 2026-11-16 | D16 | The mid-tier profile is a new set of environment defaults chosen at first run. |
| 2026-11-16 | D17 | Manual editing builds only the missing tools. A caption override is its own field read before `english_captions`. |
| 2026-11-16 | D18 | No yt-dlp argument allowlist (users supply no yt-dlp arguments). |
| 2026-11-16 | D19 | Live clipping on the mid tier is not promised until measured. |

## Owner decisions (kickoff prompt section 6)

| Date | Decision |
| --- | --- |
| 2026-11-16 | Company and author name is Amfaiz. LICENSE keeps the upstream notice and gets the line `Copyright (c) 2026 Amfaiz` above it. |
| 2026-11-16 | Updates come from this fork only. No text or link may name the original author. |
| 2026-11-16 | Roman letters are the default for Hindi and Urdu captions; native script is opt-in (assumed default, owner may change it). |
| 2026-11-16 | Rebrand later: `studio/branding.py` holds the name; the last slice (S-Brand) renames. Name, logo and style must be original. |
| 2026-11-16 | FuseClip is the owner's own earlier app. Ideas may be reused (say "idea N# from FuseClip"); no file or path is copied into this repo. |

## Slice S0 (2026-11-17)

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-17 | `studio/branding.py` has no imports from the app and no packages. `branding.env("X")` reads `<ENV_PREFIX>_X` then `PEAKCUT_X`. | The rename becomes a one-file change; old settings keep working. `config.py` still reads `PEAKCUT_*` directly: nothing is renamed yet. |
| 2026-11-17 | `config.REPO_URL` defaults to the fork. `config.FOLLOW_URL` defaults to empty. | The page already hides the Follow button when the link is empty (`web/index.html:1277`, `:1158`). No page edit was needed. |
| 2026-11-17 | `updates.REPO` defaults to `branding.REPO`. | The update check must never look at the original project. |
| 2026-11-17 | `updates.current()` = `.git` commit, else the commit id in a `VERSION` file beside the app, else unknown. The file is believed only if its first line is exactly 40 hex letters. | A zip has no `.git`, so the check silently never ran (audit D12). The file is untrusted input: validated, never executed. |
| 2026-11-17 | `.gitignore` gets `!installer/*.bat`. | `*.bat` was ignored, so a launcher would be silently untracked (audit D13). |
| 2026-11-17 | CI runs `python tests/run.py` on Windows and Linux for pushes to `develop` and pull requests. | Upstream removed its CI on purpose (audit D15); this fork wants one. UNVERIFIED: it has not run on GitHub yet. |
| 2026-11-17 | `tests/test_updates.py` no longer needs a `.git` folder in the checked-out copy. | A downloaded zip has none (audit D12). |
| 2026-11-17 | The "How to update" dialog text (`git pull`) is left as is. | It is correct for a git copy. S3 adds the release-based flow for zips. |

## Slice S1 (2026-11-17)

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-17 | `studio/bootstrap.py` (standard library only). `config.py` puts `bin/` first on the PATH once at import. | Audit D1/D2: zero edits at the seven ffmpeg call sites. |
| 2026-11-17 | A program is downloaded only if it is missing or not good enough: ffmpeg must have libx264 and the `ass`, `loudnorm` and `boxblur` filters; Deno must be 2.3.0 or newer. A good copy found on the PATH is used as is. | Second run downloads nothing; the `ffmpeg -encoders` probe proves the one thing rendering needs (`render.py:265`) instead of assuming it. |
| 2026-11-17 | `studio/pins.json` ships **empty**. Nothing without a SHA-256 is ever downloaded. `tools/make_pins.py` fills an entry on a computer with internet. | The sandbox that built this had no internet, so real addresses and fingerprints could not be checked. Inventing them would break rule 3 (never invent versions or hashes). |
| 2026-11-17 | Downloads: https only (plain http only to this computer, for tests), redirects checked, resume with Range, 3 tries, temp file, SHA-256 match, atomic replace, size cap. The zip is read by pinned file names only. | Plan section on bootstrap; zip-slip and half-written files are the usual faults. |
| 2026-11-17 | yt-dlp nightly and the daily check are **not** in S1. | It needs a network experiment (is the zipimport build usable as a library, is `yt-dlp-ejs` bundled). Moved to the S1 follow-up; see STATUS. |
| 2026-11-17 | `PEAKCUT_BOOTSTRAP=0` in `tests/run.py`. | The test server must never fetch anything. |

## Slice S2 (2026-11-17)

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-17 | `pool.complete_json(prompt, schema, purpose)` (audit D9: one prompt string, not task/system/user). Registered in `ai.py` as provider `pool`; `PoolExhausted` is an ordinary exception, so `brain.find_clips` falls back to loudness with no change. | The existing seam (AUDIT F5). |
| 2026-11-17 | The ledger is a small SQLite file `data/ai_ledger.db` (table names `ai_ledger`, `ai_ledger_state`), standard library only, **not** a SQLAlchemy table in the main database. This differs from audit D10. | PLAN Task 3 allows "a small SQLite file in the data folder". It is machine-local state (cooldowns of this computer's keys), it needs no migration, and it could be tested here without SQLAlchemy. |
| 2026-11-17 | Providers seeded: Groq, Cloudflare Workers AI, Ollama (on); Gemini (off). Mistral, OpenRouter and Z.ai are **not** seeded. | Their free-tier facts are "console only" or conflicting in the plan (section 4.1). Add them when verified. |
| 2026-11-17 | Catalog values are copied from PLAN section 4.1 and were **not re-checked** (no internet). Cloudflare's base URL, model id and context size are marked unverified in the file. | Rule 3. |
| 2026-11-17 | Strict privacy (default): `trains_on_data` is `no` and the check is at most 90 days old. A service on this computer always passes. | PLAN 4.6. |
| 2026-11-17 | Keys live in `data/pool.json` (plaintext, like `ai.json`) or in the named environment variable. Fourth plaintext store: S7's vault must cover it. | Audit D11 listed three stores; this is a new one. |
| 2026-11-17 | The pool talks HTTP with `urllib` (standard library), not `httpx`. | No new dependency and testable against a local mock server here. |
| 2026-11-17 | The model's own words are never put into a repair prompt. | Prompt-injection hygiene: the repair note holds only our own validator's reason. |
| 2026-11-17 | `jsoncheck.clean` runs in `brain.ask_ai` for every provider, not only the pool: bad items are dropped, a wrong-shaped answer raises. | Fixes audit D7/E3/E4 (one bad item silently dropped a 15-minute window) for all providers. Risk: stricter than before; `tests/test_ai.py` is unchanged and must stay green on Windows. |
| 2026-11-17 | Not done in S2: per-job stickiness (plan 4.5), learning limits from response headers (plan 4.3 item 9), the capability probe on key save (4.7), the settings page and consent dialog (UI). | Each needs a measurement or UI work; scheduled as S2b. |

## Working with an offline assistant (2026-11-17)

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-17 | `tools/claude_pack.py`, `tools/claude-pack.bat`, `tools/windows-baseline.bat`. Parts are real zips of about 25 MB each (the chat upload limit is 30 MB; the first 34.6 MB parts were too big), with SHA-256 checks. | The sandbox cannot install packages or reach the internet, so the owner fetches the Linux wheels and sends them back in parts. |
| 2026-11-17 | **Which Python versions work is computed, not written down.** `tools/pyenv.py` reads `requirements.txt`, asks PyPI which files each pinned package has, and keeps the Python versions that have a ready-made file for every package on this kind of computer (offline default: 3.10 to 3.13; the project's own floor is 3.10). | The owner's first baseline run (Python 3.14.6) failed: `numpy==2.2.6` has no 3.14 wheel and pip tried to compile it. A fixed list in scripts goes stale the day a package moves, and the owner's machine may have any version. Verified by `pip download` here: all 31 pinned packages have Linux cp313 wheels. S3's embeddable Python must come from the same computation (3.13 is the verified one). Moving past 3.13 means bumping numpy and re-checking sherpa-onnx first. |
| 2026-11-17 | The helper scripts detect, they do not assume: `find-python.bat` finds any Python 3.8+ (skipping the Store shortcut); `tools/baseline.py` and `tools/pyenv.py` pick the newest installed Python that fits, rebuild a `.venv` made with one that does not, offer a per-user, signature-checked python.org install when none fits, and stop when packages do not install. The assistant sandbox's Python and platform live in `tools/sandbox.json`, not in code. | The first baseline script ran the tests even after the install failed (misleading "no module named sqlalchemy"), and then hardcoded a version list, which the owner rightly objected to. |
| 2026-11-18 | Consent gate: until the owner allows it (dashboard or `PEAKCUT_AI_CONSENT=1`) no transcript text goes to an online service; the pool then falls back to loudness. | Risky cloud paths are default-off (rule 5). |
| 2026-11-18 | Key-save check (`Pool.probe`) runs only on a key save or a Test press, at most 4 tiny requests, never on a timer and never with the owner's text. | Free allowances are what runs out first. |
| 2026-11-18 | AI answers are cached by prompt+schema for 30 days (`studio/llmcache.py`); live checks are not cached. | A rerun or restart costs no AI requests. |
| 2026-11-18 | A clip's fingerprint (`render.revision`) is saved only after all its files are in place; output files are staged as `*.new` and renamed. | A stop in the middle is repaired by the next make instead of trusted. |
| 2026-11-18 | Stop button + supervisor (20 min of no change). A running clip render is finished, not killed. | Threads cannot be killed safely; the next step boundary stops. |
| 2026-11-18 | Pieces of a long video overlap by 60 s when the AI reads them; a clip that overlaps an earlier one is dropped. | Moments across the join were lost before. |
| 2026-11-18 | Fallback when no AI answers uses speech lines and loudness together (clips start and end at lines). | Better than loudness alone, still free. |
| 2026-11-18 | Eval counts each human pick once (one-to-one). | Two picks inside one human moment are one find. |
| 2026-11-18 | Hindi/Urdu speech model (S6d) not built: sherpa-onnx Whisper gives no word timings that could be verified offline. | Never invent an API. |
| 2026-11-18 | Keys are sealed with Windows DPAPI and read back at once; any failure keeps the key plain (`studio/vault.py`). | A key must never be lost to the vault. Cost: moving `data/` needs keys pasted again. |
| 2026-11-18 | Name ViralCut. New settings prefix `VIRALCUT_`; `PEAKCUT_` still works everywhere (`config.env`). New original logos. GitHub repo name unchanged. | Owner's choice; nothing breaks for old settings. |
| 2026-11-19 | Face reframing uses OpenCV 4.12.0.88 (optional, built-in Haar detector, no model download). OpenCV 5 dropped it, so it is pinned below 5. | Verified on a public-domain photo; default-off. |
| 2026-11-19 | Extension: one pairing key, one door (`POST /api/ext/clip`), the only route that lets an extension Origin through the cross-site check. | Smallest possible hole. |
| 2026-11-19 | Portable build downloads the embeddable Python at build time (fingerprint remembered on first use; `python.exe` must carry the PSF signature); ffmpeg and Deno are fetched on the user's first start, never bundled. | No GPL in the zip; pin + hash. |
| 2026-11-26 | Gemini catalog is now gemini-3.5-flash-lite, gemini-3.8-flash, gemini-3.1-flash-lite (was gemini-2.5-flash). The key check skips a model that answers 404 and tries the next (up to 3). | Real 404 on a new free key: Google's changelog says 2.5 models are limited to projects that already used them. Free-tier access of the new ids is UNVERIFIED. |
| 2026-11-27 | Activity log: `data/logs/viralcut.log` (rotating, 5 x 5 MB). Logs start-up, every web request, key saves (last four letters), every AI request with status code and time, check/error replies, jobs. Never keys, passwords or video text; normal AI replies are logged as a size (debug level adds 300 characters). | The owner needs to see exactly what each service answered. Keys are blanked by exact value and by shape. |
| 2026-11-27 | "Find working models": lists the service's models, drops embedding/speech/image ones, ranks (known, finished, fast and small, newer; big 'pro' later), sends one tiny no-text request to the best 6 (max 8) and keeps only those that answered. Only on a button press. | A key can list models it cannot use (Gemini 404). Rank rules are a guess, so the result decides, not the name. |
| 2026-11-27 | Trace files per video (`<video folder>/trace/transcript.txt`, `ai-NNN-*.txt` with the full prompt and reply). On when there is no sign-in, off on a shared site; `PEAKCUT_TRACE=0/1` overrides. The activity log only names the files. | The owner needs to compare what was heard and asked. The files hold video text, so they live with the video and go when it is deleted. |
| 2026-11-27 | Option `mode`: `stream` (craziest moments) or `podcast` (most informative, shareable parts). Different opening, start/end, skip and score wording and categories per mode. Also a creator default. Live checks stay `stream`. | A podcast is not a game stream. |
| 2026-11-27 | Draft first (link videos): download at 480p, find and make clips from that, then `POST /api/jobs/{id}/final` fetches just each clip's stretch at the chosen 720/1080 and makes it again. The start is found by matching sound against the draft. Drafts are not handed to posting. Output stays 1080x1920 either way. | Much less to download before the owner can judge the clips; full quality only for the ones kept. Default on for links; off per video or in Options. Uploads are unaffected. |
| 2026-11-27 | Settings per pasted video (row button) override the box's settings for that video only; "Make again" on a finished link puts it back in the box. | Owner could not change options for one link. |
