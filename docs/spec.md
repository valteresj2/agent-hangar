# Agent spec reference

The spec is validated by a strict schema (unknown fields are rejected). The full JSON Schema is served at
`GET /api/spec/schema` and by the MCP tool `get_spec_schema`.

```yaml
llm:                      # chat agents only (mutually exclusive with harness.connection)
  connection: my-litellm  # name of a connection in the catalog (protocol openai); empty = mock
  model: ""               # empty = the connection's default model
  temperature: 0.2
  stage: {model: cheap-model}         # optional per-environment overrides: connection / model / temperature
  prod: {connection: prod-gateway}
harness:                  # harness agents only
  id: claude-code         # claude-code | codex | hermes | deepseek-harness
  connection: anthropic   # protocol must match the harness; empty = mock
  stage: {connection: ...}
judge:                    # connection used by `judge` test cases (defaults to llm.connection)
  connection: my-litellm
  model: ""
instructions: |
  Free text system prompt.
skills:                   # catalog names or inline {name, description, content}
  - pdf-checklist
  - {name: tone, content: "Be concise."}
mcps:                     # catalog names or inline {name, url} (Streamable HTTP)
  - crm
tools:
  - {type: builtin, name: calculator}          # calculator | current_time | platform_dashboard
  - type: http
    name: get_weather
    description: Current weather for a city
    url: https://api.example.com/weather
    method: GET                                # GET sends args as query; others as JSON body
    parameters: {type: object, properties: {city: {type: string}}, required: [city]}
sub_agents: [researcher, writer]               # chat agents only; each becomes an ask_<slug> tool
tests:
  - name: cites the section
    input: What is the hotel limit?
    expect_contains: "180"       # case-insensitive substring
    expect_regex: "\\d+"         # Python regex
    judge: "Must cite the section it used and not invent rules."   # LLM-as-judge rubric
    timeout_s: 300               # harness tests only
channels: [slack, librechat]     # informational tags
```

## Updating a spec

- **Merge patch**: `PATCH /api/agents/<slug>` or the MCP tool `design_agent`. This is JSON Merge Patch
  ([RFC 7396](https://www.rfc-editor.org/rfc/rfc7396)): objects merge, lists and scalars replace, and `null`
  deletes. Examples:
  - switch connection and go back to its default model: `{"llm": {"connection": "b", "model": null}}`
  - turn a harness agent into a chat agent: `{"harness": null, "llm": {"connection": "x"}}`
- **Replace**: `PUT /api/agents/<slug>/spec` (the UI's *Spec* editor, and `hangar apply`).
- **Rollback**: `POST /api/agents/<slug>/rollback {"version": 3}`.

## Rules enforced by validation

- A spec cannot set both `llm.connection` and `harness`.
- A harness agent cannot have `sub_agents`.
- Sub-agents must exist, and an agent cannot list itself.
- Catalog references (skills, MCPs, connections) are resolved at deploy time; a missing one fails the deploy
  with a clear message.
