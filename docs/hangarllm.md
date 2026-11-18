# HangarLLM hub

Connect [HangarLLM](https://github.com/valteresj2/HangarLLM), the open-source LLM gateway from the same family, once,
and everything plugs in: its **models**, its **MCP servers** and its **skills** reach the agents. Every agent gets a key
of its own on the gateway. Every call, LLM or MCP, carries the agent, environment and task as tags. The real spend
comes back from the gateway instead of an estimate.

The other ways to plug these in keep working as before, **isolated**:
- A direct LLM provider (OpenAI, Anthropic, OpenRouter…), another gateway (LiteLLM, Portkey) or any OpenAI-compatible
  endpoint.
- Your own connectors ([connectors.md](connectors.md)).
- Skills made in the Skill Studio.

Isolated pieces don't get per-agent keys or the gateway's real spend.

## What the connection does

| | Isolated | HangarLLM hub |
|---|---|---|
| Key the agent receives | The connection's key, shared by every agent on it | A virtual key of its own, per agent and environment |
| Models the key can call | Whatever the provider key allows | Only the models the agent uses (plus its light model) |
| MCP servers | Connectors registered here, each with its own credential | Every server of HangarLLM's MCP gateway shows up as a `hub:<alias>` connector; the agent's key reaches only the ones in its spec |
| Skills | Made or uploaded here | Skills published on HangarLLM's Skill Hub arrive here, and the company's skills are published there |
| Budget | Hangar budgets (estimated cost) | Hangar budgets, plus a per-key budget the gateway enforces |
| Cost | Estimated from list prices | Real spend read from the gateway, per agent |
| Tags per call | none | `agent-hangar`, `agent:<slug>`, `env:<env>`, `task:<id>` and a session per task, on LLM and MCP calls |
| Model list and prices | Provider list or public price table | The gateway's own list (`/model/info`), with its prices |
| Leaving | Delete the connection | Disconnect the hub: every key is revoked on the gateway |

The management key you enter stays in the central, encrypted. It never goes to an agent. The `hangarllm` connection
itself holds a separate virtual key, used only by the central's own calls (curation, analysis, tests, checking the MCP
servers).

## Connect

**Providers → HangarLLM (hub)**, or `PUT /api/hangarllm`:

1. **HangarLLM address**: how the central and the agents reach the gateway. Leave it **empty** on a Docker install: the
   central finds the HangarLLM container, puts it on the agents' network and uses `http://hangarllm:4000`. On another
   host, use the gateway's HTTPS address.
2. **Management key**: the master key or a management key of HangarLLM. The central checks it can list models and
   manage keys before saving anything.
3. **Budget for each agent** (US$) and the period (day, week or month). HangarLLM's key policy requires a budget, an
   expiry and a model list on every key; the central fills all three and turns the gateway's automatic key rotation
   off for its keys (it renews them itself).

On save the central does the following:
- creates the `hangarllm` connection with the gateway's models and picks a text model as the default;
- brings the MCP servers and the skills;
- publishes the company's skills;
- lists the keys it created.

Pick the `hangarllm` connection or a `hub:…` connector on an agent and deploy.

`hangar setup` offers **HangarLLM** as the first option in the LLM step. On a Docker install it asks only for the
management key; elsewhere, also for the address.

### HangarLLM in the same Docker

HangarLLM runs in its own compose project behind Caddy with a local certificate. Inside Docker, the central and the
agents talk to it over plain HTTP, on the agents' and jobs' networks, under the name `hangarllm`.

- **Automatic setup.** With the address empty, the central finds the container and connects it, and the page says
  which container it found (`GET /api/hangarllm/discover`).
- **Manual setup.** **Local install with Docker → Add to the agents' network** does the same step by hand
  (`POST /api/hangarllm/network`).
- **After recreating the HangarLLM container**, add it to the network again.

## MCP servers

- **The `hub:<alias>` connector.** Every server registered on HangarLLM (MCP Servers on its dashboard) becomes a
  connector named `hub:<alias>`, in its own **From HangarLLM** section of Connectors.
  - You manage the server on HangarLLM: credentials, OAuth, stdio runners and cost per query all live there.
  - The connector can't be removed here.
- **How the agent calls it.** The agent calls the connector through the central's bridge, like any other connector.
  The bridge talks to the gateway at `<hub>/<alias>/mcp` with **the agent's own key**.
  - The key's `object_permission.mcp_servers` lists only the hub servers in that agent's spec.
  - An agent that uses MCP from the hub but an LLM from elsewhere gets a key that calls no model
    (`no-default-models`).
