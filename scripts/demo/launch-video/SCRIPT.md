# Launch video: "One home for every AI agent"

A 75-second screen recording for Product Hunt, the README and social posts. It is in English, with no voice-over:
captions carry the story, so it works muted in feeds. It is recorded on a real local install, with nothing mocked.

## The story in one line

An agent is built once from Claude.ai, reusing what the company already has, then tested and shipped. The same
agent is then used from ChatGPT, and everything stays governed in the hangar.

## Before recording

| | |
|---|---|
| Screen | 1920×1080, browser zoom 110%, dark mode off, bookmarks bar hidden, notifications off |
| Recorder | OBS Studio (Display Capture, 60 fps, MKV, then remux to MP4) or Windows + Alt + R |
| Portal | Language **EN** (PT · EN switch), signed in as `valteresj` in a second tab: `/app/` |
| Public URL | Open a quick tunnel (`docker run -d --name hangar-quicktunnel --network hangar_agents cloudflare/cloudflared tunnel --no-autoupdate --url http://central:8080`), set `PUBLIC_BASE_URL` to the `https://….trycloudflare.com` URL from its logs and run `docker compose up -d central`. A quick tunnel gets a new URL each time, so remove and re-add the Agent Hangar connector in Claude.ai and ChatGPT with the new `<url>/mcp`. With a fixed domain (Cloudflare Tunnel or ngrok, see [docs/install.md](../../../docs/install.md)) this step is only needed once |
| Data | Keep the Sales demo (Account Memory, Proposal Writer, Deal Desk, Renewal Coach). Delete any earlier "Customer Email Triage" agent so the run is fresh |
| Chats | New conversation in each app, connector enabled in the message box ("+" menu) |

Do one dry run first. Building, testing and shipping takes 1 to 3 minutes; it is sped up in the edit.

## Shot list (≈75 s)

| # | Time | Screen | Action | Caption (on screen) |
|---|---|---|---|---|
| 1 | 0–4 s | Title card (`docs/assets/social-preview.png`) | — | **One home for every AI agent** |
| 2 | 4–14 s | Claude.ai | Type prompt A (below) and send | "Ask for an agent in plain words" |
| 3 | 14–24 s | Claude.ai | Claude calls `plan_agent`: the reuse plan appears (Account Memory and the Proposal Writer as specialists, a missing skill) | "It reuses what your company already built" |
| 4 | 24–38 s | Claude.ai, sped up 4–8× | `compose_agent`, then `run_tests` and `ship_agent`; Claude reports the tests passed and the agent is in production | "Built, tested and shipped, with existing agents left untouched" |
| 5 | 38–50 s | Portal `/app/`, agent page | Overview: Production badge, **Built from** card (lineage), Tests tab green | "Every agent has an owner, tests, versions and an audit trail" |
| 6 | 50–64 s | ChatGPT | Type prompt B; ChatGPT calls `chat_with_agent` and shows the triage | "Use it from ChatGPT, Claude, Codex, Cursor or VS Code" |
| 7 | 64–70 s | Portal, **Usage** tab of the agent | Calls by channel: claude.ai and chatgpt | "One agent. Every platform. One bill." |
| 8 | 70–75 s | End card | — | **Agent Hangar** · self-hosted · Apache-2.0 · github.com/valteresj2/agent-hangar |

## Prompts to type

**A (Claude.ai)**

> In Agent Hangar, create an agent called "Customer Email Triage" for the Sales team. It reads a customer email,
> checks what we already know about that account, and returns a 3-bullet summary, the urgency (low/medium/high) and a
> short reply draft. Reuse existing agents and skills where you can, then test it and ship it to production.

**B (ChatGPT)**

> Use the Customer Email Triage agent in Agent Hangar on this email: "Hi, this is Laura from ACME. Our renewal is next
> month and we're being asked for a 15% discount by your competitor. Can we talk this week? Our usage grew a lot."

## Edit notes

- Cut the waits. Keep the cursor visible and zoom to 120–140% on the tool-call cards in Claude and ChatGPT.
- Captions: Barlow Semi Condensed 600, white on the tarmac dark `#1C2530` with the yellow `#F4B400` accent bar.
  These are the product's own colors.
- Music: quiet and royalty-free (YouTube Audio Library), with the title card at 0 s on the downbeat.
- Exports:
  - 1920×1080 MP4 (H.264, under 50 MB) for Product Hunt and YouTube;
  - a 1080×1080 crop for LinkedIn and X;
  - a 900 px GIF of shots 2 to 6 for the README.
- Check before publishing:
  - no keys, tokens or e-mails are visible;
  - the tunnel URL is blurred or the tunnel is already closed;
  - the agent and team names are demo data.

## After recording

- Close the tunnel and set `PUBLIC_BASE_URL` back to `http://localhost:8090`.
- Revoke the Claude.ai and ChatGPT authorizations under **My keys → Connected apps** if they will not be used again.
