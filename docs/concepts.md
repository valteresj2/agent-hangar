# Concepts

## Agent

An agent is a registry entry with four human-facing fields (**name**, **objective**, **final output**, **owner**) and
a versioned **spec** that defines its behavior (see [spec.md](spec.md)). The slug (`doc-qa`) is its stable ID in
URLs, API calls and sub-agent references.

Every spec change creates a new **immutable version** (v1, v2, …). Saving an identical spec is a no-op. Rolling
back copies an old spec into a *new* version, so history is never rewritten.

Every agent also has a **guide** for the people who will use it: what it is, what it does, what it does not do,
how to use it and its limits. The AI tool that builds the agent writes it as a step of the build, before the ship.
The guide is versioned with the agent, but it lives outside the spec, so fixing it needs no new version or tests.
See [guide.md](guide.md).

## Agent types

| Type | Runs as | Good for |
|---|---|---|
| **Chat** (default) | A long-running container with an LLM tool-calling loop (max 6 steps) | Q&A, analysis, writing, classification, calling tools/MCPs, orchestration |
| **Harness** (`spec.harness`) | A new ephemeral container **per call**, running a real coding agent CLI | Tasks that need to *execute*: edit files, run code, produce a diff |
| **Multi-agent** (`spec.sub_agents`) | A chat agent whose tools include `ask_<sub-agent>` | Objectives that split into specialist roles |

A harness agent cannot have sub-agents, but it can *be* a sub-agent of a chat orchestrator. When building through
MCP, the model picks the type from the objective (the hangar's instructions explain the criteria); users can always
override it.

## Environments and the promotion gate

Each agent has two environments, **stage** and **prod**, each with its own container (`agent-<slug>-<env>`).
`ship` runs the full pipeline:

1. Ship sub-agents first (recursively).
2. Deploy the current version to **stage**.
3. Run tests: protocol smoke tests (health, Agent Card, OpenAI, A2A, ACP, MCP) plus the spec's test cases.
4. Record the test run against that version.
5. Promote to **prod** only if the run passed. `promote`/`deploy prod` enforce the same gate.

Agents without an LLM connection run in **mock** mode: they echo, content checks are skipped (marked `(mock)`), and
the smoke tests still validate the plumbing.

## Connections

A connection is an external LLM endpoint: `base_url` + default `model_name` + API key (stored encrypted with
`HANGAR_SECRET_KEY`) + `protocol` + optional prices per 1M tokens. The hangar never hosts a model.

| Protocol | Used by |
|---|---|
| `openai` | chat agents, `codex`, `hermes`, LLM-as-judge |
| `anthropic` | `claude-code` |
| `deepseek` | `deepseek-harness` |

`llm.stage` / `llm.prod` (and `harness.stage` / `harness.prod`) override the connection or model per
environment, for example a cheaper model in stage.

## Gateway and channels

Clients reach agents through the hangar at `/gw/<slug>/…` (prod) and `/gw-stage/<slug>/…`, authenticated with an
API key. The gateway proxies to the agent container, streams SSE responses, and records usage (tokens, cost,
latency, errors) per agent, environment, **channel** (the `X-Channel` header, e.g. `slack`) and protocol.

## Jobs

A call to a harness agent becomes a **job**: queued → running → passed/failed/timeout/error/cancelled. The
container receives the task, the agent's instructions and skills, its MCP servers and the connection's credentials.
It runs the CLI in an empty git workspace and posts the result, the `git diff` and the token usage back through a
single-use callback token. Jobs can be followed live over SSE (`/api/jobs/<id>/events`) and cancelled.

## Usage and cost

Chat agents compute cost from the connection's prices and the LLM's reported usage. Jobs use the harness's reported
tokens: Claude Code and Codex give token counts, and Hermes also reports its own cost estimate, which is used when
the connection has no prices. DeepSeek Harness does not report usage yet.
