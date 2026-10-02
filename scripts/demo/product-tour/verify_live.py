"""Confere, depois de todo o fluxo, que as peças não mudaram; mostra linhagem e métricas."""
import hashlib
import json
import subprocess
import sys

import httpx

BASE = "http://central:8080"
A = {"Authorization": "Bearer " + open("/demo/admin_token.txt").read().strip()}
state = json.load(open("/demo/compose_state.json"))
for slug, before in state["before"].items():
    a = httpx.get(f"{BASE}/api/agents/{slug}", headers=A, timeout=30).json()
    now = {"version": a["version"], "status": a["status"], "updated_at": a["updated_at"],
           "spec": hashlib.sha256(json.dumps(a["spec"], sort_keys=True).encode()).hexdigest()[:16],
           "deployments": [list(x) for x in sorted((d["env"], d["version"], d["status"]) for d in a.get("deployments", []))]}
    diff = {k: (before[k], now[k]) for k in now if before[k] != now[k]}
    print(("UNTOUCHED " if not diff else "CHANGED   ") + slug, f"v{now['version']} spec {now['spec']}", diff or "", flush=True)


def mcp(tool, args):
    r = subprocess.run([sys.executable, "/demo/mcpcall.py", "call", tool, json.dumps(args)], capture_output=True, text=True)
    return json.loads(json.loads(r.stdout)["result"])


lin = mcp("agent_lineage", {"slug": "renewal-coach"})["built_from"]
print("LINEAGE", lin["mode"], [(s["slug"], s["version_at_composition"], s["prod_version_now"], s["updated_since"])
                               for s in lin["specialists"]], lin["new_skills"], "reused~", lin["reused_tokens_estimate"])
print("USED_BY account-memory:", mcp("agent_lineage", {"slug": "account-memory"})["used_by"])
print("STATS", httpx.get(f"{BASE}/api/compose/stats", headers=A, timeout=30).json())
