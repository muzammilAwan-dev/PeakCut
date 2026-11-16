# PeakCut fork: research and execution plan

Date: 2026-11-16 (final v1; each section notes its own verification date). Fork: https://github.com/muzammilAwan-dev/PeakCut (upstream: haziqahmedqasmi/PeakCut, MIT). Effort numbers are my estimates in working days for one developer using AI-assisted coding.

How to read this doc: the Verdict first, then Parts A to F (verified defaults, language support, hardware, manual editing, ideas, face reframing). The numbered sections 0 to 9 follow (review findings, decision log, roadmap, pool spec, eval, fork setup, risks, first tasks). Where Parts A to F conflict with a numbered section, Parts A to F win.

## Verdict (final v1, 2026-11-16)

Go, with one gate: run the line-level code audit (Task 1) before merging Tasks 2 and 3, because studio/\*.py could not be read here. Every other recommendation is research-backed with sources inline; open items are tagged UNVERIFIED.

- **Keep:** Parakeet for English, sherpa-onnx, the loudness-only fallback, the ai.py provider seam.
- **Add:** a native pool provider (Groq, Cloudflare, local Ollama by default; strict privacy), nightly yt-dlp with a pinned Deno, ffmpeg fetched at first run.
- **Ship:** a portable zip, with API keys in a passphrase-encrypted file.
- **Hindi/Urdu:** Whisper large-v3-turbo by default, IndicConformer only if the eval wins; test caption shaping first; manual caption, trim and crop editing covers what the models get wrong (section D).
- **Target:** mid = 4+ cores and 8 GB RAM; local LLM off on 8 GB.
- **Editing and reframing:** manual caption, trim and crop tools and a review queue (section D); optional face-aware reframing that is default-off and toggleable per clip, with manual crop always winning (section F).
- **Order:** Task 1 (audit, fork hygiene), then Tasks 2 (bootstrap) and 3 (pool), which can run in parallel. After that: S3 portable build, S4 resume and caching, S5 eval, S6 quality, then S6d Hindi/Urdu, S6e manual editing, S6f face reframing (default-off).
- **Biggest unknowns:** what the code actually does (update check, key storage, yt-dlp arguments), Whisper speed on 4 cores, Urdu and Devanagari caption rendering, free-LLM scoring quality on Hindi and Urdu.

Assumptions: personal plus public open-source use, no hosted shared service, Windows-first and portable (runs from a folder, no installer required), target hardware mid to high (mid = 4+ cores such as an Intel i5 8th gen with 8 GB RAM; high = 8+ cores, 16 GB or more, optional NVIDIA GPU); low-end machines are not a target and get the loudness-only fallback.

## A. Risk-free defaults (verified 2026-11-15)

Each default is reversible, has a primary or official source, and avoids terms-of-service gray areas. Where this section conflicts with the decision log or roadmap, this section wins.

