# HangarLLM hub

Connect [HangarLLM](https://github.com/valteresj2/HangarLLM), the open-source LLM gateway from the same family, once,
and it becomes the agents' hub for models. Every agent gets a key of its own on the gateway, every call carries the
agent, environment and task as tags, and the real spend comes back from the gateway instead of an estimate.

The other ways to plug in a model keep working as before, **isolated**: a direct provider (OpenAI, Anthropic,
OpenRouter…), another gateway (LiteLLM, Portkey) or any OpenAI-compatible endpoint. They just don't get per-agent keys
or the gateway's real spend.

## What the connection does

| | Isolated connection | HangarLLM hub |
|---|---|---|
| Key the agent receives | The connection's key, shared by every agent on it | A virtual key of its own, per agent and environment |
| Models the key can call | Whatever the provider key allows | Only the models the agent uses (plus its light model) |
| Budget | Hangar budgets (estimated cost) | Hangar budgets, plus a per-key budget the gateway enforces |
| Cost | Estimated from list prices | Real spend read from the gateway, per agent |
| Tags per call | none | `agent-hangar`, `agent:<slug>`, `env:<env>`, `task:<id>` and a session per task |
| Model list and prices | Provider list or public price table | The gateway's own list (`/model/info`), with its prices |
| Leaving | Delete the connection | Disconnect the hub: every key is revoked on the gateway |

The management key you enter stays in the central, encrypted. It never goes to an agent, and the `hangarllm`
connection itself holds a separate virtual key used only by the central's own calls (curation, analysis, tests).

## Connect

**Providers → HangarLLM (hub)**, or `PUT /api/hangarllm`:

1. **HangarLLM address**: how the central and the agents reach the gateway. In a Docker install it is
   `http://hangarllm:4000` (see below). On another host, use the gateway's HTTPS address.
2. **Management key**: the master key or a management key of HangarLLM. The central checks it can list models and
   manage keys before saving anything.
3. **Budget for each agent** (US$) and the period (day, week or month). HangarLLM's key policy requires a budget, an
   expiry and a model list on every key; the central fills all three.

On save the central creates the `hangarllm` connection with the gateway's models, picks a text model as the default and
lists the keys it created. Pick the `hangarllm` connection on an agent (or make it the default) and deploy.

`hangar setup` offers **HangarLLM** as the first option in the LLM step: it asks only for the address and the
management key, and can put the container on the agents' network for you.

### HangarLLM in the same Docker

HangarLLM runs in its own compose project behind Caddy with a local certificate. The simplest path is to put its
container on the agents' and jobs' networks under the name `hangarllm`, so everything talks plain HTTP inside Docker:
**Local install with Docker → Add to the agents' network** (`POST /api/hangarllm/network` with the container name,
default `hangarllm-hangarllm-1`). Do it again after recreating the HangarLLM container.

## Agent keys

- Created on deploy (stage and prod are separate keys), named `agent-hangar/<org>/<agent>/<env>` on the gateway, with
  the agent's models, the hub budget, an expiry of 30 days and metadata linking them to the agent.
- Redeploying reuses the key; changing the agent's model updates the models of the same key.
- The central renews keys that expire within 7 days and reads each key's real spend every hour (**Refresh now** does
  it on demand).
- Deleting an agent revokes its keys. If the gateway is down at that moment the keys still expire on their own.
- The hub page lists every key with the agent, environment, models, expiry and real spend. Key values are never shown.

## API

| Method | Route | What it does |
|---|---|---|
| GET | `/api/hangarllm` | Status: address, models by kind, agent keys with real spend, budget and what stays isolated |
| PUT | `/api/hangarllm` | Connect or update: `{url, admin_key, ui_url, budget_usd, budget_period}`. An empty `admin_key` keeps the current one |
| DELETE | `/api/hangarllm` | Disconnect: refused while an agent uses the `hangarllm` connection; revokes every key |
| POST | `/api/hangarllm/refresh` | Renew keys close to expiry and read the real spend now |
| POST | `/api/hangarllm/network` | Docker install: put the HangarLLM container on the agents' and jobs' networks as `hangarllm` |

All routes are for platform admins. The `hangarllm` connection can't be created or removed through
`/api/catalog/llm`: it is born and leaves with the hub.

## Next

The hub covers models today. MCP servers from HangarLLM's MCP gateway and skills from its Skills Hub are the next
steps; until then connectors ([connectors.md](connectors.md)) and skills work as they always did.
