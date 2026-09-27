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

## Contributing a template

1. Add `templates/<id>.yaml`. Use generic example data, never real customer data.
2. Include at least two test cases, with at least one `judge` rubric for open-ended answers.
3. Run `pytest tests/test_registry.py -k templates`: it validates every template against the spec schema.
4. Open a PR with a short description of the use case.
