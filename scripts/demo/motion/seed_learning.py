"""Seed da cena (rodar antes do capture.py, com maya_token.txt e admin_token.txt em /demo). Dados reais para a cena "It learns from your decisions": um Digital employee (LLM simulado) cujas ações de e-mail o
gestor corrige 3 vezes, gerando a sugestão de lição na aba Alçada. Imprime o slug."""
import time

import httpx

BASE = "http://central:8080"
H = {"Authorization": f"Bearer {open('/demo/maya_token.txt').read().strip()}"}
ADMIN = {"Authorization": f"Bearer {open('/demo/admin_token.txt').read().strip()}"}


def api(m, p, h=H, **kw):
    r = httpx.request(m, BASE + "/api" + p, headers=h, timeout=600, **kw)
    r.raise_for_status()
    return r.json()


def wait(fn, secs=300):
    t0 = time.time()
    while time.time() - t0 < secs:
        v = fn()
        if v:
            return v
        time.sleep(3)
    raise SystemExit("timeout")


me = api("GET", "/me")["user"]["email"]
job = {"name": "Support Analyst", "title": "Support Analyst",
       "mission": "Answer customer questions and keep every account informed.",
       "responsibilities": ["answer customer questions", "send account updates", "escalate risks to the account owner"],
       "manager": me, "team": "sales", "systems": ["help desk", "e-mail"], "llm": {"model": "mock/echo"},
       "tools": [{"type": "http", "name": "send_email", "url": "https://mail.acme.example/send", "method": "POST"}],
       "channels": ["portal", "mcp"], "accept_default_authority": True,
       "probation_tasks": [{"title": f"Probation {i}", "body": f"answer ticket {i}", "expected": f"answer {i}"} for i in range(3)]}
h = api("POST", "/employees", json=job)
slug = h["employee"]["slug"]
api("POST", f"/employees/{slug}/probation")
wait(lambda: (lambda e: e if e["probation"] and all(t["status"] == "done" for t in e["probation"]) else None)(
    api("GET", f"/employees/{slug}")))
adm = wait(lambda: next((d for d in api("GET", "/decisions") if d["kind"] == "admission" and d["employee"] == slug), None))
api("POST", f"/decisions/{adm['id']}", json={"decision": "approve"})
promo = next(x for x in api("GET", "/approvals", ADMIN)["to_decide"] if x["kind"] == "promotion" and x["agent"] == slug)
api("POST", f"/promotions/{promo['id']}/approve", ADMIN, json={})
assert api("GET", f"/employees/{slug}")["status"] == "active"
corrections = [("reject", {"reason": "always cc the account owner"}),
               ("reject", {"reason": "never promise a delivery date"}),
               ("approve_edited", {"edit": {"to": "ops@globex.example", "subject": "Update on your ticket",
                                            "body": "Hi Sam, quick update on your ticket. — Acme Support"}})]
for i, (dec, body) in enumerate(corrections):
    to = ["ana@initech.example", "lee@hooli.example", "ops@globex.example"][i]
    tid = api("POST", f"/employees/{slug}/tasks", json={"title": f"Reply to ticket {120 + i}",
              "body": f'use send_email {{"to": "{to}", "subject": "Your ticket", "body": "We will fix it by Friday."}}'})["id"]
    d = wait(lambda: next((x for x in api("GET", "/decisions") if x["task"] and x["task"]["id"] == tid and x["kind"] == "approval"), None))
    api("POST", f"/decisions/{d['id']}", json={"decision": dec, **body})
    wait(lambda: api("GET", f"/tasks/{tid}")["status"] in ("done", "failed"))
for d in api("GET", "/decisions"):
    if d["kind"] == "notice":
        api("POST", f"/decisions/{d['id']}", json={"decision": "ack"})
print([s["id"] for s in api("GET", f"/employees/{slug}/suggestions")])
print("SLUG", slug)