- **Tool names.** The gateway names tools `<alias>-<tool>`; the agent sees `hub_<alias>__<tool>`.
- **Tool approval.** New or changed tools stay blocked until an admin approves them, as with any connector. On the
  first sync the current tools come in approved, since the admin who connected the hub already trusts that gateway.
- **Spend and tags.** Every tool call shows up in HangarLLM's spend logs as `call_mcp_tool` with the agent's tags, and
  costs whatever the server's cost per query says.
- **Servers removed from HangarLLM.**
  - A server no agent uses is removed here too.
  - A server still in an agent's spec stays, marked "removed from HangarLLM", until you take it out of the agent.

## Skills

- **From the hub to here.** Skills published on HangarLLM's Skill Hub become skills here, marked **HangarLLM**.
  - They are **read-only** here: edit them on HangarLLM. A new version there arrives on the next sync.
  - A skill removed or unpublished there leaves here when no agent uses it. Otherwise it stays as deprecated, so new
    agents don't pick it up.
- **From here to the hub.** With **Publish the company's skills to the Skill Hub** on (the default), every active
  company skill goes to the Skill Hub as a package with `SKILL.md` at the root.
  - The package carries the namespace `agent-hangar` and the keywords `agent-hangar` and `agent-hangar-org-<org>`.
  - A new version here replaces the files there; it does not create a duplicate.
  - Turning the option off removes the company's skills from the Skill Hub.
  - The same secret scan as uploads blocks a skill before it leaves.
- **Name clashes.** A skill with the same name and a different origin is never overwritten, on either side. It shows as
  a name conflict on the hub page.
- **Upload limit.** The Skill Hub accepts 10 uploads per minute. A large catalog is published over a few syncs; the
  hub page shows the warning.

## Agent keys

- **When they are created.** On deploy (stage and prod are separate keys), or on an agent's first call to a hub MCP
  server.
- **What they carry.** Each key is named `agent-hangar/<org>/<agent>/<env>` on the gateway. It holds the agent's
  models, its hub MCP servers, the hub budget, an expiry of 30 days and metadata linking it to the agent.
- **Changes.** Redeploying reuses the key. Changing the agent's model or its hub connectors updates the same key.
- **Hourly sync.** Every hour (**Refresh now** does it on demand) the central:
  - renews keys that expire within 7 days;
  - reads each key's real spend;
  - syncs the MCP servers and the skills.
- **Revocation.** Deleting an agent revokes its keys. If the gateway is down at that moment, the keys still expire on
  their own.
- **What the page shows.** The hub page lists every key with the agent, environment, models, MCP servers, expiry and
  real spend. Key values are never shown.

## Disconnect

Disconnecting is refused while an agent uses the `hangarllm` connection or a `hub:…` connector. Once nothing uses
them, it does the following:
- revokes every key;
- removes the `hub:…` connectors;
- takes the company's skills off the Skill Hub.

Skills that came from the hub **stay** as company skills, so nothing that uses them breaks.

## API

| Method | Route | What it does |
|---|---|---|
| GET | `/api/hangarllm` | Status: address, models by kind, MCP servers, skills (from the hub, published, conflicts), agent keys with real spend, budget, last sync and what stays isolated. When not connected, `found` lists the HangarLLM containers seen in Docker |
| PUT | `/api/hangarllm` | Connect or update: `{url, admin_key, ui_url, budget_usd, budget_period, share_skills}`. An empty `url` finds HangarLLM in Docker; an empty `admin_key` keeps the current one |
| DELETE | `/api/hangarllm` | Disconnect (see above) |
| POST | `/api/hangarllm/refresh` | Renew keys, read the real spend and sync MCP servers and skills now |
| GET | `/api/hangarllm/discover` | Docker install: the HangarLLM containers the central sees |
| POST | `/api/hangarllm/network` | Docker install: put a HangarLLM container on the agents' and jobs' networks as `hangarllm` |

All routes are for platform admins. The `hangarllm` connection can't be created or removed through
`/api/catalog/llm`, and `hub:…` connectors can't be removed through `/api/connectors`: they come and go with the hub.

## Next

Agents published back to HangarLLM as A2A agents, so the gateway's clients can call them, is the next step.
