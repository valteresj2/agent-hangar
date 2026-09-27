# Connecting clients

Two different things connect to the hangar:

1. **Builders.** AI clients that create and manage agents use the hangar's MCP at `/mcp` with an **admin** key.
2. **Consumers.** Apps and people using a shipped agent go through `/gw/<slug>/…` with an **invoke** key limited
   to that agent (`hangar keys create my-app --scope invoke --agent <slug>`).

Replace `<key>` below. The UI's **Connect** page shows these snippets with your URL.

## Builders (platform MCP)

**Claude Code**
```bash
claude mcp add --transport http agent-hangar http://localhost:8090/mcp --header "Authorization: Bearer <key>"
```

**Claude Desktop** (`claude_desktop_config.json`, via [mcp-remote](https://www.npmjs.com/package/mcp-remote))
```json
{"mcpServers": {"agent-hangar": {"command": "npx", "args": ["-y", "mcp-remote", "http://localhost:8090/mcp",
  "--header", "Authorization: Bearer <key>", "--allow-http"]}}}
```

**Codex CLI** (`~/.codex/config.toml`)
```toml
[mcp_servers.agent-hangar]
url = "http://localhost:8090/mcp"
http_headers = { Authorization = "Bearer <key>" }
```

**OpenCode** (`opencode.json`)
```json
{"mcp": {"agent-hangar": {"type": "remote", "url": "http://localhost:8090/mcp",
  "headers": {"Authorization": "Bearer <key>"}}}}
```

**ChatGPT** (connectors / developer mode) requires a public HTTPS URL. Put the hangar behind a domain or tunnel and
use `https://your-domain/mcp`.

Then ask, for example: *"Create an agent that triages support tickets into P1–P4 and drafts a reply. Test it and
ship it."*

## Consumers (a shipped agent)

**LibreChat** (`librechat.yaml`)
```yaml
endpoints:
  custom:
    - name: "Ticket Triage"
      apiKey: "<invoke key>"
      baseURL: "http://hangar:8090/gw/ticket-triage/v1"
      models: { default: ["ticket-triage"] }
      headers: { X-Channel: "librechat" }
```

**Any OpenAI SDK**
```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8090/gw/ticket-triage/v1", api_key="<invoke key>")
client.chat.completions.create(model="ticket-triage", messages=[{"role": "user", "content": "..."}])
```

**As an MCP tool** (the agent's skills and tools run behind a single tool):
```bash
claude mcp add --transport http ticket-triage http://localhost:8090/gw/ticket-triage/mcp --header "Authorization: Bearer <invoke key>"
```

**A2A.** Agent Card: `GET /gw/<slug>/.well-known/agent.json`. RPC: `POST /gw/<slug>/a2a` with `message/send`.

**Slack / Teams.** Native adapters are on the roadmap. Until then, a bot can call the OpenAI-compatible endpoint
with `X-Channel: slack`.
