# Release test (Windows, owner)

Do in order. Stop at the first failure and send the text of the error.

1. **Install the update:** extract the zip over the repo. `git status` should show only expected files.
2. **Suite:** `python tests/run.py > baseline-windows.txt`. Expect every file to pass. Send the file back.
3. **Pins:** `python tools/fill_pins.py`, then check `studio/pins.json` has hashes for ffmpeg and Deno. Commit it.
4. **Optional face test:** `pip install -r requirements-optional.txt`, then `python tests/run.py` again (the face checks switch on).
5. **Dev run:** `python -m studio.server`, open http://127.0.0.1:8765. Title must say ViralCut.
6. **Free pool:** Settings, Free AI pool. Paste one free key (e.g. Groq or Gemini), tick consent, press Test. Expect a green row and a "JSON mode" note. Send a screenshot if any row is red.
7. **Real video:** add a short stream (10 to 20 min). Make clips. Check: clips start and end at sentences, Stop button works, Undo restores the previous edit, the face layout (if installed) follows the speaker.
8. **No-AI path:** remove the keys, run the same video again. Clips must still appear (loudness fallback).
9. **Portable:** `python tools/build_portable.py`. Unzip the result on a clean folder (or another PC), double-click `ViralCut.bat`. First start downloads ffmpeg; the dashboard must open.
10. **Extension:** Chrome or Edge, `chrome://extensions`, Developer mode, Load unpacked, pick `extension/`. Copy the key from Settings, Browser extension into the popup. Open any video page, press Clip this. A job must appear.
11. **Keys sealed:** open `data/pool.json`; saved keys should start with `dpapi:`.
12. **YouTube access:** run `.venv\Scripts\python.exe tools\yt_check.py` (add a video link of your own as an argument if you like) and keep `yt-check.txt`. Then Settings, YouTube access, choose Automatic, press Test; expect a green line. Make clips from a YouTube link that has captions: `data\logs\viralcut.log` must show `youtube.captions.used`.
13. **Eval (optional):** follow `docs/EVAL.md` with 3 to 5 videos you picked by hand.

Known not built: Hindi/Urdu speech model (S6d), yt-dlp nightly updater (S1b), AI candidate pre-scoring.
