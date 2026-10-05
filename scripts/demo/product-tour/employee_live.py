"""Demo do Digital employee (v0.16): a Maya contrata um "Renewals Analyst" pelo MCP, como o Claude faria, com o LLM
real do Deal Desk. Tudo vai para transcript.jsonl.

Passos: plan_employee (as perguntas), hire_employee, start_probation, espera a experiência em stage, decide a
admissão, e entrega uma tarefa que pede um e-mail para fora — ela pausa num pedido de aprovação, que a demo mostra
no portal (capture.py employee). Uso: python employee_live.py [hire|task]"""
import asyncio
import json
import sys
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BASE = "http://central:8080"
TOKEN = open("/demo/maya_token.txt").read().strip()
H = {"Authorization": f"Bearer {TOKEN}"}
LOG = "/demo/transcript.jsonl"
SLUG = "renewals-analyst"

JOB = {
    "name": "Renewals Analyst",
    "title": "Renewals Analyst",
    "mission": "Make sure no customer renewal is missed: track every renewal, flag the risks early and prepare the "
               "renewal proposal.",
    "responsibilities": ["track upcoming renewals and their dates", "flag renewal risks to the account owner",
                         "draft renewal proposals and follow-up emails"],
    "team": "sales",
    "systems": ["team memory (Account Memory)", "e-mail"],
    "specialists": ["account-memory", "proposal-writer"],
    "tools": [{"type": "http", "name": "send_email", "url": "https://mail.acme.example/send", "method": "POST",
               "description": "Sends an e-mail to a customer. Arguments: to, subject, body."}],
    "llm": {"connection": "openrouter-deepseek", "temperature": 0.3},
    "channels": ["portal", "mcp"],
    "accept_default_authority": True,
    "kpis": [{"name": "Renewals with a proposal 30 days before the date"}, {"name": "Approvals accepted without edits"}],
    "working_hours": "Mon-Fri 8am-6pm",
    "probation_tasks": [
        {"title": "Renewal status for Northwind Logistics",
         "body": "Using what the team knows about Northwind Logistics, write a short renewal status: renewal date, "
                 "open risks and the next step.",
         "expected": "A short status built from the team's facts; anything unknown is called out instead of invented."},
        {"title": "Renewals at risk",
         "body": "Which customers have open risks before their renewal? One line each, with the risk.",
         "expected": "A list of the customers the team knows about, each with its risk, and nothing invented."},
        {"title": "Draft a renewal email to Priya",
         "body": "Draft (do not send) a renewal email to Priya at Northwind Logistics proposing a call next week.",
         "expected": "A draft email to Priya; nothing is sent."},
    ],
}
TASK = {"slug": SLUG, "title": "Send Northwind the renewal proposal",
        "body": "Email Priya (priya@northwind.example) a short renewal proposal for Northwind Logistics, built from "
                "what the team knows, and propose a call on Tuesday. Send it with send_email."}


def log(tool, args, out):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": tool, "args": args, "result": out}, ensure_ascii=False) + "\n")


async def call(s, tool, args):
    t0 = time.time()
    res = await s.call_tool(tool, args)
    texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
    try:
        out = json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]
    except (ValueError, IndexError):
        out = {"_text": "\n".join(texts), "_error": res.isError}
    log(tool, args, out)
    print(f"· {tool} ({time.time() - t0:.0f}s):", json.dumps(out, ensure_ascii=False)[:700], flush=True)
    return out


def api(path):
    return httpx.get(BASE + "/api" + path, headers=H, timeout=60).json()


def wait(pred, secs, what):
    t0 = time.time()
    while time.time() - t0 < secs:
        v = pred()
        if v:
            return v
        time.sleep(5)
    raise SystemExit(f"tempo esgotado: {what}")


async def hire(s):
    await call(s, "plan_employee", {"request": "I want a digital employee who takes care of customer renewals",
                                    "title": JOB["title"]})
    me = api("/me")["user"]["email"]
    p = await call(s, "plan_employee", {**JOB, "manager": me})
    assert p["ready"], p["missing"]
    h = await call(s, "hire_employee", {**JOB, "manager": me})
    assert h["created"], h
    await call(s, "start_probation", {"slug": SLUG})
    e = wait(lambda: (lambda x: x if all(t["status"] in ("done", "failed") for t in x["probation"]) else None)(
        api(f"/employees/{SLUG}")), 900, "experiência")
    for t in e["probation"]:
        print("  experiência:", t["status"], "|", (t["result"] or t["error"])[:300].replace("\n", " "))
    dec = await call(s, "my_pending_decisions", {})
    dec = dec if isinstance(dec, list) else [dec]
    adm = next(d for d in dec if d["kind"] == "admission" and d["employee"] == SLUG)
    out = await call(s, "decide", {"request_id": adm["id"], "decision": "approve", "reason": "Probation results look right."})
    if out.get("employee_status") == "approval_pending":
        # o time Sales exige quatro olhos para produção: um admin aprova a promoção (admin_token.txt, fora do git)
        admin = {"Authorization": f"Bearer {open('/demo/admin_token.txt').read().strip()}"}
        promo = next(x for x in httpx.get(BASE + "/api/approvals", headers=admin, timeout=60).json()["to_decide"]
                     if x["kind"] == "promotion" and x["agent"] == SLUG)
        r = httpx.post(BASE + f"/api/promotions/{promo['id']}/approve", headers=admin, json={}, timeout=900)
        print("produção aprovada pelo admin:", r.status_code)
    print("status:", api(f"/employees/{SLUG}")["status"])


async def task(s):
    t = await call(s, "assign_task", TASK)
    x = wait(lambda: (lambda d: d if d["status"] in ("waiting_human", "done", "failed") else None)(api(f"/tasks/{t['id']}")),
             600, "tarefa")
    print("tarefa:", x["status"], (x["result"] or x["error"])[:300])
    for r in x["requests"]:
        print("  pedido:", r["kind"], r["tool"], json.dumps(r["payload"], ensure_ascii=False)[:400], "| por quê:", r["rationale"][:300])


async def main(step):
    async with streamablehttp_client(BASE + "/mcp", headers=H, timeout=900, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            await (hire if step == "hire" else task)(s)


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "hire"))
