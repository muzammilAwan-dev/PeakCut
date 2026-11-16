# PeakCut audit (Task 1)

Date: 2026-11-16. Code audited: fork `main` at `44b7c62` (identical to upstream at fork time). Plan: `docs/PLAN.md` (Verdict and Parts A to F win over sections 0 to 9). Line numbers are for that commit. "Estimate" means my guess in working days, not a measurement.

**Rule applied:** where the code contradicts the plan, the code wins. Section 2 lists every contradiction with a proposed plan fix. Nothing in the repo except `docs/` was changed.

## 1. Method and coverage

| Area | Depth | Notes |
| --- | --- | --- |
| `studio/ai.py config.py updates.py fetch_model.py safe.py usage.py ctx.py brain.py media.py render.py transcribe.py jobs.py roman.py load.py db.py asr_worker.py live.py` | Read fully | The pipeline, the AI seam and everything the plan touches |
| `studio/server.py` (1470 lines) | Lines 1-200, 539-760, 890-1000, 1205-1470 read; rest listed by route | Gate, status, job creation, re-render, AI routes, posting routes |
| `studio/creators.py`, `accounts.py`, `posting.py` | Defaults, storage and secret-handling parts | Frozen area per plan (F10) |
| `studio/auth.py admin.py account.py mailer.py alerts.py notices.py feedback.py profiles.py` | Headers and greps only | Accounts, email, admin. Frozen area; not on any slice's path |
| `tests/run.py test_ai test_local test_updates` | Read fully | `test_roman`, `test_limits` heads; other tests: header only |
| `web/index.html` (2440 lines) | Clip editor, update dialog, settings, greps | Other HTML pages (landing, auth, admin, legal, reset) not read: frozen |
| `README.md .env.example AGENTS.md DEPLOY.md Dockerfile LICENSE .gitignore requirements.txt` | Read | |

**Test baseline: NOT established in this container.** `fastapi`, `httpx`, `sqlalchemy`, `sherpa_onnx`, `soundfile`, `yt_dlp` are not installed and package installs are blocked on this account, so `python tests/run.py` cannot start. What I could run: byte-compile of every `studio/` and `tests/` file (OK), and `tests/test_roman.py` with the network libraries stubbed (24 PASS, 0 FAIL). That is a smoke check, not the baseline. **Needed from you:** run `python tests/run.py` once on your Windows machine and paste the result, or allow installs in a new chat.

## 2. Plan versus code: discrepancies and proposed plan fixes

Severity: **H** changes a slice's design, **M** changes scope or estimate, **L** wording.

