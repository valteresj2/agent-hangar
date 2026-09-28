# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Users, teams and roles.**
  - Company roles: admin, auditor and member.
  - Team roles: maintainer, developer and consumer.
  - Every agent belongs to a team. Existing agents move to the default **Plataforma** team.
- **Agent visibility** (`private`, `org`, `open`), with a **company catalog** and **access requests** that a
  maintainer approves. Instructions and spec stay hidden from other teams unless `expose_spec` is on.
- **Production approval (four eyes).**
  - When a developer ships, or when the team requires approval, a pinned promotion request is created.
  - Another maintainer or an admin approves it.
- **Login with OAuth2** (authorization code + PKCE): Google, Microsoft Entra ID, GitHub, and a generic OAuth2
  provider (Keycloak, Okta, Auth0; use Keycloak as the bridge for SAML).
  - Allowed domains, a fixed tenant, and required GitHub organizations.
  - Groups map to teams.
  - `BOOTSTRAP_ADMIN_EMAILS`.
- **SCIM 2.0** (`/scim/v2`): the directory provisions and deactivates users and syncs groups to teams.
- **Sessions.** The UI uses a `HttpOnly` session cookie with CSRF protection instead of a token in
  `localStorage`. "Sign in with token" remains as break-glass access.
- **Keys belong to people.**
  - New scopes `user` (personal token for the CLI and MCP) and `scim`.
  - Keys are revoked automatically when the owner loses access or is deactivated.
- **Monthly budget per team**, with an alert and an optional block (`429` at the gateway).
- UI pages: Aprovações, Times, Usuários, SSO e SCIM; an agent **Acesso** tab; role-aware buttons and tabs.
- CLI: `whoami`, `teams`, `approvals`, `request-access`, `agents ls --mine`, `templates apply --team`.
- Platform MCP: tools act as the key owner. New tools: `whoami`, `request_agent_access`, `list_approvals` and
  `decide_approval`. Catalog writes are admin-only.
- **Plug-and-play tool connections.** A new **Connect** tab on each agent, `hangar connect`, the
  `connect_agent` platform MCP tool and `/api/agents/{slug}/connections`:
  - MCP mode is offered for every tool: Claude Code, Claude Desktop, Codex, OpenCode, Cursor, VS Code, LibreChat,
    Open WebUI, and any other MCP client;
  - model mode is offered for chat tools: LibreChat, Open WebUI, OpenCode, and OpenAI SDKs;
  - each connection is a separate `invoke` key limited to that agent and tagged with the tool, so it can be
    revoked on its own;
  - the config comes ready to paste.
- The gateway tags usage with the key's tool when `X-Channel` is absent.
- Runtime: Open WebUI chat/user headers (`X-OpenWebUI-Chat-Id`) set the session.

### Fixed
- Calls through an agent's MCP endpoint now record tokens and cost (the tool result carries `_meta.usage`).
- MCP handshakes, `tools/list` and pings are no longer counted as requests.

## [0.2.1] — 2026-09-27

### Fixed
- `docker compose up data-studio` now also starts its Docker proxy (`data-studio-docker`); before, container-sandbox
  mode failed on the first kernel start.

## [0.2.0] — 2026-09-27

### Added
- **Data Studio MCP server** (`mcp-servers/data-studio`, compose profile `data-studio`):
  - a per-conversation workspace, with its own uid and its own stateful Python kernel;
  - DuckDB SQL, and file inspection with OCR;
  - PPTX (native charts) and HTML decks, interactive HTML dashboards, DOCX/HTML reports;
  - URL fetch with an SSRF guard;
  - signed download links.
- **`data-studio` template** and **LibreChat integration kit** (`integrations/librechat`), which uses the agent as
  LibreChat's engine through the OpenAI-compatible gateway.
- Runtime:
  - OpenAI-format attachments (`image_url`, `file`) are saved to the agent's MCP workspace via `ingest_file`;
  - the client conversation id is forwarded to MCPs as `X-Session-Id`;
  - client system prompts are kept;
  - SSE keepalive while tools run;
  - currency `$` is escaped for LaTeX-rendering channels.
