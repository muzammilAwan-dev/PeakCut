# Contributing

This is Amfaiz's fork of PeakCut (MIT). Start with [AGENTS.md](AGENTS.md) (map of the code and the rules) and
[docs/STATUS.md](docs/STATUS.md) (what is done and what is next).

- Work on the `develop` branch. `main` only receives finished, tested work.
- Run `python tests/run.py` before and after every change. It needs no AI key and no internet.
- Every change that adds behaviour adds a test that runs without keys.
- Keep changes small and additive. New modules are better than big edits to old ones.
- Text from videos, answers from the AI, file names and downloads are untrusted: check them before use.
- A new dependency needs a one-line reason in the pull request.
- Never commit keys, `.env`, the `data/` folder or anyone's videos.
- Write comments and messages in plain language for people who do not program.