| # | Sev | Plan says | Code says | Proposed plan fix |
| --- | --- | --- | --- | --- |
| D1 | H | yt-dlp is a binary: fetch the nightly exe, pass `--js-runtimes deno:<path>`, edit `media.py` only (A, D8, D9, Task 2) | yt-dlp is a **Python library**, pinned `yt-dlp==2026.10.21` (`requirements.txt:11`). Imported in three places: `media.py:99`, `live.py:51,57`, `profiles.py:191,193`. There are no CLI arguments | Keep library mode. Supply Deno by putting `bin/` first on PATH at startup (the Dockerfile already relies on yt-dlp finding `deno` on PATH, `Dockerfile:5-6`). Add one `media.ydl_opts()` helper if an explicit option is ever needed. "Nightly" becomes `pip install --target data/lib --pre "yt-dlp[default]"` or the zipimport file on `sys.path`: **experiment needed on a networked machine** |
| D1b | M | yt-dlp-ejs ships with the official exe (A) | Library install lacks the extra: plain `yt-dlp` in `requirements.txt:11`, no `[default]` | UNVERIFIED here (cannot inspect pip metadata offline). First experiment of S1: `pip show yt-dlp-ejs` on a clean venv, then one real extraction |
| D2 | H | ffmpeg path resolution is a `media.py` change (Task 2) | `ffmpeg`/`ffprobe` are called by bare name at 7 sites: `media.py:237,291,310`, `live.py:180,475`, `render.py:259,280` | Prepend `bin/` to `PATH` once in `config.py`/launcher: zero call-site edits, one test. Keeps the merge-friendly rule |
| D3 | H | Hindi/Urdu captions are drawn in script; needs Noto fonts and a shaping test (B, D, E5) | Captions are **never** drawn in Hindi/Urdu script. By design and tested: `brain.py:381-447`, `roman.py`, `jobs.py:373,388`, `tests/test_roman.py`; upstream commits `92aaec8`, `1f00638`, `a1d0dcb` | Product decision (question Q1). Default: keep Roman (Hinglish) captions, make script captions an opt-in per job in S6d. See experiments E1, E2 |
| D4 | H | Parakeet "variant UNVERIFIED"; v3 covers 25 European languages; add a per-job language setting (A, B) | Resolved: **v2 int8, English only** (`config.py:64`). `job["lang"]` is set only from YouTube's own transcript (`jobs.py:573`). `DEFAULTS`/`clean_options` have no language key (`jobs.py:110-137`). Uploaded Hindi/Urdu audio goes to an English model | Plan text: Hindi/Urdu on uploads and on YouTube videos without captions has **no working path today**. S6d must add the language option and the second engine; no change to the plan's engine choice |
| D5 | H | S4 (6 days) builds audio-first download, transcript/LLM cache, per-stage resume, section download (D11, S4) | Already built: audio first (`jobs.py:495`), whole video in background for videos up to 40 min (`jobs.py:493-494`), section download per clip above 40 min (`jobs.py:424-447`, `media.py:266-274`), block-level resume after restart (`jobs.py:196-229,471-475,574-588,642`), saved words (`jobs.py:621`), cached caption fixes (`jobs.py:375-377`), single-clip re-make (`jobs.py:338-361`) | Shrink S4 to what is missing: LLM response cache, output revision key, cancel and process supervisor, transactional output. Estimate 3 days (was 6) |
| D6 | M | Transcript overlap (E3) is new work | Overlap exists inside a block: `WINDOW_SEC=15 min`, `OVERLAP_SEC=60 s` (`brain.py:12,229-233`). **No overlap between the 10-minute blocks** used for videos over 20 min (`jobs.py:450-451,612-631`): `find_clips` sees only that block, so `_snap` clamps a clip at the block end (`brain.py:199`) | Add block overlap. No second "exclude found ranges" pass exists |
| D7 | M | Failures degrade to loudness-only (F6, Task 3 test e) | Partly. Loudness fallback fires only if **no** window got an answer (`brain.py:247-249`). A bad answer inside a window drops the whole window **silently** (experiments E3, E4) | Fix in S2/S7 as part of "validate LLM output": per-item validation instead of per-window |
| D8 | M | `PEAKCUT_AI_MODELS` fails over within one provider/key (F4) | Confirmed: `brain.ask_ai` loops `ai.models()` with 3 tries and sleeps of 4, 8, 12 s on HTTP 429/5xx (`brain.py:166-184`). One request is about 4,000 tokens (E5), so on an 8K-TPM provider the second request in a minute gets 429 and all three retries fall inside the same minute | S2 must raise a non-retryable error when the pool is exhausted (message must not contain `HTTP 429`/`HTTP 5`, else `brain.py:180` sleeps and retries). Chunk spacing by TPM is needed, as planned |
| D9 | M | Pool interface `complete_json(task, system, user, schema, ...)` (4.8) | The seam is `ai.call(model, prompt, schema)` with **one prompt string** and a `how` switch over three functions (`ai.py:219-222`). All AI traffic goes through `brain.ask_ai` (`brain.py:166`): clips, live judges, hooks, caption fixes, translation | Change signature to `Pool.complete_json(prompt, schema, purpose)`. Register `how="pool"` in the dispatch dict and add `pool` to `NO_KEY` (`ai.py:32`) so `ready()` passes (`ai.py:90-92`) |
| D10 | M | Ledger "in the existing database or a small SQLite file" (Task 3) | `usage` table has no provider or model column (`db.py:48-59`, `usage.py:22-32`). `db.init()` is `create_all` only, no migrations (`db.py:115-116`): new tables appear, new columns on existing tables do not | New `ai_ledger` table via `create_all`. Do not alter `usage` |
| D11 | M | Key encryption covers the AI key (D12, S7) | Three plaintext stores: `data/ai.json` (`ai.py:131`), OAuth tokens in `users/<id>/accounts/accounts.json` (`accounts.py:54-63,290,322,489`), OAuth app secrets (`accounts.py:128-149`), plus `.env` (`config.py:11-19`). All use `chmod 0o600`, which does nothing on Windows (`ai.py:133`, `accounts.py:60,149`) | Vault must cover all three JSON stores, or the plan must say "AI key only". Recommend all three, one `secrets` module with transparent read of old plaintext |
| D12 | M | Update check repoint (F1, S0) | Confirmed and wider: default repo is upstream (`updates.py:18`). Version comes only from `.git` (`updates.py:26-47`), so a **portable zip has no version and the check silently never runs**. The dialog tells users to `git pull` (`web/index.html:1212,1218,1219`). `REPO_URL` and `FOLLOW_URL` default to upstream's repo and Instagram (`config.py:90-91`), shown in the dashboard (`server.py:544`). `tests/test_updates.py:31` asserts a `.git` folder exists | S0: repoint default and hide the Follow button. S3: add a `VERSION` file written by the build and a release-based check (zip + SHA-256). Test must not need `.git` |
| D13 | M | `.bat` launcher in `installer/` (S3) | `.gitignore:22` contains `*.bat`: a `run.bat` would be silently untracked | Name it `.cmd` or add `!installer/*.bat`. Decide in S3 |
| D14 | L | Posting: export-only default (D13) | Already true: `autopost` defaults to `False` (`creators.py:21`) and posting needs the owner's own OAuth app (`accounts.py`) | Keep D13, mark "already the behaviour"; no code |
| D15 | L | S0 adds CI | Upstream **removed** its CI on purpose (commit `a920a91`). No `.github/` | Fine to add; say so in the PR |
| D16 | M | Standard profile defaults (C) | `JOB_WORKERS` defaults to `max(2, cores)` (`config.py:109`), `MAX_LIVE` to `max(4, 2*cores)` (`config.py:111`). ASR uses 2 threads on 4 cores (`transcribe.py:22`). Guards exist: `load.py:13-15`, `jobs.py:31-36`. `load._ram_free_gb` reads **available** RAM only (`load.py:38-53`); total RAM is in the same Windows struct but unused | Profile = new env defaults chosen at first run from total RAM and cores. Small, additive |
| D17 | M | Manual editing is all new (D, S6e: 12-15 days) | Exists: per-clip hook, style, layout, start, end (numeric), title, description plus "Save and re-make" (`web/index.html:2108-2116,2399-2402`, `jobs.py:338-361`, `server.py:893-906`), clip delete (`server.py:927-935`). Missing: caption word editor, visual trim, crop, add-by-hand, review queue, undo. Captions are regenerated at every render from `words.json` plus an AI call unless cached under key `fixed_for` (`jobs.py:373-386`) | S6e estimate about 9-11 days (was 12-15). A caption override must be its own field that `render_one` reads first; `fixed_words` is internal and stripped from the API (`jobs.py:151`) |
| D18 | L | S7 "yt-dlp argument allowlist" | There are no user-supplied yt-dlp arguments. Options are fixed dicts; the user controls only the URL (host-allowlisted at `server.py:654,678`, `live.py:644`, `media.py:69-77`), `quality` (clamped 360-1080, `jobs.py:114,125`) and range seconds (finite floats, `jobs.py:130-134`) | Drop that line from S7. Keep LLM-output validation and the key vault |
| D19 | M | Live clipping works on Standard (C) | Live runs the English model every ~7 s on the same CPU (`live.py:274-297`) and triggers are English words (`live.py:409-432`). Real-time speed with 2 threads is not measured | Measure real-time factor on a 4-core machine before promising live on Standard |

