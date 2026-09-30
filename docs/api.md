# HTTP API

Interactive OpenAPI docs: `GET /docs`. Authenticate with `Authorization: Bearer <token>` or
`X-API-Key: <token>`. The token is an admin key, a personal token (scope `user`) or a session token.
The browser UI uses the session cookie and must send `X-CSRF-Token` (the value of the `hangar_csrf` cookie) on
writes.

Every route below checks the caller's permission on the resource ([access.md](access.md)). Lists are filtered to
what the caller can see. Admins see everything.

## Login and session (`/api/auth`, open)

| Method | Path | Description |
|---|---|---|
| GET | `/api/auth/providers` | Configured login providers |
| GET | `/api/auth/login/{provider}?next=#/…` | Redirects to Google, Microsoft, GitHub or generic OAuth2 (authorization code + PKCE) |
| GET | `/api/auth/callback/{provider}` | Provider callback; opens the session and redirects to the UI |
| POST | `/api/auth/token` | `{token}` → session cookie (ADMIN_TOKEN, admin key or personal token) |
| POST | `/api/auth/logout` | Ends the session |
| GET | `/api/me` | Who am I: company role, teams, pending approvals |

## Company, teams, users, approvals

| Method | Path | Description |
|---|---|---|
| GET / PATCH | `/api/org` | Company name and default visibility (PATCH: admin) |
| GET / POST | `/api/teams` | List (with spend and your role) / create `{name, description?, require_approval?, maintainer?}` (admin) |
| GET / PATCH / DELETE | `/api/teams/{team}` | Detail / name, description (maintainer), `require_approval`, `budget_usd_month`, `budget_enforce` (admin) / delete (admin, no agents) |
| GET / POST | `/api/teams/{team}/members` | Members / add `{email, role}` (maintainer; pre-registers unknown e-mails) |
| PATCH / DELETE | `/api/teams/{team}/members/{user_id}` | Change role / remove |
| GET / POST / PATCH | `/api/users`, `/api/users/{id}` | List (auditor) / pre-register / role and `active` (admin; deactivating revokes sessions and keys) |
| GET | `/api/approvals` | What you can decide now, and your own requests |
| POST | `/api/promotions/{id}/approve` · `/reject` | Production approval (the requester cannot approve) |
| POST | `/api/agents/{slug}/access-requests` | `{reason}` request to use an agent of another team |
| GET | `/api/agents/{slug}/grants` | Pending and approved access (maintainer) |
| POST | `/api/access-requests/{id}/approve` · `/reject` · `/revoke` | Decide or revoke (revoking also revokes the person's keys) |
| PATCH | `/api/agents/{slug}/access` | `{visibility, expose_spec, team}` (maintainer) |
| GET | `/api/sso` | Providers, group mappings, SCIM URL (admin) |
| PUT | `/api/sso/{provider}` | `{enabled, client_id, client_secret, settings}` (secret encrypted) |
| POST / DELETE | `/api/sso/mappings`, `/api/sso/mappings/{id}` | Group → team `{provider, external_group, team, role}` |

## Schedules (`/api`)

A scheduled agent runs by itself in production at the chosen day and time. Creating, changing and deleting a
schedule requires the right to edit the agent. Team members can see schedules and their runs.

| Method | Path | Description |
|---|---|---|
| GET / POST | `/api/agents/{slug}/schedules` | List / create `{message, cron? \| run_at?, timezone?, name?, notify_url?}` |
| GET | `/api/schedules` | Every schedule you can see |
| PATCH / DELETE | `/api/schedules/{id}` | Change time, message or webhook; pause or resume with `enabled` / delete |
| POST | `/api/schedules/{id}/run` | Run now and wait for the result |
| GET | `/api/schedules/{id}/runs` | History: status, answer, tokens, cost, webhook delivery |

- **`cron`:** five fields (minute, hour, day of month, month, day of week) in the schedule's time zone.
  Examples: `0 9 * * 1-5` runs on weekdays at 09:00, and `0 8 5 * *` runs on the 5th at 08:00. Aliases such as
  `@daily` work too.
- **`run_at`:** a one-off run, for example `2026-10-05T09:00`.
- **Time zone:** defaults to the company's, set with `PATCH /api/org {"timezone": "America/Sao_Paulo"}`.
- **When it runs:** only while the agent is in production. A schedule created earlier waits, and takes effect
  when the agent goes live.
- **`notify_url`:** receives `{text, agent, schedule, status, output, …}`, a payload that works with Slack and
  Teams incoming webhooks.
- **Limits:** runs at least 5 minutes apart, and webhooks to the internal network are blocked.

## Remote MCPs with OAuth (`/api/remote-mcps`, admin)

| Method | Path | Description |
|---|---|---|
| GET / POST | `/api/remote-mcps` | List / start a connection `{name, url, description?, browser_base?}` → `{authorize_url}` |
| GET | `/api/remote-mcps/callback` | OAuth redirect target (stores the tokens, creates the catalog MCP) |
| POST | `/api/remote-mcps/{name}/test` | List the tools with the stored token |
| DELETE | `/api/remote-mcps/{name}` | Revoke and remove |

Agents reach the MCP at `/internal/mcp-remote/{name}` with their internal token. See [remote-mcp.md](remote-mcp.md).

## SCIM 2.0 (`/scim/v2`, scope `scim`)

`Users`, `Groups`, `ServiceProviderConfig`, `ResourceTypes` and `Schemas`, with filters (`userName eq`,
`externalId eq`, `displayName eq`) and PATCH in the Entra ID and Okta formats. See [access.md](access.md#scim-20-provisioning).

## Agents and platform (`/api`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Open. `{status, version}` |
| GET | `/api/overview` | KPIs, 14-day series, top agents, cost |
| GET | `/api/spec/schema` | JSON Schema of the agent spec |
| GET / POST | `/api/agents` | List (with `team`, `visibility`, `access`, `permissions`) / register `{name, objective, final_output, owner?, slug?, team?, visibility?}` (developer+) |
| GET | `/api/agents/{slug}` | Detail: spec, versions, tests, deployments, jobs, endpoints, usage |
| PATCH | `/api/agents/{slug}` | JSON Merge Patch on spec (and name/objective/final_output/owner) |
| PUT | `/api/agents/{slug}/spec` | Replace the spec |
| POST | `/api/agents/{slug}/rollback` | `{version}` → new version with that spec |
| POST | `/api/agents/{slug}/edit` | Edit later: `{changes, test, promote, note}`. Creates a new version, runs the tests in stage (`test`) and, if they pass, promotes to production or asks for approval (`promote`). Returns what changed |
| GET | `/api/agents/{slug}/diff?from_version=&to_version=` | What changed in the spec between two versions |
| POST | `/api/agents/{slug}/test` | Deploy stage + run tests |
| POST | `/api/agents/{slug}/deploy` | `{env: stage\|prod}`. Prod is gated by tests; without the right to promote it returns `status: approval_pending` and a request |
| POST | `/api/agents/{slug}/ship` | Sub-agents → stage → tests → prod. The last step can be `approval_pending` |
| POST | `/api/agents/{slug}/stop` | `{env}` |
| POST | `/api/agents/{slug}/chat` | `{message, env}` |
| GET | `/api/agents/{slug}/logs?env=` | Container logs |
| DELETE | `/api/agents/{slug}` | Delete agent and containers |
| POST | `/api/agents/{slug}/job` | `{task, env, timeout_s?, wait}`; `wait=false` returns immediately |
| GET | `/api/jobs/{id}` | Job state |
| POST | `/api/jobs/{id}/cancel` | Cancel |
| GET | `/api/jobs/{id}/events` | **SSE**: `status`, `log`, `done` |
| GET | `/api/catalog` | Skills, MCP servers, connections (keys masked) |
| POST | `/api/catalog/skills` · `/api/catalog/mcps` · `/api/catalog/llm` | Upsert |
| DELETE | `/api/catalog/llm/{name}` | Refused while an agent uses it |
| POST | `/api/apply` | GitOps document `{skills, mcp_servers, agents}` (idempotent) |
| GET | `/api/templates`, `/api/templates/{id}` | Gallery |
| POST | `/api/templates/{id}/apply` | `{connection?, harness_connection?}` |
| GET / POST | `/api/keys` | Your keys (admin: all) / create `{name, scopes: [user\|invoke\|admin\|scim], agents: []}`; the key is returned once |
| DELETE | `/api/keys/{id}` | Revoke (also disconnects a tool connection) |
| GET | `/api/connect/clients` | Tools that can be connected and the modes each supports (`mcp`, `model`) |
| GET | `/api/agents/{slug}/connections` | Active tool connections of an agent |
| GET | `/api/agents/{slug}/connections/snippet?client=&mode=` | Config preview with a placeholder key; creates nothing |
| POST | `/api/agents/{slug}/connections` | `{client, mode}` → per-tool `invoke` key (returned once) + `{language, file, content, steps}` |
| GET | `/api/tests`, `/api/deployments`, `/api/usage`, `/api/audit` | Recent records |

## Gateway (`/gw/<slug>`: invoke key for that agent, a user who can use it, or admin)

`/gw/<slug>/…` = prod, `/gw-stage/<slug>/…` = stage.

| Protocol | Path |
|---|---|
| OpenAI-compatible | `POST v1/chat/completions` (`stream: true` supported), `GET v1/models` |
| A2A | `GET .well-known/agent.json` (also `agent-card.json`), `POST a2a` (`message/send`) |
| ACP | `GET acp/agents`, `POST acp/runs` |
| MCP | `POST mcp` (Streamable HTTP, stateless, JSON responses) |

Optional header `X-Channel: <name>` tags usage for per-channel metrics. Without it, a key created by a tool
connection tags usage with its tool (`claude-code`, `open-webui`, …); other keys fall back to `api`.

## Platform MCP (`/mcp`, admin key or personal token)

The client acts with the key owner's roles. The tools are:

- **Guidance:** `platform_guide`, `get_spec_schema`, `whoami`.
- **Access:** `request_agent_access`, `list_approvals`, `decide_approval`.
- **Schedules:** `schedule_agent`, `list_schedules`, `update_schedule`, `delete_schedule`, `run_schedule_now`, `schedule_runs`.
- **Catalog:** `list_catalog`, `register_llm_connection`, `register_skill`, `register_mcp_server`.
- **Templates:** `list_templates`, `apply_template`.
- **Build:** `register_agent`, `design_agent` (merge patch plus `remove`), `rollback_agent`, `build_multi_agent`.
- **Inspect:** `list_agents`, `get_agent`, `get_agent_spec` (spec, plus which version runs in prod and in stage).
- **Edit later:** `edit_agent` (changes, then stage and tests, then publish when `promote=True`), `diff_agent_versions`, `update_agent_access`.
- **Test and deploy:** `run_tests`, `deploy_stage`, `promote_to_production`, `ship_agent`, `stop_agent`.
- **Use:** `chat_with_agent`, `run_harness_job` (`wait`), `get_job`, `cancel_job`, `create_consumer_key`,
  `connect_agent` (per-tool key + ready-to-paste config).

## Internal (`/internal`, called from containers only)

These routes are:

- `POST /internal/jobs/{id}/callback`, authenticated by the job token.
- `/internal/gw/…`, used for agent → sub-agent calls.
- `GET /internal/dashboard/*`, a read-only view for agents with `platform_dashboard`.

The last two are authenticated by `X-Agent-Slug` plus that agent's HMAC token.
