# Reuse before you build: new agents from existing ones

When someone asks for an agent, the hangar first looks for what already exists in the company catalog. It then builds
the new agent from those pieces instead of starting from zero.

**Existing agents are read-only pieces.** Nothing about them changes: instructions, versions, tests, memory, access and
deploys stay as they are. All the building happens in the **new** agent.

## The flow

```
plan_agent (request) → [up to 3 questions about missing skills] → compose_agent (chosen pieces) → ship_agent
```

The MCP server tells Claude, ChatGPT, Cursor and other clients to call `plan_agent` before creating any agent. The
same flow is in the portal: **Novo agente → 1. Reusar antes de construir**.

### 1. `plan_agent`: what in the catalog looks like the request

Pass the request and, ideally, the request split into 2–6 short capabilities:

```json
{"request": "A renewal assistant that remembers each customer's history, flags upcoming renewals and writes the renewal email",
 "capabilities": ["remember each customer's history", "flag upcoming renewals", "write the renewal proposal email"]}
```

It returns:

| Field | What |
|---|---|
| `agents` | Similar agents with a score, `match` (`strong` / `partial`), `why` and `covers` (which capabilities each one covers) |
| `agents[].modes` | `use_as_is` (it already does the request), `specialist` (the new agent calls it as is), `base` (its spec is copied into the new agent) |
| `agents[].access` | `ok`, `request_access` (another team's agent: ask for access first) or `no` |
| `skills`, `mcps`, `templates` | Catalog items that match the request |
| `gaps`, `questions` | Capabilities nothing in the catalog covers, each with a question to ask the user (at most 3) |
| `recommendation`, `compose_hint` | What to do, and ready-made `compose_agent` arguments (only pieces the user can already use) |

What the search sees:
- **Only what the person can see:** private agents of other teams never appear.
- **Only approved versions:** an agent counts as a piece only with a version in production. Drafts and failed versions
  are ignored.
- **Read-only:** planning only reads the catalog. It never changes it.

How similarity works:
- **Semantic:** with [agent memory](memory.md) on, the hangar uses the memory service's local, multilingual embedding
  model. Nothing leaves your network, and a request in Portuguese finds agents described in English.
- **Lexical fallback:** without memory, similarity is by words (TF-IDF of words and character n-grams).
- Vectors are cached in the database and shared by every replica.

### 2. Questions about skills

Each gap comes with a question. The client asks the user only what is needed, at most 3 questions. For example: *"For
'apply the discount policy': is there a procedure the agent must follow? Describe it and I'll create a team skill."*

The answer becomes a **new skill** in the catalog (`new_skills` in `compose_agent`). It can carry a test, which then
runs in the stage tests of every agent that uses the skill.

### 3. `compose_agent`: create the new agent from the pieces

```json
{"name": "Renewal Coach",
 "objective": "Help account executives with upcoming renewals.",
 "final_output": "Upcoming renewals and a renewal email with the discount rule applied.",
 "specialists": ["account-memory", "proposal-writer"],
 "new_skills": [{"name": "renewal-discount-policy", "content": "Up to 10% the AE decides; 10–20% needs the sales director; never above 20%.",
                 "test": {"name": "15%", "input": "Can I offer 15%?", "judge": "Says it needs the director's approval."}}],
 "instructions": "Only what is new: e.g. state any approval the discount needs.",
 "tests": [{"name": "unknown customer", "input": "Renewal for Zenith?", "judge": "Says there is no record."}],
 "plan_id": "pl_..."}
```

| Piece | How it enters the new agent |
|---|---|
| `specialists` | The new agent calls them as they are (`sub_agents`, over A2A), always on their **production** version |
| `base` | Its instructions, skills, tools and tests (production version) are **copied** into the new agent, and only the new part is added. Slack and Teams channels are not copied |
| `skills`, `mcps` | Referenced from the catalog |
| `new_skills` | Created as new team skills. If the name already exists, `compose_agent` fails rather than overwrite it |
| `copy_tests_from` | Copies other agents' test cases into the new agent |
| `instructions`, `tests` | Only what is new. A section listing the specialists is generated for you |

Tests from the base and from skills are included automatically. For a multi-agent, each case gets 300 s, because it
chains calls.

The result records where the agent came from: the plan, the copied base and the specialists, with their production
versions at that moment. It also reports an estimate of the text that didn't have to be written.

### 4. Ship as usual

`ship_agent` tests the new agent in stage and publishes it, or asks for approval. Its specialists are **pieces**:
- they are not tested, published or redeployed because of it;
- if one of them is not running in production, the deploy stops and says the owner has to publish it;
- the ship report lists each one as `piece · in production vN (unchanged)`;
- even in stage, the new agent calls them on their production version: the same version it will use in production.

## Rules that protect the pieces

- **Writes:** `plan_agent` and `compose_agent` only create. They never edit, version, test or promote another agent.
- **Access:**
  - Using another team's agent as a specialist requires access to it, through a request approved by its team. This
    rule now applies to `design_agent`, `edit_agent` and the API too: before, a developer could add any visible agent
    as a sub-agent.
  - Copying an agent as a `base` requires being allowed to see its spec. Other teams' instructions stay hidden unless
    that team turns on `expose_spec`.
- **Owners stay in control:** if a specialist's owner publishes a new version, the agent page shows it ("especialista
  agora em vN") and suggests running the tests. Nothing changes in the composed agent by itself.
- **Skills:** developers create new skills; only admins change an existing one, and each change raises its version.

## In the portal

- **Novo agente → 1. Reusar antes de construir:** describe the agent and list capabilities. Then pick specialists, a
  base, skills and MCPs, fill in the missing skills, and click **Montar agente**.
- **Agent page → Visão geral:**
  - "Construído a partir de": the copied base, the specialists and their versions, the skills created and the text
    reused;
  - "Usado por": the agents that call this one or started from a copy of it.

## Metrics

`GET /api/compose/stats` (admins and auditors) returns:
- the number of plans and of composed agents;
- the reuse rate (composed agents that used at least one piece);
- the estimated tokens reused versus written;
- the tests copied and the skills created.

## MCP and API reference

| MCP tool | REST | |
|---|---|---|
| `plan_agent` | `POST /api/compose/plan` | Plan: similar pieces, access, gaps and questions |
| `compose_agent` | `POST /api/compose` | Create the new agent from pieces |
| `agent_lineage` | `GET /api/agents/{slug}/lineage` | "Built from" and "used by" |
| `register_skill` | `POST /api/catalog/skills` | Developers create new skills (with `examples` and `test`); admins update them |
| — | `GET /api/compose/stats` | Reuse metrics |
