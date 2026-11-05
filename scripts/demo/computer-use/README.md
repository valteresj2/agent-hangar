# Computer use video: a Digital employee on a desktop app

These files regenerate the README's computer use video (`docs/assets/computer-use.mp4`) and the stills in
`docs/assets/computer-use/`.

## What was recorded

The run happened on 2026-11-04 on a regular install (0.58.4) with the `desktop` profile up and a real model
(`openrouter-deepseek`). It is case D of `tests/e2e/pilot_llm.py`: a Digital employee logs into the sample Tk
"legacy ERP" with a vault password, posts the payment of invoice 102 and confirms the dialog, which waits for a
manager's approval. The ERP is a sample app and the people are created by the script for the test.

- **The desktop, live:** while the task ran, a loop took one screenshot of the desktop per second.
- **The console:** `ui_shots.cjs` (Playwright in Edge, with the admin token in a header) captures the task page, the
  employee's allowed apps, and the screenshot that went with the approval request.
- **Assembly:** `make_video.py` adds the cards and captions, crops the ERP window out of each desktop frame, and writes
  the MP4 and the README stills.

## Running it again

```bash
# the desktop, one frame per second, while the case runs (stop with Ctrl+C when it ends)
mkdir -p frames; i=0; while :; do docker compose exec -T desktop sh -c "DISPLAY=:1 import -window root png:-" > frames/f$(printf %04d $i).png; i=$((i+1)); sleep 1; done
# in another terminal: the case, keeping its data
HANGAR_URL=http://localhost:8090 HANGAR_TOKEN=<admin> LLM_CONNECTION=<connection> PILOT_DESKTOP_APPS="ERP Legado,Gnumeric" \
  python tests/e2e/pilot_llm.py desk_dialogo --keep
# the console screens (task id and employee slug from the run) and the approval screenshot saved as ui/evidence.png
HANGAR_URL=http://localhost:8090 HANGAR_TOKEN=<admin> node ui_shots.cjs <task-id> <employee-slug> ui
docker run --rm -v "$PWD:/demo" mcr.microsoft.com/playwright/python:v1.63.0-noble \
  sh -c "pip install -q pillow numpy imageio-ffmpeg && python /demo/make_video.py"
```

The frame numbers in `make_video.py` (`LIVE`) match this run; pick the matching moments in a new one. Remove the data
that `--keep` left (the team, the two test people, the employee and the vault secret) when done.
