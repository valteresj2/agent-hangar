# Security model

Agent Hangar runs other people's prompts and code-writing agents, so treat it like CI infrastructure. This page
describes what is protected today, and what is **not**.

## Credentials

| Credential | Power | Where it lives |
|---|---|---|
| `ADMIN_TOKEN` | Everything | `.env` of the hangar only. It is never injected into agents or jobs. Use it to bootstrap, then prefer API keys. |
| API key, scope `admin` | UI, `/api`, the hangar MCP, every agent | Shown once, stored as SHA-256. Revocable. |
| API key, scope `invoke` | Only `/gw/<slug>` for the listed agents (or all, if none listed) | This is what goes into LibreChat, Slack bots, OpenCode… |
| Per-agent internal token | `HMAC(INTERNAL_SECRET, slug)` | Injected into that agent's container only. With `X-Agent-Slug`, the hangar lets it call **only its own sub-agents** and, if the spec has the `platform_dashboard` tool, the read-only dashboard. A compromised agent cannot impersonate another. |
| Job token | Single job's callback | Random per job; accepted once. |
| Connection API keys | Your LLM provider | Encrypted at rest with Fernet (`HANGAR_SECRET_KEY`). Never returned by the API (only the last 4 characters). Decrypted only to start the container that needs it. |

Keep `HANGAR_SECRET_KEY` safe and backed up. Losing it makes the stored connection keys unreadable, so you would
have to re-enter them.

## Networks

| Network | Members | Why |
|---|---|---|
| `db_net` (internal) | Postgres, hangar | Agents and tool servers (which may execute code) can't reach the database |
| `hangar_agents` | hangar, agent containers, MCP servers such as Data Studio | Gateway → agents, agents → hangar `/internal`, agents → MCPs |
| `hangar_jobs` | hangar, harness job containers | Job callbacks. Jobs don't see agents |
| `docker_api` (internal) | hangar, docker-socket-proxy | Only the hangar talks to Docker |

## Containers

- **Agents** get a read-only root FS, a 64 MB tmpfs, `cap_drop: ALL` and `no-new-privileges`, plus memory, CPU and
  PID limits. They run on the `hangar_agents` network and never receive the Docker socket.
- **Jobs** get a new container per call and a non-root user, run on the separate `hangar_jobs` network, and are
  removed after the callback or timeout.

## The Docker socket (read this)

The hangar does not mount `/var/run/docker.sock`. It talks to
[`tecnativa/docker-socket-proxy`](https://github.com/Tecnativa/docker-socket-proxy) on an internal network, and
the proxy only allows the container, network and volume APIs. `exec`, `build`, image pulls, swarm, secrets and
plugins are denied.

**Limitation.** Anyone who controls the hangar process can still create a container with arbitrary settings,
such as a privileged container or a host bind mount. With a Docker backend, that is equivalent to root on the
host. The proxy reduces the attack surface, but it is not a sandbox boundary against a compromised hangar. For
real multi-tenant isolation, use a rootless Docker/Podman host, a dedicated VM, or the Kubernetes driver planned
on the roadmap, together with admission policies.

## Data Studio (code execution)

The Data Studio MCP server runs user-driven Python and SQL. Each conversation (session) has its own directory and its
own Linux uid, and every file-reading or SQL tool runs inside that session's kernel. One conversation can't read
another's files or the link-signing secret; the smoke test checks this. Limits:
- Kernels have outbound network access.
- Resource limits are per container, not per session.

With `DATA_STUDIO_SANDBOX=container`, each conversation gets its own sandbox container:
- only its workspace is mounted;
- per-session memory, CPU and PID limits;
- read-only root FS and no capabilities;
- a separate network with no path to agents or the database.

Use that mode when users don't trust each other. In that mode Data Studio talks to Docker through its own socket
proxy, so the Docker-socket caveat above applies to it too. See `mcp-servers/data-studio/README.md`.

## Network exposure

- Put the hangar behind TLS (a reverse proxy) before exposing it. ChatGPT connectors require HTTPS anyway.
- `/internal/*` is reachable from the published port, but every route there checks its own credential (a job
  token or a per-agent HMAC).
- Job containers can reach the internet, because they must call your LLM and MCPs. An egress allowlist is on the
  roadmap.

## Known gaps (tracked as issues)

These are not implemented yet:

- Egress allowlist for jobs.
- Human approval for destructive actions.
- Input/output guardrails.
- Secret references for HTTP tool auth headers (today, do not put tokens in tool URLs).
- OIDC/SSO and RBAC per team.
- Budgets and rate limits.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