- Spec: `llm.max_steps` and `llm.vision`.
- **Live tool progress** streamed as `reasoning_content` (a collapsible "Thoughts" block in LibreChat).
- **Lite mode** (`X-Hangar-Mode: lite`): one short LLM call without tools, used for conversation titles (about 20x
  cheaper). The LibreChat kit routes titles there via `titleEndpoint`.
- Images returned by MCP tools are passed to vision models, so an agent can look at its own output.
- Data Studio:
  - `preview_file` renders PPTX/DOCX/XLSX/PDF with LibreOffice and returns the images to the agent for visual QA;
  - `offline=true` embeds the chart libraries in HTML;
  - compact KPI formats (`R$ 6,26 mi`);
  - workspace retention (`RETENTION_DAYS`);
  - optional **one sandbox container per conversation** (`DATA_STUDIO_SANDBOX=container`).
- The UI "Connect" page shows the full LibreChat config (per-conversation sessions, attachments, titles).
- E2E: attachments flow through the gateway into the MCP workspace; streamed usage is recorded. CI also runs the Data
  Studio smoke test in container-sandbox mode, plus the retention test.
- README demo GIF and screenshots, recorded by `scripts/demo/record_demo.py`.

### Changed
- Postgres moved to an internal `db_net` network that agents can't reach.
- The gateway forwards `X-Conversation-Id`, `X-Session-Id` and `X-User-Id`, allows up to 900 s between stream chunks,
  and records token usage and cost from streamed responses.

## [0.1.0] — 2026-09-27

First public release (previously an internal prototype called "Central de Agents").

### Added
- Scoped API keys (`admin`, `invoke` limited to specific agents); keys stored as SHA-256 and shown once.
- Per-agent internal tokens (HMAC of the slug): agents can only call their own sub-agents and, if allowed, the
  read-only dashboard. The admin token is never injected into containers.
- Connection API keys encrypted at rest (Fernet, `HANGAR_SECRET_KEY`); existing plaintext keys are migrated on startup.
- Docker access through `docker-socket-proxy` (no socket mounted in the hangar).
- Typed agent spec (Pydantic, JSON Schema at `/api/spec/schema`), JSON Merge Patch updates (`null` deletes),
  full-spec replace, rollback to any version.
- Async harness jobs: queue, cancel, live status/logs over SSE, orphan recovery after restart.
- One Docker image per harness (base/mock, claude-code, codex, deepseek-harness, hermes) with pinned versions;
  DeepSeek Harness telemetry disabled.
- Token usage from harness jobs (Claude Code, Codex, Hermes) and cost in US$ from per-connection prices.
- LLM-as-judge test cases (`judge` rubric); smoke tests include MCP `tools/list`; mock agents skip content checks.
- GitOps: `POST /api/apply` and `hangar apply -f`; template gallery (6 templates) in UI, API, CLI and MCP.
- `hangar` CLI; UI pages for creating agents, spec editor, rollback, templates, API keys, costs, async job playground.
- Alembic migrations (pre-Alembic databases are stamped automatically), pytest suite, E2E smoke script, CI.

### Changed
- Project renamed to **Agent Hangar**; compose project `agent-hangar`, networks `hangar_agents` / `hangar_jobs`.
- The gateway streams SSE responses instead of buffering them; the Docker state of all agents is read in a single call.

### Upgrading from "central-agents"
Stop the old stack without removing volumes, then add these to `.env`:
- `HANGAR_SECRET_KEY` and `INTERNAL_SECRET` (run `scripts/setup.sh`).
- `PGDATA_VOLUME=central-agents_pgdata`.
- `POSTGRES_USER=central` and `POSTGRES_DB=central`.

Then run `docker compose up -d --build` and re-ship your agents (`hangar ship <slug>`) so their containers get
per-agent tokens.