## 3. Task 1 checklist: the ten questions

| Question | Answer |
| --- | --- |
| **Where is the AI key stored, encrypted?** | `data/ai.json`, plaintext (`ai.py:39-40,131`); or `.env` / `PEAKCUT_AI_KEY_FILE` (`config.py:11-19,127-129`). Never sent to the browser: only `has_key` and the last 4 characters (`ai.py:95-103`). Errors redact it (`ai.py:182-184`, `server.py:1217`). Other secrets: D11 |
| **How is yt-dlp invoked, and which arguments does a user influence?** | As a library, fixed option dicts (`media.py:98-103`). Audio format fixed (`media.py:252`); video format built from a clamped integer (`media.py:106-107`); section ranges are floats from job data (`media.py:266-274`). Only the URL and the numbers above are user-controlled (D18). Caption URLs come from the extractor and are read with a 40 MB cap (`media.py:142,161`) |
| **Where is the full video downloaded?** | Videos up to 40 min: in the background while audio is processed (`jobs.py:493-494`, `media.py:258-263`). Longer: never; only clip sections (`jobs.py:428-447`). Uploads are copied into the job folder (`server.py:736`) |
| **Where are transcript chunks built and sent to the LLM?** | `jobs.py:605-631` cuts 10-minute blocks (only above 20 min; below that one block), then `brain.find_clips` (`brain.py:222-261`) makes 15-minute windows with 60 s overlap and calls `ask_ai` per window (`brain.py:241`). A window is about 4,000 tokens (E5). Live: 240-second window (`live.py:21`, `brain.py:337-352`) |
| **Where is LLM JSON parsed and validated?** | Parse: `ai._parse` (`ai.py:202-215`), Gemini `json.loads` (`ai.py:235`). Gemini gets a schema; others get the schema in the prompt plus `response_format: json_object` (`ai.py:197-199,242`). Validation: none against the schema. `brain._tidy` (`brain.py:109-123`) clamps and sanitizes fields that survive, `_snap` fixes times. Weak spot: D7, E3, E4 |
| **How is a mid-job provider failure handled?** | Per window: three tries with sleeps, then the window is skipped (`brain.py:175-184,244-245`). Whole job falls to loudness only if no window answered (`brain.py:247-249`). Otherwise silently fewer clips. Captions: any failure returns the original words (`brain.py:474-477`) |
| **How does `render.py` crop, lay out and draw captions?** | Layouts `blur`, `zoom`, `crop` (`render.py:81`). `_filter` (`render.py:221-228`): `crop` is one centred scale-and-crop; `blur`/`zoom` overlay a centred foreground on a blurred copy. Captions: one ASS event **per word**, placed by hand with measured widths (`render.py:158-218`, x grows left to right at `:200-206`). Fonts: Poppins ExtraBold, Anton, Archivo Black (`render.py:24`). Needs libx264 (`:265`), `ass`, `loudnorm`, `boxblur`, `eq` (`:221-228,258-260`); tries Intel QSV first (`:263-266`). Work folder in the system temp, moved into place (`:245,282-283`). Shaping: E1, E2 |
| **Which Parakeet variant, and how are word times made?** | `sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8`, English (`config.py:64`, `fetch_model.py:8`), no hash check (`fetch_model.py:18`). Audio cut at the quietest 50 ms frame between 12 and 24 s (`transcribe.py:116-133`). A word starts at its first token's time; the end is the next start, capped (`transcribe.py:140-162,265-267`) |
| **Does any manual editor exist?** | Partly: D17 |
| **How are paths and the data folder resolved?** | `ROOT/.env` (`config.py:8-22`), `DATA_DIR = $PEAKCUT_DATA or ROOT/data` (`config.py:55`), models in `data/models`, uploads in `data/tmp` (`config.py:57-58`). `job.json` stores absolute paths but `_load_file` rewrites `dir` and re-finds files by name (`jobs.py:187-229`), so moving the folder works. Exceptions: the render work folder uses the system temp (`render.py:245`); fonts are copied to `data/fonts` (`config.py:59`, `render.py:73-78`) |

