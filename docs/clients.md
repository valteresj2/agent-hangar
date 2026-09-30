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
| **Model, as a coding agent** | The agent is the model, and the editor's own tools (read and edit files, terminal) run on the developer's machine | VS Code chat, Cline / Roo Code, Continue |

| Tool | MCP | Model | Where the config goes |
|---|:-:|:-:|---|
| Claude Code | ✓ | | `claude mcp add --transport http …` |
| Claude Desktop | ✓ | | `claude_desktop_config.json` (via `mcp-remote`) |
| Codex CLI | ✓ | | `~/.codex/config.toml` |
| OpenCode | ✓ | ✓ | `opencode.json` (`mcp` or `provider`) |
| Cursor | ✓ | | `.cursor/mcp.json` |
| VS Code (Copilot) | ✓ | ✓ | `.vscode/mcp.json`, or *Manage models → OpenAI Compatible* for the coding agent |
| Cline / Roo Code | | ✓ | *API Provider: OpenAI Compatible* (base URL, key, model id) |
| Continue | | ✓ | `~/.continue/config.yaml` (`provider: openai`, `capabilities: [tool_use]`) |
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

## VS Code extension: Agent Hangar

This is the plug-and-play way to use agents in VS Code. The hangar builds the extension with the central image and
serves it at `/downloads/agent-hangar-vscode.vsix`. The source is in [extensions/vscode](../extensions/vscode/).

| | |
|---|---|
| **Your agents as chat models** | The chat agents you can use appear in VS Code's model picker (`lm.registerLanguageModelChatProvider`). In **Agent** mode the agent works on your project with VS Code's own tools (files, terminal) through the client-tools path below |
| **Platform MCP** | Registered by the extension (`lm.registerMcpServerDefinitionProvider`) with your personal token, so the chat can create, edit, test and publish agents with your roles |
| **Sign-in** | Through the portal, with PKCE: the extension opens `/app/#/vscode`, you confirm (you are already signed in with SSO or a local account), and VS Code comes back connected. No keys to copy |
| **Test** | **Agent Hangar: Testar conexão** runs the same end-to-end check as the Connect tab |
| **stage** | Set `agentHangar.environment` to `stage` to see the stage version of the agents you edit, and test them before publishing |

**How sign-in works:**
1. `POST /api/vscode/authorize` runs in the portal, with your session. It returns a signed, single-use code, valid
   for 5 minutes and bound to the extension's PKCE challenge.
2. The browser goes to `vscode://agent-hangar.agent-hangar/auth`.
3. The extension exchanges code + verifier at `POST /api/auth/vscode/token` for a personal key: scope `user`, client
   `vscode-ext`, listed under **Minhas chaves**.
4. Signing out of the extension revokes the key on the server. Losing access revokes it too.

**Install:**
1. In the portal, go to **Conectar ferramentas** (or an agent's **Connect** tab) and use **Baixar extensão (.vsix)**.
2. Run `code --install-extension agent-hangar-vscode.vsix`.
3. Click **Abrir no VS Code** in the portal. You need VS Code 1.104 or later.

## Coding agents in VS Code (client tools)

A coding client sends its **own tools** with each request, in the OpenAI format (`tools`): read and edit files,
search the project, run a terminal command. Examples are the VS Code chat, Cline, Roo Code and Continue. The agent
works like this:
- It offers the model the client's tools next to its own: MCPs, memory, sub-agents, skills.
- When the model calls **one of the agent's tools**, the agent runs it on the server, as always.
- When the model calls **one of the client's tools**, the agent returns it to the client (`tool_calls`, with
  `finish_reason: "tool_calls"`, streaming or not). The editor runs it on the developer's machine, with the
  developer's approval, and sends the result back. The loop goes on until the final answer.
- If both kinds come in the same round, the server part runs first. Its context is kept and put back in place when
  the client sends its results, so nothing is lost between requests.

So the files and the terminal never leave the developer's machine, and the hangar adds the governed part:
- instructions and company standards (skills);
- MCPs and memory;
- versioning with tests;
- a per-tool key, usage and cost per person.

When client tools are present, the agent also gets a short standing instruction: read before editing, make small
verifiable changes, run the project's tests or build before finishing, and never read or expose secrets.

**Connect:** in the agent's **Connect** tab, choose *VS Code → Como modelo*, *Cline / Roo Code* or *Continue*. You get a
per-tool key and the values to paste: base URL `…/gw/<slug>/v1`, the key and the model id `<slug>`.

**Test the connection:** the **Testar conexão** card in the same tab, `POST /api/agents/<slug>/connections/test`, or
the platform MCP tool `test_agent_connection`, runs the exact path a coding client takes:
1. It sends a client tool (`hangar_ping`) and checks, over the stream, that the agent calls it
   (`tool_calls` + `finish_reason: tool_calls`).
2. It returns the result the way the editor would, and checks that the agent uses it to answer.

The test costs one short LLM call and works in stage (for whoever can edit the agent) or in prod.

**Turning it off:** set `llm.client_tools: false` in an agent's spec. The agent then ignores the tools a client sends
and answers only with its own. Harness agents don't take client tools, because they run in their own throwaway
container.

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
