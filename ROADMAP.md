# Roadmap

Each item links to a GitHub issue once the repository is public. Priorities follow feedback: 👍 the issues you care about.

## v0.1 — first public cut ✅
- Registry, immutable versions, stage → tests → prod gate, one-click rollback
- Chat, harness (Claude Code, Codex, Hermes, DeepSeek Harness) and multi-agent (A2A) agents
- OpenAI-compatible, A2A, ACP and MCP per agent, behind an authenticated gateway
- Scoped API keys, per-agent internal tokens, encrypted connection keys, Docker socket proxy
- Async jobs with SSE, cancel and orphan recovery; one image per harness with pinned versions
- LLM-as-judge tests; cost in US$ per call, agent, channel and job
- UI (create, spec editor, templates, keys), `hangar` CLI, GitOps `apply`, 6 templates
- Alembic migrations, pytest suite, CI

## v0.2 — delivered ✅ (Data Studio, LibreChat kit, live progress, sandbox per conversation)
- See CHANGELOG 0.2.0

## v0.3 — reliable (moved from v0.2)
- Real token streaming from the agent runtime (today the full answer is sent as one SSE chunk)
- Redis-backed job queue so the hangar can run with multiple replicas
- A2A task lifecycle (`tasks/get`, streaming, push notifications)
- Images published to GHCR on every release (`docker compose pull`, no build)
- Eval datasets per agent + regression check against the prod version before promoting

## v0.3 — adoptable
- Slack and Microsoft Teams channel adapters
- Docs site, hero GIF, 20 `good first issue`s
- React/Svelte frontend with component library; version diff view
- Telemetry (opt-in, anonymous) for time-to-first-agent

## v0.4 — observable & governed
- OpenTelemetry traces end-to-end (gateway → agent → LLM → tools → sub-agents), Langfuse export
- Rate limits per agent and per consumer key (monthly budgets per team: done)
- Guardrails (prompt-injection detection, PII redaction) as gateway plugins
- Secret references for HTTP tool auth (`secret:crm-token`)

## v1.0 — enterprise-ready
- Kubernetes runtime driver + Helm chart + NetworkPolicies
- Multi-tenancy (several companies per installation; `org_id` is already on the tables). Done earlier: OAuth2 SSO, teams and roles, SCIM
- Egress allowlist for jobs; human approval for destructive harness actions
- Exportable audit trail (SIEM)
