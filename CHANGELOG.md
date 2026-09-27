# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-09-27

First public release (previously an internal prototype called "Central de Agents").

### Added
- Scoped API keys (`admin`, `invoke` limited to specific agents); keys stored as SHA-256 and shown once.
- Per-agent internal tokens (HMAC of the slug): agents can only call their own sub-agents and, if allowed, the
  read-only dashboard. The admin token is never injected into containers.
- Connection API keys encrypted at rest (Fernet, `HANGAR_SECRET_KEY`); existing plaintext keys are migrated on startup.
- Docker access through `docker-socket-proxy` (no socket mounted in the hangar).
- Typed agent spec (Pydantic, JSON Schema at `/api/spec/schema`), JSON Merge Patch updates (`null` deletes),
  full-spec replace, rollback to any version.
- Async harness jobs: queue, cancel, live status/logs over SSE, orphan recovery after restart.
- One Docker image per harness (base/mock, claude-code, codex, deepseek-harness, hermes) with pinned versions;
  DeepSeek Harness telemetry disabled.
- Token usage from harness jobs (Claude Code, Codex, Hermes) and cost in US$ from per-connection prices.
- LLM-as-judge test cases (`judge` rubric); smoke tests include MCP `tools/list`; mock agents skip content checks.
- GitOps: `POST /api/apply` and `hangar apply -f`; template gallery (6 templates) in UI, API, CLI and MCP.
- `hangar` CLI; UI pages for creating agents, spec editor, rollback, templates, API keys, costs, async job playground.
- Alembic migrations (pre-Alembic databases are stamped automatically), pytest suite, E2E smoke script, CI.

### Changed
- Project renamed to **Agent Hangar**; compose project `agent-hangar`, networks `hangar_agents` / `hangar_jobs`.
- The gateway streams SSE responses instead of buffering them; the Docker state of all agents is read in a single call.

### Upgrading from "central-agents"
Stop the old stack without removing volumes, then add these to `.env`:
- `HANGAR_SECRET_KEY` and `INTERNAL_SECRET` (run `scripts/setup.sh`).
- `PGDATA_VOLUME=central-agents_pgdata`.
- `POSTGRES_USER=central` and `POSTGRES_DB=central`.

Then run `docker compose up -d --build` and re-ship your agents (`hangar ship <slug>`) so their containers get
per-agent tokens.
