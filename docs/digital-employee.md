# Digital employee

A **Digital employee** is an agent hired for a job. Unlike a normal agent, it is not only called. It has:

- a **job profile**: title, mission, responsibilities, systems, goals;
- a **human manager**, plus backups;
- an **authority level** (alçada) that says what it may do on its own;
- a **task queue**: it works on tasks in the background and stops to ask a person when an action needs it.

The person stays in the loop for everything sensitive, and **the platform enforces the authority, not the
prompt**. Before every tool call, the agent's runtime asks the central (`/internal/gate`). If the central does not
answer, the action does not run (it fails closed).

This is phase F1. Integrations with the company's chat tool are planned for F3; see [Roadmap](#roadmap).

## Lifecycle

```
onboarding ──► probation ──► (manager admits) ──► active ◄──► paused
     ▲              │                                │
     └── not yet ───┘                                └──► offboarded
```

| Status | What happens |
|---|---|
| `onboarding` | Hired: the agent, the job, the authority rules and the probation tasks exist. Nothing runs yet. |
| `probation` | Runs in **stage** and does the probation tasks (3 or more real tasks of the job, each with an expected result). When they are all finished, the manager gets an **admission** request with each expected result next to what was delivered. |
| `active` | Admitted by the manager: tested and published to **production** (the normal `ship` flow). It receives tasks. |
| `paused` | Nothing gets through the gate until someone resumes it. Any manager can pause their employee; an admin can pause all of them at once. |
| `offboarded` | Open tasks and decisions are cancelled and containers stop. History, reports and the audit log stay. |

## Hiring in self mode (MCP)

The recommended way to hire is from the AI tool (Claude, ChatGPT, Codex, Cursor) connected to the platform MCP.
The platform instructions tell the tool to:

1. Call `plan_employee` with what it already knows. The answer lists `missing` fields, each with a ready question for
   the owner, plus optional questions, catalog pieces to reuse (`reuse`) and the default authority with the company
   floor (`authority_default`).
2. Ask the owner the missing questions, **at most 4 at a time**, and never invent the answers. Then call
   `plan_employee` again until `ready=true`.
3. Show the owner a summary of the job and confirm it.
4. Call `hire_employee`. If a required field is still missing, it creates nothing and returns the questions again.
5. Call `start_probation`.

Required fields:

| Field | Rule |
|---|---|
| `title`, `mission` | Not empty |
| `responsibilities` | 3 or more |
| `manager` | An existing user (e-mail or username) |
| `systems` or pieces | The systems it works with, or catalog pieces (`specialists`, `base`, `skills`, `mcps`, `tools`) |
| `authority` | Explicit rules, or `accept_default_authority=true` after the owner confirms the default |
| `channels` | At least one of `portal`, `mcp`, `schedule`, `webhook` |
| `probation_tasks` | 3 or more, each with `title`, `body` and `expected` |

Optional fields: `backups`, `team`, `kpis`, `autonomy_level` (default `intern`), `working_hours`, `task_budget_usd`
(default 1.00), `task_time_limit_min` (default 30), `report_webhook`, `report_hour` (default 18), `llm`, `memory`,
`instructions`.

The questions follow the language of the request (Portuguese or English).

The portal has the same flow as a guided form (**Digital employees → + Hire**). Its *Check* button calls the same
planner.

The hire builds the agent through the normal composer:
- its instructions come from the job profile;
- the probation tasks also become judge tests;
- a guide is written for its **Guide** tab.

## Authority

Every tool call has an **action type**:

| Action type | Examples |
|---|---|
| `read` | Look up, search, `GET` |
| `delegate` | Ask another agent |
| `write_internal` | Change internal data |
| `send_external` | E-mail, message to a customer |
| `speak_for_company` | Public statements |
| `publish` | Publish, deploy, merge |
| `financial` | Pay, refund, invoice |
| `delete` | Delete, remove |
| `prod_change` | Change production |

Each action type has a **mode**:

| Mode | Meaning |
|---|---|
| `auto` | Does it on its own |
| `notify` | Does it and sends a notice |
| `approve` | The task pauses until an approver decides on the **exact** action (tool and arguments) |
| `approve_2` | Two different people must approve |
| `never` | Denied |

The effective mode comes from three layers, and the strictest one wins:

1. **Job rules.** Each rule has `{action_type, mode, conditions?, approver?, expires_in_min?}`.
   - Conditions compare arguments with `> >= < <= == != contains not_contains domain_not`, for example
     `{"field": "amount", "op": ">", "value": 1000}`.
   - The approver is `manager`, `team_maintainer` or `user:<e-mail>`.
2. **The autonomy level's default.** `intern` only reads on its own and delegates with a notice. `junior`, `pleno`
   and `senior` are progressively looser. Anything not listed needs approval.
