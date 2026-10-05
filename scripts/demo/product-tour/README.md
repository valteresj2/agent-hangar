# Interactive demo (Product Hunt)

These files regenerate the interactive tour published at `docs/demo/` (GitHub Pages:
https://valteresj2.github.io/agent-hangar/demo/).

## What was recorded

The run happened on a local install of v0.12.0 on 2026-10-01; the portal screens were taken again on v0.15.0 on 2026-10-04, in English, adding the Guide and "reuse before you build" steps (`capture.py main|extra|reuse`, signing in with `maya_password.txt`). People and customers are fictional; the agents, tests,
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
6. **Digital employee (v0.16.0, 2026-10-05):** `employee_live.py hire` hires a *Renewals Analyst* over MCP as Maya,
   with Deal Desk's LLM and Account Memory and Proposal Writer as specialists. During probation it asked Maya twice
   for Northwind's renewal date (not on record) instead of guessing; she answered in the portal. She admitted it, and
   because Sales requires four-eyes, an admin approved production (`admin_token.txt`, deleted after). Then
   `employee_live.py task` gives it the e-mail task, which pauses on the exact `send_email` call. `capture.py employee`
   takes the probation, decision and authority screens. The e-mail was never approved or sent.
7. **Tour:** the screens are converted to WebP in `docs/demo/img/`, and `docs/demo/index.html` holds the steps,
   captions and hotspots.

## Running it again

Put `maya_token.txt` and `maya_password.txt` (the demo account's password) in this folder. They are secrets: git-ignored, never commit them.

```bash
docker run --rm --network hangar_agents -v "$PWD:/demo" agent-hangar/central:latest python /demo/run_calls.py
docker run --rm --network hangar_agents -v "$PWD:/demo" mcr.microsoft.com/playwright/python:v1.63.0-noble   sh -c "pip install -q playwright==1.63.0 && python /demo/capture.py main"
```

## Live test of "reuse before you build"

`compose_live.py` runs the composer for real as Maya, and `verify_live.py` checks the result:
- `compose_live.py`: `plan_agent` with a Portuguese request against English agents, then `compose_agent` with the
  suggested specialists and two new skills from the gap answers. It fingerprints the source agents before and after.
- `verify_live.py`: after the new agent is shipped, approved and used, it checks that the pieces are unchanged and
  prints the lineage and metrics.
- `ui_check.py`: drives the portal screens with Playwright.

The scripts need `admin_token.txt`, the ADMIN_TOKEN copied from `.env`. It is git-ignored; delete it after running.