| Area | Default | Evidence | Remaining risk |
| --- | --- | --- | --- |
| Speech-to-text | Keep Parakeet TDT 0.6B int8 via sherpa-onnx on CPU. Whisper large-v3-turbo only for languages Parakeet v3 lacks (it covers 25 European ones) | Self-published CPU benchmark: about 29.7x real time on an i7-12700KF, 17x on an i7-4790, vs 7.6x for faster-whisper small int8 (https://github.com/groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai). Open ASR word error rate: Parakeet v2 6.91%, v3 7.03%, Whisper large-v3 8.18% (https://micdrop.dev/blog/top-open-source-speech-to-text-models). Prebuilt Windows x64 sherpa-onnx wheels exist (https://pypi.org/project/sherpa-onnx-core/2.0.1/) | Which Parakeet variant PeakCut ships is UNVERIFIED (check fetch\_model.py). Benchmarks are third-party |
| Canary-Qwen, Moonshine | Not defaults. Test Moonshine v2 for live mode in the eval only | Canary-Qwen has the lowest listed error (5.63%) but is 2.5B parameters, English-only, GPU-class (https://www.gladia.io/blog/best-open-source-speech-to-text-models, https://chutes.ai/docs/models/vonkaiser-audiodojo). Moonshine is MIT, CPU, streaming (micdrop link above) | No PeakCut-specific measurement |
| yt-dlp | Official release binary on the nightly channel, checked daily | yt-dlp recommends nightly for regular users (https://github.com/MatyInfo/yt-dlp). Official executables include the yt-dlp-ejs component (https://github.com/yt-dlp/yt-dlp/issues/15012) | YouTube can still break extraction |
| JS runtime | Deno >= 2.3.0, pinned and tested in CI. Fallback QuickJS-NG >= 0.12.0. Never Bun | Deno is recommended and the only runtime enabled by default; others need `--js-runtimes`; older QuickJS-NG can take minutes (https://forgejo.cuqmbr.xyz/mirrors/yt-dlp/wiki/EJS). yt-dlp 2026.07.04 raised minimums (Deno 2.3.0, Node 22) and limited Bun (https://www.videohelp.com/software/yt-dlp/version-history, https://github.com/yt-dlp/yt-dlp/issues/16766) | yt-dlp can raise minimums on update, so CI runs a real extraction nightly |
| ffmpeg | BtbN win64 GPL static build, pinned to a dated monthly release with its checksums.sha256, fetched at first run. Not bundled in the zip or installer | The LGPL variant lacks libx264 and libx265 (https://github.com/BtbN/FFmpeg-Builds). The last 14 daily builds and each month's last build (kept two years) exist, so pin, never float on latest; the zip is about 163 MiB (https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest) | Not bundling avoids GPL redistribution duties: my reasoning, not legal advice. Confirm render.py needs libx264. Pins expire after two years, so CI bumps them |
| Packaging | Portable zip: embeddable Python plus pip-installed wheels, data beside the app. Inno Setup optional later. No PyInstaller in v1 | No compile step because wheels exist (PyPI link above). PyInstaller with native libraries needed iterative hidden-import fixes in one project plan (https://glama.ai/mcp/servers/@iconben/z-image-studio/blob/f68b108e8cd0e310dafce1accc861cb341a1abf9/docs/.planning/41-windows-installer-plan.md). windows-latest reportedly ships Inno Setup, so install via Chocolatey only if ISCC.exe is missing and assert its path (https://github.com/thpoll83/wincompose/pull/3) | Effect of unsigned downloads on Windows warnings UNVERIFIED; decide on signing before a public release. Needs a writable-folder fallback. Gate: clean-VM run from a fresh folder |
| Key storage | Portable default: Fernet-encrypted key file in data/, key derived from a user passphrase. Optional machine-bound mode: master key in Windows Credential Manager via python-keyring | The WinVault backend stores encrypted passwords in Credential Manager and needs pywin32 (https://sources.debian.org/src/python-keyring/25.7.0-1/keyring/backends/Windows.py). The 2560-byte blob cap is ample for 32 bytes (https://www.github.com/zalando/go-keyring/blob/master/keyring\_windows.go) | Credential Manager keys stay with that PC and Windows user, so they do not travel with a portable folder. Same-user processes can read unlocked keys. The passphrase scheme is my design, no source |
| Pool v0 providers | Groq, Cloudflare Workers AI, local Ollama. Everything else opt-in | Groq docs: gpt-oss-120b free = 30 RPM, 1K RPD, 8K TPM, 200K TPD, per organisation not per key, with x-ratelimit-\* headers (https://console.groq.com/docs/rate-limits.md, https://www.bolna.ai/docs/custom-llm-inference/groq.md). Capacity estimate: at about 30K tokens per video hour (my estimate), 200K TPD is roughly 6 video hours a day on Groq alone | Tokens per video hour UNVERIFIED until the eval measures it. Cloudflare's daily Neuron cap is verified, but tokens per Neuron vary by model, so its token capacity is UNVERIFIED |
| Gemini | Opt-in only | Limits are per project, not per key (https://ai.google.dev/gemini-api/docs/rate-limits); free tier may train on data outside EEA, Switzerland and the UK (https://www.developersdigest.tech/models/free-api) | Terms scope: see FreeLLMAPI ToS note in section 4.1 |
| Local Ollama | Local only. Keep Ollama Cloud out of the JSON pool | Cloud does not support structured outputs; local accepts a JSON schema in `format` (https://docs.ollama.com/capabilities/structured-outputs) | Small models still need validation and retry |
| Local model size | 8 GB RAM: local LLM off by default (use the pool, then loudness-only); opt-in qwen3.5:4b only with other models unloaded. 16 GB or more: qwen3:8b. Always validate and retry | Qwen3 8B Q4 about 5 GB, Gemma 3 4B about 2.6 GB (https://dev.to/joseph\_orduna\_b458c7df808/which-local-llm-fits-your-ram-best-ollama-models-for-4gb-8gb-16gb-and-32gb-in-2026-2dmf). Qwen3.5 4B is 3.3-4.0 GB with vendor-reported benchmarks (https://www.promptquorum.com/local-llms/small-local-llm-models) | Clip-scoring quality UNVERIFIED. Fallback tier, not a quality tier |
| Posting | Export-only default, posting opt-in | Official quota page (updated 2026-11-12): videos.insert has its own bucket, 100 calls/day by default at cost 1, so 1600 is legacy (https://developers.google.com/youtube/data/determine\_quota\_cost). Unverified projects upload private-only (https://developers.google.com/youtube/v3/docs/videos/insert) | Audit effort if you want public uploads |

**Rejected as risky:** Bun runtime; the floating ffmpeg latest build; GPL ffmpeg inside the zip or installer; Ollama Cloud for JSON scoring; several keys per provider; auto-posting on by default; Cerebras as a default (card requirement still conflicts between sources); PyInstaller as the first packaging attempt; Canary or Moonshine as defaults before an eval.

**Still not verified:** the Sieve blog, live-stream highlight papers, OpusClip-style feature gaps, Instagram and TikTok quotas, Z.ai current limits, Cloudflare tokens per day, and everything inside studio/\*.py.

## B. Language support: English, Hindi, Urdu (verified 2026-11-15)

Parakeet stays the English default. Hindi and Urdu need a second model, chosen by a per-job language setting (auto, English, Hindi, Urdu). Auto-detection on the first 30 seconds is my design and UNVERIFIED.

| Language | Safe default | Optional upgrade (flag-gated, enabled only if the eval wins) | Evidence |
| --- | --- | --- | --- |
| English | Parakeet TDT 0.6B int8 | none | See the speech-to-text row above |
| Hindi | Whisper large-v3-turbo (covers English, Hindi, Urdu in one model) | IndicConformer-600M int8 via ONNX Runtime (MIT, no English) | Hugging Face leaderboard Hindi (Monsoon) word error: IndicConformer 8.47% vs Whisper large-v3 28.17% (https://huggingface.co/udgamlabs/Shruti). Community int8 build: 0.74 GB on disk, about 2.5 GB RAM, about 0.29 s of CPU per audio second (https://huggingface.co/hazardscarn10/indic-conformer-600m-int8) |
| Urdu | Whisper large-v3-turbo | A Urdu fine-tune of Whisper large-v3, opt-in only | Self-reported: 16.7% FLEURS and 16.0% Common Voice, 35.4% on Urdu-English code-switch (https://huggingface.co/emads/whisper-large-v3-urdu-v2); a turbo fine-tune 26.2% on Common Voice 17 (https://huggingface.co/kingabzpro/whisper-large-v3-turbo-urdu). IndicConformer lists Urdu among its 22 languages (https://huggingface.co/hazardscarn10/indic-conformer-600m-int8) |
| Hinglish / Urdu-English mix | Whisper large-v3-turbo plus human caption review | none verified | Best open code-switch figure found is 35.4% word error (Urdu link above) |

**Notes**

- Whisper large-v3-turbo has 809M parameters and needs about 6 GB of VRAM in PyTorch; its q5\_0 whisper.cpp build is a 574 MB file (https://pinggy.io/blog/best\_open\_source\_self\_hosted\_speech\_to\_text\_models/). CPU speed on low-end hardware is UNVERIFIED, so measure it on a mid-tier machine (4 cores, 8 GB RAM) before promising Hindi/Urdu.
- IndicConformer packaging: sherpa-onnx per-language int8 files exist for Bengali, Gujarati, Kannada, Malayalam, Marathi, Punjabi, Tamil and Telugu, but not Hindi or Urdu (https://huggingface.co/nikh360pro/capsbro-indic-conformer). Use ONNX Runtime directly with a pinned, hash-checked file. All int8 builds above are community-made, so treat them as opt-in until verified.
- Opt-in cloud fallback: Groq's free whisper-large-v3 allows 20 requests/min and 7,200 audio seconds/hour (https://fast.io/resources/groq-rate-limit/). Audio leaves the machine, so it needs explicit consent and stays off in strict privacy mode.
- Captions: Urdu is right-to-left Arabic script and Hindi is Devanagari. Whether render.py shapes both correctly (Pillow needs a text-layout engine for complex scripts) are UNVERIFIED. The README lists the bundled caption fonts as Anton, Archivo Black and Poppins; whether they cover Devanagari and Arabic script is UNVERIFIED, so plan Noto-family fonts for both (check licences). Test this before any language work.
- LLM scoring quality on Hindi and Urdu transcripts is UNVERIFIED per provider; the eval set should include these languages.
- Eval mix: 60% English, 20% Hindi, 20% Urdu clips, with hand-corrected word error rate for each candidate model. Merge a Hindi/Urdu model only if it beats Whisper turbo on your own clips.

## C. Hardware profiles (mid = 4+ cores, 8 GB RAM)

Mid is the minimum supported tier: 4+ cores (for example Intel i5 8th gen), 8 GB RAM, SSD. English works well there; Hindi and Urdu work but slower. The app picks a profile at first run from detected RAM and cores (detection method UNVERIFIED, check what the existing CPU/RAM guard in config.py uses).

| Profile | Spec | Behaviour |
| --- | --- | --- |
| Standard (mid) | 4+ cores, 8 GB RAM | One job at a time, one live stream, one heavy model loaded at a time and unloaded after its stage, local LLM off, Hindi/Urdu pack optional |
| Performance (high) | 8+ cores, 16 GB or more, optional NVIDIA GPU | Parallel stages, local LLM tier available, faster Hindi/Urdu |

**Evidence for the mid tier**

- English speech-to-text: Parakeet int8 ran at about 17x real time on an older 4-core i7-4790 (https://github.com/groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai). Even a Raspberry Pi 5 reached a real-time factor of 0.21 with about 1.76 GB RAM (https://hashnode-hub.vercel.app/posts/68262037cbfffe5887227bb0). An i5 8th gen should be in the same range or better (extrapolation).
- Whisper large-v3-turbo (Hindi/Urdu default): RAM estimates conflict, about 1.9 GB (https://pypi.org/project/offline-stt-router/) versus about 4 GB (https://github.com/aralde/whisperhook), so budget 4 GB. One heuristic estimate gives about 3.5x real time on an 8-core CPU (offline-stt-router link); on 4 cores I expect roughly 1-2x real time, UNVERIFIED. A one-hour Hindi video may take 30-60 minutes to transcribe.
- Whisper small is the lighter fallback (about 0.9-1.2 GB RAM, same sources), but its Hindi/Urdu quality is UNVERIFIED, so offer it only as a draft mode.
- IndicConformer int8: about 2.5 GB RAM (https://huggingface.co/hazardscarn10/indic-conformer-600m-int8).
- qwen3.5:4b: 3.3-4.0 GB (https://www.promptquorum.com/local-llms/small-local-llm-models). With Windows and a browser already using several GB (my estimate), that is too tight on 8 GB, hence off by default.

**Rules**

- Never load two heavy models at once on Standard. Order: speech-to-text, unload, then scoring, then rendering.
- Defaults on Standard: `PEAKCUT_JOB_WORKERS=1`, `PEAKCUT_MAX_LIVE=1`; keep the existing free-RAM and CPU guards (`PEAKCUT_MIN_FREE_RAM_GB`, `PEAKCUT_BUSY_CPU`).
- Hindi/Urdu pack download checks free RAM and disk first and warns when the machine is Standard.
- Acceptance: on a 4-core, 8 GB machine, record end-to-end time and peak RAM for a one-hour English video and a one-hour Hindi video, then set the performance budget from those numbers.

## D. Manual editing tools (feasible, scoped)

All of the tools below are feasible. The README confirms the pipeline renders word-by-word captions in three styles and that the UI is plain HTML and JavaScript with no build step (https://github.com/muzammilAwan-dev/PeakCut). Whether any manual editor exists today is UNVERIFIED, because the README does not mention one; Task 1 should check.

**Design rule:** edits are saved as a small per-clip override file, and only the cheap render step reruns. Edits therefore survive restarts and re-scoring, and no transcription or AI call is repeated. Logic stays on the server with validated inputs; the browser UI stays thin, since UI code is hard to unit-test here.

| Tool | What it does | Feasibility | Est. days |
| --- | --- | --- | --- |
| Caption editor | Edit words in a list, merge or split words, find-and-replace across clips, re-render | Easy to medium. An edited word keeps its time slot; a split or merge shares the time proportionally (my design) | 4-5 |
| Trim handles | Move a clip's start and end on the source video with a preview | Easy | 2 |
| Static crop | Drag a 9:16 window over a preview frame, per clip | Medium; must hook into the existing render layouts | 2-3 |
| Add, remove, reorder clips | Mark in and out points by hand, drop AI picks | Easy | 2 |
| Style tweaks | Caption style, position, size, hook text | Easy | 1-2 |
| Export captions | SRT or ASS file plus the clip, to finish in CapCut or DaVinci | Easy; a cheap escape hatch | 1 |
| Moving crop | Pan between 2-3 crop keyframes | Medium to hard; add later | 3-4 |

Estimates are mine, for one developer using AI-assisted coding. Total for the first six rows is about 12-15 days, built in this order: caption editor and trim first, then crop, then the rest.

**Not in the first release:** automatic face-tracking reframing, which moves to slice S6f (section F) and stays default-off until the eval passes and a full timeline editor (do not build; export to an editor instead).

**Why this matters for Hindi and Urdu:** transcripts of Hindi, Urdu and mixed speech will have errors (section B), so manual caption editing is the safety net. Its prerequisite is script support in the renderer: right-to-left shaping and fonts that cover Devanagari and Arabic script.

**Acceptance (slice S6e):** correct a caption and see the fixed clip without rerunning transcription or the AI; edits persist after a restart; a deleted pick is not re-added on rerun; trimming and cropping change only that clip.

## E. Ideas from the FuseClip 0.75.1 research bundle (feature-level only)

Source: the uploaded research bundle, a static analysis of a third-party desktop app. Its own README says to keep it private and to write your own implementation and prompts. Use only the feature ideas below. Do not copy its recovered code, prompts, caption style names, fonts or assets. I did not assess whether analysing that app was permitted by its licence; this is not legal advice.

| # | Idea | Why it helps | Days (my est.) | Slice |
| --- | --- | --- | --- | --- |
| 1 | Review queue: proposed, edited, approved, resumable after restart. Auto-approve is a setting, off by default, on for live and auto-post | Human control; safe posting | 3 | With S6e |
| 2 | Propose, then verify: the LLM returns approximate times plus the opening and closing words; code aligns them to word timestamps, snaps to sentence ends, enforces duration, drops overlaps and duplicates. Optional second LLM review of the final cut text. Verified clips rank first | Fewer bad cuts and invented timestamps; treats LLM output as untrusted | 4-5 | S6 |
| 3 | Overlap between transcript chunks (10-15%, my estimate) with dedupe; a second pass excluding found ranges when too few clips come back | No moments lost at chunk edges | 1-2 | S2 chunker, S6 |
| 4 | Transcript-aware fallback: when the pool is exhausted, pick sentence-based candidates using transcript plus loudness, not loudness alone | Better last tier | 2-3 | S2, S6 |
| 5 | Hindi/Urdu caption repair: LLM correction with stable cue IDs, a script check that rejects output in the wrong script, token-bounded batches, a user glossary of names. Optional conversion of Hindi-recognised text to Roman or Urdu script | Targets the weakest language path | 4-5 | S6d |
| 6 | One emphasised word per caption line, chosen by an LLM batch with neighbour context, falling back to plain text | Cheap visual polish | 2 | S6e |
| 7 | Layout presets: blurred-background fit, centre crop, top/bottom split for two speakers; aspect presets 9:16, 1:1, 4:5, 16:9 | Covers more platforms; blur-fit is plain ffmpeg | 2-3 | S6e |
| 8 | Optional face-aware reframing: small CPU face detector, smoothly interpolated keyframes, centred fallback, always manually overridable. Speaker-by-mouth-motion is a heuristic only | The smart-crop feature | 5-6 | S6f (section F) |
| 9 | Output revision key: a hash of clip range, transcript, style, layout, encoder and engine versions decides whether to re-render | No stale or needless renders | 1-2 | S4, S6e |
| 10 | Undo and redo through saved revisions (the bundle found no undo in that app's editor) | Cheap differentiator | 1-2 | S6e |
| 11 | Portable project hygiene: schema version and migrations, relative paths, relink if the source video moved, identity by size plus partial hash rather than name | Folder moves between PCs | 2-3 | S3, S4 |
| 12 | Transactional export and job supervisor: write a .part file then rename; cancel kills the whole ffmpeg process tree and cleans temp files; states success, cancelled, partial, failed, cleanup-pending | No corrupt or half clips | 2-3 | S4 |
| 13 | Consent preview: show exactly which text goes to which provider before sending | Trust; fits the privacy toggle | 1 | S2 |
| 14 | Brand kit: watermark, overlay, user-supplied music only | Creator branding | 2-3 | Later |

**Whisper engine options for the Hindi/Urdu path** (decide by measured speed and error rate on a mid machine): sherpa-onnx Whisper (no new dependency), whisper.cpp (single CLI, no Python; it takes 16 kHz WAV and supports CUDA and Vulkan, https://github.com/ggml-org/whisper.cpp), or faster-whisper. whisper.cpp memory is about 2.1 GB for medium and 3.9 GB for large (https://github.com/borgoat/whisper.cpp); a third-party wrapper lists large-v3-turbo-q5\_0 at 547 MiB (https://pub.dev/documentation/flutter\_whisper\_ggml/latest/). Prebuilt Windows binary availability is UNVERIFIED.

**Where PeakCut can be ahead:** the bundle found no integrated online-video downloader, no manual crop editor and no undo in that app. PeakCut already has link import, live clipping, posting and workspaces.

**Avoid:** automating third-party AI websites with a browser session (fragile, terms risk), broad file access from the UI, downloads without hash checks (the bundle saw no model digest check), and any claim to predict virality.

## F. Face-aware reframing (slice S6f, medium effort)

Verdict: feasible as an optional, default-off step with one new module and one hook in the render step. Whether that counts as no big structural change depends on how render.py crops today, which is UNVERIFIED; the Task 1 audit must confirm it.

**Switches (always under your control)**

- **Mode per project and per clip:** Off (today's behaviour), Centre, or Auto (faces). Default is Off until the eval passes.
- **Auto is on request or opt-in:** an "Analyze this clip" button, or automatic for approved clips if you enable it. It has a time limit and can be cancelled. If it times out or fails, the clip falls back to centre or fit and the app says so.
- **Manual crop always wins:** saving a manual crop locks that clip's framing, and re-running Auto never overwrites it. "Reset to Auto" is one click.
- **Off costs nothing:** the detector and OpenCV are not even loaded.

**Zoom and podcast layouts**

- **Zoom** means a smaller crop window around the face, so the face fills more of the frame. Each framing keyframe carries a centre point and a zoom level (my design). The FuseClip analysis describes the same idea there: focus, confidence and zoom keyframes, smoothly interpolated. That is static analysis, so how it actually looks is unverified.
- **Two people in one wide podcast shot:** a vertical crop cannot hold both. Offer a top/bottom split with one crop per face, or a blurred-background fit. Following the active speaker comes later and needs speaker detection, which is a heuristic and UNVERIFIED.
- **Version 1:** one static zoom per shot, adjustable with a slider. No animated punch-in zooms.

**Design**

1. Run only on approved clips, after the review queue, never on the whole video. This keeps CPU use low on mid machines.
2. Sample 2-4 frames a second of the clip at about 320-640 px wide with ffmpeg (my choice of rate).
3. Detect faces with YuNet through OpenCV's `FaceDetectorYN`.
4. Find shot cuts with ffmpeg's scene filter; its docs call a threshold between 0.3 and 0.5 generally sane (https://ffmpeg.org/pipermail/ffmpeg-devel/2012-December/135576.html).
5. Per shot, pick the main face (largest and most consistent) and place the eyes in the upper third (my design). Version 1 uses one static crop per shot, so nothing drifts. A gentle pan with a dead zone and a speed cap comes later.
6. Save the result as framing keyframes in the same per-clip override file as the manual crop tool (section D), so the editor shows and edits them.
7. Render with ffmpeg's `crop` filter: x and y are evaluated for every frame and can use time `t`, while width and height are evaluated once (https://ffmpeg.org/pipermail/ffmpeg-devel/2010-September/101061.html, from the patch that introduced it; confirm on current docs). If the expression gets too long, render per-shot segments instead (expression length limit UNVERIFIED).
8. Fallbacks: no face or low confidence gives a centre crop or blurred-background fit; two or more similar faces give a fit or top/bottom split. Never an erratic crop.

**Evidence**

| Item | Finding | Source |
| --- | --- | --- |
| Model | YuNet, MIT licence; the pinned 2026may file is 229,738 bytes; loads through `FaceDetectorYN` on CPU | https://www.learnopencv.com/face-detection-opencv/ |
| Accuracy | WIDER Face AP 0.834 easy, 0.824 medium, 0.708 hard; detects faces of roughly 10x10 to 300x300 px | https://github.com/opencv/opencv\_zoo/blob/main/models/face\_detection\_yunet/README.md |
| Speed | libfacedetection's own benchmark: about 9.5-30 FPS at 320x240 on a Raspberry Pi 4. I expect a mid PC to be faster; we need only 2-4 samples a second | https://awesome.ecosyste.ms/projects/github.com%2Fshiqiyu%2Flibfacedetection |
| Version fit | OpenCV 4.x needs the fixed-shape 2023mar model; the dynamic 2026may model targets OpenCV 5 | https://huggingface.co/pollen-robotics/face\_detection\_yunet\_2023mar |
| Licence caution | The model is MIT, but a third-party model card lists its training set WIDER Face as CC-BY-NC-ND-4.0. Whether that affects the weights is a legal question I cannot answer; low concern for a free tool, review before any monetisation | https://huggingface.co/Blaize-AI/YUNet\_Widerface |

**Decisions**

- Pin `opencv-python-headless` 4.x with the 2023mar model, and ship the roughly 230 KB model file in the repo with its MIT notice. Wheel size is UNVERIFIED. It is the shortest path to a tested detector; the alternative (onnxruntime plus our own decoding) is more code.
- No active-speaker detection in version 1. Mouth-motion guessing is a heuristic and comes later, if at all.

**Known limits**

- Misses very small, side-on, masked or covered faces.
- Screen recordings and gaming streams need facecam handling, which is later.
- Camera pans inside a shot are not followed in version 1.

**Cost (my estimate, about 8 days):** analyzer 3, render hook 2, editor integration 2, eval 1-2. A pan smoothing pass adds about 2 more.

**Acceptance and eval:** against a centre-crop baseline on 20 clips, the main face is fully in frame in at least 95% of sampled frames (my proposed bar); added time is at most about 20% of render time (my proposal); a blind A/B on the same clips is not worse; the crop moves only at shot cuts. Default-on only if all of these pass.

## 0. Evidence status (read first)

| Area | Status |
| --- | --- |
| README, AGENTS.md, .env.example (fork main) | Read |
| studio/\*.py (ai.py, jobs.py, brain.py, media.py, live.py), tests/, web/, DEPLOY.md | **NOT read.** GitHub's folder pages block automated access and the file URLs could not be retrieved |
| Free-tier data, yt-dlp, TF-SELECTOR, FreeLLMAPI, YouTube API | Read, links inline |
| Sieve blog, live-stream highlight papers, OpusClip-style feature gaps, Instagram/TikTok quotas, yt-downloader-pro code | **UNVERIFIED** (not researched) |

Consequence: section 1 is architecture-level from AGENTS.md, with no line citations. Task 1 (section 8) produces the line-level audit before anything is built. Items tagged "check in code" must be confirmed there. Update 2026-11-15: a second verification pass resolved the YouTube quota conflict and checked the yt-dlp runtime, ffmpeg, Groq, Ollama, keyring and packaging claims; see sections A to C above (risk-free defaults, language support, hardware profiles).

## 1. Code-review findings

### Architecture map (source: https://github.com/muzammilAwan-dev/PeakCut/blob/main/AGENTS.md)

| File | Role |
| --- | --- |
| studio/server.py | All routes + pre-request gate |
| studio/config.py | All settings from env |
| studio/ai.py | Only code that talks to an AI service; dashboard AI settings in ai.json |
| studio/brain.py | Prompts (clips, live judging, hooks/titles, caption fixes) |
| studio/usage.py | AI call/token ledger for the usage page |
| studio/jobs.py | Video pipeline + fair queue |
| studio/live.py | Live recording and clipping |
| studio/transcribe.py, asr\_worker.py | Parakeet STT, local or remote GPU box |
| studio/render.py | ffmpeg + Pillow cutting, layouts, captions |
| studio/media.py | yt-dlp download, probe, audio |
| studio/auth.py, account.py, admin.py, db.py | Accounts, admin, SQLAlchemy core (SQLite/Postgres) |
| web/index.html | Whole app, one file, no build step |

### Findings

| # | Finding | Impact |
| --- | --- | --- |
| F1 | README says PeakCut checks GitHub every few hours for a newer version and shows an update notice with a `git pull` hint (`PEAKCUT_UPDATE_CHECK`). In a fork this likely points at upstream. Check in code | **High**: users could be told to pull upstream over the fork. Repoint or disable first |
| F2 | Install is git clone, pip, ffmpeg on PATH, 480 MB model download (README) | Blocks goal 2 |
| F3 | README names only ffmpeg and yt-dlp. No JS runtime, no update channel. YouTube extraction now wants a JS runtime (https://gigazine.net/gsc\_news/en/20250925-yt-dlp-deno-javascript-runtime) and stable lagged nightly during the Aug 2026 SABR/PO-token 403s (https://github.com/EvroHQ/EvroHQ-YouTube-Downloader/releases). Check media.py | Fresh installs likely fail on YouTube |
| F4 | `PEAKCUT_AI_MODELS` takes comma-separated ids "tried in order" (.env.example), but within one provider and one key. No cross-provider failover, cooldowns or quota tracking | Gap for goal 1 |
| F5 | **Good seam:** a provider is a `PROVIDERS` row, or one function returning `(parsed JSON, tokens in, tokens out)` (AGENTS.md). A `pool` adapter fits without touching brain.py | Keep |
| F6 | No key already means loudness-only (README) | Keep as terminal tier. Check in code whether a mid-job provider failure degrades or fails the job |
| F7 | Dashboard-saved key lives in the data folder (README), settings in ai.json (AGENTS.md). Encryption at rest UNVERIFIED, assume plaintext | Goal 5 |
| F8 | Untrusted text handling exists: `brain._safe`/`brain._text`, site allowlist `PEAKCUT_ALLOWED_SITES`, `*_FILE` secrets | Keep. Check whether LLM JSON is schema-validated |
| F9 | README: a one-hour video is read in about four requests | Request count is tiny. The binding free-tier limit is tokens per minute (e.g. Groq gpt-oss-120b 8K TPM, see section 4), so chunk size drives design |
| F10 | Accounts, admin, Postgres, Caddy, Cloudflare, SMTP = a server product | Keep working, freeze. Do not extend for the Windows desktop path |
| F11 | jobs.py holds pipeline and fair queue (AGENTS.md). Coupling UNVERIFIED | Likely the checkpoint insertion point |
| F12 | Single-file UI, no build | Fine for an extension API. Hard to unit test |

**Keep:** ai.py seam, `_safe/_text`, loudness fallback, tests/run.py throwaway-server harness, `ctx.bump()` pattern, short-temp-folder rendering (Windows 260-char limit). **Replace/extend:** install path, yt-dlp invocation, key storage, update check, single-provider fallback. **Leave alone:** accounts, Postgres, deploy files.

Interim win with zero code: the existing `custom` provider accepts any OpenAI-compatible URL, so FreeLLMAPI or OpenRouter can be pointed at today.

## 2. Decision log

| ID | Decision | Options | Chosen and evidence | Reversal cost |
| --- | --- | --- | --- | --- |
| D1 | Where the free pool lives | A native `pool` in ai.py; B run FreeLLMAPI as a sidecar; C LiteLLM-style library | **A.** FreeLLMAPI is Node/Express, single-user by design, self-labels personal experimentation and its router uses a bandit plus persistent ledger (https://github.com/tashfeenahmed/freellmapi/blob/main/docs/en/architecture/00-high-level-index.md). Borrow the ideas (cooldown on 429/5xx, RPM/RPD/TPM/TPD ledger, health probe), skip the bandit in v1. B stays available through `custom` | Low |
| D2 | Provider catalog | Hardcode; community providers.json on GitHub raw; paid live feed | **Bundled default plus optional raw fetch, hash-checked.** Limits for Gemini, Mistral and Z.ai are shown only in logged-in consoles, and Groq publishes only sample limits with exact values on its console page (https://www.developersdigest.tech/models/free-api, https://ai.google.dev/gemini-api/docs/rate-limits), so limits are optional hints and the ledger learns from 429s | Low |
| D3 | Multiple keys per provider | Pool several keys; one account per provider | **One per provider.** Gemini limits are per project, not per key (https://ai.google.dev/gemini-api/docs/rate-limits), so extra keys in one project add nothing. FreeLLMAPI's own ToS review advises one account per provider, no resale, no sharing | Low |
| D4 | Privacy default | Any free provider; strict no-training only | **Strict by default**, toggle to relax. Per the 2026-10-18 read: Gemini free may train outside EEA/CH/UK, Mistral Free trains unless opted out, OpenRouter depends on the serving provider. Cost: smaller pool | Low |
| D5 | Scoring approach | LLM on whole transcript; TF-SELECTOR-style segments; plus visual captions | **Segments from transcript sentences and audio energy, LLM scores segments.** TF-SELECTOR: transcripts add the most, audio volume alone is weak, scoring-LLM choice matters more than captioner (https://www.alphaxiv.org/abs/2606.06926). Skip per-segment VLM captions (cost). Caveat: benchmark is sports broadcasts and best HIT@1 is 26.56, so transfer to talking-head content is UNVERIFIED and must be measured | Medium |
| D6 | Two-stage pipeline | Single pass; audio candidates then LLM | **Two-stage.** Cuts tokens per hour, which is the free-tier bottleneck (F9) | Medium |
| D7 | Eval before quality work | Build quality features first; harness first | **Harness first.** Without it D5/D6 are unfalsifiable | n/a |
| D8 | yt-dlp engine | System/pip install; bundled stable; bootstrapped nightly | **Bootstrapped nightly plus daily check.** yt-dlp recommends nightly for regular users (https://github.com/MatyInfo/yt-dlp); the official exe bundles yt-dlp-ejs (https://github.com/yt-dlp/yt-dlp/issues/15012). A downloader fixed PO-token/SABR 403s by moving to nightly (https://github.com/EvroHQ/EvroHQ-YouTube-Downloader/releases). Verified 2026-11-15. | Low |
| D9 | JS runtime | Deno; QuickJS-NG; Node | **Deno >= 2.3.0 pinned**, QuickJS-NG >= 0.12.0 fallback, never Bun. Deno is the only runtime enabled by default; yt-dlp 2026.07.04 raised minimums and deprecated Bun (https://www.videohelp.com/software/yt-dlp/version-history). Other runtimes need `--js-runtimes` (https://forgejo.cuqmbr.xyz/mirrors/yt-dlp/wiki/EJS). Verified 2026-11-15. | Low |
| D10 | Windows packaging | PyInstaller; embeddable Python + Inno Setup; Briefcase; WPF launcher | **Portable zip as the primary build: embeddable Python plus pip-installed wheels in one folder, data in a `data/` folder beside the app; first-run bootstrap fetches ffmpeg, yt-dlp, deno and the STT model into `bin/` and `models/`. Optional Inno Setup wrapper later.** sherpa-onnx has win\_amd64 wheels, so no compile step (https://pypi.org/project/sherpa-onnx-core/2.0.1/). Falls back to %LOCALAPPDATA%\\PeakCut when the folder is not writable. Keep the folder path short (Windows 260-character limit). Effect of unsigned downloads on Windows warnings UNVERIFIED. Gate: clean-VM run from a fresh folder. | Medium |
| D11 | Audio-first download | Full video; audio then `--download-sections` | **Audio first, then sections of chosen moments** (feature listed in README mirror https://github.com/EricRa/yt-dlp). Section accuracy and SABR behaviour UNVERIFIED, so test on 10 videos before committing | Medium |
| D12 | Key encryption | Plain file; Fernet with key file; OS keyring (DPAPI) | **Portable mode: Fernet-encrypted key file in `data/`, key derived from a user passphrase (scrypt) and asked at start. Optional machine-bound mode: master key in Windows Credential Manager via python-keyring (needs pywin32).** Credential Manager keys stay with that PC and Windows user, so they do not travel with a portable folder. The passphrase scheme is my design (no source). Same-user processes can read unlocked keys. | Low |
| D13 | Auto-posting default | Keep as is; default to export-only | **Export-only default, posting opt-in.** Resolved 2026-11-15: the official quota page (updated 2026-11-12) gives videos.insert its own bucket, 100 calls/day at cost 1, so the 1600 figure is legacy (https://developers.google.com/youtube/data/determine\_quota\_cost). Unverified projects still upload private-only (https://developers.google.com/youtube/v3/docs/videos/insert). | Low |
| D13b | Instagram/TikTok posting | Expand; freeze | **Freeze.** Quotas and review rules UNVERIFIED | Low |
| D14 | Extension | Build now; last | **Last.** Needs stable local API and token | Low |

## 3. Phased roadmap (thin vertical slices)

Each slice ships alone and ends with `python tests/run.py` green on Windows and Linux CI.

| Slice | Scope | Days | Depends | Acceptance |
| --- | --- | --- | --- | --- |
| S0 Fork hygiene | LICENSE keeps original notice plus a fork line; README fork section; update check repointed; CI | 1 | none | CI green; update notice never references upstream commits |
| S1 Engine bootstrap | studio/bootstrap.py fetches ffmpeg, yt-dlp (nightly), deno into the app's bin/ folder (fallback: the per-user app-data folder when not writable) with SHA-256 pins; daily yt-dlp update | 4 | S0 | Clean machine with no ffmpeg/Python tools on PATH downloads a public YouTube video; second run downloads nothing; offline start still works |
| S2 Pool v0 | `pool` provider, bundled providers.json, ledger, cooldown, privacy toggle, ends in loudness-only | 5 | S0 (parallel to S1) | Mock-provider tests: 429 failover, malformed-JSON retry, all-dead falls to loudness-only, strict mode excludes non-verified providers |
| S3 Portable build | Portable zip (embeddable Python + wheels, data/ beside the app, launcher); optional Inno Setup wrapper; CI builds the zip on tag | 4 | S1 | Fresh Windows machine or VM: unzip to any folder, run, first clip with no manual steps. Copying the folder to another PC keeps projects and settings (keys need the passphrase) |
| S4 Audio-first + checkpoints | Audio download, transcript/LLM cache, per-stage resume, section download of chosen moments | 6 | S1 | Kill the server mid-stage; restart resumes without repeating finished stages; cached rerun makes zero LLM calls |
| S5 Eval harness | Labeled set, metrics script, baseline report (loudness-only vs current) | 4 | S2 | One command prints precision@k, cost/hour, latency, failover rate per video |
| S6 Quality | Segmenting + audio-energy candidates -> LLM scores candidates only; instruction-driven clipping; genre prompts | 7 | S4, S5 | Beats baseline precision@k on the eval set, or is not merged |
| S6b Optional | Panel vote across 2-3 models; causal live scoring (smart reframing moved to S6f) | 3-6 each | S6 | Each flag-gated and measured; drop if no gain |
| S7 Security | Key encryption, yt-dlp arg allowlist, LLM-output schema validation | 3 | S2 | Tests for injection-style transcript, path traversal, bad args |
| S8 Extension | MV3 "Clip this" button -> local server with token | 4 | S3 | Button queues a job on localhost; no job without token |

Order note: your suggested order holds, with the harness (S5) inserted before quality work (D7). S1 and S2 are independent, so run them in parallel if using two agents. Hindi/Urdu support (section B) follows S5 as slice S6d: a caption-shaping test for Urdu and Devanagari first (1 day, my estimate), then a per-job language setting with Whisper large-v3-turbo (4 days), then IndicConformer only if the eval wins (3 days). Manual editing tools (section D) are slice S6e, after S4.

**Later slices** (details in sections B, D, E and F; days are my estimates):

- **S6d Hindi/Urdu pack** (depends on S5): caption-shaping test 1, language setting plus Whisper turbo 4, caption repair 4-5, IndicConformer 3 only if the eval wins.
- **S6e Manual editing** (depends on S4): editing tools 12-15, review queue 3, layout presets 2-3, undo through revisions 1-2.
- **S6f Face-aware reframing** (depends on S6e): about 8, default-off until it passes the eval bar in section F.
- **Cross-cutting items from section E:** output revision key (S4, S6e), transactional export and job supervisor (S4), portable project hygiene (S3, S4), consent preview (S2).

## 4. Pool provider spec

### 4.1 Free-tier snapshot (seed data, re-verify before shipping)

Sources: https://www.developersdigest.tech/models/free-api (verified by them 2026-10-18), https://github.com/open-free-llm-api/awesome-freellm-apis (2026-11-09), FreeLLMAPI ToS review (link in D1).

| Provider | Card | Published limits | Trains on data | Notes |
| --- | --- | --- | --- | --- |
| Groq | not stated | gpt-oss-120b: 30 RPM, 1K RPD, 8K TPM, 200K TPD | No | Verified against Groq's docs 2026-11-15: limits are per organisation, not per key; exact values are on the console limits page; responses carry `x-ratelimit-*` headers (https://console.groq.com/docs/rate-limits.md). Limits are per model; the awesome list quotes 14,400 RPD for llama-3.3-70b, so per-model entries are required. |
| Cloudflare Workers AI | not stated | 10,000 Neurons/day shared across models, reset 00:00 UTC; 300 RPM for text generation | No | Verified 2026-11-15 (https://developers.cloudflare.com/workers-ai/platform/pricing/, https://blog.cloudflare.com/workers-ai-ga-huggingface-loras-python-support). Tokens per Neuron vary by model, so tokens/day is UNVERIFIED; some frontier models need a paid plan. The no-training statement is quoted from Cloudflare's data terms by https://www.developersdigest.tech/models/free-api/cloudflare. ToS ambiguous (FreeLLMAPI) |
| Z.ai (GLM Flash) | not stated | console only | No for API | FreeLLMAPI flags ToS "caution" |
| Gemini | not stated | per model in AI Studio only; per project; daily reset midnight Pacific | Yes outside EEA/CH/UK | ToS narrowed to business use (FreeLLMAPI) |
| Mistral | No | console only, lowest tier | Yes unless opt-out | Opt-out toggle in Admin |
| OpenRouter `:free` | not stated | 20 RPM; 50 RPD (1000 after $10 credits) | Depends on server | Opt out of training in account to avoid those routes |
| NVIDIA NIM | phone (awesome list) | DevDigest: none published; FreeLLMAPI: 40 RPM | Not stated | Evaluation/prototyping only |
| Cerebras | **conflict** | DevDigest: $5 credits, card required, expires 30 days; awesome list: no card, 6 free models | No | Do not make default until verified |
| Cohere | not stated | 1,000 calls/month trial | Not stated | FreeLLMAPI: **avoid** (terms forbid personal use) |
| Local Ollama | none | unlimited | local | Local Ollama supports JSON-schema `format`; Ollama Cloud does not support structured outputs, so keep Cloud out of the JSON pool (https://docs.ollama.com/capabilities/structured-outputs). Optional final tier before loudness-only. |

Data quality warning: the awesome list contains visible errors (the Gemini and Cohere rows show another provider's base URL), so treat it as a lead, not a source. JSON-mode support per provider is **UNVERIFIED**; the capability probe below decides it at runtime.

### 4.2 providers.json schema

```json
{
  "schema_version": 1,
  "updated": "2026-11-15",
  "providers": [{
    "id": "groq",
    "adapter": "openai",            // openai | gemini | cloudflare | anthropic
    "base_url": "https://api.groq.com/openai/v1",
    "key_env": "GROQ_API_KEY",
    "signup_url": "https://console.groq.com/keys",
    "requires": {"card": "no|yes|unknown", "phone": "no|yes|unknown"},
    "privacy": {"trains_on_data": "no|yes|depends|unknown", "source_url": "...", "verified_on": "2026-10-18"},
    "tos": {"note": "...", "source_url": "..."},
    "models": [{
      "id": "openai/gpt-oss-120b",
      "ctx": 131072,
      "json_mode": "schema|object|none|unknown",
      "tier": 1,                    // 1 best quality .. 3 weakest
      "limits": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000, "concurrent": null,
                 "reset": "utc|pacific|rolling", "source": "docs|observed|unknown"},
      "status": "active|deprecated"
    }]
  }]
}
```

Rules: every provider needs `privacy.source_url` and `verified_on`; PRs without a URL are rejected. Raw fetch is optional (`PEAKCUT_POOL_CATALOG_URL`), pinned to a SHA-256 shown in the release notes, falls back to the bundled copy. Local user overrides live in the data folder and win.

### 4.3 Routing, cooldowns, quotas

1. **Eligible set** = key present, not disabled, passes privacy filter, `json_mode != none`, `ctx` >= chunk need, not in cooldown, under every known limit (use 80% of published numbers).
2. **Order** = tier ascending, then most remaining headroom, then lowest recent failure rate. No bandit in v1.
3. **Ledger** (SQLite table `ai_ledger`: provider, model, minute and day buckets, req, tokens in/out, cooldown\_until, consecutive\_fail, schema\_fail). Counts survive restarts.
4. **429:** cooldown = `Retry-After` if present, else 30 s doubling to 15 min; if the daily limit is the cause (error body or RPD counter), cool down until that provider's reset. Reset times differ (Gemini: midnight Pacific; FreeLLMAPI uses UTC), hence the `reset` field.
5. **5xx/timeout:** 60 s cooldown; breaker opens after 3 consecutive failures and half-opens after 10 min.
6. **401/403:** disable the provider and surface it in the UI. Never retry.
7. **Bad JSON or schema mismatch:** one repair retry on the same provider, then next provider. Count as `schema_fail` (a quality signal), not a provider outage.
8. **Terminal chain:** pool exhausted -> local Ollama if configured -> loudness-only. The job is marked `degraded` and, because of S4 checkpoints, can be re-scored later without redoing earlier stages.
9. Learn limits from response headers where present (UNVERIFIED that all providers send them), otherwise from 429 behaviour.

### 4.4 TPM-aware chunking

`chunk_tokens = min(0.5 * ctx, 0.6 * tpm)` over the providers likely to be used, with a floor of \~2K. Estimate tokens as chars/3.5 (conservative heuristic, no tokenizer dependency). Example arithmetic: an 8K-TPM provider yields \~4.8K-token chunks; at my rough estimate of 200-400 transcript tokens per minute of speech that is about 12-24 minutes per chunk, so a one-hour video needs 3-5 chunks sent at least a minute apart. The scheduler spaces requests by the tightest TPM instead of failing and retrying.

### 4.5 Consistency across providers

Scores from different models are not comparable. v1 rule: **stickiness per job**. Pick a primary for all chunks; on mid-job failover, rescore only that chunk and normalize scores to within-job percentiles. Stage 2 (final ranking of the top N candidate summaries) always goes through one call on one provider, so cross-provider variance affects candidate generation only. Measure the effect in the eval (failover rate vs precision@k).

### 4.6 Privacy toggle

`PEAKCUT_AI_PRIVACY=strict` (default): only providers with `trains_on_data: no` and `verified_on` within 90 days. `relaxed`: also `depends` and `unknown`. `any`: includes `yes`. UI states plainly: speech-to-text stays local, but transcript text is sent to the chosen LLM provider.

### 4.7 Health checks

On key save: `GET /models` where supported (assumed not to cost quota, UNVERIFIED per provider) plus a one-time capability probe for `json_schema`, `json_object` and a 1-token completion. No periodic completion pings: OpenRouter's 50 RPD and similar caps would burn the budget. After that, health is inferred from real traffic.

### 4.8 Interface in studio/ai.py

Keep the existing contract from AGENTS.md: a provider function returns `(parsed_json, tokens_in, tokens_out)`.

```python
# studio/pool.py (new)
class Pool:
    def __init__(self, catalog, ledger, cfg): ...
    def complete_json(self, *, task, system, user, schema, job_id, est_tokens):
        """Returns (parsed, tok_in, tok_out); records route in usage.py.
        Raises PoolExhausted when nothing is eligible."""

# studio/ai.py (edit): PROVIDERS["pool"] -> one adapter calling Pool.complete_json.
# Callers treat PoolExhausted exactly like "no key": fall back to loudness-only.
```

## 5. Evaluation plan

- **Set:** 20 videos, 30-60 min each, \~4 each of podcast, gaming/live stream, interview, lecture/talk, sports. Use videos you own, have permission for, or CC-licensed. Store IDs, timestamps and labels, not the media.
- **Labels:** two people each pick their top 10 moments per video as start/end times. A system pick is a hit if it overlaps a human pick by at least 50% of the shorter span. Keep both annotators' labels and report agreement.
- **Metrics:** precision@5 and precision@10 vs human picks; cost per hour (requests, tokens in/out from usage.py); latency per stage; failover rate (rerouted calls / calls); schema-fail rate; run-to-run variance over 3 runs.
- **Baselines:** loudness-only; current upstream pipeline; new pipeline. Report per-video results plus bootstrap confidence intervals. With 20 videos, small gains are noise, so set the merge bar at a clear margin (suggest +10 points precision@5 or equal quality at 50% lower token cost).
- **Regression tests** (extend tests/run.py, which already spins up a throwaway server with no keys): a mock OpenAI-style server returning 429, 500, malformed JSON and slow responses; assertions for failover order, cooldown expiry, privacy filter, loudness-only terminal state, checkpoint resume after kill, bootstrap against a fake release server, and a prompt-injection transcript that must not alter the output schema. Test file layout UNVERIFIED, so follow the existing pattern.
- **Languages and hardware:** include English, Hindi and Urdu clips (60/20/20) and record time and peak RAM per stage on a 4-core, 8 GB machine (sections B and C).

## 6. Fork setup

- **License:** keep LICENSE as is (original copyright and permission notice must stay for MIT). Add a second line for your copyright below it. Add a README "Fork notice" naming upstream.
- **Remotes/branches:** `upstream` = haziqahmedqasmi/PeakCut. `main` = releasable. Short-lived `feat/*` branches. Merge upstream into a `sync/upstream-YYYY-MM` branch monthly, test, then merge to main.
- **Merge-friendly rule:** additive modules (studio/pool.py, studio/bootstrap.py, installer/), minimal edits to ai.py, media.py, config.py.
- **Structure additions:** `installer/` (launcher, optional Inno Setup script), `studio/providers.default.json`, `eval/` (labels, scripts, reports), `docs/` (AUDIT.md, DECISIONS.md, POOL.md), `.github/workflows/`.
- **CI:** GitHub Actions on windows-latest and ubuntu-latest running `python tests/run.py`. A tag `v*` triggers the portable zip build (and the optional installer), SHA-256 file, draft release. windows-latest reportedly ships Inno Setup; install it via Chocolatey only if ISCC.exe is missing (see section A).
- **Release flow:** tag, CI draft release (portable zip, optional installer, checksum, providers.json hash), manual publish.
- **Contributing:** CONTRIBUTING.md covering how to add a provider (PR to providers.json with privacy and ToS URLs and a verification date), how to run tests, and the AGENTS.md rules (plain-language comments, `ctx.bump()` after user-visible changes).
- **Docs changes:** README quick start becomes "download the zip, unzip, run"; keep the pip path under "Developers". State the free-tier caveats honestly.

## 7. Top risks and do-not-build

| Risk | Mitigation |
| --- | --- |
| Free tiers change or vanish without notice (FreeLLMAPI lists this as a core limitation) | Optional catalog refresh, observed-limit learning, terminal loudness-only mode |
| ToS: free tiers are often scoped to prototyping or business use; multi-account pooling and shared endpoints are the usual violations | One account per provider, local-only, no shared endpoint. Document per-provider ToS notes. Not legal advice |
| YouTube breakage (PO tokens/SABR, JS challenges; 403 waves reported Aug 2026, https://www.videoproc.com/resource/yt-dlp-not-working.htm) | Nightly channel, bundled JS runtime, clear in-app error mapping, optional PO-token provider later |
| Downloading content: yt-dlp use and ToS | Keep README responsibility notice; default to user-owned or permitted content; no legal conclusion here |
| Auto-posting: unaudited YouTube projects upload private only | Export-only default; posting opt-in with an explicit warning |
| Quality gains not real | Eval harness gates merges (D7) |
| Transcript text leaves the machine | Privacy toggle default strict; state it in UI |
| Prompt injection via transcript | Keep `_safe/_text`; schema-validate every LLM output; fuzz test |
| Upstream drift or hostile merge | Additive modules, monthly sync |
| sherpa-onnx native packaging on Windows | Prove it in S3 on a clean VM before promising a one-click portable build |

**Do not build:** a hosted or shared proxy; multi-key farming of one provider; a WPF launcher; per-segment VLM captioning; fine-tuning; a bandit router in v1; a React rewrite of the UI; more accounts/Postgres/admin features; a mobile app; cloud STT; a paid catalog feed; TikTok/Instagram posting work.

## 8. First three tasks for a coding agent

**Task 1: audit and fork hygiene** (S0, \~1 day)

- Files: `docs/AUDIT.md` (new), `LICENSE`, `README.md`, `CONTRIBUTING.md` (new), `.github/workflows/ci.yml` (new), and the module found by `grep -rn PEAKCUT_UPDATE_CHECK studio/` plus its update-check code.
- Do: read every studio/\*.py and tests/run.py. In AUDIT.md list, with line numbers: where the AI key is stored and whether encrypted; how yt-dlp is invoked and which args are user-influenced; where the full video is downloaded; where transcript chunks are built and sent to the LLM; where LLM JSON is parsed and validated; how a mid-job provider failure is handled; how render.py crops, lays out and draws captions (fonts, script shaping); which Parakeet variant fetch\_model.py downloads and how word timings are produced; whether any manual editor exists; how paths and the data folder are resolved (portability). Repoint the update check to muzammilAwan-dev/PeakCut (or default it off).
- Tests: CI green on windows-latest. New test: with the update check enabled and a mocked GitHub response, no notice or message references haziqahmedqasmi. LICENSE still contains the original notice and the added fork line.

**Task 2: engine bootstrap** (S1, \~4 days)

- Files: `studio/bootstrap.py` (new), `studio/media.py` (use resolved binary paths and pass `--js-runtimes deno:<path>`), `studio/config.py` (`PEAKCUT_BIN_DIR`, `PEAKCUT_YTDLP_CHANNEL`, default nightly), new test in tests/ using a local fake release server.
- Behaviour: first run downloads ffmpeg, yt-dlp (nightly) and deno to `the app's bin/ folder (fallback %LOCALAPPDATA%\PeakCut\bin when not writable)`, verifies pinned SHA-256, writes `versions.json`; yt-dlp is re-checked at most every 24 h; offline start uses what exists; a failed download never deletes a working binary. Use the BtbN win64 GPL static build pinned to a dated monthly release with its checksums.sha256 (never the floating latest), fetched at first run and not bundled in the zip or installer. Pin Deno >= 2.3.0.
- Tests: temp bin dir plus fake server: (a) first run installs all three, (b) second run makes zero downloads, (c) corrupted download is rejected and the old binary kept, (d) offline start succeeds, (e) a yt-dlp call includes the JS runtime argument.

**Task 3: pool v0** (S2, \~5 days, can run alongside Task 2)

- Files: `studio/pool.py`, `studio/providers.default.json` (seed with Groq, Cloudflare, Z.ai, Gemini, Mistral, OpenRouter free, local Ollama using section 4.1; enabled by default: Groq, Cloudflare and local Ollama only), `studio/ai.py` (register `pool`), `studio/config.py` (`PEAKCUT_AI_PRIVACY`, `PEAKCUT_POOL_CATALOG_URL`), `studio/usage.py` (record route), a mock provider server under tests/.
- Behaviour: section 4.3 and 4.6, terminal chain to loudness-only, ledger persisted in the existing database or a small SQLite file in the data folder.
- Tests (no real keys): (a) 429 with Retry-After fails over to the next provider and the first is skipped until expiry; (b) malformed JSON gets one repair retry, then the next provider; (c) 401 disables the provider; (d) strict mode never calls a `yes`/`unknown` provider, relaxed mode may; (e) all providers failing yields loudness-only clips with the job marked degraded; (f) oversized chunk is split to fit the lowest TPM in the eligible set; (g) ledger counts survive a restart.

## 9. Open questions

1. Please provide studio/ai.py, jobs.py, brain.py, media.py and tests/run.py (paste or zip). Then I can replace section 1 with line-cited findings, which Task 1 would otherwise do.
2. Assumed: no hosted service. If you plan one, the ToS picture in section 7 changes materially.
3. Assumed: the fork keeps the PeakCut name for now. A rename is cheap now and expensive after the first release.