## 4. UNVERIFIED items: what I resolved

| Plan item | Result | How |
| --- | --- | --- |
| Which Parakeet variant | v2 int8, English only | `config.py:64` |
| Does render.py need libx264 | Yes, as fallback after QSV; also needs `ass`, `loudnorm` | `render.py:258-265`; local ffmpeg 6.1 has all (GPL build) |
| Is there a manual editor | Partly | D17 |
| Does the update check point at upstream | Yes, also two dashboard links | D12 |
| How does render.py crop (does face reframing need a big change) | One function, 8 lines: `_filter`. Replace `crop=W:H` with `crop=W:H:x:y` per shot. Face reframing needs **one hook**, as Part F hoped | `render.py:221-228` |
| Do the bundled fonts cover Devanagari and Urdu | **Devanagari: Poppins yes (33/33 core letters), Anton and Archivo Black no. Urdu: none.** | E1 |
| Does per-word placement work for right-to-left | **No: reading order is reversed** | E2 |
| Are YouTube auto-captions available for Urdu | Still UNVERIFIED (needs a live check) | |
| yt-dlp finds Deno on PATH; `yt-dlp-ejs` present | Still UNVERIFIED (needs network and a clean venv) | S1 first step |
| Whisper large-v3-turbo speed on 4 cores | Still UNVERIFIED (no model, no network here) | S6d benchmark |

