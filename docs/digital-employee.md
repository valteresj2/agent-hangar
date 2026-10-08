# Digital employee

A **Digital employee** is an agent hired for a job. Unlike a normal agent, it is not only called. It has:

- a **job profile**: title, mission, responsibilities, systems, goals;
- a **human manager**, plus backups;
- an **authority level** (alçada) that says what it may do on its own;
- a **task queue**: it works on tasks in the background and stops to ask a person when an action needs it.

The person stays in the loop for everything sensitive, and **the platform enforces the authority, not the
prompt**. Before every tool call, the agent's runtime asks the central (`/internal/gate`). If the central does not
answer, the action does not run (it fails closed).

Phases F1 (the job, authority and decisions) and F2 (recurring work, inbound webhooks, measured goals, weekly
reports and learning from decisions) are done. Integrations with the company's chat tool are planned for F3; see
[Roadmap](#roadmap).

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
| `active` | Admitted by the manager: tested and published to **production** through the team's normal flow. If the team requires four-eyes for production and the manager cannot publish directly, the admission opens a promotion request in *Approvals*, and the employee becomes active when someone else approves it. It receives tasks. |
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

Optional fields: `backups`, `team`, `kpis` (see [Goals](#goals)), `routines` (see [Routines](#routines)),
`autonomy_level` (default `intern`), `working_hours`, `task_budget_usd` (default 1.00), `task_time_limit_min`
(default 30), `report_webhook`, `report_hour` (default 18), `report_weekday` (default 0, Monday; -1 for no weekly
report), `llm`, `memory`, `instructions`.

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
| `run_code` | Delegate a task to an agent with a harness (Claude Code, Codex…), which runs a code job in a sandbox |
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
   - `run_code`, `send_external`, `speak_for_company` and `publish` need approval.

   A job rule looser than the floor is saved with a warning but does not apply.

**Classifying tools.** The first time a tool is used, the platform classifies it into the action catalog:
- `GET` is `read` and `DELETE` is `delete`; agents are `delegate`; memory recall is `read`.
- Other HTTP and MCP tools are classified by name (`pay_invoice` is `financial`, `send_email` is `send_external`,
  and so on) and marked for **admin review**.

## Code work (harness)

A Digital employee is always a **chat agent**: the authority can only be enforced when every tool call goes through
the runtime's gate. A harness (Claude Code CLI, Codex…) runs its own tools inside a sandbox, where the gate cannot
see them. So the employee itself is never a harness: `hire_employee` refuses one.

To give it code work, put an agent with a harness in its `specialists`:

1. The employee decides it needs code changed and calls that specialist with the full instruction: what to change,
   where and how to check it.
2. The call is the action type **`run_code`**. By default it needs the manager's approval, on the company floor too,
   so the manager approves the **exact** instruction before any job runs.
3. After approval, the platform runs a **harness job** (an ephemeral container, the code governance rules of the
   harness agent apply). The call waits up to `JOB_MAX_TIMEOUT_S` (not the 3 minutes of a chat delegation).
4. The job number and its diff come back in the tool result. They show in the task's timeline, and the employee
   reports them in its result.

Notes:
- A `delegate` to a chat agent stays `delegate`. An agent that gains a harness later is reclassified as `run_code`
  on its next call.
- The job's own cost is recorded on the harness agent (its usage page), not in the employee's task budget.
- The harness agent must be in production to be a specialist, like any other piece.

## Missing capability

A Digital employee works only with what its job gives it: its LLM, its tools, skills and MCPs, and its specialists. It
never builds or attaches agents by itself. An agent that could give itself new agents could also give itself more power
than its authority allows.

When a task needs something it does not have, it calls **`request_capability(need, why)`** instead of improvising:

1. The task pauses, and the manager gets a **capability** decision. It shows:
   - what is missing and why;
   - what the catalog already has: the same search as "reuse before you build", seen with the manager's access.
2. The manager decides:

   | Decision | What happens |
   |---|---|
   | **Attach** (`attach`, `edit={"specialist": slug}`) | The agent is added to the employee's specialists as a read-only piece. This creates a new version, which is tested and published through the team's normal flow. With four-eyes, the task resumes when someone else approves production; otherwise it resumes right away. The manager must be allowed to use that agent, and it must be in production. |
   | **Build** (`build`) | The Hangar returns a ready request for the manager's AI tool (self mode). The decision stays open for 7 days, and the manager attaches the new agent when it is in production. |
   | **Reject** / **Instruct** | The task resumes without the capability, and the employee explains what was left undone or follows the instruction. |

3. On resume, the employee gets the new tool's name and continues. If the new specialist has a harness, each job still
   goes through `run_code`.

In the portal, the capability card in *Decisions* lists the catalog options with an *Attach* button and a *Build it with
your AI tool* button. Over MCP, use `my_pending_decisions` and `decide`.

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
| Capability (`request_capability` tool) | `attach`, `build`, `reject`, `instruct` (see [Missing capability](#missing-capability)) |

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

- Tasks come from the portal (*Give it a task*), MCP (`assign_task`), [routines](#routines) and the
  [inbound webhook](#inbound-webhook), with priority 1 to 3.
- A runner in the central claims queued tasks and calls the agent: stage during probation, production afterwards.
- Every round saves a **checkpoint** and events (tool calls, gate results, decisions), shown as a timeline on the
  task page.
- **Limits per task:** a budget (`task_budget_usd`), a time limit, and at most `EMPLOYEE_MAX_RUNS` rounds.
- A round that fails (the agent is unreachable or returns an error) or is lost to a crash goes back to the queue
  **with a growing wait**: 30 s, then 60 s, then 120 s (`EMPLOYEE_RETRY_BASE_S`, at most 10 minutes). After 3 attempts
  the task fails. A decision resumes the task right away, without the wait.
- [Lessons](#learning-from-decisions) approved by the manager go into the prompt of every new task.

## Routines

Recurring work: each run of a cron becomes a task.

- Example: `0 9 * * 1` is every Monday at 9am, in the company time zone. Runs must be at least
  `SCHEDULE_MIN_INTERVAL_MIN` minutes apart (default 5).
- A routine runs only while the employee is **active** (not during onboarding, probation or a pause).
- **Never two at once:** if the routine's previous task is still open, the run is skipped and counted.
- Several central replicas never fire the same run twice (the run is claimed with a conditional update).
- Create them at hire (`routines=[{title, body, cron}]`), over MCP (`set_routine`, `list_routines`,
  `delete_routine`) or in the portal (*Routines* tab, with presets and *Run now*). Creating a routine turns on the
  `schedule` channel.

## Inbound webhook

Other systems (CRM, forms, alerts) create tasks with a POST:

```bash
curl -X POST https://hangar.example.com/hooks/employees/<slug> \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"title": "New ticket #881", "body": "customer cannot log in", "dedupe_key": "zendesk-881", "source": "Zendesk"}'
```

- Each employee has its own token. The manager generates or rotates it in the *Routines* tab; it is shown **once** and
  stored only as a hash. Rotating it stops the old one at once; turning the webhook off closes the `webhook` channel.
- The token also works in an `X-Hangar-Token` header.
- **Deduplication:** a `dedupe_key` seen in the last `EMPLOYEE_DEDUPE_DAYS` days (default 7) returns the existing
  task with `"duplicate": true` instead of creating another.
- Answers: `200` with `{id, status, duplicate}`; `401` for a missing or wrong token or a closed channel; `409` when the
  employee does not take tasks now (onboarding or offboarded).
- The token is never shown over MCP, so it never lands in an AI tool's conversation.

## Goals

Each goal (`kpis`) can point to a metric the platform measures, with a target:

| Metric | Measures (30 days) | Better |
|---|---|---|
| `tasks_done` | Tasks done | higher |
| `done_rate` | % of finished tasks that were done | higher |
| `on_time_rate` | % done before their due date | higher |
| `approved_unedited_rate` | % of decided actions approved without edits | higher |
| `avg_decision_min` | Average time people take to decide | lower |
| `cost_per_task` | Cost per done task (US$) | lower |
| `expired_decisions` | Decisions that expired | lower |

Example: `{"name": "Finish what it starts", "metric": "done_rate", "target": 90}`. A goal without a metric is kept as
text. The *Overview* tab shows each goal as *on target*, *off target* or *no data yet*, and the weekly report compares
them.

## Reports

- **A daily report** at `report_hour`, in the company time zone, with:
  - tasks done, failed and waiting;
  - open decisions;
  - cost.
- **A weekly report** on `report_weekday` (default Monday), covering 7 days, with each [goal](#goals) compared with
  its target. The *Reports* tab can also generate either one now.
- Reports follow the language the job was written in.
- It is stored in the **Reports** tab and, when `report_webhook` is set, posted there. Slack and Teams incoming
  webhooks both work, so use whichever your company runs on.
- **30-day metrics:**
  - done and failed tasks, cost per task;
  - approvals approved unedited, rejected and expired;
  - average time to decide.

## Learning from decisions

The decisions of the last 30 days turn into **suggestions**. Nothing changes on its own: the manager applies or
dismisses them (*Authority* tab, or `employee_suggestions` / `apply_suggestion` over MCP).

- **Loosen an action type.** Suppose the manager approved `LEARN_MIN_APPROVALS` (default 8) or more actions of one type
  in 30 days, all without edits. The suggestion is to move that type from *approve* to *notify*: it does the action and
  sends a notice.
  - It is never suggested below the company floor. For example, sending outside stays at *approve* by default.
  - Only the manager (or an admin) applies it.
- **Turn corrections into a lesson.** Suppose `LEARN_MIN_CORRECTIONS` (default 3) or more actions of the same tool were
  edited, rejected or redirected. The suggestion is a lesson built from the reasons and the edited fields; the manager
  can rewrite it before applying.
  - Lessons go into the prompt of every new task, under "Lessons from your manager".
  - The *Settings* tab lists them (at most 20), removes them and accepts lessons written by hand.
- A dismissed suggestion stays hidden for 30 days.

## Where it lives

**Portal (owner and manager)**
- **Digital employees** lists them. Each has a page with these tabs:
  - *Overview*: job, metrics, give a task;
  - *Tasks*: each task links to its timeline, marked when it came from a routine or the webhook;
  - *Routines*: routines (presets, *Run now*, pause) and the inbound webhook (token, URL, example);
  - *Decisions*;
  - *Authority*: suggestions from decisions, effective authority and the job rules editor;
  - *Probation*: expected vs. delivered;
  - *Reports*;
  - *Settings*: job, limits, report webhook and days, goals, lessons, autonomy level, offboarding.
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
| `EMPLOYEE_RETRY_BASE_S` | 30 | First wait after a failed round; it doubles each attempt, up to 10 minutes |
| `EMPLOYEE_DEDUPE_DAYS` | 7 | How long a webhook `dedupe_key` is remembered |
| `LEARN_MIN_APPROVALS` | 8 | Approvals without edits before suggesting to loosen an action type |
| `LEARN_MIN_CORRECTIONS` | 3 | Corrections on one tool before suggesting a lesson |

## API and MCP

- REST endpoints are listed in [api.md](api.md#digital-employee-api).
- MCP tools:
  - hiring: `plan_employee`, `hire_employee`, `start_probation`, `set_authority`;
  - work: `assign_task`, `task_status`, `employee_status`, `list_employees`;
  - decisions: `my_pending_decisions`, `decide`;
  - lifecycle: `pause_employee`, `resume_employee`, `offboard_employee`;
  - recurring work: `set_routine`, `list_routines`, `delete_routine`;
  - code work: put an agent with a harness in `specialists` (see [Code work](#code-work-harness));
  - learning: `employee_suggestions`, `apply_suggestion` (only with the manager's explicit OK).

## Roadmap

- **F2 (done):** routines, the inbound webhook with deduplication, measured goals, weekly reports, learning from
  decisions and growing waits between retries.
- **F3:** decisions inside the company's chat tool. **Slack or Microsoft Teams is optional:** each company turns on the
  one that is core to it (or neither, keeping the portal and MCP). It will offer interactive approval buttons and
  tasks assigned from a message.
