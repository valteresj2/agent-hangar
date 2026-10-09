# Plugins

A plugin connects a company system (an ERP, a CRM, a billing API…) to Agent Hangar with a **declarative manifest**. It
declares:
- the tools;
- the team's credential;
- the action type of each tool, which drives the [authority](digital-employee.md#authority);
- settings and skills.

No plugin code runs inside the platform. The credential stays in the central and never reaches the agent.

```
agent ──MCP──▶ central (/internal/plugins/<name>/mcp) ──HTTPS + team credential──▶ the system
                 │ checks the agent's token and spec, picks its team's install,
                 │ fills the path, query and body, injects the credential, blocks private hosts
```

## The manifest

```yaml
name: acme-erp                  # slug: lowercase, digits and hyphens
title: ACME ERP
version: 1.0.0                  # bump it to change an approved plugin
description: Invoices and customers from the ERP.
publisher: Finance IT
base_url: https://{{settings.tenant}}.erp.example.com/api   # the only host the plugin talks to
auth: {type: api_key, in: header, name: X-ERP-Key, label: ERP API key}   # none | api_key | bearer | basic
settings:                       # asked at install time; secret ones are stored encrypted
  - {key: tenant, title: Tenant, required: true}
  - {key: company_id, title: Company, required: true}
tools:
  - name: get_invoice
    description: One invoice by number.
    method: GET
    path: /companies/{{settings.company_id}}/invoices/{number}   # {x} comes from the arguments (URL-encoded)
    parameters: {type: object, properties: {number: {type: string}}, required: [number]}
  - name: send_invoice
    description: Sends the invoice to the customer.
    method: POST
    path: /invoices/{number}/send
    action: send_external       # the authority type; default: GET read, DELETE delete, others write_internal
    parameters: {type: object, properties: {number: {type: string}, email: {type: string}}}
skills:
  - {name: glossary, content: "Overdue invoice: more than 30 days unpaid."}
test: {tool: get_invoice, args: {number: "1"}}   # what "Test connection" calls
```

- **Arguments.** Path parameters (`{number}`) come from the tool's arguments. The other arguments go in the query
  string (GET, DELETE) or in a JSON body (POST, PUT, PATCH).
- **`{{settings.key}}`** works in `base_url`, `path` and per-tool `headers`.
- **Credentials:**
  - `api_key` goes in the header or query parameter named by `name` (default `X-API-Key`);
  - `bearer` sends `Authorization: Bearer <credential>`;
  - `basic` takes `user:password`.
- **Calls.** Responses longer than 8,000 characters are cut. Redirects are not followed. A call times out after
  `PLUGIN_TIMEOUT_S` seconds (30 by default).

### From an OpenAPI

*Plugins → New plugin → Import from an OpenAPI* (or `POST /api/plugins/import-openapi`) turns an OpenAPI 3 document
into a draft manifest. Each operation becomes a tool, `$ref` schemas are resolved, and the security scheme becomes the
`auth`. The action types are a guess from the method and the operation name (`createCharge` → financial,
`sendReminder` → send external). **Review them before submitting.**

## Lifecycle

1. **Draft.** Someone who builds agents (a developer or an admin) creates the plugin, optionally owned by a team.
2. **Review.** The owner submits it. An **admin who did not create or submit it** approves, or rejects with a note.
   The review screen shows what to check:
   - the host it talks to;
   - the authentication;
   - the count per action type, with the risky ones highlighted;
   - the secrets.
3. **Approved.** On approval, each tool enters the [action catalog](digital-employee.md#authority) as
   `mcp:plugin-<name>:<tool>`, with the manifest's type and risk. A Digital employee's authority therefore treats
   `send_invoice` as *send external* from day one.
4. **New version.** Editing an approved plugin requires a higher `version`. The new version is a draft and goes
   through review again. Installs keep the approved version until then.
5. **Turning it off.** An admin can turn a plugin off. Agents stop reaching it at once.

## Install and use

- **Who installs.** A team maintainer installs a plugin for the team, with the team's credential and settings. An admin
  can also install it for the whole company; a team install takes precedence over it.
- **Test connection** calls the manifest's `test` tool (or the first read tool).
- **Using it in an agent.** Put the plugin in the agent's spec:

  ```yaml
  plugins: [acme-erp]
  ```

  At deploy time the agent gets an MCP server `plugin-acme-erp`, so its tools appear as `plugin-acme-erp__get_invoice`.
  The plugin's skills are added too. The deploy fails with a clear message when the plugin is not approved or not
  installed for the agent's team.
- **Usage.** Each install counts calls and errors and keeps the last error.

## Security

- **The secret stays in the central:**
  - the credential and secret settings are encrypted (`HANGAR_SECRET_KEY`) and never returned by the API;
  - the agent's container only knows the central's internal URL;
  - each call checks the agent's internal token and that its spec lists the plugin.
- **One host.** Paths cannot change the host (no scheme, no `..`).
- **Private hosts are blocked** (private, loopback and link-local addresses), so a plugin cannot reach the platform's
  own network. Internal systems (an on-premises ERP) need `PLUGIN_ALLOW_PRIVATE=1`.
- **Every action still goes through the authority** (Digital employees), and the audit log records create, submit,
  approve, install and uninstall.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PLUGIN_ALLOW_PRIVATE` | 0 | 1 lets plugins call hosts in private networks |
| `PLUGIN_TIMEOUT_S` | 30 | Timeout of each call to the system |

## What's next

- **P2:** plugins with code, running in a container like an MCP server, plus OAuth credentials, triggers (events that
  become tasks) and third-party decision channels.
- **P3:** building plugins by chat through the MCP, tested in stage.
- **P4:** a company plugin gallery.
