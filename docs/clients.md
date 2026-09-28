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

## Plug a shipped agent into a tool (plug and play)

Open the agent in the UI, go to the **Connect** tab, pick a tool and a mode. The hangar creates an `invoke` key that
only reaches that agent, tags it with the tool (usage shows up under that channel) and gives you the config to paste.
Every connection is optional and independent: connect the same agent to Claude Code as a tool and to Open WebUI as a
model, and revoke either one alone with **Disconnect**.

| Mode | What the tool sees | Offered for |
|---|---|---|
| **MCP (tool)** | One tool named after the agent; its skills, MCPs and LLM run behind it | Every tool |
| **Model** | The agent is a chat model (OpenAI-compatible, streaming, attachments) | LibreChat, Open WebUI, OpenCode, OpenAI SDKs |

| Tool | MCP | Model | Where the config goes |
|---|:-:|:-:|---|
| Claude Code | ✓ | | `claude mcp add --transport http …` |
| Claude Desktop | ✓ | | `claude_desktop_config.json` (via `mcp-remote`) |
| Codex CLI | ✓ | | `~/.codex/config.toml` |
| OpenCode | ✓ | ✓ | `opencode.json` (`mcp` or `provider`) |
| Cursor | ✓ | | `.cursor/mcp.json` |
| VS Code (Copilot) | ✓ | | `.vscode/mcp.json` |
| LibreChat | ✓ | ✓ | `librechat.yaml` (`mcpServers` or `endpoints.custom`) |
| Open WebUI | ✓ | ✓ | Admin → Settings → *External Tools* (MCP) or *Connections* (OpenAI API) |
| OpenAI SDK / other | | ✓ | `base_url` + key |
| Other MCP client | ✓ | | Streamable HTTP URL + `Authorization` header |

The same flow is available without the UI:

```bash
hangar connect ticket-triage                            # list tools and modes
hangar connect ticket-triage claude-code                # MCP (default): creates the key, prints the config
hangar connect ticket-triage open-webui --mode model    # as a model
hangar connect ticket-triage librechat --preview        # config with a placeholder, creates nothing
hangar connect ticket-triage --list                     # active connections (revoke: hangar keys revoke <id>)
```

From an AI client connected to the platform MCP, ask for it: the `connect_agent(slug, client, mode)` tool returns the
same key and config.

Notes:
- Only **prod** agents answer on `/gw/<slug>`; connect after `ship`.
- MCP usage counts only real tool calls (handshake and `tools/list` are not metered), with tokens and cost.
- Open WebUI: to get one Data Studio workspace per chat, run it with `ENABLE_FORWARD_USER_INFO_HEADERS=true`; the
  runtime reads `X-OpenWebUI-Chat-Id`.
- Claude Code asks once to approve servers added with `--scope project`; `--scope user` (the default in the
  snippet) does not.

## Consumers (a shipped agent)

**LibreChat**: the full kit, with per-conversation workspaces, attachments and a Docker Compose file, is in [integrations/librechat](../integrations/librechat/). Minimal `librechat.yaml`:
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
