# Measuring clip quality

Nothing that changes which moments are picked is kept unless this shows it is better.

## Build the labelled set (once)
1. Choose about 20 videos you own or may use (30 to 60 minutes each): podcast, gaming, interview, talk, sports. Mix English, Hindi, Urdu (about 60/20/20).
2. Two people each write down their top 10 moments per video as start and end seconds.
3. One folder per video inside one folder, for example `evalset/podcast01/`:
   - `words.json`: the transcript, `[{"w": "hello", "s": 12.3, "e": 12.7}, ...]` (the `words.json` a finished job leaves in its folder is exactly this)
   - `labels.json`: `{"annotators": [[{"start": 120, "end": 150}, ...], [{"start": 118, "end": 152}, ...]]}`
   - `meta.json`: `{"title": "...", "uploader": "...", "duration": 2400, "genre": "podcast", "language": "en"}`
   - `loudness.json` (optional): one loudness number per second. Without it every second counts as equally loud.
   Only these small files are stored, never the videos.

## Run it
- `python tools/eval.py --demo` shows how it works on a made-up set.
- `python tools/eval.py evalset --systems loudness,current --k 5,10 --runs 3`
  - `loudness` is the no-AI last resort. `current` is the real pipeline and uses the AI you set up (free pool or a key), so it costs requests.
  - `--json result.json` also saves everything.

## Read it
- **p@5**: of the 5 best picks, the share a person also picked (a pick counts when it overlaps a human pick by at least half of the shorter one).
- **95% range**: with 20 videos small differences are noise. Trust a change only when the ranges do not overlap, or the gain is at least 10 points of p@5 (or the same quality with half the tokens).
- **How much the two people agree**: scores near this number cannot be told apart from a person.
- **tokens per hour**: the free allowance is what runs out first, so lower is better.
- **run-to-run spread**: how much the same system differs between runs (0 means it always picks the same).

To try a new way of picking clips, add one function to `SYSTEMS` in `tools/eval.py`.
