# HTTP API

Interactive OpenAPI docs: `GET /docs` (admin credential required). Authenticate with
`Authorization: Bearer <token>` or `X-API-Key: <token>`.

## Admin API (`/api`, scope `admin`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Open. `{status, version}` |
| GET | `/api/overview` | KPIs, 14-day series, top agents, cost |
| GET | `/api/spec/schema` | JSON Schema of the agent spec |
| GET / POST | `/api/agents` | List / register `{name, objective, final_output, owner?, slug?}` |
| GET | `/api/agents/{slug}` | Detail: spec, versions, tests, deployments, jobs, endpoints, usage |
| PATCH | `/api/agents/{slug}` | JSON Merge Patch on spec (and name/objective/final_output/owner) |
| PUT | `/api/agents/{slug}/spec` | Replace the spec |
| POST | `/api/agents/{slug}/rollback` | `{version}` → new version with that spec |
| POST | `/api/agents/{slug}/test` | Deploy stage + run tests |
| POST | `/api/agents/{slug}/deploy` | `{env: stage|prod}` (prod is gated by tests) |
| POST | `/api/agents/{slug}/ship` | Sub-agents → stage → tests → prod |
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
| GET / POST | `/api/keys` | List / create `{name, scopes: [admin|invoke], agents: []}`; the key is returned once |
| DELETE | `/api/keys/{id}` | Revoke |
| GET | `/api/tests`, `/api/deployments`, `/api/usage`, `/api/audit` | Recent records |

## Gateway (`/gw/<slug>`, scope `invoke` for that agent, or `admin`)

`/gw/<slug>/…` = prod, `/gw-stage/<slug>/…` = stage.

| Protocol | Path |
|---|---|
| OpenAI-compatible | `POST v1/chat/completions` (`stream: true` supported), `GET v1/models` |
| A2A | `GET .well-known/agent.json` (also `agent-card.json`), `POST a2a` (`message/send`) |
| ACP | `GET acp/agents`, `POST acp/runs` |
| MCP | `POST mcp` (Streamable HTTP, stateless, JSON responses) |

Optional header `X-Channel: <name>` tags usage for per-channel metrics.

## Platform MCP (`/mcp`, scope `admin`)

The tools are:

- **Guidance:** `platform_guide`, `get_spec_schema`.
- **Catalog:** `list_catalog`, `register_llm_connection`, `register_skill`, `register_mcp_server`.
- **Templates:** `list_templates`, `apply_template`.
- **Build:** `register_agent`, `design_agent` (merge patch plus `remove`), `rollback_agent`, `build_multi_agent`.
- **Inspect:** `list_agents`, `get_agent`.
- **Test and deploy:** `run_tests`, `deploy_stage`, `promote_to_production`, `ship_agent`, `stop_agent`.
- **Use:** `chat_with_agent`, `run_harness_job` (`wait`), `get_job`, `cancel_job`, `create_consumer_key`.

## Internal (`/internal`, called from containers only)

These routes are:

- `POST /internal/jobs/{id}/callback`, authenticated by the job token.
- `/internal/gw/…`, used for agent → sub-agent calls.
- `GET /internal/dashboard/*`, a read-only view for agents with `platform_dashboard`.

The last two are authenticated by `X-Agent-Slug` plus that agent's HMAC token.
