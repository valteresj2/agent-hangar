# Portal tour: from a request in Claude to a working agent

These files regenerate the README's portal tour (`docs/assets/portal-tour.gif` / `.mp4`) and the screenshots in
`docs/assets/portal/`.

## What was recorded

The run happened on a local install on 2026-09-30.

**Setup.** A non-admin user, Ana Souza, maintains the *Comercial* team. She has a personal token (scope `user`),
created in **Chaves de API**.

**Claude builds the agent.** Claude drove the Hangar's MCP server with Ana's token. `mcpcall.py` is the MCP
client, and every call and result is appended to `transcript.jsonl`. The calls were:
- `whoami` and `list_catalog`;
- `register_agent`;
- `design_agent` with `design.json`: instructions, LLM, `memory: {scope: team}` and three LLM-as-judge tests;
- `ship_agent`: stage, 9/9 checks passed, then production;
- `schedule_agent`: weekdays at 08:00;
- `run_schedule_now`.

**Ana uses it.** `chat.py` talks to the agent through the OpenAI-compatible gateway with Ana's token, so the usage
shows up as hers.

**Capture.** `capture.py` (Playwright) signs in to the portal as Ana, asks a real question in the Playground, and
takes the screenshots. `claude_chat.html` renders the Claude conversation from the recorded transcript.

**Assembly.** `make_video.py` builds the captioned GIF (for the README) and the MP4.

## Running it again

Put `ana_token.txt` (Ana's personal token) and `ana_session.txt` (a UI session for her) in the working folder.
Both are secrets: they are git-ignored and must never be committed. Then run:

```bash
docker run --rm --network hangar_agents -v "$PWD:/demo" agent-hangar/central:latest python /demo/mcpcall.py list
docker run --rm --network hangar_agents -v "$PWD:/demo" mcr.microsoft.com/playwright/python:v1.63.0-noble \
  sh -c "pip install -q playwright==1.63.0 && python /demo/capture.py"
docker run --rm -v "$PWD:/demo" mcr.microsoft.com/playwright/python:v1.63.0-noble \
  sh -c "pip install -q pillow numpy imageio-ffmpeg && python /demo/make_video.py"
```
