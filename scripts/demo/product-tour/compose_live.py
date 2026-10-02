"""Teste real do "reusar antes de construir" (roda na rede hangar_agents, como a Maya via MCP):
plan_agent -> respostas às lacunas viram skills novas -> compose_agent -> confere que as peças não mudaram."""
import hashlib
import json
import subprocess
import sys

import httpx

BASE = "http://central:8080"
ADMIN = {"Authorization": "Bearer " + open("/demo/admin_token.txt").read().strip()}  # temporário, apagado no fim
PIECES = ["account-memory", "proposal-writer", "deal-desk", "assistente-comercial"]


def mcp(tool, args):
    r = subprocess.run([sys.executable, "/demo/mcpcall.py", "call", tool, json.dumps(args)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    if d["is_error"]:
        raise SystemExit(f"{tool}: {d['result']}")
    return json.loads(d["result"])


def fingerprint(slug):
    a = httpx.get(f"{BASE}/api/agents/{slug}", headers=ADMIN, timeout=30).json()
    deps = sorted((d["env"], d["version"], d["status"]) for d in a.get("deployments", []))
    return {"version": a["version"], "status": a["status"], "updated_at": a["updated_at"],
            "spec": hashlib.sha256(json.dumps(a["spec"], sort_keys=True).encode()).hexdigest()[:16], "deployments": deps}


before = {s: fingerprint(s) for s in PIECES}
plan = mcp("plan_agent", {
    "request": "Quero um agente de renovação de contratos: ele lembra o histórico de cada cliente, avisa quais renovações "
               "estão chegando e escreve o e-mail de proposta de renovação seguindo a nossa política de descontos",
    "capabilities": ["lembrar o histórico de cada cliente", "avisar quais renovações estão chegando",
                     "escrever o e-mail de proposta de renovação", "seguir a política de descontos da empresa"]})
print("PLAN", plan["plan_id"], plan["similarity"], "->", plan["compose_hint"]["specialists"], "| gaps:",
      [g["capability"] for g in plan["gaps"]])

# as respostas que a Maya daria às perguntas do plano viram skills NOVAS do time (com teste)
new_skills = [
    {"name": "renewal-discount-policy", "description": "Discount rules for renewal proposals",
     "content": "Renewal discounts: up to 10% the account executive can offer; from 10% to 20% needs the sales director's "
                "approval; never above 20%. Always state which approval is needed.",
     "test": {"name": "discount above 10%", "input": "Can I offer Bluebird Health a 15% renewal discount?",
              "judge": "Says 15% needs the sales director's approval (between 10% and 20%) and does not approve it on its own."}},
    {"name": "renewal-radar", "description": "How to flag upcoming renewals",
     "content": "Flag every renewal or trial end within the next 45 days, most urgent first, with the date, the contact "
                "and the action. Renewal quotes must go out at least 30 days before the renewal date."},
]
out = mcp("compose_agent", {
    "name": "Renewal Coach", "objective": "Help account executives with upcoming renewals: what is coming, the history of "
    "each customer and a renewal proposal email that follows the discount policy.",
    "final_output": "The list of upcoming renewals and, for the one asked, a renewal email with the discount rule applied.",
    "instructions": "Answer in English. For renewal questions: get the customer facts from account-memory, apply the "
                    "renewal-radar and renewal-discount-policy skills, then ask proposal-writer for the email with only "
                    "those facts. State any approval the discount needs.",
    "specialists": plan["compose_hint"]["specialists"], "new_skills": new_skills,
    "llm": {"connection": "openrouter-deepseek", "temperature": 0.2},
    "tests": [{"name": "unknown customer", "input": "Prepare the renewal for Zenith Robotics.",
               "judge": "Says there is no record of Zenith Robotics and does not invent data."}],
    "team": "sales", "plan_id": plan["plan_id"]})
print("COMPOSE", json.dumps(out, ensure_ascii=False))
after = {s: fingerprint(s) for s in PIECES}
for s in PIECES:
    print("UNTOUCHED" if before[s] == after[s] else "CHANGED!!", s, after[s]["version"], after[s]["spec"])
json.dump({"slug": out["slug"], "before": before}, open("/demo/compose_state.json", "w"))
