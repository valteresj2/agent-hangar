# Docker MCP catalog (prebuilt MCP servers)

Agent Hangar can give agents **230+ ready-made MCP servers** from Docker's official MCP catalog: search, web
fetch, Wikipedia, GitHub, Postgres, Notion, Slack, AWS and more.
- **Isolation:** each server runs in its own container, from a signed image.
- **Management:** admins turn servers on or off in the UI. Agents use them like any other catalog MCP.

This runs on the open-source [Docker MCP Gateway](https://github.com/docker/mcp-gateway) (MIT) and is
optional: compose profile `mcp-gateway`.

## Turn it on

```bash
docker compose --profile mcp-gateway up -d
```

1. Open **Catálogo → Catálogo Docker MCP**, as an admin.
2. Search and click **Ativar**. When a server needs credentials (for example a GitHub token), the card asks for
   them. They are stored encrypted in the Hangar database.
3. The server becomes the catalog MCP **`docker:<name>`**. Add it to an agent's `mcps`, for example with
   `design_agent(slug, mcps=["docker:duckduckgo", "docker:fetch"])`, and ship.

Each `docker:<name>` item exposes **only that server's tools**: an agent using `docker:fetch` does not see the
GitHub tools, even though the gateway runs both. The filter is the item's `tool_prefix`, applied by the agent
runtime.

API (admin): `GET /api/mcp-gateway/catalog?q=`, `PUT /api/mcp-gateway/servers/{name}` with
`{secrets, config}`, `DELETE /api/mcp-gateway/servers/{name}` and `GET /api/mcp-gateway/status`.

## How it fits together

```
agents (hangar_agents) ──► mcp-gateway (socat forwarder) ──► mcp-gateway-core ──► MCP server containers
                                                              │  (hangar_mcp_servers: internet egress)
central ── writes registry/config/secrets ──► volume ──► gateway reloads (--watch)
mcp-gateway-core ── unix socket ──► shim ──► docker-socket-proxy (containers + images only) ──► Docker
```

- **Only admins decide which servers run.** The gateway's `dynamic-tools` feature, which would let an LLM add
  servers by itself (`mcp-add` / `mcp-remove`), is disabled in `mcp-servers/docker-gateway/docker-config.json`.
- **Signed images.** The gateway runs with `--verify-signatures` and `--block-secrets`. Every server runs with
  `no-new-privileges` and CPU and memory limits.
- **Network isolation.** The gateway attaches the servers it starts to every network the gateway is on. So the
  gateway lives only on `hangar_mcp_servers`, which has internet egress but no agents and no database. Agents
  reach it through a small forwarder, and neither the gateway nor the servers are on the Docker-API network.
- **Restricted Docker access.** Docker is reached through a unix socket (shim) in front of a
  `docker-socket-proxy` limited to containers and images. That is the same pattern as the Data Studio
  sandboxes. Treat the gateway like other components with Docker access (see [security.md](security.md)).
- **No token between agents and the gateway yet.** The gateway accepts unauthenticated requests, but it is
  reachable only from the internal agents network through the forwarder, and it has no published port. Per-MCP
  auth headers are the next step.

## Limits of this version

- **Container servers only.** Only the catalog's container servers (237) are supported. Remote servers, which
  mostly use per-user OAuth, are not yet.
- **One credential per server.** Credentials are per server, shared by the agents that use it, not per end user.
- **Gateway version.** The version is pinned (`MCP_GATEWAY_VERSION`, default the stable `v0.43.3`). The catalog
  URL is `MCP_GATEWAY_CATALOG_URL`.
