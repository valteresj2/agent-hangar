# Interactive demo (Product Hunt)

These files regenerate the interactive tour published at `docs/demo/` (GitHub Pages:
https://valteresj2.github.io/agent-hangar/demo/).

## What was recorded

The run happened on a local install of v0.12.0 on 2026-10-01. People and customers are fictional; the agents, tests,
memory, answers and costs are real.

1. **Setup:** Maya Chen (a local account) maintains the *Sales* team, which requires approval for production. She
   has a personal token (scope `user`) and a UI session.
2. **Claude builds the agents.** `run_calls.py` runs the MCP calls in `calls.json` with Maya's token, through
   `mcpcall.py`; every call and result goes to `transcript.jsonl`. It creates Account Memory (team memory), Proposal
   Writer, and Deal Desk (`sub_agents: [account-memory, proposal-writer]`), ships them and schedules Deal Desk.
3. **Approval:** the release stopped at four-eyes approval; `capture.py approval` took that screen, then an admin
   approved it.
4. **Usage:** `chat.py` gives Account Memory facts about three customers through the OpenAI-compatible gateway, then
   the schedule runs once (`run_schedule_now`).
5. **Capture:** `capture.py main|extra|claude` (Playwright) signs in as Maya and takes the screens. The Deal Desk
   answer in the Playground is generated live. In the Connect step, a Cursor connection is created, its key is masked
   on screen and revoked right after. `claude_chat.html` is a visual reconstruction of Claude built from
   `transcript.jsonl`; the demo says so.
6. **Tour:** the screens are converted to WebP in `docs/demo/img/`, and `docs/demo/index.html` holds the steps,
   captions and hotspots.

## Running it again

Put `maya_token.txt` and `maya_session.txt` in this folder. They are secrets: git-ignored, never commit them.

```bash
docker run --rm --network hangar_agents -v "$PWD:/demo" agent-hangar/central:latest python /demo/run_calls.py
docker run --rm --network hangar_agents -v "$PWD:/demo" mcr.microsoft.com/playwright/python:v1.63.0-noble   sh -c "pip install -q playwright==1.63.0 && python /demo/capture.py main"
```
