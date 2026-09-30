# Templates

Templates are YAML files in [`templates/`](../templates/) that wrap a GitOps document:

```yaml
id: my-template            # unique, used in URLs and `hangar templates apply <id>`
title: Human title
description: One paragraph shown in the gallery.
tags: [chat, support]
needs: "What the user must provide (e.g. an LLM connection with protocol openai)."
document:
  skills: [...]            # optional, same shape as `hangar apply`
  mcp_servers: [...]       # optional
  agents:                  # members first, orchestrator last
    - name: ...
      slug: ...
      objective: ...
      final_output: ...
      spec: {...}          # see docs/spec.md
```

When a template is applied, `connection` fills `llm.connection` for chat agents that have none, and
`harness_connection` fills `harness.connection` for harness agents. The protocols are checked. With no connections,
agents run in mock mode.

## Code Assistant (`code-assistant`)

A coding agent for VS Code (the Agent Hangar extension), Cline, Roo Code and Continue:
- a `coding-standards` skill: read before changing, make minimal changes, never edit tests to make them pass, run
  the tests before claiming success, never touch secrets;
- `max_steps: 30`;
- three stage tests:
  - an LLM-as-judge case on how it approaches a bug fix;
  - **two code evaluations**: fixing the bugs in a statistics module, and implementing `slugify` from a stub, both
    with the tests protected.

The agent only reaches production if it really solves both. Apply it with `hangar templates apply code-assistant
--connection <conn>`, or from **Templates** in the UI. If the company uses the "approved connections only" code
policy, the connection must be approved for code.

## Contributing a template

1. Add `templates/<id>.yaml`. Use generic example data, never real customer data.
2. Include at least two test cases, with at least one `judge` rubric for open-ended answers.
3. Run `pytest tests/test_registry.py -k templates`: it validates every template against the spec schema.
4. Open a PR with a short description of the use case.
