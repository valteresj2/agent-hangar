# Agent Hangar for VS Code

This extension puts your company's AI agents, governed by [Agent Hangar](https://github.com/valteresj2/agent-hangar),
inside the VS Code chat.

## What you get

**Your agents in the chat's model picker.** Pick an agent and use the chat in **Agent** mode. The agent:
- follows its instructions, company skills, MCPs and memory, which run in the hangar;
- works on **your project** with VS Code's own tools: it reads and edits files and runs terminal commands, always
  with your approval;
- is told to run the project's tests before it finishes.

The files and the terminal never leave your machine.

**The platform MCP (Agent Hangar).** Ask the chat to *create*, *edit*, *test* or *publish* an agent without leaving
the editor, with your roles and teams.

**One-click sign-in.**
1. **Agent Hangar: Entrar pelo portal** opens the company portal. You are already signed in there (SSO or a local
   account), so you just confirm.
2. VS Code comes back on its own, connected. No keys to copy.
3. The connection is a personal key, listed under **Minhas chaves** in the portal. It is revoked when you sign out,
   or automatically when you lose access.

**Connection test.** **Agent Hangar: Testar conexão** runs the same path the chat uses (client tools over
streaming) and shows each step.

## Settings

| Setting | Default | |
|---|---|---|
| `agentHangar.url` | `http://localhost:8090` | Your company's hangar address |
| `agentHangar.environment` | `prod` | `stage` shows the stage version of the agents you edit, to test them before publishing |

## Install

1. Download the `.vsix` from the portal: **Conectar ferramentas → VS Code**. It is also at
   `<hangar>/downloads/agent-hangar-vscode.vsix`.
2. Install it with `code --install-extension agent-hangar-vscode.vsix`, or in VS Code under **Extensions → … →
   Install from VSIX**.

You need VS Code 1.104 or later, with the chat available.
