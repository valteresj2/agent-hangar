# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] — 2026-09-29

### Added
- **Agent schedules.** An agent in production runs by itself at the day and time the user asks for.
  - **Recurrence and time zone:** a cron expression or a one-off date and time, in the company's time zone
    (`PATCH /api/org {"timezone": …}`) or the schedule's own.
  - **MCP:** `schedule_agent`, `list_schedules`, `update_schedule`, `delete_schedule`, `run_schedule_now` and
    `schedule_runs`. The platform guide tells the assistant to schedule when the request includes days and times.
  - **Before production:** a schedule created before the agent goes live waits and starts once the agent is in
    production.
  - **Results:** a run history with the answer, tokens and cost, and an optional webhook (Slack, Teams or HTTP).
  - **Where to find it:** a **Schedules** tab on each agent, *Upcoming scheduled runs* on the dashboard, the API
    (`/api/agents/{slug}/schedules`, `/api/schedules/…`) and the `hangar schedules` CLI.
  - **Safeguards:** only editors can schedule, runs are at least 5 minutes apart, the team budget is respected,
    and webhooks to the internal network are blocked. The scheduler reserves each run with a conditional update,
    so it is safe with several replicas. A run missed while the central was down runs once, marked as `late`.
- **Edit agents later through the MCP** (and the API):
  - `get_agent_spec` shows the current spec and which version runs in production and in stage;
  - `edit_agent` applies changes to the spec and to name, objective, final output and contact as a new
    version, deploys it to stage and runs the tests. Production keeps the previous version. With
    `promote=True` it publishes only if the tests pass, or asks for approval when the role or team requires it;
  - `diff_agent_versions` shows what changed before publishing;
  - `update_agent_access` changes visibility, owner team and exposed spec.
- API: `POST /api/agents/{slug}/edit` and `GET /api/agents/{slug}/diff`.

### Fixed
- Deleting an agent that had schedules, access requests or promotion requests failed on Postgres.
- Elements with the `hidden` attribute could still show when a component set `display`.

### Upgrading from 0.3.x
- **Migration 0006 runs on start.** It adds the schedules and run history, and the company time zone.
- **Set the company time zone** used by default in schedules: `PATCH /api/org {"timezone": "America/Sao_Paulo"}`.
  The default is UTC.
- **The scheduler runs inside the central** (`SCHEDULER_ENABLED=1`). With more than one replica, each run is
  claimed once.

## [0.3.1] — 2026-09-29

### Fixed
- Text fields that send with Enter (Playground, token login, new team name) blocked typing: only accented letters
  got through. The key handler returned `false` for every other key, which cancels the keystroke. A test now
  guards against this pattern.
- Playground:
  - the send button is disabled while the agent answers, and focus returns to the field;
  - latency, tokens, cost and tools used appear under each answer;
  - errors are highlighted.

## [0.3.0] — 2026-09-28

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
- **Local accounts** (username and password, optional with `LOCAL_LOGIN`).
  - Passwords are hashed with scrypt; accounts lock out after 5 failures.
  - Users change their own password; admins reset passwords.
- **SCIM 2.0** (`/scim/v2`): the directory provisions and deactivates users and syncs groups to teams.
- **Sessions.** The UI uses a `HttpOnly` session cookie with CSRF protection instead of a token in
  `localStorage`. "Sign in with token" remains as break-glass access.
- **Keys belong to people.**
  - New scopes `user` (personal token for the CLI and MCP) and `scim`.
  - Keys are revoked automatically when the owner loses access or is deactivated.
- **Monthly budget per team**, with an alert and an optional block (`429` at the gateway).
- Creating a team: a visible **+ Novo time** button (list and team detail) and an optional first maintainer (`maintainer` on `POST /api/teams`).
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

### Changed
- **New UI design** following the *Frontend Design* skill (aitmpl.com), with the pre-delivery checklist of
  *UI/UX Pro Max*.
  - **Hangar look:** a tarmac-dark sidebar with grouped navigation (Operação, Construção, Monitoramento,
    Acesso) and a single safety-yellow accent for primary actions, the active item and focus.
  - **Type:** Barlow Semi Condensed for headings, IBM Plex Sans for text, IBM Plex Mono for code.
  - **Screens:** KPIs as one status board, agent rows as flight strips colored by status, and a two-column
    login.
  - **Icons:** SVG icons instead of emojis.
  - **Accessibility:** visible keyboard focus, 44px touch targets, `prefers-reduced-motion`, and dark mode.

### Fixed
- `http://…/ui` without the trailing slash returned 404; `/ui` and `/login` now redirect to the UI, and `/favicon.ico` exists.
- A page left in the browser cache by an older version reloads itself at the current version instead of failing.
- The UI is served with `Cache-Control: no-cache`, and its assets carry a content hash (`app.js?v=…`), so
  browsers never keep an old version after an upgrade.
- Calls through an agent's MCP endpoint now record tokens and cost (the tool result carries `_meta.usage`).
- MCP handshakes, `tools/list` and pings are no longer counted as requests.

### Upgrading from 0.2.x
- **Migrations run on start.** Migration 0004 adds the users, teams and access tables, and 0005 adds local
  accounts. Existing agents move to the default **Plataforma** team with visibility `org`.
- **The UI now opens on a login page.** The first time, use **Entrar com token** with your `ADMIN_TOKEN`. Then
  create people in **Usuários** (SSO, or a local account with username and password) and teams in **Times**.
  You can also set `BOOTSTRAP_ADMIN_EMAILS` to get admin on the first SSO login.
- **Existing keys keep working.** Admin keys and invoke keys, such as the one in LibreChat, are unchanged.
- **Personal tokens for builders.** People who build agents through the platform MCP should switch to a personal
  token (scope `user`), so the client acts with their team roles.
- **Re-ship chat agents** (`hangar ship <slug>`) to get the new runtime: MCP usage with tokens and Open WebUI
  session headers.

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
