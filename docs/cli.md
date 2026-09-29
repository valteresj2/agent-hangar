# CLI (`hangar`)

```bash
pip install ./cli            # from a clone; requires Python 3.10+
hangar login http://localhost:8090 --token <personal token>   # UI → Chaves de API → scope "user"
```

Credentials are read from `HANGAR_URL` / `HANGAR_TOKEN`, or from `~/.config/hangar/config.json` (written by
`login`, mode 600). Every command accepts `--json`.

| Command | What it does |
|---|---|
| `hangar whoami` | Your company role and teams |
| `hangar agents ls [--mine]` | Agents you can see: team, your access, status, version, stage/prod, requests and cost (7d) |
| `hangar agents get <slug> [--spec]` | Detail, or just the spec as YAML |
| `hangar apply -f file.yaml [--ship]` | GitOps apply (`{skills, mcp_servers, agents}`; multiple YAML documents allowed; `-` = stdin). Template files are accepted too |
| `hangar export <slug>` | Print an agent as an applyable YAML document |
| `hangar test <slug>` | Run stage tests; exit code 1 if they fail (useful in CI) |
| `hangar ship <slug>` | Stage → tests → prod |
| `hangar deploy <slug> --env stage|prod` | Deploy one environment |
| `hangar rollback <slug> <version>` | Restore an old spec as a new version |
| `hangar chat <slug> <message…> [--env]` | Talk to an agent |
| `hangar logs <slug> [--env]` | Container logs |
| `hangar jobs run <slug> <task…> [--follow] [--timeout N]` | Harness job; `--follow` streams status and logs, Ctrl+C cancels |
| `hangar jobs get <id>` / `hangar jobs cancel <id>` | Inspect / cancel |
| `hangar templates ls` / `hangar templates apply <id> [--connection C] [--harness-connection H]` | Template gallery |
| `hangar connect <slug> [tool] [--mode mcp\|model] [--preview] [--list]` | Plug an agent into a tool: creates a per-tool key and prints the config (steps on stderr). No tool = list tools |
| `hangar keys ls` / `create <name> --scope invoke --agent <slug>` / `revoke <id>` | API keys (`create` prints the key on stdout). `--scope user` = personal token for the CLI and the platform MCP |
| `hangar teams ls` / `hangar teams add <team> <email> --role developer` | Teams (with spend) and members |
| `hangar approvals ls` / `approve <kind> <id>` / `reject <kind> <id>` | Production (`promotion`) and access (`access`) approvals |
| `hangar request-access <slug> <reason…>` | Ask a team to use its agent |
| `hangar schedules ls [slug]` / `add <slug> <message…> --cron '0 9 * * 1-5'` (or `--at 2026-10-05T09:00`) / `run <id>` / `rm <id>` | Schedules: the agent runs by itself in production |

## Agents in CI

```yaml
# .github/workflows/agents.yml
- run: pip install ./cli
- run: hangar apply -f agents/ --ship
  env:
    HANGAR_URL: ${{ secrets.HANGAR_URL }}
    HANGAR_TOKEN: ${{ secrets.HANGAR_ADMIN_KEY }}
```

`apply` only creates versions for specs that changed, and `ship` refuses to promote a version whose tests fail.