## 5. Experiments run

| # | Question | Result |
| --- | --- | --- |
| E1 | Glyph coverage of the three bundled fonts (parsed the `cmap` tables) | Devanagari core: Poppins 33/33, Anton 0/33, Archivo Black 0/33. Urdu core: 0/31 in all three |
| E2 | One shaped RTL line versus `render.py`'s one-event-per-word layout (libass, DejaVu Sans, Urdu "yaar kya hai") | The single line reads right to left correctly. Per-word placement puts the first spoken word on the **left**, so the line reads in reverse. Fix when script captions are wanted: place words from the right for RTL groups. ffmpeg here has harfbuzz and fribidi; Pillow has raqm. Image: `docs/audit/rtl.png`, source `docs/audit/rtl.ass` |
| E3 | AI answer where one item has `start: null` | Whole 15-minute window dropped (`float()` raises inside the per-window `try`, `brain.py:243`), the valid second clip lost too, 0 clips, no fallback, empty note |
| E4 | AI answer that is an object, not a list | 0 clips, no log, no fallback |
| E5 | Tokens in one 15-minute window at 150 words a minute | About 3,956 tokens by the plan's chars/3.5 rule (13,845 characters). Two such requests inside a minute exceed an 8K-TPM limit |
| E6 | `tests/test_roman.py` with stubbed imports | 24 PASS (smoke only) |

Scripts and the image are in `docs/audit/`. Run from the repo root: `python -I docs/audit/exp_brain.py` (E3 to E5), `python -I docs/audit/stub_runner.py tests/test_roman.py` (E6). The RTL frame: `ffmpeg -f lavfi -i color=c=0x202020:s=1080x400:d=1 -vf ass=docs/audit/rtl.ass -frames:v 1 out.png` (needs a system font with Arabic letters, e.g. DejaVu Sans).

## 6. Seams and hook points per slice