3. **The company floor.** It is set by the admin and always applies. By default:
   - `financial` needs two approvals;
   - `delete` and `prod_change` need approval with separation of duties;
   - `send_external`, `speak_for_company` and `publish` need approval.

   A job rule looser than the floor is saved with a warning but does not apply.

**Classifying tools.** The first time a tool is used, the platform classifies it into the action catalog:
- `GET` is `read` and `DELETE` is `delete`; agents are `delegate`; memory recall is `read`.
- Other HTTP and MCP tools are classified by name (`pay_invoice` is `financial`, `send_email` is `send_external`,
  and so on) and marked for **admin review**.

## Human in the loop

When an action needs a person, the agent's round stops and the task becomes `waiting_human`. A **decision request**
is created with:
- the exact payload, the agent's rationale, the risk and whether the action is reversible;
- the person it is assigned to, and an expiry time.

| Kind | Possible decisions |
|---|---|
| Approval | `approve`, `approve_edited` (with corrected arguments), `reject` (with a reason), `instruct` (what to do instead) |
| Question (`ask_human` tool) | `answer` |
| Admission | `approve` (ship to production) or `reject` (back to onboarding) |
| Notice | `ack` |

- An approval grants a **one-time** permission for that exact tool and those exact arguments. The task resumes from
  its last checkpoint; the same action later needs a new approval.
- With **separation of duties**, the person who requested the task cannot approve it.
- `approve_2` needs two different people.
- **No answer in time:** the request is escalated once to the backup, then it expires and the agent is told
  **not to** do the action.

Decisions appear:
- in the portal (**Decisions**, with a badge, batch approve and batch acknowledge, plus a card on the home page);
- over MCP (`my_pending_decisions`, `decide`);
- as a notice on the report webhook, when one is set.

## Tasks

- Tasks come from the portal (*Give it a task*) and MCP (`assign_task`), with priority 1 to 3. Schedules and inbound
  webhooks as task sources come in F2; the `schedule` and `webhook` channels can already be declared on the job.
- A runner in the central claims queued tasks and calls the agent: stage during probation, production afterwards.
- Every round saves a **checkpoint** and events (tool calls, gate results, decisions), shown as a timeline on the
  task page.
- **Limits per task:** a budget (`task_budget_usd`), a time limit, and at most `EMPLOYEE_MAX_RUNS` rounds.
- A round that fails (the agent is unreachable or returns an error) or is lost to a crash goes back to the queue. After
  3 attempts the task fails.

## Reports

- **A daily report** at `report_hour`, in the company time zone, with:
  - tasks done, failed and waiting;
  - open decisions;
  - cost.
- It is stored in the **Reports** tab and, when `report_webhook` is set, posted there. Slack and Teams incoming
  webhooks both work, so use whichever your company runs on.
- **30-day metrics:**
  - done and failed tasks, cost per task;
  - approvals approved unedited, rejected and expired;
  - average time to decide.

## Where it lives

**Portal (owner and manager)**
- **Digital employees** lists them. Each has a page with these tabs:
  - *Overview*: job, metrics, give a task;
  - *Tasks*: each task links to its timeline;
  - *Decisions*;
  - *Authority*: effective authority and the job rules editor;
  - *Probation*: expected vs. delivered;
  - *Reports*;
  - *Settings*: job, limits, webhook, autonomy level, offboarding.
- **Decisions** is the inbox for everything waiting for you.

Only the manager (or an admin) changes the autonomy level and decides the admission.

**Console (admin)**, under **Digital employees**:
- *Overview*: status counts, open decisions by age, approvals by type, expired decisions, every employee, **Stop
  all now**;
- *Action catalog*: confirm or fix how each tool is classified, starting with the review queue;
- *Company floor*: the minimum mode and separation of duties for each action type.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `EMPLOYEE_WORKERS` | 3 | Tasks run in parallel per central replica |
| `EMPLOYEE_MAX_RUNS` | 12 | Rounds per task before it fails |
| `DECISION_EXPIRES_MIN` | 240 | Default time to decide before escalation and expiry |

## API and MCP

- REST endpoints are listed in [api.md](api.md#digital-employee-api).
- MCP tools:
  - hiring: `plan_employee`, `hire_employee`, `start_probation`, `set_authority`;
  - work: `assign_task`, `task_status`, `employee_status`, `list_employees`;
  - decisions: `my_pending_decisions`, `decide`;
  - lifecycle: `pause_employee`, `resume_employee`, `offboard_employee`.

## Roadmap

- **F2:** recurring work from schedules and inbound webhooks with deduplication; KPI tracking against goals; weekly
  reports; a learning loop from edited approvals.
- **F3:** decisions inside the company's chat tool. **Slack or Microsoft Teams is optional:** each company turns on the
  one that is core to it (or neither, keeping the portal and MCP). It will offer interactive approval buttons and
  tasks assigned from a message.
