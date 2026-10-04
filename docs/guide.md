# Agent guide (the Guide tab)

Every agent has a **Guide** tab, between *Usage* and *Playground*. It is the page for the people who will **use** the
agent, not for those who build it. It answers three questions: what the agent is, how it works, and how to call it.
Everyone who can see the agent sees its guide, including people who find it in the company catalog, so it is also
the page that helps them decide whether to request access.

## What it shows

**How it works (flow).** A diagram built automatically from the spec of the described version:

```
Request (channels) ─┐
Schedules ──────────┴─► Agent (model) ──► Delivers (final output)
                          │
                          └─► skills · MCP tools · tools · memory · specialists (A2A) · harness job
```

- It shows *which* skills, tools and specialists the agent uses, never their content. Instructions stay hidden from
  people outside the team unless the team turns on *expose spec*.
- Specialists you can see are links to their own guide.
- Nobody draws the diagram, so it never goes out of date.

**Fact sheet.**
- Goal, final output, owner, model, skills, MCPs, tools, memory scope, schedules and *built from* (for composed
  agents).
- The described version, and the versions running in production and stage.
- **Example requests:** the inputs of the test cases that passed for that version. These are real examples, not
  invented ones.
- **Where to call:** the agent's endpoints, plus a link to the *Connect* tab.

Examples and endpoints are shown only to people who can use the agent.

**Guide text.** Markdown written for users, with these sections: *What it is*, *What it does*, *What it does not do*,
*How to use it* (with example requests) and *Limits*.

## Where the text comes from

| Source | When | Status |
|---|---|---|
| The AI tool that built the agent | Claude, ChatGPT or Codex call `set_agent_guide(slug, text)` after the ship; the platform instructions ask them to | Reviewed |
| A maintainer | **Write guide** / **Edit** in the tab | Reviewed |
| The agent's own LLM | Automatically when a version reaches production with no guide for it, or on **Generate draft with AI** | **Generated draft, not reviewed** until a maintainer clicks **Approve draft** |

- **Drafts stay close to the spec.** A draft is written only from the spec (instructions, skills, tools,
  specialists, memory) and the test cases that passed. The model is told not to invent capabilities, integrations,
  data or numbers.
- **Who can generate a draft.** It needs an OpenAI-protocol connection: the agent's `llm.connection` or
  `judge.connection`. Agents in mock mode get no draft; write the guide instead.
- **Human text wins.** An automatic draft never replaces a guide written by a person.

## Versions

- **Kept outside the spec on purpose.** The text lives in its own table (`agent_guides`), not in the spec. Fixing the
  documentation therefore creates no new agent version and requires no new tests.
- **Each text records the version it describes.** That is the production version, or the newest version if the
  agent is not in production.
- **Outdated warning.** When production moves to a newer version, the old text stays and the tab shows *"This text
  was written for vN"* until someone updates it or a new draft is generated.

## Discovery by other agents (A2A)

Once a guide is **reviewed**, its first paragraph becomes the `description` of the agent's A2A Agent Card
(`/gw/<slug>/.well-known/agent.json`). Other agents and A2A clients then get a clearer description. Unreviewed drafts
never reach the card.

## API and MCP

| Method | Path | Who |
|---|---|---|
| GET | `/api/agents/{slug}/guide` | Anyone who can see the agent. Returns `{facts, graph: {nodes, edges}, doc, can_edit, can_generate}` |
| PUT | `/api/agents/{slug}/guide` | Editors. `{text}` (Markdown, up to 20,000 characters) |
| POST | `/api/agents/{slug}/guide/approve` | Editors: marks the draft as reviewed |
| POST | `/api/agents/{slug}/guide/generate` | Editors: new draft from the agent's LLM; it replaces the current text |

MCP tools:
- `get_agent_guide(slug)`: lets Claude or ChatGPT answer "what does this agent do?" from the same page.
- `set_agent_guide(slug, text)`: writes the guide.

To turn off automatic drafts on ship, set `GUIDE_AUTOGEN=0`.