| Slice | Hook | Change size |
| --- | --- | --- |
| S1 bootstrap | `config.py` (PATH prepend, `PEAKCUT_BIN_DIR`), new `studio/bootstrap.py`, one test. No call-site edits (D1, D2) | Small |
| S2 pool | `ai.py` dispatch dict (`:222`) and `NO_KEY` (`:32`); new `studio/pool.py`; new `ai_ledger` table in `db.py`; route info via the thread-local used by `usage.set_context` (`usage.py:13-19`); error text must not match `brain.py:180` | Medium, additive |
| S3 portable | New `installer/`. `VERSION` file and release check replace `.git` version (D12). Launcher must open the browser and set `PEAKCUT_DATA` | Medium |
| S4 | LLM cache keyed by prompt hash around `brain.ask_ai`; revision key in `render_one`; cancel for running jobs (none exists: only `delete` after finish, `server.py:909-915`) | Small to medium |
| S6 | `brain.find_clips`: block overlap, per-item validation, deterministic verification of AI times against `words` (the `_snap` function is the start) | Medium |
| S6d | `transcribe.py` second engine behind the same `transcribe(audio)` function; `lang` in `jobs.DEFAULTS`; script/Roman decision (Q1) | Medium |
| S6e | Per-clip `overrides` field read by `render_one` before `english_captions` (`jobs.py:373-386`); new routes beside `server.py:893` | Medium |
| S6f | `_filter` in `render.py:221-228`; `cv2` already importable here (5.0.0) but the plan pins 4.x: check on Windows | Medium |

## 7. Revised estimates (mine, not measured)

| Slice | Plan | Now | Why |
| --- | --- | --- | --- |
| S1 | 4 | 3 to 4 | PATH approach removes call-site edits; nightly yt-dlp mechanism needs an experiment |
| S2 | 5 | 5 | Same, plus ledger table and exhaustion error |
| S4 | 6 | 3 | D5 |
| S6 | 7 | 7 to 8 | Block overlap and per-item validation added |
| S6e | 12-15 + 3 + 2-3 + 1-2 | about 9-11 + 3 + 2-3 + 1-2 | D17 |
| Others | | unchanged | |

## 8. Proposed changes to the plan text

1. Task 2 and A/D8/D9: replace "binary, `--js-runtimes`, media.py only" with "library mode, bin/ on PATH, verify yt-dlp-ejs" (D1, D1b, D2).
2. B/D/E5: state that Roman captions are the shipped behaviour and script captions are opt-in (D3, Q1).
3. A and B: Parakeet is v2 English-only (D4).
4. S4: reduce to the gaps (D5). E3: block overlap, not chunk overlap (D6).
5. 4.8 interface: `complete_json(prompt, schema, purpose)` (D9). Task 3: new `ai_ledger` table (D10).
6. D12: vault covers three stores (D11). S7: drop the yt-dlp argument allowlist (D18).
7. S0/S3: version and update flow for a zip with no `.git` (D12); `.bat` is git-ignored (D13).
8. D13 (posting): mark already true (D14). S0 CI: note upstream removed it (D15).

## 9. Ideas from the FuseClip research bundle (feature level only)

**Provenance.** The bundle describes a third-party desktop app. Its own metadata says author "Amfaiz", repository `github.com/Amfaiz/fuseclip`, and "source code is proprietary… all rights reserved" (`extracted/app/package.json`, `extracted/app/README.md`). Its README says to keep the research private and write your own implementation and prompts. I therefore read only the analyst reports (`reports/01` to `04`) and **did not open or copy the recovered source, prompts, assets, fonts or style names**. Everything below is a general technique, to be implemented independently. If you can show the app is yours (for example the repository is under your account), tell me and I will revisit; until then this line stays.

Ideas already in Part E (review queue, propose-then-verify, overlap, transcript fallback, Hindi/Urdu repair, emphasis, layouts, face reframing, revision key, undo, portable projects, transactional export, consent preview, brand kit) are not repeated. **New, not in Part E:**

| # | Idea | Where it helps | Slice |
| --- | --- | --- | --- |
| N1 | Urdu speech recognised as Hindi, then transliterated: the report says both the local and cloud paths map Urdu to Hindi recognition. Test `language=hi` plus Roman conversion against `language=ur` on your Urdu clips | May beat Whisper's weak Urdu (plan's best figure 16-35% word error) | S6d eval |
| N2 | Long-audio cloud transcription in parts with 2 s overlap and a "covered up to" mark to drop duplicate words | Groq Whisper opt-in fallback (20 requests a minute, plan section B) | S6d |
| N3 | Repeat suppression for transcript segments (Whisper-style loops) | Whisper path will repeat lines on silence | S6d |
| N4 | AI checkpoint file named by a hash of operation plus settings, stores each finished request, deleted on success, kept on failure | Exactly the missing LLM cache of D5 | S4 |
| N5 | Retry a structured AI answer up to three times when the JSON is invalid, separately from network retries | Fixes D7 cleanly | S2 |
| N6 | Whisper run order: first with word-alignment options, retry without, then retry on CPU | Whisper engine robustness | S6d |
| N7 | Hardware probing that only recommends a model and encoder, never assumes acceleration; encoder probing for hardware H.264 with software fallback | Standard/Performance profile; add NVENC/AMF beside the existing QSV try (`render.py:263`) | S6/S6e |
| N8 | Keyframe interpolation with binary-search neighbours and smooth easing; use a discrete keyframe across tiny gaps or layout changes | The later "gentle pan" in S6f | S6f |
| N9 | Caption row editing: word menu (edit, delete, manual line break, emphasise, move to previous or next line); replacing one word with several splits its time evenly; a user glossary | Caption editor UX | S6e |
| N10 | Manual line breaks stored and cleared when grouping changes | Same | S6e |
| N11 | Review panel: timeline with proposed clips, accept all, verified marker removed when a boundary moves | Review queue | S6e |
| N12 | Aspect presets 9:16, 1:1, 4:5, 3:4, 16:9 and output size choices | Layout presets | S6e |
| N13 | Verification matrix from the analyst: Unicode/RTL fixtures, trim boundary, audio sync, cancel at each stage, atomic writes, tampered download | Seed for `eval/` and tests | S5 |
| N14 | A Hinglish-tuned Whisper model is named as a status alias in the report: candidate for the eval, provenance UNVERIFIED | Hindi/Urdu | S6d eval |

**Avoid** (the report lists them as weaknesses): automating a third-party AI website through a hidden browser, broad file access from the UI, downloads without hash checks, an updater with no artifact verification, announcements fetched from a vendor server (phone-home).

## 10. Questions for you (blocked decisions only)

1. **Captions (D3):** keep Roman letters (works today, tested) as the default and add Devanagari/Urdu script as an opt-in later, or make script the default? This sets S6d scope.
2. **FuseClip (section 9):** is that app yours, and can you show it (repository under your account)? If not, I keep to ideas only.
3. **Fork identity (S0):** name for the fork's copyright line, and should the dashboard's "Follow" button (upstream author's Instagram) be hidden?

## 11. S0 plan, for your OK (fork hygiene, about 1 day)

Files: `LICENSE` (add one line under the original), `README.md` (Fork notice), `studio/config.py` (`REPO_URL` default to the fork, `FOLLOW_URL` default empty), `studio/updates.py` (default repo to the fork), `.github/workflows/ci.yml` (new, Windows and Linux), `CONTRIBUTING.md` (new), `docs/DECISIONS.md` (new), `AGENTS.md` (fork rules). Tests: new `tests/test_fork.py` (LICENSE keeps the original notice plus the fork line; mocked GitHub reply produces no text containing `haziqahmedqasmi`; config defaults contain no upstream link), registered in `tests/run.py`. Needs: your answer to Q3, and the baseline test output from your Windows machine. I cannot push until GitHub is linked to this session.
